import argparse
import csv
import json
import math
import random
import statistics
import sys
import time
from pathlib import Path

RAIZ_EVAL = Path(__file__).resolve().parent
RAIZ_ECOM = RAIZ_EVAL.parent
if str(RAIZ_ECOM) not in sys.path:
    sys.path.insert(0, str(RAIZ_ECOM))

import cliente_bd as bd
import recomendador
from config import (
    K_CANDIDATOS,
    K_RECOMENDACIONES,
    MODELOS_VISUALES,
    PESOS_DEFECTO,
    RAIZ_PROYECTO,
    TABLA_CATALOGO,
    TABLA_ORDENES,
)

# Partición fija de usuarios (independiente de --semilla, que solo elige los casos): así los pesos
# calibrados en val nunca ven usuarios de test, para ninguna semilla de evaluación.
SEMILLA_PARTICION = 2026
FRACCION_VAL = 0.2
FRACCION_TEST = 0.2
SENALES_FUSION = ("cocompra", "visual", "texto", "metadata")
PASO_CALIBRACION = 0.05

ESTRATEGIAS_EVAL = (
    ("cocompra", "cocompra", {}),
    ("visual", "visual", {}),
    ("texto", "texto", {}),
    ("metadata", "metadata", {}),
    ("hibrido_rrf", "hibrido", {"fusion": "rrf"}),
    ("hibrido_score", "hibrido", {"fusion": "score"}),
)
# --visuales: cada modelo visual solo y dentro del híbrido score (pesos por defecto).
ESTRATEGIAS_VISUALES = tuple(
    (f"{prefijo}_{m}", modo, {"modelo_visual": m, **extra})
    for prefijo, modo, extra in (("visual", "visual", {}), ("hibrido_score", "hibrido", {"fusion": "score"}))
    for m in MODELOS_VISUALES
)
SALIDA_DEFECTO = RAIZ_PROYECTO / "benchmarks" / "ecommerce_results"

# Puntos reales de Lima (aprox.) desde donde "compra" cada usuario simulado.
UBICACIONES_LIMA = (
    ("Plaza Mayor", -12.0464, -77.0300),
    ("Parque Kennedy", -12.1211, -77.0297),
    ("UTEC Barranco", -12.1353, -77.0220),
    ("Estadio Nacional", -12.0670, -77.0337),
    ("Aeropuerto Jorge Chávez", -12.0219, -77.1143),
    ("UNALM La Molina", -12.0820, -76.9480),
    ("Plaza San Miguel", -12.0772, -77.0830),
    ("Malecón de Chorrillos", -12.1700, -77.0250),
)
PESOS_ESPACIAL_EVAL = (0.0, 0.10, 0.25, 0.50)
RADIO_LATENCIA_M = 6000.0
ZONA_LIMA_MODERNA = (-12.13, -77.06, -12.08, -76.99)  # sur, oeste, norte, este


def _percentil(valores, p):
    ordenados = sorted(valores)
    indice = max(0, min(len(ordenados) - 1, int(round(p / 100 * len(ordenados) + 0.5)) - 1))
    return ordenados[indice]


def particionar_usuarios(usuarios, semilla=SEMILLA_PARTICION):
    """Train / val / test al azar. Los usuario_id de la ingesta van de más a menos compras,
    así que cortar por rango de id dejaría en test solo a los usuarios con menos historial."""
    mezclados = sorted(usuarios)
    random.Random(semilla).shuffle(mezclados)
    n_test = max(1, round(len(mezclados) * FRACCION_TEST))
    n_val = max(1, round(len(mezclados) * FRACCION_VAL))
    if len(mezclados) - n_test - n_val < 1:
        raise ValueError("se necesitan al menos 3 usuarios con >= 2 ítems para evaluar")
    return {
        "test": mezclados[:n_test],
        "val": mezclados[n_test:n_test + n_val],
        "train": mezclados[n_test + n_val:],
    }


def _casos_de(usuarios, por_usuario, categorias, muestras, rng):
    orden = list(usuarios)
    rng.shuffle(orden)
    casos = []
    for uid in orden:
        unicos = sorted(set(por_usuario[uid]))
        semilla_id = rng.choice(unicos)
        objetivos = {pid for pid in unicos if pid != semilla_id}
        if not objetivos:
            continue
        casos.append({
            "usuario_id": uid,
            "semilla_id": semilla_id,
            "categoria": categorias.get(semilla_id),
            "objetivos": objetivos,
        })
        if len(casos) >= muestras:
            break
    return casos


def _cargar_casos(muestras, semilla):
    """Casos de test y de val, y qué usuarios excluir de la co-compra en cada escenario."""
    filas_ord = bd.filas(f"SELECT usuario_id, item_id FROM {TABLA_ORDENES};")
    por_usuario = {}
    for fila in filas_ord:
        por_usuario.setdefault(int(fila["usuario_id"]), []).append(int(fila["item_id"]))

    usuarios = [uid for uid, items in por_usuario.items() if len(set(items)) >= 2]
    particion = particionar_usuarios(usuarios)

    categorias = {
        int(fila["id"]): fila.get("categoria")
        for fila in bd.filas(f"SELECT id, categoria FROM {TABLA_CATALOGO};")
    }
    rng = random.Random(semilla)
    return {
        "casos_test": _casos_de(particion["test"], por_usuario, categorias, muestras, rng),
        "casos_val": _casos_de(particion["val"], por_usuario, categorias, muestras, rng),
        # test: la co-compra usa train + val; val (calibración): solo train; cold-start: nadie.
        "excluir_test": set(particion["test"]),
        "excluir_val": set(particion["test"]) | set(particion["val"]),
        "excluir_todos": set(por_usuario),
    }


def _metricas_caso(recomendados, objetivos, categoria_semilla, k):
    rec_ids = [int(item["id"]) for item in recomendados[:k]]
    primer_rango = next((i for i, pid in enumerate(rec_ids, start=1) if pid in objetivos), None)
    hit = 1.0 if primer_rango is not None else 0.0
    mrr = (1.0 / primer_rango) if primer_rango is not None else 0.0
    recall_k = len(set(rec_ids) & objetivos) / len(objetivos)

    dcg = sum(1.0 / math.log2(pos + 1) for pos, pid in enumerate(rec_ids, start=1) if pid in objetivos)
    idcg = sum(1.0 / math.log2(pos + 1) for pos in range(1, min(len(objetivos), k) + 1))
    ndcg = (dcg / idcg) if idcg > 0 else 0.0

    iguales_cat = sum(1 for item in recomendados[:k] if item.get("categoria") == categoria_semilla)
    precision_cat = (iguales_cat / len(rec_ids)) if rec_ids else 0.0

    salida = {
        "hit": hit,
        "recall_k": round(recall_k, 4),
        "ndcg_k": round(ndcg, 4),
        "mrr": round(mrr, 4),
        "precision_cat": round(precision_cat, 4),
    }
    if k > 5:
        salida["recall_5"] = round(len(set(rec_ids[:5]) & objetivos) / len(objetivos), 4)
    return salida


def _resumir(etiqueta, filas, k):
    latencias = [f["ms"] for f in filas]
    resumen = {
        "modo": etiqueta,
        "casos": len(filas),
        f"hit@{k}": round(statistics.mean(f["hit"] for f in filas), 4),
    }
    if k > 5:
        resumen["recall@5"] = round(statistics.mean(f["recall_5"] for f in filas), 4)
    resumen.update({
        f"recall@{k}": round(statistics.mean(f["recall_k"] for f in filas), 4),
        f"ndcg@{k}": round(statistics.mean(f["ndcg_k"] for f in filas), 4),
        "mrr": round(statistics.mean(f["mrr"] for f in filas), 4),
        f"precision_cat@{k}": round(statistics.mean(f["precision_cat"] for f in filas), 4),
        "ms_promedio": round(statistics.mean(latencias), 1),
        "ms_p95": round(_percentil(latencias, 95), 1),
    })
    return resumen


def _escribir_csv(ruta, filas):
    with open(ruta, "w", newline="", encoding="utf-8") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=list(filas[0]))
        escritor.writeheader()
        escritor.writerows(filas)


def _evaluar_escenario(casos, k, usuarios_excluidos, etiqueta_log=None, estrategias=ESTRATEGIAS_EVAL):
    detalle = []
    resumenes = []
    for etiqueta, modo, kwargs in estrategias:
        filas_modo = []
        for idx, caso in enumerate(casos, start=1):
            t0 = time.perf_counter()
            respuesta = recomendador.recomendar(
                caso["semilla_id"],
                modo=modo,
                k=k,
                usuarios_excluidos=usuarios_excluidos,
                **kwargs,
            )
            ms = round((time.perf_counter() - t0) * 1000, 1)
            metricas = _metricas_caso(
                respuesta["recomendaciones"], caso["objetivos"], caso["categoria"], k
            )
            fila = {
                "modo": etiqueta,
                "caso": idx,
                "usuario_id": caso["usuario_id"],
                "semilla_id": caso["semilla_id"],
                **metricas,
                "ms": ms,
            }
            filas_modo.append(fila)
            detalle.append(fila)
        resumen = _resumir(etiqueta, filas_modo, k)
        resumenes.append(resumen)
        prefijo = f"[{etiqueta_log}] " if etiqueta_log else ""
        print(prefijo + json.dumps(resumen, ensure_ascii=False))
    return resumenes, detalle


def _medir_ms(fn, *args, **kwargs):
    t0 = time.perf_counter()
    fn(*args, **kwargs)
    return (time.perf_counter() - t0) * 1000


def _preparar(muestras, semilla, salida):
    datos = _cargar_casos(muestras, semilla)
    if not datos["casos_test"]:
        raise ValueError("no se encontraron casos válidos en el split de prueba")
    destino = Path(salida)
    destino.mkdir(parents=True, exist_ok=True)
    return datos, destino


def _grilla_pesos(paso):
    """Todas las combinaciones de pesos de SENALES_FUSION que suman 1, con el paso dado."""
    n = round(1 / paso)
    for a in range(n + 1):
        for b in range(n + 1 - a):
            for c in range(n + 1 - a - b):
                d = n - a - b - c
                yield dict(zip(SENALES_FUSION, (round(x * paso, 4) for x in (a, b, c, d))))


def calibrar_pesos(muestras=100, k=K_RECOMENDACIONES, salida=SALIDA_DEFECTO, semilla=42, paso=PASO_CALIBRACION):
    """Busca los pesos del híbrido score que maximizan el NDCG@k promedio (normal y cold-start) en val.

    Cada señal se consulta una sola vez por caso (no depende de los pesos); la grilla solo repite la fusión.
    """
    datos, destino = _preparar(muestras, semilla, salida)
    if not datos["casos_val"]:
        raise ValueError("no se encontraron casos válidos en el split de validación")
    preparados = []
    for caso in datos["casos_val"]:
        semilla_prod = recomendador.obtener_producto(caso["semilla_id"])
        listas, _ = recomendador.calcular_senales(
            semilla_prod, SENALES_FUSION, K_CANDIDATOS, usuarios_excluidos=datos["excluir_val"]
        )
        preparados.append((caso, listas))

    def media(pesos, sin_cocompra):
        metricas = []
        for caso, listas in preparados:
            # cold-start = las mismas listas sin co-compra (equivale a excluir a todos los usuarios)
            usadas = {s: l for s, l in listas.items() if not (sin_cocompra and s == "cocompra")}
            top = recomendador.fusionar(usadas, pesos, k, "score")
            metricas.append(_metricas_caso(top, caso["objetivos"], caso["categoria"], k))
        return {clave: statistics.mean(m[clave] for m in metricas) for clave in ("ndcg_k", "hit", "mrr")}

    filas = []
    for pesos in _grilla_pesos(paso):
        normal, cold = media(pesos, False), media(pesos, True)
        filas.append({
            **{f"w_{s}": pesos[s] for s in SENALES_FUSION},
            # objetivo: el sistema enfrenta ambos escenarios; solo "normal" deja en 0 a las señales de contenido
            f"ndcg@{k}_promedio": round((normal["ndcg_k"] + cold["ndcg_k"]) / 2, 4),
            f"ndcg@{k}": round(normal["ndcg_k"], 4),
            f"hit@{k}": round(normal["hit"], 4),
            "mrr": round(normal["mrr"], 4),
            f"ndcg@{k}_cold": round(cold["ndcg_k"], 4),
            f"hit@{k}_cold": round(cold["hit"], 4),
            "mrr_cold": round(cold["mrr"], 4),
        })
    filas.sort(key=lambda f: (-f[f"ndcg@{k}_promedio"], -f[f"ndcg@{k}"], -f["mrr"]))
    _escribir_csv(destino / "calibracion.csv", filas)
    actuales = next(
        (f for f in filas if all(abs(f[f"w_{s}"] - PESOS_DEFECTO.get(s, 0)) < 1e-9 for s in SENALES_FUSION)), None
    )
    print(f"[calibracion] {len(preparados)} casos de val, {len(filas)} combinaciones")
    print("[calibracion] mejor: " + json.dumps(filas[0], ensure_ascii=False))
    if actuales is not None:
        print("[calibracion] PESOS_DEFECTO actuales: " + json.dumps(actuales, ensure_ascii=False))
    return filas


def ejecutar_evaluacion_espacial(muestras=100, k=K_RECOMENDACIONES, salida=SALIDA_DEFECTO, semilla=42):
    """Compromiso Hit@k/NDCG@k vs. distancia media del Top k al variar w_espacial (híbrido score)."""
    datos, destino = _preparar(muestras, semilla, salida)
    return evaluar_espacial(datos["casos_test"], k, datos["excluir_test"], semilla, destino)


def evaluar_espacial(casos, k, usuarios_excluidos, semilla, destino, pesos_espaciales=PESOS_ESPACIAL_EVAL):
    rng = random.Random(semilla)
    lugares = [rng.choice(UBICACIONES_LIMA) for _ in casos]
    resumenes, detalle = [], []
    for w in pesos_espaciales:
        pesos = {**PESOS_DEFECTO, "espacial": w}
        filas_w = []
        for idx, (caso, (lugar, lat, lon)) in enumerate(zip(casos, lugares), start=1):
            t0 = time.perf_counter()
            respuesta = recomendador.recomendar(
                caso["semilla_id"],
                modo="hibrido",
                k=k,
                pesos=pesos,
                filtros={"lat": lat, "lon": lon},
                usuarios_excluidos=usuarios_excluidos,
                fusion="score",
            )
            ms = round((time.perf_counter() - t0) * 1000, 1)
            top = respuesta["recomendaciones"][:k]
            distancias = [r["distancia_m"] for r in top if r.get("distancia_m") is not None]
            fila = {
                "w_espacial": w,
                "caso": idx,
                "lugar": lugar,
                "usuario_id": caso["usuario_id"],
                "semilla_id": caso["semilla_id"],
                **_metricas_caso(top, caso["objetivos"], caso["categoria"], k),
                "dist_km": round(statistics.mean(distancias) / 1000, 3) if distancias else None,
                "ms": ms,
            }
            filas_w.append(fila)
            detalle.append(fila)
        resumen = _resumir(f"w_espacial={w}", filas_w, k)
        con_dist = [f["dist_km"] for f in filas_w if f["dist_km"] is not None]
        resumen["dist_media_km"] = round(statistics.mean(con_dist), 3) if con_dist else None
        resumenes.append(resumen)
        print("[espacial] " + json.dumps(resumen, ensure_ascii=False))

    latencias = []
    operaciones = (
        ("RTREE-radius", recomendador.sucursales_cercanas, lambda lat, lon: (lat, lon, RADIO_LATENCIA_M)),
        ("RTREE-knn", recomendador.sucursales_knn, lambda lat, lon: (lat, lon, 3)),
        ("RTREE-polygon", recomendador.sucursales_en_zona, lambda lat, lon: (ZONA_LIMA_MODERNA,)),
    )
    for nombre, fn, argumentos in operaciones:
        tiempos = [_medir_ms(fn, *argumentos(lat, lon)) for _, lat, lon in UBICACIONES_LIMA for _ in range(5)]
        latencias.append({
            "operacion": nombre,
            "repeticiones": len(tiempos),
            "ms_promedio": round(statistics.mean(tiempos), 2),
            "ms_p95": round(_percentil(tiempos, 95), 2),
        })
        print("[latencia] " + json.dumps(latencias[-1], ensure_ascii=False))

    _escribir_csv(destino / "resumen_espacial.csv", resumenes)
    _escribir_csv(destino / "detalle_espacial.csv", detalle)
    _escribir_csv(destino / "latencias_espaciales.csv", latencias)
    return resumenes, latencias


def ejecutar_evaluacion_visual(muestras=100, k=K_RECOMENDACIONES, salida=SALIDA_DEFECTO, semilla=42):
    """SIFT k=256 vs. SIFT k=4096 vs. CLIP: señal visual sola y dentro del híbrido score."""
    datos, destino = _preparar(muestras, semilla, salida)
    resumenes, detalle = _evaluar_escenario(
        datos["casos_test"], k, datos["excluir_test"], "visuales", ESTRATEGIAS_VISUALES
    )
    _escribir_csv(destino / "resumen_visuales.csv", resumenes)
    _escribir_csv(destino / "detalle_visuales.csv", detalle)
    print(f"resultados en {destino}")
    return resumenes, detalle


def ejecutar_evaluacion(
    muestras=100,
    k=K_RECOMENDACIONES,
    salida=SALIDA_DEFECTO,
    semilla=42,
    incluir_cold_start=True,
):
    """Evalúa señales e híbridos en hold-out normal y escenario cold-start sin co-compras."""
    datos, destino = _preparar(muestras, semilla, salida)
    casos = datos["casos_test"]

    resumenes, detalle = _evaluar_escenario(casos, k, datos["excluir_test"], "normal")
    _escribir_csv(destino / "resumen.csv", resumenes)
    _escribir_csv(destino / "detalle.csv", detalle)

    if incluir_cold_start:
        res_cold, det_cold = _evaluar_escenario(casos, k, datos["excluir_todos"], "cold-start")
        _escribir_csv(destino / "resumen_cold_start.csv", res_cold)
        _escribir_csv(destino / "detalle_cold_start.csv", det_cold)

    print(f"resultados en {destino}")
    return resumenes, detalle


def main():
    parser = argparse.ArgumentParser(description="Evalúa el recomendador e-commerce por señal e híbrido")
    parser.add_argument("--muestras", type=int, default=100)
    parser.add_argument("--k", type=int, default=K_RECOMENDACIONES)
    parser.add_argument("--semilla", type=int, default=42)
    parser.add_argument("--salida", type=Path, default=SALIDA_DEFECTO)
    parser.add_argument("--sin-cold-start", action="store_true")
    parser.add_argument(
        "--espacial", action="store_true",
        help="solo el benchmark espacial: Hit/NDCG vs. distancia del Top k por w_espacial y latencias del R-Tree",
    )
    parser.add_argument(
        "--visuales", action="store_true",
        help="solo la comparación de modelos visuales (SIFT k=256, SIFT k=4096, CLIP)",
    )
    parser.add_argument(
        "--calibrar", action="store_true",
        help="solo la búsqueda de pesos del híbrido score sobre los usuarios de val (calibracion.csv)",
    )
    args = parser.parse_args()
    if not bd.disponible():
        raise SystemExit("el motor no responde; levanta el backend en el puerto configurado")
    if args.calibrar:
        calibrar_pesos(args.muestras, args.k, args.salida, args.semilla)
        return
    if args.visuales:
        ejecutar_evaluacion_visual(args.muestras, args.k, args.salida, args.semilla)
        return
    if args.espacial:
        ejecutar_evaluacion_espacial(args.muestras, args.k, args.salida, args.semilla)
        return
    ejecutar_evaluacion(
        args.muestras, args.k, args.salida, args.semilla, incluir_cold_start=not args.sin_cold_start
    )


if __name__ == "__main__":
    main()
