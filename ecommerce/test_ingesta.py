import csv
import gzip
import io
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

RAIZ_ECOM = Path(__file__).resolve().parent
RAIZ_PROYECTO = RAIZ_ECOM.parent
sys.path.insert(0, str(RAIZ_ECOM))
sys.path.insert(0, str(RAIZ_PROYECTO / "backend"))

from PIL import Image, ImageDraw

from engine.multimedia.pipeline import FeaturePipeline
from engine.parser.executor import Executor
from engine.parser.scanner import Scanner
from engine.parser.sql_parser import Parser

import cliente_bd as bd
import config
import ingesta


def _dibujar_patron(ruta, paso):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with Image.new("RGB", (256, 256), (242, 242, 242)) as img:
        d = ImageDraw.Draw(img)
        for x in range(16, 240, paso):
            d.rectangle((x, 16, x + 10, 240), fill=(25, 25, 25))
            d.line((16, x, 240, x), fill=(60, 60, 60), width=4)
        img.save(ruta, format="JPEG", quality=90)


def _jpeg_bytes(paso=28):
    buf = io.BytesIO()
    with Image.new("RGB", (128, 128), (240, 240, 240)) as img:
        d = ImageDraw.Draw(img)
        for x in range(12, 116, paso):
            d.rectangle((x, 12, x + 8, 116), fill=(25, 25, 25))
        img.save(buf, format="JPEG")
    return buf.getvalue()


def probar_helpers_ingesta():
    assert ingesta.parsear_precio("$29.99") == 29.99
    assert ingesta.parsear_precio("$1,299.5") == 1299.5
    assert ingesta.parsear_precio("from $19.99") == 19.99
    assert ingesta.parsear_precio(15) == 15.0
    for nulo in (None, "", "None", "null", -5, float("inf"), 2_000_000, True):
        assert ingesta.parsear_precio(nulo) is None

    assert ingesta.parsear_fecha(1672531200000) == "2023-01-01"
    assert ingesta.parsear_fecha(1672617600) == "2023-01-02"
    assert ingesta.parsear_fecha(None) == "2023-01-01"
    assert ingesta.parsear_fecha(-10) == "2023-01-01"
    assert ingesta.parsear_fecha("no-fecha") == "2023-01-01"

    img_dict = {
        "variant": ["PT01", "MAIN"],
        "large": ["https://ex.com/pt01_l.jpg", None],
        "hi_res": ["https://ex.com/pt01_h.jpg", "https://ex.com/main_h.jpg"],
        "thumb": ["https://ex.com/pt01_t.jpg", "https://ex.com/main_t.jpg"],
    }
    assert ingesta.extraer_url_imagen(img_dict) == "https://ex.com/main_h.jpg"

    img_list = [
        {"variant": "PT01", "large": "https://ex.com/pt.jpg"},
        {"variant": "MAIN", "large": "https://ex.com/main.jpg"},
    ]
    assert ingesta.extraer_url_imagen(img_list) == "https://ex.com/main.jpg"
    assert ingesta.extraer_url_imagen({"large": ["no-http"]}) is None

    assert ingesta.extraer_categoria(
        {"categories": ["Video Games", "PlayStation 5", "Controllers"], "main_category": "VG"},
        "Video_Games",
    ) == "PlayStation 5 > Controllers"
    assert ingesta.extraer_categoria({"categories": [], "main_category": "Consoles"}, "VG") == "Consoles"
    assert ingesta.extraer_categoria({}, "Video_Games") == "Video_Games"

    recortado = ingesta.recortar_utf8("🎮" * 25 + "\n\ttexto", 20)
    assert len(recortado) <= 20 and len(recortado.encode("utf-8")) <= 80

    desc = ingesta.armar_descripcion(
        {
            "title": "DualSense\nController",
            "store": "Sony",
            "features": ["Haptic feedback", "USB-C"],
            "description": ["Ergonomic\nwireless controller's grip"],
        },
        "Controllers",
    )
    assert "\n" not in desc and "Haptic feedback" in desc and "controller's" in desc

    inter = [
        ("u1", "A", 1672531200), ("u1", "B", 1672531200), ("u1", "B", 1672617600),
        ("u2", "A", 1672617600), ("u2", "C", 1672617600),
        ("u3", "A", 1672704000),
    ]
    ordenes = ingesta.construir_ordenes(inter, {"A": 1, "B": 2, "C": 3}, max_ordenes=10)
    assert len(ordenes) == 4
    assert all(o["usuario_id"] in (1, 2) for o in ordenes)
    assert ingesta.construir_ordenes(inter, {"A": 1, "B": 2, "C": 3}, max_ordenes=0) == []


def probar_descarga_imagenes():
    with tempfile.TemporaryDirectory(prefix="ecom_img_") as carpeta:
        carpeta_img = Path(carpeta) / config.SUBCARPETA_MULTIMEDIA / "Video_Games" / "imagenes"
        candidatos = [
            {"asin": "OK1", "codigo": "OK1", "url_imagen": "https://img/1.jpg"},
            {"asin": "BAD", "codigo": "BAD", "url_imagen": "https://img/bad.jpg"},
            {"asin": "OK2", "codigo": "OK2", "url_imagen": "https://img/2.jpg"},
            {"asin": "EXTRA", "codigo": "EXTRA", "url_imagen": "https://img/3.jpg"},
        ]

        def fake_get(url, timeout=20):
            resp = Mock()
            if "bad" in url:
                resp.raise_for_status.side_effect = OSError("404")
            else:
                resp.content = _jpeg_bytes()
            return resp

        with patch("ingesta.requests.get", side_effect=fake_get) as get_mock:
            productos = ingesta.descargar_imagenes(
                candidatos, carpeta_img, limite=2, hilos=2, categoria="Video_Games"
            )
            assert [p["asin"] for p in productos] == ["OK1", "OK2"]
            assert [p["id"] for p in productos] == [1, 2]
            assert productos[0]["imagen"] == "ecommerce/Video_Games/imagenes/OK1.jpg"
            assert Path(productos[0]["ruta_imagen"]).exists()
            assert get_mock.call_count <= 3


def probar_e2e_motor():
    with tempfile.TemporaryDirectory(prefix="ecom_e2e_datos_") as carpeta_datos, \
            tempfile.TemporaryDirectory(prefix="ecom_e2e_media_") as carpeta_media, \
            tempfile.TemporaryDirectory(prefix="ecom_e2e_bd_") as carpeta_bd:
        tmp = Path(carpeta_datos)
        media = Path(carpeta_media)
        csv_gz = tmp / "Video_Games.csv.gz"
        with gzip.open(csv_gz, "wt", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["user_id", "parent_asin", "rating", "timestamp"])
            for u, asin, r, ts in [
                ("U1", "P1", "5.0", "1672531200000"),
                ("U1", "P2", "4.0", "1672531200000"),
                ("U2", "P1", "5.0", "1672617600000"),
                ("U2", "P2", "5.0", "1672617600000"),
                ("U2", "P3", "4.5", "1672617600000"),
                ("U3", "P1", "1.0", "1672617600000"),
                ("U4", "P3", "5.0", "1672704000000"),
                ("U4", "P4", "4.0", "1672704000000"),
            ]:
                w.writerow([u, asin, r, ts])

        meta_gz = tmp / "meta_Video_Games.jsonl.gz"
        registros = [
            {
                "parent_asin": "P1",
                "title": "Wireless Pro Controller",
                "store": "Sony",
                "categories": ["Video Games", "Accessories", "Controllers"],
                "price": "$59.99",
                "average_rating": 4.8,
                "features": ["Bluetooth wireless", "USB-C"],
                "description": ["Ergonomic gamepad\nfor console gaming"],
                "images": {"variant": ["MAIN"], "large": ["https://img/p1.jpg"]},
            },
            {
                "parent_asin": "P2",
                "title": "Dual Charging Station",
                "store": "Sony",
                "categories": ["Video Games", "Accessories", "Chargers"],
                "price": "$24.99",
                "average_rating": 4.7,
                "features": ["Fast wireless controller dock"],
                "description": ["LED charger's stand for two gamepads"],
                "images": [{"variant": "MAIN", "hi_res": "https://img/p2.jpg"}],
            },
            {
                "parent_asin": "P3",
                "title": "Surround Gaming Headset",
                "store": "HyperX",
                "categories": ["Video Games", "Audio", "Headsets"],
                "price": "$89.00",
                "average_rating": 4.6,
                "features": ["Noise cancelling mic"],
                "description": ["Comfortable wireless headset"],
                "images": {"variant": ["MAIN"], "large": ["https://img/p3.jpg"]},
            },
            {
                "parent_asin": "P4",
                "title": "Retro Adventure Edition",
                "store": "Nintendo",
                "categories": ["Video Games", "Games", "RPG"],
                "price": "$49.99",
                "average_rating": 4.9,
                "features": ["Collector's edition"],
                "description": ["Classic pixel RPG cartridge"],
                "images": {"variant": ["MAIN"], "thumb": ["https://img/p4.jpg"]},
            },
        ]
        with gzip.open(meta_gz, "wt", encoding="utf-8") as f:
            for reg in registros:
                f.write(json.dumps(reg) + "\n")

        pipeline = FeaturePipeline(media, RAIZ_PROYECTO / "data" / "modelos")
        with patch("ingesta.CARPETA_DATOS", tmp), patch("ingesta.CARPETA_MULTIMEDIA", media):
            carpeta_img = ingesta.carpeta_imagenes("Video_Games")
            for asin, paso in (("P1", 24), ("P2", 26), ("P3", 38), ("P4", 52)):
                _dibujar_patron(carpeta_img / f"{asin}.jpg", paso)

            asins, inter = ingesta.leer_interacciones(csv_gz, limite=4)
            assert asins[:2] == ["P1", "P2"]

            candidatos = ingesta.leer_metadata_streaming("Video_Games", asins, 10, archivo_local=meta_gz)
            assert [c["asin"] for c in candidatos] == asins

            productos = ingesta.descargar_imagenes(candidatos, carpeta_img, limite=4, categoria="Video_Games")
            assert len(productos) == 4
            assert productos[0]["imagen"] == "ecommerce/Video_Games/imagenes/P1.jpg"
            mapa_asin_id = {p["asin"]: p["id"] for p in productos}
            ordenes = ingesta.construir_ordenes(inter, mapa_asin_id, max_ordenes=50)
            assert len(ordenes) == 7

        catalogo_bd = {}
        executor = Executor(catalogo_bd, data_dir=carpeta_bd, vectorizador=pipeline.vectorizar)

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

            assert set(catalogo_bd) == {config.TABLA_SUCURSALES, config.TABLA_CATALOGO, config.TABLA_ORDENES}
            assert len(catalogo_bd[config.TABLA_CATALOGO].almacenes["emb"]) == 4
            assert config.INDICE_VECTORES in catalogo_bd[config.TABLA_CATALOGO].indices_vectoriales
            assert config.INDICE_TEXTO in catalogo_bd[config.TABLA_CATALOGO].indices_texto
            for tabla in catalogo_bd.values():
                assert tabla.estadisticas is not None
                assert Path(tabla.stats_path).exists()

            id_p1 = mapa_asin_id["P1"]
            id_p2 = mapa_asin_id["P2"]

            txt = ejecutar_local(
                f"SELECT id, SCORE() AS puntaje FROM {config.TABLA_CATALOGO} "
                f"WHERE MATCH(descripcion, 'wireless controller') AND id != {id_p1} USING BM25 LIMIT 3;"
            )
            assert txt["rows"] and txt["rows"][0]["id"] == id_p2

            vis = ejecutar_local(
                f"SELECT id, SIMILARITY_SCORE() AS puntaje FROM {config.TABLA_CATALOGO} "
                f"WHERE SIMILAR_TO('ecommerce/Video_Games/imagenes/P1.jpg', k=2) "
                f"USING HNSW WITH METRIC=cosine;"
            )
            assert vis["rows"][0]["id"] == id_p1

            cocompra = ejecutar_local(
                f"SELECT o2.item_id, COUNT(*) FROM {config.TABLA_ORDENES} AS o1 "
                f"JOIN {config.TABLA_ORDENES} AS o2 ON o1.usuario_id = o2.usuario_id "
                f"WHERE o1.item_id = {id_p1} AND o2.item_id != {id_p1} "
                f"GROUP BY o2.item_id ORDER BY conteo DESC LIMIT 5;"
            )
            assert cocompra["rows"][0]["o2.item_id"] == id_p2 and cocompra["rows"][0]["conteo"] == 2

            suc = ejecutar_local(
                f"SELECT id FROM {config.TABLA_SUCURSALES} "
                f"WHERE distancia(ubicacion, {bd.punto_sql(-12.1190, -77.0290)}) < 6000;"
            )
            assert len(suc["rows"]) >= 4
        finally:
            for tabla in catalogo_bd.values():
                tabla.cerrar()


if __name__ == "__main__":
    probar_helpers_ingesta()
    probar_descarga_imagenes()
    probar_e2e_motor()
    print("OK: ecommerce ingesta")
