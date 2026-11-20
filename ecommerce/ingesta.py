import argparse
import csv
import gzip
import io
import json
import math
import re
import time
import zlib
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import requests
from PIL import Image

import cliente_bd as bd
import visuales
from config import (
    CARPETA_DATOS,
    CARPETA_MULTIMEDIA,
    CATEGORIA_DATASET,
    DESCRIPTOR_VISUAL,
    DIMENSION,
    INDICE_CAT_CATEGORIA,
    INDICE_CAT_SUCURSAL,
    INDICE_ORD_ITEM,
    INDICE_ORD_USUARIO,
    INDICE_TEXTO,
    INDICE_VECTORES,
    LARGOS_CATALOGO,
    LARGOS_SUCURSALES,
    LIMITE_PRODUCTOS,
    LOTE_INSERT,
    MAX_ORDENES,
    SUBCARPETA_MULTIMEDIA,
    TABLA_CATALOGO,
    TABLA_ORDENES,
    TABLA_SUCURSALES,
    TABLAS_VISUALES,
    URL_DATASET,
    URL_DATASET_UCSD,
)

SUCURSALES_LIMA = [
    (1, "Tienda Miraflores", "Miraflores", -12.1190, -77.0290),
    (2, "Tienda San Isidro", "San Isidro", -12.0980, -77.0360),
    (3, "Tienda Surco Jockey", "Santiago de Surco", -12.0860, -76.9760),
    (4, "Tienda San Borja", "San Borja", -12.0880, -77.0030),
    (5, "Tienda Barranco", "Barranco", -12.1480, -77.0210),
    (6, "Tienda Salaverry", "Jesús María", -12.0890, -77.0520),
    (7, "Tienda San Miguel", "San Miguel", -12.0770, -77.0820),
    (8, "Tienda Callao Mall", "Callao", -12.0080, -77.1150),
]

COLUMNAS_INSERT_CATALOGO = (
    "id, codigo, nombre, marca, categoria, precio, rating, sucursal_id, imagen, descripcion"
)
_PATRON_PRECIO = re.compile(r"(\d+(?:,\d{3})*(?:\.\d+)?|\d+\.\d+)")
_FECHA_DEFECTO = "2023-01-01"


def sucursal_para(codigo):
    return zlib.crc32(str(codigo).encode("utf-8")) % len(SUCURSALES_LIMA) + 1


def recortar_utf8(texto, limite):
    """Limpia espacios/saltos de línea y ajusta largo de caracteres y bytes UTF-8."""
    if texto is None:
        return None
    limpio = " ".join(str(texto).replace("\x00", "").split())
    if not limpio:
        return ""
    limpio = limpio[:limite]
    while len(limpio.encode("utf-8")) > limite * 4:
        limpio = limpio[:-1]
    return limpio


def parsear_precio(valor):
    if valor is None or isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float)):
        numero = float(valor)
    else:
        texto = str(valor).strip()
        if not texto or texto.lower() in ("none", "null", "nan"):
            return None
        coincidencia = _PATRON_PRECIO.search(texto)
        if not coincidencia:
            return None
        numero = float(coincidencia.group(1).replace(",", ""))
    if not math.isfinite(numero) or numero < 0.0 or numero > 1_000_000.0:
        return None
    return round(numero, 2)


def parsear_fecha(timestamp):
    if timestamp is None or isinstance(timestamp, bool):
        return _FECHA_DEFECTO
    try:
        segundos = float(timestamp)
    except (TypeError, ValueError):
        return _FECHA_DEFECTO
    if not math.isfinite(segundos) or segundos < 0:
        return _FECHA_DEFECTO
    if segundos > 1e11:
        segundos /= 1000.0
    try:
        dt = datetime.fromtimestamp(segundos, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return _FECHA_DEFECTO
    if dt.year < 1990 or dt.year > 2030:
        return _FECHA_DEFECTO
    return dt.strftime("%Y-%m-%d")


def _url_valida(url):
    return isinstance(url, str) and url.strip().startswith(("http://", "https://"))


def _normalizar_entradas_imagen(images):
    if isinstance(images, dict):
        claves = ("large", "hi_res", "thumb", "variant")
        listas = {k: images.get(k) if isinstance(images.get(k), list) else [] for k in claves}
        total = max((len(v) for v in listas.values()), default=0)
        return [
            {k: listas[k][i] if i < len(listas[k]) else None for k in claves}
            for i in range(total)
        ]
    if isinstance(images, list):
        return [item for item in images if isinstance(item, dict)]
    return []


def extraer_url_imagen(images):
    """Soporta images como dict de listas o lista de dicts, priorizando MAIN y large."""
    entradas = _normalizar_entradas_imagen(images)
    ordenadas = sorted(
        entradas,
        key=lambda e: 0 if str(e.get("variant") or "").upper() == "MAIN" else 1,
    )
    for entrada in ordenadas:
        for clave in ("large", "hi_res", "thumb"):
            url = entrada.get(clave)
            if _url_valida(url):
                return url.strip()
    return None


def extraer_categoria(fila, defecto):
    crudo = fila.get("categories") or []
    cats = [c.strip() for c in crudo if isinstance(c, str) and c.strip()]
    if len(cats) >= 2:
        elegida = " > ".join(cats[1:3])
    elif cats:
        elegida = cats[-1]
    else:
        elegida = fila.get("main_category") or defecto
    return recortar_utf8(elegida, LARGOS_CATALOGO["categoria"]) or defecto


def _aplanar_texto(valor):
    if isinstance(valor, str):
        return [valor]
    if isinstance(valor, list):
        return [item for item in valor if isinstance(item, str)]
    return []


def armar_descripcion(fila, categoria):
    partes = []
    for campo in (fila.get("title"), fila.get("store"), categoria):
        if isinstance(campo, str) and campo.strip():
            partes.append(campo)
    partes.extend(_aplanar_texto(fila.get("features")))
    partes.extend(_aplanar_texto(fila.get("description")))
    limpio = " ".join(" ".join(partes).replace("\x00", "").split())
    return limpio or categoria


def carpeta_categoria(categoria):
    carpeta = CARPETA_DATOS / categoria
    carpeta.mkdir(parents=True, exist_ok=True)
    return carpeta


def carpeta_imagenes(categoria):
    carpeta = CARPETA_MULTIMEDIA / SUBCARPETA_MULTIMEDIA / categoria / "imagenes"
    carpeta.mkdir(parents=True, exist_ok=True)
    return carpeta


def _urls_interacciones(categoria):
    return [
        f"{URL_DATASET_UCSD}/benchmark/5core/rating_only/{categoria}.csv.gz",
        f"{URL_DATASET}/benchmark/5core/rating_only/{categoria}.csv",
    ]


def _urls_metadata(categoria):
    return [
        f"{URL_DATASET_UCSD}/raw/meta_categories/meta_{categoria}.jsonl.gz",
        f"{URL_DATASET}/raw/meta_categories/meta_{categoria}.jsonl",
    ]


def _abrir_texto_archivo(ruta):
    if str(ruta).endswith(".gz"):
        return gzip.open(ruta, "rt", encoding="utf-8", errors="replace")
    return open(ruta, "rt", encoding="utf-8", errors="replace")


def descargar_interacciones(categoria, archivo_local=None):
    if archivo_local is not None:
        return Path(archivo_local)
    carpeta = carpeta_categoria(categoria)
    for nombre in (f"{categoria}.csv.gz", f"{categoria}.csv"):
        existente = carpeta / nombre
        if existente.exists() and existente.stat().st_size > 0:
            return existente
    ultimo_error = None
    for url in _urls_interacciones(categoria):
        destino = carpeta / url.rsplit("/", 1)[-1]
        temporal = destino.with_suffix(destino.suffix + ".part")
        try:
            print(f"descargando interacciones {destino.name}...")
            with requests.get(url, stream=True, timeout=180) as respuesta:
                respuesta.raise_for_status()
                with open(temporal, "wb") as archivo:
                    for bloque in respuesta.iter_content(1 << 20):
                        if bloque:
                            archivo.write(bloque)
            temporal.rename(destino)
            return destino
        except requests.RequestException as error:
            ultimo_error = error
            if temporal.exists():
                temporal.unlink()
    raise RuntimeError(f"no se pudo descargar interacciones para '{categoria}': {ultimo_error}")


def _indices_csv(primera_fila):
    if primera_fila and primera_fila[0].strip().lower() == "user_id":
        mapa = {col.strip().lower(): i for i, col in enumerate(primera_fila)}
        return True, (mapa["user_id"], mapa["parent_asin"], mapa["rating"], mapa["timestamp"])
    return False, (0, 1, 2, 3)


def _iterar_filas_interacciones(ruta):
    with _abrir_texto_archivo(ruta) as archivo:
        lector = csv.reader(archivo)
        primera = next(lector, None)
        if primera is None:
            return
        tiene_cabecera, (i_usr, i_asin, i_rat, i_ts) = _indices_csv(primera)
        filas = lector if tiene_cabecera else [primera, *lector]
        for fila in filas:
            if len(fila) <= max(i_usr, i_asin, i_rat, i_ts):
                continue
            usr = fila[i_usr].strip()
            asin = fila[i_asin].strip()
            if not usr or not asin:
                continue
            try:
                rating = float(fila[i_rat])
            except ValueError:
                continue
            if not math.isfinite(rating) or rating < 3.0:
                continue
            yield usr, asin, fila[i_ts].strip()


def leer_interacciones(ruta, limite):
    """Selecciona los ASIN más populares y recoge sus interacciones válidas en streaming."""
    conteo = Counter()
    for _, asin, _ in _iterar_filas_interacciones(ruta):
        conteo[asin] += 1
    tam_pool = max(limite * 3, 2000)
    ordenados = sorted(conteo.items(), key=lambda par: (-par[1], par[0]))[:tam_pool]
    asins_objetivo = [asin for asin, _ in ordenados]
    conjunto = set(asins_objetivo)
    interacciones = [
        (usr, asin, ts)
        for usr, asin, ts in _iterar_filas_interacciones(ruta)
        if asin in conjunto
    ]
    return asins_objetivo, interacciones


def _iterar_lineas_http(url):
    with requests.get(url, stream=True, timeout=180) as respuesta:
        respuesta.raise_for_status()
        decomp = None
        buffer = b""
        primero = True
        for chunk in respuesta.iter_content(chunk_size=65536):
            if not chunk:
                continue
            if primero:
                primero = False
                if chunk.startswith(b"\x1f\x8b"):
                    decomp = zlib.decompressobj(16 + zlib.MAX_WBITS)
            datos = decomp.decompress(chunk) if decomp is not None else chunk
            buffer += datos
            while b"\n" in buffer:
                linea, buffer = buffer.split(b"\n", 1)
                yield linea.decode("utf-8", errors="replace")
        if decomp is not None:
            buffer += decomp.flush()
        if buffer.strip():
            yield buffer.decode("utf-8", errors="replace")


def _parsear_candidato_meta(fila, categoria_defecto):
    asin = fila.get("parent_asin") or fila.get("asin")
    if not asin:
        return None
    titulo = recortar_utf8(fila.get("title"), LARGOS_CATALOGO["nombre"])
    if not titulo:
        return None
    url_imagen = extraer_url_imagen(fila.get("images"))
    if url_imagen is None:
        return None
    categoria = extraer_categoria(fila, categoria_defecto)
    rating_crudo = fila.get("average_rating")
    rating = None
    if rating_crudo is not None and not isinstance(rating_crudo, bool):
        try:
            r = float(rating_crudo)
            if math.isfinite(r) and 0.0 <= r <= 5.0:
                rating = round(r, 2)
        except (TypeError, ValueError):
            pass
    return {
        "codigo": recortar_utf8(asin, LARGOS_CATALOGO["codigo"]),
        "asin": str(asin),
        "nombre": titulo,
        "marca": recortar_utf8(fila.get("store"), LARGOS_CATALOGO["marca"]) or "Genérico",
        "categoria": categoria,
        "precio": parsear_precio(fila.get("price")),
        "rating": rating,
        "url_imagen": url_imagen,
        "descripcion": armar_descripcion(fila, categoria),
    }


def _recolectar_metadata(lineas, asins_objetivo, cantidad_meta, categoria_defecto):
    ranking = {asin: pos for pos, asin in enumerate(asins_objetivo)}
    meta_objetivo = min(cantidad_meta, len(ranking))
    vistos = {}
    for linea in lineas:
        if not linea.strip():
            continue
        try:
            fila = json.loads(linea)
        except json.JSONDecodeError:
            continue
        asin = str(fila.get("parent_asin") or fila.get("asin") or "")
        if asin not in ranking or asin in vistos:
            continue
        candidato = _parsear_candidato_meta(fila, categoria_defecto)
        if candidato is not None:
            vistos[asin] = candidato
            if len(vistos) >= meta_objetivo:
                break
    return [vistos[a] for a in asins_objetivo if a in vistos]


def leer_metadata_streaming(categoria, asins_objetivo, cantidad_meta, archivo_local=None):
    """Lee metadata en streaming hasta recolectar cantidad_meta candidatos válidos."""
    if not asins_objetivo:
        return []
    carpeta = carpeta_categoria(categoria)
    cache = carpeta / f"metadata_{cantidad_meta}.jsonl"
    if archivo_local is None and cache.exists() and cache.stat().st_size > 0:
        with open(cache, encoding="utf-8") as archivo:
            return [json.loads(linea) for linea in archivo if linea.strip()]

    if archivo_local is not None:
        with _abrir_texto_archivo(archivo_local) as archivo:
            return _recolectar_metadata(archivo, asins_objetivo, cantidad_meta, categoria)

    ultimo_error = None
    candidatos = []
    for url in _urls_metadata(categoria):
        try:
            print(f"leyendo metadata en streaming desde {url.rsplit('/', 1)[-1]}...")
            candidatos = _recolectar_metadata(
                _iterar_lineas_http(url), asins_objetivo, cantidad_meta, categoria
            )
            break
        except requests.RequestException as error:
            ultimo_error = error
    else:
        raise RuntimeError(f"no se pudo leer metadata para '{categoria}': {ultimo_error}")

    if candidatos:
        temporal = cache.with_suffix(".jsonl.part")
        with open(temporal, "w", encoding="utf-8") as archivo:
            for item in candidatos:
                archivo.write(json.dumps(item, ensure_ascii=False) + "\n")
        temporal.rename(cache)
    return candidatos


def _preparar_imagen_local(candidato, carpeta_img, categoria):
    asin = candidato["asin"]
    destino = carpeta_img / f"{asin}.jpg"
    temporal = destino.with_suffix(".jpg.part")
    if destino.exists() and destino.stat().st_size > 0:
        try:
            with Image.open(destino) as img:
                img.verify()
        except Exception:
            destino.unlink(missing_ok=True)
    if not destino.exists():
        try:
            respuesta = requests.get(candidato["url_imagen"], timeout=20)
            respuesta.raise_for_status()
            with Image.open(io.BytesIO(respuesta.content)) as img:
                with img.convert("RGB") as rgb:
                    rgb.thumbnail((384, 384))
                    rgb.save(temporal, format="JPEG", quality=85)
            temporal.rename(destino)
        except Exception:
            temporal.unlink(missing_ok=True)
            return None
    producto = dict(candidato)
    producto["ruta_imagen"] = str(destino)
    producto["imagen"] = recortar_utf8(
        f"{SUBCARPETA_MULTIMEDIA}/{categoria}/imagenes/{asin}.jpg",
        LARGOS_CATALOGO["imagen"],
    )
    return producto


def descargar_imagenes(candidatos, carpeta_img, limite, hilos=8, categoria=None):
    """Descarga/valida miniaturas locales por lotes y asigna id secuencial y sucursal."""
    if limite <= 0:
        return []
    carpeta_img = Path(carpeta_img)
    carpeta_img.mkdir(parents=True, exist_ok=True)
    nombre_cat = categoria or carpeta_img.parent.name
    productos = []
    indice = 0
    with ThreadPoolExecutor(max_workers=hilos) as pool:
        while indice < len(candidatos) and len(productos) < limite:
            tam = limite - len(productos)
            lote = candidatos[indice:indice + tam]
            indice += tam
            for producto in pool.map(
                lambda c: _preparar_imagen_local(c, carpeta_img, nombre_cat), lote
            ):
                if producto is None:
                    continue
                producto["id"] = len(productos) + 1
                producto["sucursal_id"] = sucursal_para(producto["codigo"])
                productos.append(producto)
                if len(productos) >= limite:
                    break
    return productos


def construir_ordenes(interacciones, mapa_asin_id, max_ordenes=MAX_ORDENES):
    """Genera órdenes deduplicadas reteniendo solo usuarios con >= 2 ítems del catálogo."""
    if max_ordenes <= 0:
        return []
    por_usuario = {}
    for usr, asin, ts in interacciones:
        item_id = mapa_asin_id.get(asin)
        if item_id is None:
            continue
        pares = por_usuario.setdefault(usr, {})
        if item_id not in pares:
            pares[item_id] = ts

    usuarios_ricos = [
        (usr, pares) for usr, pares in por_usuario.items() if len(pares) >= 2
    ]
    usuarios_ricos.sort(key=lambda par: (-len(par[1]), par[0]))

    ordenes = []
    for uid, (_, pares) in enumerate(usuarios_ricos, start=1):
        items_usuario = sorted(pares.items(), key=lambda par: par[0])
        if ordenes and len(ordenes) + len(items_usuario) > max_ordenes:
            break
        for item_id, ts in items_usuario:
            if len(ordenes) >= max_ordenes:
                break
            ordenes.append({
                "id": len(ordenes) + 1,
                "usuario_id": uid,
                "item_id": item_id,
                "fecha": parsear_fecha(ts),
            })
        if len(ordenes) >= max_ordenes:
            break
    return ordenes


def crear_tablas():
    bd.ejecutar(
        f"DROP TABLE IF EXISTS {TABLA_ORDENES}; "
        f"DROP TABLE IF EXISTS {TABLA_CATALOGO}; "
        f"DROP TABLE IF EXISTS {TABLA_SUCURSALES};"
    )
    bd.ejecutar(
        f"CREATE TABLE {TABLA_SUCURSALES} ("
        f"id INT PRIMARY KEY, "
        f"nombre VARCHAR({LARGOS_SUCURSALES['nombre']}), "
        f"distrito VARCHAR({LARGOS_SUCURSALES['distrito']}), "
        f"ubicacion POINT"
        f") USING BPLUS;"
    )
    bd.ejecutar(_ddl_catalogo(TABLA_CATALOGO, DIMENSION))
    bd.ejecutar(
        f"CREATE TABLE {TABLA_ORDENES} ("
        f"id INT PRIMARY KEY, "
        f"usuario_id INT, "
        f"item_id INT, "
        f"fecha DATE"
        f") USING BPLUS;"
    )


def _ddl_catalogo(tabla, dimension):
    return (
        f"CREATE TABLE {tabla} ("
        f"id INT PRIMARY KEY, "
        f"codigo VARCHAR({LARGOS_CATALOGO['codigo']}), "
        f"nombre VARCHAR({LARGOS_CATALOGO['nombre']}), "
        f"marca VARCHAR({LARGOS_CATALOGO['marca']}), "
        f"categoria VARCHAR({LARGOS_CATALOGO['categoria']}), "
        f"precio FLOAT, "
        f"rating FLOAT, "
        f"sucursal_id INT, "
        f"imagen VARCHAR({LARGOS_CATALOGO['imagen']}), "
        f"descripcion TEXT, "
        f"emb VECTOR({dimension})"
        f") USING BPLUS;"
    )


def insertar_por_lotes(tabla, filas, formatear, columnas=None):
    cabecera = f"INSERT INTO {tabla} ({columnas}) VALUES " if columnas else f"INSERT INTO {tabla} VALUES "
    for inicio in range(0, len(filas), LOTE_INSERT):
        bloque = filas[inicio:inicio + LOTE_INSERT]
        valores = ", ".join(formatear(fila) for fila in bloque)
        bd.ejecutar(cabecera + valores + ";")
        hechos = min(inicio + LOTE_INSERT, len(filas))
        if hechos % (LOTE_INSERT * 25) == 0 or hechos == len(filas):
            print(f"  {tabla}: {hechos}/{len(filas)}")


def _fila_sucursal(sucursal):
    return (
        f"({bd.numero_sql(sucursal[0])}, {bd.texto_sql(sucursal[1])}, "
        f"{bd.texto_sql(sucursal[2])}, {bd.punto_sql(sucursal[3], sucursal[4])})"
    )


def _fila_producto(producto):
    partes = [
        bd.numero_sql(producto["id"]),
        bd.texto_sql(producto["codigo"]),
        bd.texto_sql(producto["nombre"]),
        bd.texto_sql(producto["marca"]),
        bd.texto_sql(producto["categoria"]),
        bd.numero_sql(producto["precio"]),
        bd.numero_sql(producto["rating"]),
        bd.numero_sql(producto["sucursal_id"]),
        bd.texto_sql(producto["imagen"]),
        bd.texto_sql(producto["descripcion"]),
    ]
    return "(" + ", ".join(partes) + ")"


def _fila_orden(orden):
    return (
        f"({bd.numero_sql(orden['id'])}, {bd.numero_sql(orden['usuario_id'])}, "
        f"{bd.numero_sql(orden['item_id'])}, {bd.texto_sql(orden['fecha'])})"
    )


def crear_indices():
    consultas = [
        f"CREATE INDEX {INDICE_CAT_CATEGORIA} ON {TABLA_CATALOGO} (categoria) USING BPLUS;",
        f"CREATE INDEX {INDICE_CAT_SUCURSAL} ON {TABLA_CATALOGO} (sucursal_id) USING BPLUS;",
        f"CREATE INDEX {INDICE_TEXTO} ON {TABLA_CATALOGO} (descripcion) USING FULLTEXT;",
        f"CREATE INDEX {INDICE_VECTORES} ON {TABLA_CATALOGO} (emb) USING HNSW WITH (METRIC=cosine);",
        f"CREATE INDEX {INDICE_ORD_USUARIO} ON {TABLA_ORDENES} (usuario_id) USING BPLUS;",
        f"CREATE INDEX {INDICE_ORD_ITEM} ON {TABLA_ORDENES} (item_id) USING BPLUS;",
    ]
    for sql in consultas:
        print(" ", bd.ejecutar(sql)["message"])


def analizar_tablas():
    bd.ejecutar(
        f"ANALYZE {TABLA_SUCURSALES}; "
        f"ANALYZE {TABLA_CATALOGO}; "
        f"ANALYZE {TABLA_ORDENES};"
    )


def cargar(productos, ordenes):
    """Recrea tablas, extrae SIFT+BoVW+TF-IDF en el motor y construye los índices."""
    crear_tablas()
    insertar_por_lotes(TABLA_SUCURSALES, SUCURSALES_LIMA, _fila_sucursal)
    insertar_por_lotes(
        TABLA_CATALOGO, productos, _fila_producto, columnas=COLUMNAS_INSERT_CATALOGO
    )
    if ordenes:
        insertar_por_lotes(TABLA_ORDENES, ordenes, _fila_orden)
    print(f"extrayendo características visuales ({DESCRIPTOR_VISUAL}) en el motor...")
    res_feat = bd.cargar_caracteristicas(TABLA_CATALOGO, "imagen", DESCRIPTOR_VISUAL)
    print(" ", res_feat.get("message", f"{len(productos)} filas vectorizadas"))
    print("creando índices (B+, FULLTEXT, HNSW)...")
    crear_indices()
    analizar_tablas()


def _vectores_visuales(modelo, productos):
    rutas = [CARPETA_MULTIMEDIA / p["imagen"] for p in productos]
    if modelo == "clip":
        return visuales.vectores_clip(rutas)
    # sift4096: histogramas del catálogo -> IDF propio de esta tabla -> TF-IDF por producto
    histogramas = np.array([visuales.histograma_sift4096(ruta) for ruta in rutas])
    tfidf = visuales.ajustar_tfidf_sift4096(histogramas)
    return np.array([tfidf.transformar(h) for h in histogramas])


def cargar_visuales(modelos, lote=10):
    """Copia 'catalogo' a una tabla por modelo con su vector calculado en la app e índice HNSW."""
    productos = bd.filas(f"SELECT {COLUMNAS_INSERT_CATALOGO} FROM {TABLA_CATALOGO} ORDER BY id;")
    if not productos:
        raise SystemExit("el catálogo está vacío; corre primero la ingesta completa")
    for modelo in modelos:
        tabla = TABLAS_VISUALES[modelo]
        inicio = time.time()
        print(f"vectorizando {len(productos)} imágenes con {modelo} en la app...")
        vectores = _vectores_visuales(modelo, productos)
        print(f"  {vectores.shape[1]} dimensiones en {time.time() - inicio:.0f} s")
        bd.ejecutar(f"DROP TABLE IF EXISTS {tabla};")
        bd.ejecutar(_ddl_catalogo(tabla, vectores.shape[1]))
        filas = [{**p, "emb": v} for p, v in zip(productos, vectores)]
        # lotes chicos: cada fila lleva hasta 4096 números en el SQL
        for i in range(0, len(filas), lote):
            bloque = filas[i:i + lote]
            valores = ", ".join(
                _fila_producto(f)[:-1] + ", " + bd.vector_sql(f["emb"]) + ")" for f in bloque
            )
            bd.ejecutar(f"INSERT INTO {tabla} ({COLUMNAS_INSERT_CATALOGO}, emb) VALUES {valores};")
        print(" ", bd.ejecutar(
            f"CREATE INDEX hnsw_{tabla} ON {tabla} (emb) USING HNSW WITH (METRIC=cosine);"
        )["message"])
        bd.ejecutar(f"ANALYZE {tabla};")
        print(f"  {tabla} lista en {time.time() - inicio:.0f} s")


def main():
    parser = argparse.ArgumentParser(description="Ingesta de Amazon Reviews 2023 al motor BD2")
    parser.add_argument("--categoria", default=CATEGORIA_DATASET)
    parser.add_argument("--limite", type=int, default=LIMITE_PRODUCTOS)
    parser.add_argument("--max-ordenes", type=int, default=MAX_ORDENES)
    parser.add_argument("--sin-cargar", action="store_true")
    parser.add_argument("--archivo-interacciones", default=None)
    parser.add_argument("--archivo-meta", default=None)
    parser.add_argument(
        "--visuales", default=None,
        help="solo crea las tablas de modelos visuales extra sobre el catálogo ya cargado (ej. sift4096,clip)",
    )
    argumentos = parser.parse_args()

    if not argumentos.sin_cargar and not bd.disponible():
        raise SystemExit("el motor no responde; levanta el backend en el puerto configurado")
    if argumentos.visuales:
        modelos = [m.strip() for m in argumentos.visuales.split(",") if m.strip()]
        invalidos = [m for m in modelos if m not in TABLAS_VISUALES or m == "sift256"]
        if invalidos:
            raise SystemExit(f"modelos inválidos {invalidos}; usa sift4096 y/o clip")
        cargar_visuales(modelos)
        return

    inicio = time.time()
    ruta_inter = descargar_interacciones(argumentos.categoria, argumentos.archivo_interacciones)
    asins_objetivo, interacciones = leer_interacciones(ruta_inter, argumentos.limite)
    print(f"{len(asins_objetivo)} ASINs candidatos y {len(interacciones)} interacciones")

    cantidad_meta = max(argumentos.limite, int(argumentos.limite * 1.5))
    candidatos = leer_metadata_streaming(
        argumentos.categoria, asins_objetivo, cantidad_meta, argumentos.archivo_meta
    )
    print(f"{len(candidatos)} candidatos con metadata e imagen")

    carpeta_img = carpeta_imagenes(argumentos.categoria)
    productos = descargar_imagenes(
        candidatos, carpeta_img, argumentos.limite, categoria=argumentos.categoria
    )
    if not productos:
        raise SystemExit("no se pudo descargar ninguna imagen válida del catálogo")
    mapa_asin_id = {p["asin"]: p["id"] for p in productos}
    ordenes = construir_ordenes(interacciones, mapa_asin_id, argumentos.max_ordenes)
    print(f"{len(productos)} productos y {len(ordenes)} órdenes listos")

    if not argumentos.sin_cargar:
        cargar(productos, ordenes)
    print(f"listo en {time.time() - inicio:.0f} s")


if __name__ == "__main__":
    main()
