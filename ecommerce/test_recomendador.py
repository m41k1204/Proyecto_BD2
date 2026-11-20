import csv
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

RAIZ_ECOM = Path(__file__).resolve().parent
RAIZ_PROYECTO = RAIZ_ECOM.parent
sys.path.insert(0, str(RAIZ_ECOM))
sys.path.insert(0, str(RAIZ_PROYECTO / "backend"))

from PIL import Image, ImageDraw

from engine.multimedia.pipeline import FeaturePipeline
from engine.parser.executor import Executor
from engine.parser.scanner import Scanner
from engine.parser.sql_parser import Parser

import config
import ingesta
import recomendador
from evaluacion import evaluar


def _dibujar_patron(ruta, estilo):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with Image.new("RGB", (256, 256), (242, 242, 242)) as img:
        d = ImageDraw.Draw(img)
        if estilo == "grid":
            for x in range(16, 240, 32):
                d.rectangle((x, 16, x + 10, 240), fill=(25, 25, 25))
            for y in range(16, 240, 32):
                d.line((16, y, 240, y), fill=(60, 60, 60), width=4)
        elif estilo == "grid_b":
            for x in range(20, 236, 34):
                d.rectangle((x, 20, x + 12, 236), fill=(30, 30, 30))
            for y in range(20, 236, 34):
                d.line((20, y, 236, y), fill=(55, 55, 55), width=4)
        elif estilo == "circles":
            for r in range(20, 120, 18):
                d.ellipse((128 - r, 128 - r, 128 + r, 128 + r), outline=(20, 20, 20), width=4)
            d.line((10, 128, 246, 128), fill=(40, 40, 40), width=3)
        elif estilo == "stripes":
            for offset in range(-220, 260, 24):
                d.line((offset, 0, offset + 220, 256), fill=(25, 25, 25), width=6)
        elif estilo == "diamonds":
            for s in range(24, 120, 22):
                d.polygon([(128, 128 - s), (128 + s, 128), (128, 128 + s), (128 - s, 128)], outline=(20, 20, 20), width=4)
        else:
            for y in range(16, 240, 28):
                for x in range(16, 240, 28):
                    if ((x + y) // 28) % 2 == 0:
                        d.rectangle((x, y, x + 16, y + 16), fill=(25, 25, 25))
        img.save(ruta, format="JPEG", quality=90)


def _dataset_prueba(carpeta_media):
    productos = [
        {
            "id": 1, "codigo": "P1", "asin": "P1", "nombre": "Wireless Pro Controller",
            "marca": "Sony", "categoria": "Controllers", "precio": 60.0, "rating": 4.9,
            "sucursal_id": 1, "imagen": f"{config.SUBCARPETA_MULTIMEDIA}/{config.CATEGORIA_DATASET}/imagenes/P1.jpg",
            "descripcion": "Wireless pro controller gamepad for console gaming", "estilo": "grid",
        },
        {
            "id": 2, "codigo": "P2", "asin": "P2", "nombre": "Dual Controller Charger",
            "marca": "Sony", "categoria": "Controllers", "precio": 40.0, "rating": 4.8,
            "sucursal_id": 1, "imagen": f"{config.SUBCARPETA_MULTIMEDIA}/{config.CATEGORIA_DATASET}/imagenes/P2.jpg",
            "descripcion": "Fast wireless controller charging dock stand", "estilo": "grid_b",
        },
        {
            "id": 3, "codigo": "P3", "asin": "P3", "nombre": "Tactile Thumb Grips",
            "marca": "Kontrol", "categoria": "Controllers", "precio": 18.0, "rating": 4.6,
            "sucursal_id": 2, "imagen": f"{config.SUBCARPETA_MULTIMEDIA}/{config.CATEGORIA_DATASET}/imagenes/P3.jpg",
            "descripcion": "Grip pack for wireless pro controller sticks", "estilo": "circles",
        },
        {
            "id": 4, "codigo": "P4", "asin": "P4", "nombre": "Studio Gaming Headset",
            "marca": "HyperX", "categoria": "Headsets", "precio": 95.0, "rating": 4.7,
            "sucursal_id": 2, "imagen": f"{config.SUBCARPETA_MULTIMEDIA}/{config.CATEGORIA_DATASET}/imagenes/P4.jpg",
            "descripcion": "Surround audio headset with detachable mic", "estilo": "stripes",
        },
        {
            "id": 5, "codigo": "P5", "asin": "P5", "nombre": "Arcade Fight Stick",
            "marca": "Hori", "categoria": "Controllers", "precio": 80.0, "rating": 4.5,
            "sucursal_id": 8, "imagen": f"{config.SUBCARPETA_MULTIMEDIA}/{config.CATEGORIA_DATASET}/imagenes/P5.jpg",
            "descripcion": "Tournament arcade stick for fighting games", "estilo": "diamonds",
        },
        {
            "id": 6, "codigo": "P6", "asin": "P6", "nombre": "Console Travel Case",
            "marca": "PowerA", "categoria": "Accessories", "precio": 35.0, "rating": 4.4,
            "sucursal_id": 8, "imagen": f"{config.SUBCARPETA_MULTIMEDIA}/{config.CATEGORIA_DATASET}/imagenes/P6.jpg",
            "descripcion": "Hard shell protective case for console gear", "estilo": "checker",
        },
    ]
    for p in productos:
        _dibujar_patron(Path(carpeta_media) / p["imagen"], p["estilo"])

    pares_orden = [
        (1, 1), (1, 2), (1, 3),
        (2, 1), (2, 2),
        (3, 1), (3, 3),
        (4, 2), (4, 4),
        (5, 1), (5, 2), (5, 6),
        (6, 1), (6, 2), (6, 3),
    ]
    ordenes = [
        {"id": i, "usuario_id": u, "item_id": item, "fecha": "2025-01-10"}
        for i, (u, item) in enumerate(pares_orden, start=1)
    ]
    return productos, ordenes


def main():
    with tempfile.TemporaryDirectory(prefix="ecom_rec_media_") as dir_media, \
            tempfile.TemporaryDirectory(prefix="ecom_rec_bd_") as dir_bd, \
            tempfile.TemporaryDirectory(prefix="ecom_rec_eval_") as dir_eval:
        media = Path(dir_media)
        productos, ordenes = _dataset_prueba(media)
        pipeline = FeaturePipeline(media, RAIZ_PROYECTO / "data" / "modelos")
        catalogo_bd = {}
        executor = Executor(catalogo_bd, data_dir=dir_bd, vectorizador=pipeline.vectorizar)

        def ejecutar_local(sql):
            sentencias = Parser(Scanner(sql)).parse_program()
            resultados = executor.run(sentencias)
            for res in resultados:
                assert "error" not in res, f"SQL falló: {sql}\n{res.get('error')}"
            return resultados[-1]

        def cargar_feat_local(tabla, columna_ruta, descriptor_id):
            n = pipeline.cargar(catalogo_bd[tabla], columna_ruta, descriptor_id)
            return {"message": f"{n} filas", "rowsLoaded": n}

        try:
            with patch("cliente_bd.ejecutar", side_effect=ejecutar_local), \
                    patch("cliente_bd.cargar_caracteristicas", side_effect=cargar_feat_local):
                ingesta.cargar(productos, ordenes)

                sucursales = recomendador.listar_sucursales()
                assert len(sucursales) == 8
                categorias = recomendador.listar_categorias()
                assert {c["categoria"]: c["productos"] for c in categorias} == {
                    "Accessories": 1, "Controllers": 4, "Headsets": 1
                }
                pag1 = recomendador.listar_productos(orden="precio_asc", limite=2, pagina=1)
                pag2 = recomendador.listar_productos(orden="precio_asc", limite=2, pagina=2)
                assert [p["id"] for p in pag1["productos"]] == [3, 6] and pag1["hay_mas"]
                assert [p["id"] for p in pag2["productos"]] == [2, 1]

                for modo in recomendador.MODOS:
                    filtros_modo = {"lat": -12.1190, "lon": -77.0290} if modo == "espacial" else None
                    res = recomendador.recomendar(1, modo=modo, k=5, filtros=filtros_modo)
                    ids = [r["id"] for r in res["recomendaciones"]]
                    assert 1 not in ids and len(ids) >= 1, (modo, ids)
                    if modo != "hibrido":
                        assert all(modo in r["posiciones"] for r in res["recomendaciones"])

                assert [s["id"] for s in recomendador.sucursales_knn(-12.1190, -77.0290, k=3)] == [1, 2, 5]

                zona_lima = (-12.13, -77.06, -12.08, -76.99)
                assert [s["id"] for s in recomendador.sucursales_en_zona(zona_lima)] == [1, 2, 4, 6]
                en_zona = recomendador.listar_productos(zona=zona_lima, limite=10)
                assert {p["id"] for p in en_zona["productos"]} == {1, 2, 3, 4}
                assert [s["id"] for s in en_zona["sucursales_en_radio"]] == [1, 2, 4, 6]
                rec_zona = recomendador.recomendar(1, modo="hibrido", k=5, filtros={"zona": zona_lima})
                assert rec_zona["recomendaciones"]
                assert all(r["sucursal_id"] in (1, 2, 4, 6) for r in rec_zona["recomendaciones"])
                zona_y_radio = recomendador.listar_productos(
                    zona=zona_lima, lat=-12.1190, lon=-77.0290, radio_m=3000, limite=10
                )
                assert [s["id"] for s in zona_y_radio["sucursales_en_radio"]] == [1, 2]

                # Desde el Callao: tiendas 8 → 7 → 6 → 2 → 1 (k-NN), y por rating dentro de cada tienda.
                callao = {"lat": -12.0080, "lon": -77.1150}
                cerca1 = recomendador.listar_productos(orden="cercania", limite=3, pagina=1, **callao)
                cerca2 = recomendador.listar_productos(orden="cercania", limite=3, pagina=2, **callao)
                assert [p["id"] for p in cerca1["productos"]] == [5, 6, 4] and cerca1["hay_mas"]
                assert [p["id"] for p in cerca2["productos"]] == [3, 1, 2] and not cerca2["hay_mas"]
                try:
                    recomendador.listar_productos(orden="cercania")
                    raise AssertionError("debió lanzar ValueError")
                except ValueError:
                    pass

                hib = recomendador.recomendar(1, modo="hibrido", k=5, fusion="score")
                assert hib["fusion"] == "score"
                assert hib["recomendaciones"][0]["id"] == 2
                assert len(hib["recomendaciones"][0]["posiciones"]) >= 2
                assert hib["recomendaciones"][0]["aportes"]
                assert {"cocompra_ms", "visual_ms", "texto_ms", "metadata_ms"} <= set(hib["tiempos"])
                assert "espacial_ms" not in hib["tiempos"] and hib["sucursales_knn"] == []

                hib_callao = recomendador.recomendar(
                    1, modo="hibrido", k=5, fusion="score",
                    filtros={"lat": -12.0080, "lon": -77.1150},
                )
                assert "espacial_ms" in hib_callao["tiempos"]
                assert hib_callao["sucursales_knn"][0]["id"] == 8
                en_callao = [r for r in hib_callao["recomendaciones"] if r["sucursal_id"] == 8]
                assert en_callao and all("espacial" in r["posiciones"] and "espacial" in r["aportes"] for r in en_callao)

                sin_esp = recomendador.recomendar(
                    1, modo="hibrido", k=5, fusion="score",
                    pesos={"cocompra": 0.55, "texto": 0.25, "metadata": 0.12, "visual": 0.08, "espacial": 0.0},
                    filtros={"lat": -12.0080, "lon": -77.1150},
                )
                con_esp = recomendador.recomendar(
                    1, modo="hibrido", k=5, fusion="score",
                    pesos={"cocompra": 0.20, "texto": 0.10, "metadata": 0.05, "visual": 0.05, "espacial": 0.60},
                    filtros={"lat": -12.0080, "lon": -77.1150},
                )
                pos_sin = next(i for i, r in enumerate(sin_esp["recomendaciones"]) if r["sucursal_id"] == 8)
                pos_con = next(i for i, r in enumerate(con_esp["recomendaciones"]) if r["sucursal_id"] == 8)
                assert pos_con < pos_sin

                solo_esp = recomendador.recomendar(
                    1, modo="espacial", k=5,
                    filtros={"lat": -12.0080, "lon": -77.1150},
                )
                assert [r["id"] for r in solo_esp["recomendaciones"]] == [5, 6]
                assert "espacial_ms" in solo_esp["tiempos"]

                hib_rrf = recomendador.recomendar(1, modo="hibrido", k=5, fusion="rrf")
                assert hib_rrf["fusion"] == "rrf"
                assert hib_rrf["recomendaciones"][0]["id"] == 2
                assert hib_rrf["recomendaciones"][0]["aportes"]

                cold_hib = recomendador.recomendar(1, modo="hibrido", k=5, max_usuario_id=0, fusion="score")
                assert recomendador.cocompra(1, k=5, max_usuario_id=0) == []
                assert cold_hib["recomendaciones"] and all(
                    "cocompra" not in r["posiciones"] for r in cold_hib["recomendaciones"]
                )

                sin_fuga = recomendador.cocompra(1, k=10, max_usuario_id=4)
                assert {r["id"] for r in sin_fuga} == {2, 3}
                con_fuga = recomendador.cocompra(1, k=10, max_usuario_id=None)
                assert 6 in {r["id"] for r in con_fuga}

                plan_ord = ejecutar_local(
                    f"EXPLAIN ANALYZE SELECT o2.item_id, COUNT(*) FROM {config.TABLA_ORDENES} AS o1 "
                    f"JOIN {config.TABLA_ORDENES} AS o2 ON o1.usuario_id = o2.usuario_id "
                    f"WHERE o1.item_id = 1 AND o2.item_id != 1 GROUP BY o2.item_id "
                    f"ORDER BY conteo DESC LIMIT {config.K_CANDIDATOS};"
                )
                texto_plan = "\n".join(r["QUERY PLAN"] for r in plan_ord["rows"])
                assert "top-N heapsort" in texto_plan

                cerca = recomendador.recomendar(
                    1, modo="hibrido", k=5,
                    filtros={"lat": -12.1190, "lon": -77.0290, "radio_m": 6000},
                )
                assert cerca["recomendaciones"]
                assert "espacial_ms" in cerca["tiempos"]
                ids_radio = {s["id"] for s in cerca["sucursales_en_radio"]}
                assert {s["id"] for s in cerca["sucursales_knn"]} <= ids_radio
                assert all(r["sucursal_id"] in ids_radio for r in cerca["recomendaciones"])
                assert all(r["distancia_m"] <= 6000 for r in cerca["recomendaciones"])

                vacio = recomendador.recomendar(
                    1, modo="hibrido", k=5,
                    filtros={"lat": 0.0, "lon": 0.0, "radio_m": 100},
                )
                assert vacio["recomendaciones"] == [] and vacio["sucursales_en_radio"] == [] and vacio["sucursales_knn"] == []

                res_bm25 = recomendador.buscar_texto("wireless controller", modo="bm25", k=4)
                assert res_bm25["productos"][0]["id"] in (1, 2)
                assert "bm25_ms" in res_bm25["tiempos"]

                res_tfidf = recomendador.buscar_texto("surrounding audio headset", modo="tf_idf", k=4)
                assert res_tfidf["productos"][0]["id"] == 4
                assert "tf_idf_ms" in res_tfidf["tiempos"]

                res_img = recomendador.buscar_imagen(productos[0]["imagen"], k=3)
                assert res_img["productos"][0]["id"] == 1
                assert res_img["productos"][0]["puntaje"] > 0.99

                for fn, kwargs in ((recomendador.recomendar, {"item_id": 999}),):
                    try:
                        fn(**kwargs)
                        raise AssertionError("debió lanzar LookupError")
                    except LookupError:
                        pass
                try:
                    recomendador.recomendar(1, modo="desconocido")
                    raise AssertionError("debió lanzar ValueError")
                except ValueError:
                    pass
                try:
                    recomendador.recomendar(1, modo="hibrido", fusion="invalida")
                    raise AssertionError("debió lanzar ValueError")
                except ValueError:
                    pass
                try:
                    recomendador.buscar_texto("controller", modo="invalido")
                    raise AssertionError("debió lanzar ValueError")
                except ValueError:
                    pass
                try:
                    recomendador.recomendar(1, modo="espacial")
                    raise AssertionError("debió lanzar ValueError")
                except ValueError:
                    pass

                resumenes, detalle = evaluar.ejecutar_evaluacion(
                    muestras=10, k=5, salida=Path(dir_eval), semilla=7, incluir_cold_start=True
                )
                etiquetas = [e[0] for e in evaluar.ESTRATEGIAS_EVAL]
                assert [r["modo"] for r in resumenes] == etiquetas
                assert len(detalle) == len(etiquetas) * 2
                with open(Path(dir_eval) / "resumen.csv", encoding="utf-8") as f:
                    filas_csv = list(csv.DictReader(f))
                assert len(filas_csv) == 6
                for fila in filas_csv:
                    assert 0.0 <= float(fila["hit@5"]) <= 1.0
                    assert 0.0 <= float(fila["ndcg@5"]) <= 1.0

                with open(Path(dir_eval) / "resumen_cold_start.csv", encoding="utf-8") as f:
                    cold_csv = {r["modo"]: r for r in csv.DictReader(f)}
                assert float(cold_csv["cocompra"]["hit@5"]) == 0.0
                assert float(cold_csv["hibrido_score"]["hit@5"]) > 0.0
                assert float(cold_csv["hibrido_rrf"]["hit@5"]) > 0.0

                res_esp, latencias = evaluar.ejecutar_evaluacion_espacial(
                    muestras=10, k=5, salida=Path(dir_eval), semilla=7
                )
                assert [r["modo"] for r in res_esp] == [f"w_espacial={w}" for w in evaluar.PESOS_ESPACIAL_EVAL]
                assert all(r["dist_media_km"] is not None for r in res_esp)
                assert res_esp[-1]["dist_media_km"] <= res_esp[0]["dist_media_km"] + 1e-9
                assert [l["operacion"] for l in latencias] == ["RTREE-radius", "RTREE-knn", "RTREE-polygon"]
                for nombre in ("resumen_espacial.csv", "detalle_espacial.csv", "latencias_espaciales.csv"):
                    assert (Path(dir_eval) / nombre).exists()
        finally:
            for tabla in catalogo_bd.values():
                tabla.cerrar()

    print("OK: ecommerce recomendador y evaluacion")


if __name__ == "__main__":
    main()
