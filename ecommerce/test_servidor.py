import io
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

RAIZ_ECOM = Path(__file__).resolve().parent
RAIZ_PROYECTO = RAIZ_ECOM.parent
sys.path.insert(0, str(RAIZ_ECOM))
sys.path.insert(0, str(RAIZ_PROYECTO / "backend"))

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from engine.multimedia.pipeline import FeaturePipeline
from engine.parser.executor import Executor
from engine.parser.scanner import Scanner
from engine.parser.sql_parser import Parser

import config
import ingesta
import servidor


def _dibujar_patron(ruta, estilo):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with Image.new("RGB", (256, 256), (242, 242, 242)) as img:
        d = ImageDraw.Draw(img)
        if estilo == "grid":
            for x in range(16, 240, 32):
                d.rectangle((x, 16, x + 10, 240), fill=(25, 25, 25))
            for y in range(16, 240, 32):
                d.line((16, y, 240, y), fill=(60, 60, 60), width=4)
        elif estilo == "circles":
            for r in range(20, 120, 18):
                d.ellipse((128 - r, 128 - r, 128 + r, 128 + r), outline=(20, 20, 20), width=4)
        else:
            for offset in range(-220, 260, 24):
                d.line((offset, 0, offset + 220, 256), fill=(25, 25, 25), width=6)
        img.save(ruta, format="JPEG", quality=90)


def main():
    with tempfile.TemporaryDirectory(prefix="ecom_srv_media_") as dir_media, \
            tempfile.TemporaryDirectory(prefix="ecom_srv_bd_") as dir_bd:
        media = Path(dir_media)
        productos = [
            {
                "id": 1, "codigo": "A1", "asin": "A1", "nombre": "Wireless Controller",
                "marca": "Sony", "categoria": "Controllers", "precio": 59.99, "rating": 4.9,
                "sucursal_id": 1, "imagen": f"{config.SUBCARPETA_MULTIMEDIA}/{config.CATEGORIA_DATASET}/imagenes/A1.jpg",
                "descripcion": "Wireless gamepad controller for console", "estilo": "grid",
            },
            {
                "id": 2, "codigo": "A2", "asin": "A2", "nombre": "Controller Dock",
                "marca": "Sony", "categoria": "Controllers", "precio": 29.99, "rating": 4.7,
                "sucursal_id": 1, "imagen": f"{config.SUBCARPETA_MULTIMEDIA}/{config.CATEGORIA_DATASET}/imagenes/A2.jpg",
                "descripcion": "Dual controller charger dock wireless", "estilo": "circles",
            },
            {
                "id": 3, "codigo": "A3", "asin": "A3", "nombre": "Gaming Headset",
                "marca": "HyperX", "categoria": "Audio", "precio": 89.0, "rating": 4.6,
                "sucursal_id": 2, "imagen": f"{config.SUBCARPETA_MULTIMEDIA}/{config.CATEGORIA_DATASET}/imagenes/A3.jpg",
                "descripcion": "Surround audio headset", "estilo": "stripes",
            },
        ]
        for p in productos:
            _dibujar_patron(media / p["imagen"], p["estilo"])

        ordenes = [
            {"id": 1, "usuario_id": 1, "item_id": 1, "fecha": "2025-01-10"},
            {"id": 2, "usuario_id": 1, "item_id": 2, "fecha": "2025-01-10"},
            {"id": 3, "usuario_id": 2, "item_id": 1, "fecha": "2025-01-11"},
            {"id": 4, "usuario_id": 2, "item_id": 3, "fecha": "2025-01-11"},
        ]

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
            with patch("servidor.CARPETA_MULTIMEDIA", media), \
                    patch("cliente_bd.ejecutar", side_effect=ejecutar_local), \
                    patch("cliente_bd.cargar_caracteristicas", side_effect=cargar_feat_local), \
                    patch("cliente_bd.disponible", return_value=True):
                ingesta.cargar(productos, ordenes)
                client = TestClient(servidor.app)

                r_home = client.get("/")
                assert r_home.status_code == 200 and "MiniTienda BD2" in r_home.text

                r_estado = client.get("/api/estado")
                assert r_estado.status_code == 200
                est = r_estado.json()
                assert est["extractor"] == config.DESCRIPTOR_VISUAL and est["dimension"] == 256
                assert est["productos"] == 3 and est["ordenes"] == 4

                assert len(client.get("/api/sucursales").json()) == 8
                assert len(client.get("/api/categorias").json()) == 2

                r_prod = client.get("/api/productos", params={"categoria": "Controllers", "orden": "precio_asc"})
                assert r_prod.status_code == 200
                assert [p["id"] for p in r_prod.json()["productos"]] == [2, 1]

                assert client.get("/api/productos", params={"lat": -12.1}).status_code == 400
                assert client.get("/api/productos", params={"precio_min": 50, "precio_max": 10}).status_code == 400

                zona_miraflores = "-12.125,-77.035,-12.11,-77.02"
                r_zona = client.get("/api/productos", params={"zona": zona_miraflores})
                assert r_zona.status_code == 200
                assert {p["id"] for p in r_zona.json()["productos"]} == {1, 2}
                assert [s["id"] for s in r_zona.json()["sucursales_en_radio"]] == [1]
                pasos_zona = [p for c in r_zona.json()["consultas"] for p in c["plan"]]
                assert any(p.get("method") == "RTREE-polygon" for p in pasos_zona)
                assert all(c["sql"].endswith(";") and "ms_total" in c for c in r_zona.json()["consultas"])
                for mala in ("1,2,3", "a,b,c,d", "-12.0,-77.0,-12.1,-76.9", "-12.1,-77.0,-12.0,-77.1",
                             "nan,-77.0,-12.0,-76.9", "-95,-77.0,-12.0,-76.9"):
                    assert client.get("/api/productos", params={"zona": mala}).status_code == 400, mala
                r_rec_zona = client.get(
                    "/api/productos/1/recomendaciones", params={"zona": zona_miraflores, "k": 5}
                )
                assert r_rec_zona.status_code == 200
                assert all(r["sucursal_id"] == 1 for r in r_rec_zona.json()["recomendaciones"])
                assert client.get("/api/buscar", params={"q": "wireless", "zona": zona_miraflores}).status_code == 200
                assert client.get("/api/buscar", params={"q": "wireless", "zona": "x"}).status_code == 400

                assert client.get("/api/productos", params={"orden": "cercania"}).status_code == 400
                r_cerca = client.get(
                    "/api/productos", params={"orden": "cercania", "lat": -12.0980, "lon": -77.0360}
                )
                assert r_cerca.status_code == 200
                assert [p["id"] for p in r_cerca.json()["productos"]] == [3, 1, 2]

                assert client.get("/api/productos/1").json()["codigo"] == "A1"
                assert client.get("/api/productos/999").status_code == 404

                r_rec = client.get("/api/productos/1/recomendaciones", params={"modo": "hibrido", "fusion": "score", "k": 5})
                assert r_rec.status_code == 200
                assert r_rec.json()["fusion"] == "score"
                assert r_rec.json()["recomendaciones"][0]["id"] == 2
                assert "aportes" in r_rec.json()["recomendaciones"][0]
                assert "total_ms" in r_rec.json()["tiempos"]
                pasos_rec = [p["op"] for c in r_rec.json()["consultas"] for p in c["plan"]]
                assert "Vector Index Scan" in pasos_rec and "Text Index Scan" in pasos_rec

                r_rrf = client.get("/api/productos/1/recomendaciones", params={"modo": "hibrido", "fusion": "rrf", "k": 5})
                assert r_rrf.status_code == 200 and r_rrf.json()["fusion"] == "rrf"

                r_pesos = client.get(
                    "/api/productos/1/recomendaciones",
                    params={"modo": "hibrido", "w_cocompra": 1.0, "w_visual": 0.0, "w_texto": 0.0, "w_metadata": 0.0},
                )
                assert r_pesos.status_code == 200 and r_pesos.json()["recomendaciones"]
                assert client.get("/api/productos/1/recomendaciones", params={"modo": "espacial"}).status_code == 400
                r_esp = client.get(
                    "/api/productos/1/recomendaciones",
                    params={"modo": "espacial", "lat": -12.1190, "lon": -77.0290, "k": 5},
                )
                assert r_esp.status_code == 200
                assert r_esp.json()["sucursales_knn"]
                assert "espacial" in r_esp.json()["recomendaciones"][0]["posiciones"]
                r_hib_esp = client.get(
                    "/api/productos/1/recomendaciones",
                    params={"modo": "hibrido", "lat": -12.1190, "lon": -77.0290, "w_espacial": 0.3, "k": 5},
                )
                assert r_hib_esp.status_code == 200
                assert "espacial_ms" in r_hib_esp.json()["tiempos"]
                assert r_hib_esp.json()["sucursales_knn"]
                assert any("espacial" in r["aportes"] for r in r_hib_esp.json()["recomendaciones"])
                assert client.get("/api/productos/1/recomendaciones", params={"modo": "malo"}).status_code == 400
                assert client.get("/api/productos/1/recomendaciones", params={"modo": "hibrido", "fusion": "malo"}).status_code == 400
                assert client.get("/api/productos/999/recomendaciones").status_code == 404

                assert client.get("/api/buscar", params={"q": "wireless", "modo": "bm25"}).status_code == 200
                assert client.get("/api/buscar", params={"q": "wireless", "modo": "tf_idf"}).status_code == 200
                assert client.get("/api/buscar", params={"q": "wireless", "modo": "malo"}).status_code == 400
                assert client.get("/api/buscar", params={"q": "   "}).status_code == 400

                img_bytes = (media / productos[0]["imagen"]).read_bytes()
                r_img = client.post(
                    "/api/buscar/imagen",
                    files={"archivo": ("consulta.jpg", img_bytes, "image/jpeg")},
                    data={"k": "2"},
                )
                assert r_img.status_code == 200
                assert r_img.json()["productos"][0]["id"] == 1
                consultas_dir = media / config.SUBCARPETA_MULTIMEDIA / "_consultas"
                assert list(consultas_dir.iterdir()) == []

                assert client.post(
                    "/api/buscar/imagen",
                    files={"archivo": ("mal.jpg", b"no es jpeg", "image/jpeg")},
                ).status_code == 400

                assert client.post(
                    "/api/buscar/imagen",
                    files={"archivo": ("foto.jpg", img_bytes, "image/jpeg")},
                    data={"precio_min": "-5"},
                ).status_code == 400

            with patch("cliente_bd.disponible", return_value=False):
                est_down = client.get("/api/estado").json()
                assert est_down["motor"] is False and est_down["productos"] == 0
        finally:
            for tabla in catalogo_bd.values():
                tabla.cerrar()

    print("OK: ecommerce servidor API")


if __name__ == "__main__":
    main()
