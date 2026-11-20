import math
import re
import time

import cliente_bd as bd
from config import (
    ESCALA_ESPACIAL_M,
    FUSION_DEFECTO,
    FUSIONES,
    K_CANDIDATOS,
    K_RECOMENDACIONES,
    K_SUCURSALES_KNN,
    METODO_VECTORIAL,
    PESO_ESPACIAL_DEFECTO,
    PESOS_DEFECTO,
    RRF_K,
    TABLA_CATALOGO,
    TABLA_ORDENES,
    TABLA_SUCURSALES,
)

MODOS = ("hibrido", "cocompra", "visual", "texto", "metadata", "espacial")
MODOS_BUSQUEDA = ("bm25", "tf_idf")
COLUMNAS_PRODUCTO = (
    "id, codigo, nombre, marca, categoria, precio, rating, sucursal_id, imagen, descripcion"
)
MAX_PALABRAS_TEXTO = 25
_RADIO_TIERRA_M = 6_371_000.0
_PATRON_PALABRAS = re.compile(r"[0-9A-Za-zÁÉÍÓÚáéíóúÑñÜü]+")


def distancia_metros(lat1, lon1, lat2, lon2):
    """Distancia Haversine en metros entre dos coordenadas geográficas."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    hav = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * _RADIO_TIERRA_M * math.asin(math.sqrt(min(1.0, max(0.0, hav))))


def _sucursal_de_fila(fila):
    ubicacion = fila.get("ubicacion")
    lat = float(ubicacion[0]) if ubicacion is not None else None
    lon = float(ubicacion[1]) if ubicacion is not None else None
    return {
        "id": fila["id"],
        "nombre": fila["nombre"],
        "distrito": fila["distrito"],
        "lat": lat,
        "lon": lon,
    }


def listar_sucursales():
    filas = bd.filas(f"SELECT id, nombre, distrito, ubicacion FROM {TABLA_SUCURSALES} ORDER BY id;")
    return [_sucursal_de_fila(fila) for fila in filas]


def _mapa_sucursales():
    return {suc["id"]: suc for suc in listar_sucursales()}


def sucursales_cercanas(lat, lon, radio_m):
    sql = (
        f"SELECT id, nombre, distrito, ubicacion FROM {TABLA_SUCURSALES} "
        f"WHERE distancia(ubicacion, {bd.punto_sql(lat, lon)}) < {bd.numero_sql(float(radio_m))};"
    )
    salida = []
    for fila in bd.filas(sql):
        suc = _sucursal_de_fila(fila)
        suc["distancia_m"] = round(distancia_metros(lat, lon, suc["lat"], suc["lon"]), 1)
        salida.append(suc)
    salida.sort(key=lambda s: (s["distancia_m"], s["id"]))
    return salida


def sucursales_en_zona(zona):
    """Tiendas dentro del rectángulo (sur, oeste, norte, este) vía RTREE-polygon."""
    sur, oeste, norte, este = zona
    vertices = ((sur, oeste), (norte, oeste), (norte, este), (sur, este))
    poligono = "POLYGON(" + ", ".join(bd.punto_sql(lat, lon) for lat, lon in vertices) + ")"
    sql = (
        f"SELECT id, nombre, distrito, ubicacion FROM {TABLA_SUCURSALES} "
        f"WHERE intersecta(ubicacion, {poligono});"
    )
    salida = [_sucursal_de_fila(fila) for fila in bd.filas(sql)]
    salida.sort(key=lambda s: s["id"])
    return salida


def sucursales_knn(lat, lon, k=K_SUCURSALES_KNN, ids_sucursales=None):
    if int(k) <= 0:
        return []
    lat_f, lon_f = float(lat), float(lon)
    sql = (
        f"SELECT id, nombre, distrito, ubicacion FROM {TABLA_SUCURSALES} "
        f"ORDER BY distancia(ubicacion, {bd.punto_sql(lat_f, lon_f)}) LIMIT {int(k)};"
    )
    permitidas = set(ids_sucursales) if ids_sucursales is not None else None
    salida = []
    for fila in bd.filas(sql):
        suc = _sucursal_de_fila(fila)
        if permitidas is not None and suc["id"] not in permitidas:
            continue
        suc["distancia_m"] = round(distancia_metros(lat_f, lon_f, suc["lat"], suc["lon"]), 1)
        salida.append(suc)
    salida.sort(key=lambda s: (s["distancia_m"], s["id"]))
    return salida


def listar_categorias():
    filas = bd.filas(f"SELECT categoria, COUNT(*) FROM {TABLA_CATALOGO} GROUP BY categoria;")
    salida = [
        {"categoria": fila["categoria"], "productos": fila["conteo"]}
        for fila in filas
        if fila.get("categoria")
    ]
    salida.sort(key=lambda c: c["categoria"])
    return salida


def _enriquecer_sucursal(filas, mapa_sucursales, lat=None, lon=None):
    salida = []
    con_ubicacion = lat is not None and lon is not None
    for fila in filas:
        item = dict(fila)
        suc = mapa_sucursales.get(item.get("sucursal_id"))
        item["sucursal"] = suc
        if con_ubicacion and suc and suc["lat"] is not None and suc["lon"] is not None:
            item["distancia_m"] = round(
                distancia_metros(float(lat), float(lon), suc["lat"], suc["lon"]), 1
            )
        else:
            item["distancia_m"] = None
        salida.append(item)
    return salida


def obtener_producto(item_id, lat=None, lon=None, mapa_sucursales=None):
    filas = bd.filas(
        f"SELECT {COLUMNAS_PRODUCTO} FROM {TABLA_CATALOGO} WHERE id = {bd.numero_sql(int(item_id))};"
    )
    if not filas:
        return None
    return _enriquecer_sucursal(filas, mapa_sucursales or _mapa_sucursales(), lat=lat, lon=lon)[0]


def _clausulas_filtro(filtros, excluir_id=None, ids_sucursales=None):
    filtros = filtros or {}
    clausulas = []
    if excluir_id is not None:
        clausulas.append(f"id != {bd.numero_sql(int(excluir_id))}")
    if filtros.get("categoria"):
        clausulas.append(f"categoria = {bd.texto_sql(filtros['categoria'])}")
    if filtros.get("precio_min") is not None:
        clausulas.append(f"precio >= {bd.numero_sql(float(filtros['precio_min']))}")
    if filtros.get("precio_max") is not None:
        clausulas.append(f"precio <= {bd.numero_sql(float(filtros['precio_max']))}")
    if ids_sucursales is not None:
        clausulas.append(f"sucursal_id IN {bd.lista_sql(ids_sucursales)}")
    return clausulas


def _sufijo_and(clausulas):
    if not clausulas:
        return ""
    return " AND " + " AND ".join(clausulas)


def _resolver_espacial(filtros):
    lat = filtros.get("lat")
    lon = filtros.get("lon")
    radio_m = filtros.get("radio_m")
    zona = filtros.get("zona")
    seleccion = None
    if lat is not None and lon is not None and radio_m is not None:
        seleccion = sucursales_cercanas(float(lat), float(lon), float(radio_m))
    if zona is not None:
        en_zona = sucursales_en_zona(zona)
        if seleccion is None:
            seleccion = en_zona
        else:
            ids_zona = {s["id"] for s in en_zona}
            seleccion = [s for s in seleccion if s["id"] in ids_zona]
    if seleccion is None:
        return None, []
    return [s["id"] for s in seleccion], seleccion


def listar_productos(
    categoria=None,
    precio_min=None,
    precio_max=None,
    orden="rating",
    limite=24,
    pagina=1,
    lat=None,
    lon=None,
    radio_m=None,
    zona=None,
):
    if orden == "cercania" and (lat is None or lon is None):
        raise ValueError("el orden 'cercania' requiere fijar una ubicación (lat y lon)")
    filtros = {
        "categoria": categoria,
        "precio_min": precio_min,
        "precio_max": precio_max,
        "lat": lat,
        "lon": lon,
        "radio_m": radio_m,
        "zona": zona,
    }
    ids_sucursales, cercanas = _resolver_espacial(filtros)
    if ids_sucursales is not None and not ids_sucursales:
        return {
            "productos": [],
            "sucursales_en_radio": [],
            "pagina": pagina,
            "limite": limite,
            "hay_mas": False,
        }
    ordenes = {
        "rating": "rating DESC",
        "precio_asc": "precio ASC",
        "precio_desc": "precio DESC",
        "id": "id ASC",
    }
    clausula_orden = ordenes.get(orden, "rating DESC")
    mapa_sucursales = _mapa_sucursales()
    tope = int(pagina) * int(limite) + 1
    if orden == "cercania":
        filas = _productos_por_cercania(filtros, ids_sucursales, tope, len(mapa_sucursales))
    else:
        clausulas = _clausulas_filtro(filtros, ids_sucursales=ids_sucursales)
        if orden in ("precio_asc", "precio_desc") and precio_min is None and precio_max is None:
            clausulas.append("precio IS NOT NULL")
        where = (" WHERE " + " AND ".join(clausulas)) if clausulas else ""
        filas = bd.filas(
            f"SELECT {COLUMNAS_PRODUCTO} FROM {TABLA_CATALOGO}{where} "
            f"ORDER BY {clausula_orden} LIMIT {tope};"
        )
    inicio = (int(pagina) - 1) * int(limite)
    fin = inicio + int(limite)
    hay_mas = len(filas) > fin
    pagina_filas = _enriquecer_sucursal(
        filas[inicio:fin], mapa_sucursales, lat=lat, lon=lon
    )
    return {
        "productos": pagina_filas,
        "sucursales_en_radio": cercanas,
        "pagina": pagina,
        "limite": limite,
        "hay_mas": hay_mas,
    }


def _productos_por_cercania(filtros, ids_sucursales, tope, total_sucursales):
    """Catálogo por bloques de tienda: RTREE-knn ordena las tiendas y cada bloque sale
    por idx_cat_sucursal, sin JOIN ni sort externo de todo el catálogo."""
    tiendas = sucursales_knn(
        filtros["lat"], filtros["lon"], k=total_sucursales, ids_sucursales=ids_sucursales
    )
    clausulas = _clausulas_filtro(filtros)
    filas = []
    for suc in tiendas:
        faltan = tope - len(filas)
        if faltan <= 0:
            break
        filas.extend(bd.filas(
            f"SELECT {COLUMNAS_PRODUCTO} FROM {TABLA_CATALOGO} "
            f"WHERE sucursal_id = {bd.numero_sql(int(suc['id']))}{_sufijo_and(clausulas)} "
            f"ORDER BY rating DESC LIMIT {int(faltan)};"
        ))
    return filas


def cocompra(item_id, k, filtros=None, ids_sucursales=None, max_usuario_id=None):
    if max_usuario_id is not None and int(max_usuario_id) <= 0:
        return []
    filtros = filtros or {}
    hay_filtros_cat = (
        bool(filtros.get("categoria"))
        or filtros.get("precio_min") is not None
        or filtros.get("precio_max") is not None
        or ids_sucursales is not None
    )
    limite_ord = int(k) * 3 if hay_filtros_cat else int(k)
    cond_train = (
        f" AND o1.usuario_id <= {bd.numero_sql(int(max_usuario_id))}"
        if max_usuario_id is not None
        else ""
    )
    sql_ord = (
        f"SELECT o2.item_id, COUNT(*) FROM {TABLA_ORDENES} AS o1 "
        f"JOIN {TABLA_ORDENES} AS o2 ON o1.usuario_id = o2.usuario_id "
        f"WHERE o1.item_id = {bd.numero_sql(int(item_id))} "
        f"AND o2.item_id != {bd.numero_sql(int(item_id))}{cond_train} "
        f"GROUP BY o2.item_id ORDER BY conteo DESC LIMIT {limite_ord};"
    )
    pares = [(r["o2.item_id"], r["conteo"]) for r in bd.filas(sql_ord)]
    if not pares:
        return []
    clausulas = _clausulas_filtro(filtros, excluir_id=item_id, ids_sucursales=ids_sucursales)
    ids_cand = [pid for pid, _ in pares]
    sql_cat = (
        f"SELECT {COLUMNAS_PRODUCTO} FROM {TABLA_CATALOGO} "
        f"WHERE id IN {bd.lista_sql(ids_cand)}{_sufijo_and(clausulas)};"
    )
    por_id = {fila["id"]: fila for fila in bd.filas(sql_cat)}
    salida = []
    for pid, conteo in pares:
        fila = por_id.get(pid)
        if fila is None:
            continue
        item = dict(fila)
        item["cocompras"] = conteo
        item["puntaje"] = float(conteo)
        salida.append(item)
        if len(salida) >= k:
            break
    return salida


def metadata(producto, k, filtros=None, ids_sucursales=None):
    filtros_meta = dict(filtros or {})
    if not filtros_meta.get("categoria") and producto.get("categoria"):
        filtros_meta["categoria"] = producto["categoria"]

    def consultar(f, bono=0.0):
        clausulas = _clausulas_filtro(f, excluir_id=producto["id"], ids_sucursales=ids_sucursales)
        where = " AND ".join(clausulas)
        filas = bd.filas(
            f"SELECT {COLUMNAS_PRODUCTO} FROM {TABLA_CATALOGO} "
            f"WHERE {where} ORDER BY rating DESC LIMIT {int(k)};"
        )
        salida = []
        for fila in filas:
            item = dict(fila)
            item["puntaje"] = round(float(item.get("rating") or 3.0) / 5.0 + bono, 4)
            salida.append(item)
        return salida

    tiene_rango = filtros_meta.get("precio_min") is not None or filtros_meta.get("precio_max") is not None
    precio = producto.get("precio")
    if not tiene_rango and precio is not None and precio > 0:
        banda = dict(filtros_meta)
        banda["precio_min"] = round(precio * 0.5, 2)
        banda["precio_max"] = round(precio * 1.8, 2)
        filas = consultar(banda, bono=0.2)
        if len(filas) < k:
            vistos = {fila["id"] for fila in filas}
            for extra in consultar(filtros_meta, bono=0.0):
                if extra["id"] not in vistos:
                    filas.append(extra)
                    vistos.add(extra["id"])
                    if len(filas) >= k:
                        break
        return filas
    return consultar(filtros_meta, bono=0.0)


def visual(
    ruta_imagen,
    k,
    filtros=None,
    excluir_id=None,
    ids_sucursales=None,
    metodo=METODO_VECTORIAL,
):
    if not ruta_imagen:
        return []
    clausulas = _clausulas_filtro(filtros, excluir_id=excluir_id, ids_sucursales=ids_sucursales)
    sql = (
        f"SELECT {COLUMNAS_PRODUCTO}, SIMILARITY_SCORE() AS puntaje FROM {TABLA_CATALOGO} "
        f"WHERE SIMILAR_TO({bd.texto_sql(ruta_imagen)}, k={int(k)}){_sufijo_and(clausulas)} "
        f"USING {metodo} WITH METRIC=cosine;"
    )
    return bd.filas(sql)


def texto(consulta, k, filtros=None, excluir_id=None, ids_sucursales=None, ranking="BM25"):
    if ranking not in ("BM25", "TF_IDF"):
        raise ValueError(f"ranking desconocido '{ranking}'; usa BM25 o TF_IDF")
    palabras = _PATRON_PALABRAS.findall(str(consulta or ""))
    consulta_limpia = " ".join(palabras[:MAX_PALABRAS_TEXTO])
    if not consulta_limpia:
        return []
    clausulas = _clausulas_filtro(filtros, excluir_id=excluir_id, ids_sucursales=ids_sucursales)
    sql = (
        f"SELECT {COLUMNAS_PRODUCTO}, SCORE() AS puntaje FROM {TABLA_CATALOGO} "
        f"WHERE MATCH(descripcion, {bd.texto_sql(consulta_limpia)}){_sufijo_and(clausulas)} "
        f"USING {ranking} LIMIT {int(k)};"
    )
    try:
        return bd.filas(sql)
    except bd.ErrorMotor:
        return []


def espacial(producto, k, lat, lon, filtros=None, ids_sucursales=None, candidatos=None):
    cercanas_knn = sucursales_knn(lat, lon, k=K_SUCURSALES_KNN, ids_sucursales=ids_sucursales)
    if not cercanas_knn:
        return [], []
    puntaje_por_suc = {
        suc["id"]: 1.0 / (1.0 + suc["distancia_m"] / ESCALA_ESPACIAL_M)
        for suc in cercanas_knn
    }
    dist_por_suc = {suc["id"]: suc["distancia_m"] for suc in cercanas_knn}

    if candidatos:
        salida = []
        for fila in candidatos.values():
            sid = fila.get("sucursal_id")
            if sid not in puntaje_por_suc:
                continue
            item = dict(fila)
            item["puntaje"] = round(puntaje_por_suc[sid], 6)
            item["distancia_m"] = dist_por_suc[sid]
            salida.append(item)
        salida.sort(key=lambda r: (-r["puntaje"], -(r.get("rating") or 0.0), r["id"]))
        return salida, cercanas_knn

    filtros_base = dict(filtros or {})
    pasadas = [filtros_base]
    if not filtros_base.get("categoria") and producto.get("categoria"):
        filtros_cat = dict(filtros_base)
        filtros_cat["categoria"] = producto["categoria"]
        pasadas = [filtros_cat, filtros_base]

    salida = []
    vistos = set()
    for f_pasada in pasadas:
        for suc in cercanas_knn:
            faltan = int(k) - len(salida)
            if faltan <= 0:
                break
            sid = suc["id"]
            clausulas = _clausulas_filtro(
                f_pasada, excluir_id=producto["id"], ids_sucursales=[sid]
            )
            where = " AND ".join(clausulas)
            # Margen para no quedarse corto si la primera pasada ya tomó filas de esta sucursal
            vistos_suc = sum(1 for item in salida if item.get("sucursal_id") == sid)
            limite_q = min(int(k), faltan + vistos_suc)
            filas = bd.filas(
                f"SELECT {COLUMNAS_PRODUCTO} FROM {TABLA_CATALOGO} "
                f"WHERE {where} ORDER BY rating DESC LIMIT {limite_q};"
            )
            for fila in filas:
                if fila["id"] in vistos:
                    continue
                vistos.add(fila["id"])
                item = dict(fila)
                item["puntaje"] = round(puntaje_por_suc[sid], 6)
                item["distancia_m"] = dist_por_suc[sid]
                salida.append(item)
                if len(salida) >= int(k):
                    break
        if len(salida) >= int(k):
            break
    return salida[:int(k)], cercanas_knn


def _normalizar_puntajes(metodo, lista):
    if metodo == "espacial":
        return [min(1.0, max(0.0, float(fila.get("puntaje") or 0.0))) for fila in lista]
    crudos = []
    for fila in lista:
        if metodo == "cocompra":
            valor = math.log1p(max(0.0, float(fila.get("puntaje") or fila.get("cocompras") or 0.0)))
        else:
            valor = max(0.0, float(fila.get("puntaje") or 0.0))
        crudos.append(valor)
    maximo = max(crudos, default=0.0)
    if maximo <= 0.0:
        return [0.0] * len(crudos)
    return [v / maximo for v in crudos]


def fusionar(listas, pesos=None, k=K_RECOMENDACIONES, metodo_fusion=FUSION_DEFECTO):
    """Combina rankings por suma ponderada de scores normalizados o por RRF."""
    if metodo_fusion not in FUSIONES:
        raise ValueError(f"fusión desconocida '{metodo_fusion}'; usa {', '.join(FUSIONES)}")
    activas = {metodo: lista for metodo, lista in (listas or {}).items() if lista}
    if not activas:
        return []
    base_pesos = pesos if pesos is not None else PESOS_DEFECTO
    crudos = {metodo: max(0.0, float(base_pesos.get(metodo, 0.0))) for metodo in activas}
    suma = sum(crudos.values())
    if suma > 0:
        pesos_norm = {m: w / suma for m, w in crudos.items() if w > 0}
    else:
        pesos_norm = {m: 1.0 / len(activas) for m in activas}

    puntajes = {}
    filas = {}
    posiciones = {}
    aportes = {}
    for metodo, peso in pesos_norm.items():
        lista = activas[metodo]
        norm_scores = _normalizar_puntajes(metodo, lista) if metodo_fusion == "score" else None
        for posicion, fila in enumerate(lista, start=1):
            pid = fila["id"]
            aporte = (
                peso * norm_scores[posicion - 1]
                if metodo_fusion == "score"
                else peso / (RRF_K + posicion)
            )
            puntajes[pid] = puntajes.get(pid, 0.0) + aporte
            if pid not in filas:
                filas[pid] = dict(fila)
            elif "cocompras" in fila:
                filas[pid]["cocompras"] = fila["cocompras"]
            posiciones.setdefault(pid, {})[metodo] = posicion
            aportes.setdefault(pid, {})[metodo] = round(aporte, 6)

    ordenados = sorted(
        puntajes,
        key=lambda pid: (-puntajes[pid], -(filas[pid].get("rating") or 0.0), pid),
    )
    salida = []
    for pid in ordenados[:k]:
        item = dict(filas[pid])
        item["puntaje"] = round(puntajes[pid], 6)
        item["posiciones"] = posiciones[pid]
        item["aportes"] = aportes[pid]
        salida.append(item)
    return salida


def _formatear_simple(filas, metodo, k):
    salida = []
    for posicion, fila in enumerate(filas[:k], start=1):
        item = dict(fila)
        if "puntaje" not in item or item["puntaje"] is None:
            item["puntaje"] = float(item.get("rating") or 0.0)
        item["posiciones"] = {metodo: posicion}
        salida.append(item)
    return salida


def recomendar(
    item_id,
    modo="hibrido",
    k=K_RECOMENDACIONES,
    pesos=None,
    filtros=None,
    candidatos=K_CANDIDATOS,
    max_usuario_id=None,
    fusion=FUSION_DEFECTO,
):
    if modo not in MODOS:
        raise ValueError(f"modo desconocido '{modo}'; usa {', '.join(MODOS)}")
    if fusion not in FUSIONES:
        raise ValueError(f"fusión desconocida '{fusion}'; usa {', '.join(FUSIONES)}")
    filtros = dict(filtros or {})
    tiene_ubicacion = filtros.get("lat") is not None and filtros.get("lon") is not None
    if modo == "espacial" and not tiene_ubicacion:
        raise ValueError("el modo 'espacial' requiere fijar una ubicación (lat y lon)")
    mapa_sucursales = _mapa_sucursales()
    semilla = obtener_producto(
        item_id, lat=filtros.get("lat"), lon=filtros.get("lon"), mapa_sucursales=mapa_sucursales
    )
    if semilla is None:
        raise LookupError(f"producto {item_id} no encontrado")

    ids_sucursales, cercanas = _resolver_espacial(filtros)
    if ids_sucursales is not None and not ids_sucursales:
        return {
            "semilla": semilla,
            "recomendaciones": [],
            "tiempos": {},
            "sucursales_en_radio": [],
            "sucursales_knn": [],
            "fusion": fusion if modo == "hibrido" else None,
        }

    pesos_activos = (
        dict(pesos) if pesos is not None else {**PESOS_DEFECTO, "espacial": PESO_ESPACIAL_DEFECTO}
    )
    if modo == "hibrido":
        activas = [m for m in ("cocompra", "visual", "texto", "metadata") if pesos_activos.get(m, 0) > 0]
        usar_espacial = tiene_ubicacion and pesos_activos.get("espacial", 0) > 0
        if not activas and not usar_espacial:
            activas = ["cocompra", "visual", "texto", "metadata"]
            usar_espacial = tiene_ubicacion
        k_senal = candidatos
    elif modo == "espacial":
        activas = []
        usar_espacial = True
        k_senal = k
    else:
        activas = [modo]
        usar_espacial = False
        k_senal = k

    listas = {}
    tiempos = {}
    for senal in activas:
        t0 = time.perf_counter()
        if senal == "cocompra":
            listas[senal] = cocompra(
                item_id,
                k_senal,
                filtros,
                ids_sucursales=ids_sucursales,
                max_usuario_id=max_usuario_id,
            )
        elif senal == "metadata":
            listas[senal] = metadata(semilla, k_senal, filtros, ids_sucursales=ids_sucursales)
        elif senal == "visual":
            listas[senal] = visual(
                semilla.get("imagen"),
                k_senal,
                filtros,
                excluir_id=item_id,
                ids_sucursales=ids_sucursales,
            )
        elif senal == "texto":
            consulta_txt = " ".join(
                p
                for p in (
                    semilla.get("nombre"),
                    semilla.get("marca"),
                    semilla.get("categoria"),
                    semilla.get("descripcion"),
                )
                if p
            )
            listas[senal] = texto(
                consulta_txt, k_senal, filtros, excluir_id=item_id, ids_sucursales=ids_sucursales
            )
        tiempos[f"{senal}_ms"] = round((time.perf_counter() - t0) * 1000, 1)

    cercanas_knn = []
    if usar_espacial:
        candidatos_pool = {}
        if modo == "hibrido":
            for lista in listas.values():
                for fila in lista:
                    candidatos_pool.setdefault(fila["id"], fila)
        t0 = time.perf_counter()
        lista_espacial, cercanas_knn = espacial(
            semilla,
            k_senal,
            filtros["lat"],
            filtros["lon"],
            filtros=filtros,
            ids_sucursales=ids_sucursales,
            candidatos=candidatos_pool if modo == "hibrido" and candidatos_pool else None,
        )
        listas["espacial"] = lista_espacial
        tiempos["espacial_ms"] = round((time.perf_counter() - t0) * 1000, 1)

    if modo == "hibrido":
        recomendaciones = fusionar(listas, pesos_activos, k, metodo_fusion=fusion)
    else:
        recomendaciones = _formatear_simple(listas[modo], modo, k)

    recomendaciones = _enriquecer_sucursal(
        recomendaciones, mapa_sucursales, lat=filtros.get("lat"), lon=filtros.get("lon")
    )
    return {
        "semilla": semilla,
        "recomendaciones": recomendaciones,
        "tiempos": tiempos,
        "sucursales_en_radio": cercanas,
        "sucursales_knn": cercanas_knn,
        "fusion": fusion if modo == "hibrido" else None,
    }


def buscar_texto(consulta, modo="bm25", k=K_RECOMENDACIONES, filtros=None):
    if modo not in MODOS_BUSQUEDA:
        raise ValueError(f"modo desconocido '{modo}'; usa {', '.join(MODOS_BUSQUEDA)}")
    filtros = dict(filtros or {})
    ids_sucursales, cercanas = _resolver_espacial(filtros)
    if ids_sucursales is not None and not ids_sucursales:
        return {"productos": [], "tiempos": {}, "sucursales_en_radio": []}

    ranking = "BM25" if modo == "bm25" else "TF_IDF"
    t0 = time.perf_counter()
    filas = texto(consulta, k, filtros, ids_sucursales=ids_sucursales, ranking=ranking)
    tiempos = {f"{modo}_ms": round((time.perf_counter() - t0) * 1000, 1)}
    resultados = _formatear_simple(filas, modo, k)
    resultados = _enriquecer_sucursal(
        resultados, _mapa_sucursales(), lat=filtros.get("lat"), lon=filtros.get("lon")
    )
    return {
        "productos": resultados,
        "tiempos": tiempos,
        "sucursales_en_radio": cercanas,
    }


def buscar_imagen(ruta_relativa, k=K_RECOMENDACIONES, filtros=None, metodo=METODO_VECTORIAL):
    filtros = dict(filtros or {})
    ids_sucursales, cercanas = _resolver_espacial(filtros)
    if ids_sucursales is not None and not ids_sucursales:
        return {"productos": [], "tiempos": {}, "sucursales_en_radio": []}

    t0 = time.perf_counter()
    filas = visual(ruta_relativa, k, filtros, ids_sucursales=ids_sucursales, metodo=metodo)
    tiempos = {"visual_ms": round((time.perf_counter() - t0) * 1000, 1)}
    resultados = _formatear_simple(filas, "visual", k)
    resultados = _enriquecer_sucursal(
        resultados, _mapa_sucursales(), lat=filtros.get("lat"), lon=filtros.get("lon")
    )
    return {
        "productos": resultados,
        "tiempos": tiempos,
        "sucursales_en_radio": cercanas,
    }
