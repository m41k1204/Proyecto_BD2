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
from config import K_RECOMENDACIONES, PESOS_DEFECTO, RAIZ_PROYECTO, TABLA_CATALOGO, TABLA_ORDENES

ESTRATEGIAS_EVAL = (
    ("cocompra", "cocompra", None),
    ("visual", "visual", None),
    ("texto", "texto", None),
    ("metadata", "metadata", None),
    ("hibrido_rrf", "hibrido", "rrf"),
    ("hibrido_score", "hibrido", "score"),
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


def _cargar_casos(muestras, semilla):
    filas_ord = bd.filas(f"SELECT usuario_id, item_id FROM {TABLA_ORDENES};")
    por_usuario = {}
    for fila in filas_ord:
        por_usuario.setdefault(int(fila["usuario_id"]), []).append(int(fila["item_id"]))

    usuarios = sorted(uid for uid, items in por_usuario.items() if len(set(items)) >= 2)
    if len(usuarios) < 2:
        raise ValueError("se necesitan al menos 2 usuarios con >= 2 ítems para evaluar")

    n_train = max(1, min(len(usuarios) - 1, int(len(usuarios) * 0.8)))
    corte_train = usuarios[n_train - 1]
    usuarios_test = usuarios[n_train:]

    categorias = {
        int(fila["id"]): fila.get("categoria")
        for fila in bd.filas(f"SELECT id, categoria FROM {TABLA_CATALOGO};")
    }

    rng = random.Random(semilla)
    rng.shuffle(usuarios_test)
    casos = []
    for uid in usuarios_test:
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
    return corte_train, casos


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


def _evaluar_escenario(casos, k, max_usuario_id, etiqueta_log=None):
    detalle = []
    resumenes = []
    for etiqueta, modo, fusion in ESTRATEGIAS_EVAL:
        filas_modo = []
        kwargs = {"fusion": fusion} if fusion else {}
        for idx, caso in enumerate(casos, start=1):
            t0 = time.perf_counter()
            respuesta = recomendador.recomendar(
                caso["semilla_id"],
                modo=modo,
                k=k,
                max_usuario_id=max_usuario_id,
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
    corte_train, casos = _cargar_casos(muestras, semilla)
    if not casos:
        raise ValueError("no se encontraron casos válidos en el split de prueba")
    destino = Path(salida)
    destino.mkdir(parents=True, exist_ok=True)
    return corte_train, casos, destino


def ejecutar_evaluacion_espacial(muestras=100, k=K_RECOMENDACIONES, salida=SALIDA_DEFECTO, semilla=42):
    """Compromiso Hit@k/NDCG@k vs. distancia media del Top k al variar w_espacial (híbrido score)."""
    corte_train, casos, destino = _preparar(muestras, semilla, salida)
    return evaluar_espacial(casos, k, corte_train, semilla, destino)


def evaluar_espacial(casos, k, max_usuario_id, semilla, destino, pesos_espaciales=PESOS_ESPACIAL_EVAL):
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
                max_usuario_id=max_usuario_id,
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


def ejecutar_evaluacion(
    muestras=100,
    k=K_RECOMENDACIONES,
    salida=SALIDA_DEFECTO,
    semilla=42,
    incluir_cold_start=True,
):
    """Evalúa señales e híbridos en hold-out normal y escenario cold-start sin co-compras."""
    corte_train, casos, destino = _preparar(muestras, semilla, salida)

    resumenes, detalle = _evaluar_escenario(casos, k, corte_train, "normal")
    _escribir_csv(destino / "resumen.csv", resumenes)
    _escribir_csv(destino / "detalle.csv", detalle)

    if incluir_cold_start:
        res_cold, det_cold = _evaluar_escenario(casos, k, 0, "cold-start")
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
    args = parser.parse_args()
    if not bd.disponible():
        raise SystemExit("el motor no responde; levanta el backend en el puerto configurado")
    if args.espacial:
        ejecutar_evaluacion_espacial(args.muestras, args.k, args.salida, args.semilla)
        return
    ejecutar_evaluacion(
        args.muestras, args.k, args.salida, args.semilla, incluir_cold_start=not args.sin_cold_start
    )


if __name__ == "__main__":
    main()
