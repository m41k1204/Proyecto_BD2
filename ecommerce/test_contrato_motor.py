import sys
import tempfile
from pathlib import Path

RAIZ_ECOM = Path(__file__).resolve().parent
RAIZ_PROYECTO = RAIZ_ECOM.parent
sys.path.insert(0, str(RAIZ_ECOM))
sys.path.insert(0, str(RAIZ_PROYECTO / "backend"))

from PIL import Image, ImageDraw

from engine.catalog import _load_tables
from engine.multimedia.pipeline import FeaturePipeline
from engine.parser.executor import Executor
from engine.parser.scanner import Scanner
from engine.parser.sql_parser import Parser

import cliente_bd as bd
import config


def correr(executor, sql):
    sentencias = Parser(Scanner(sql)).parse_program()
    resultados = executor.run(sentencias)
    for resultado in resultados:
        assert "error" not in resultado, f"SQL falló: {sql}\n{resultado.get('error')}"
    return resultados[-1]


def dibujar_patron(ruta, estilo):
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
            d.line((128, 10, 128, 246), fill=(40, 40, 40), width=3)
        elif estilo == "stripes":
            for offset in range(-220, 260, 24):
                d.line((offset, 0, offset + 220, 256), fill=(25, 25, 25), width=6)
                d.rectangle((max(0, offset), 40, max(12, offset + 12), 52), fill=(80, 80, 80))
        elif estilo == "diamonds":
            for s in range(24, 120, 22):
                d.polygon([(128, 128 - s), (128 + s, 128), (128, 128 + s), (128 - s, 128)], outline=(20, 20, 20), width=4)
        else:
            for y in range(16, 240, 28):
                for x in range(16, 240, 28):
                    if ((x + y) // 28) % 2 == 0:
                        d.rectangle((x, y, x + 16, y + 16), fill=(25, 25, 25))
        img.save(ruta, format="JPEG", quality=90)


def crear_esquema(executor):
    correr(
        executor,
        f"""
        CREATE TABLE {config.TABLA_SUCURSALES} (
            id INT PRIMARY KEY,
            nombre VARCHAR(100),
            distrito VARCHAR(60),
            ubicacion POINT
        ) USING BPLUS;
        CREATE TABLE {config.TABLA_CATALOGO} (
            id INT PRIMARY KEY,
            codigo VARCHAR(20),
            nombre VARCHAR(200),
            marca VARCHAR(80),
            categoria VARCHAR(80),
            precio FLOAT,
            rating FLOAT,
            sucursal_id INT,
            imagen VARCHAR(255),
            descripcion TEXT,
            emb VECTOR({config.DIMENSION})
        ) USING BPLUS;
        CREATE TABLE {config.TABLA_ORDENES} (
            id INT PRIMARY KEY,
            usuario_id INT,
            item_id INT,
            fecha DATE
        ) USING BPLUS;
        """,
    )


def sembrar_datos(executor, pipeline, carpeta_media):
    sucursales = [
        (1, "Tienda Miraflores", "Miraflores", -12.1190, -77.0290),
        (2, "Tienda San Isidro", "San Isidro", -12.0980, -77.0360),
        (3, "Tienda Callao Norte", "Callao", -11.9800, -77.1200),
    ]
    valores_suc = ", ".join(
        f"({bd.numero_sql(s[0])}, {bd.texto_sql(s[1])}, {bd.texto_sql(s[2])}, {bd.punto_sql(s[3], s[4])})"
        for s in sucursales
    )
    correr(executor, f"INSERT INTO {config.TABLA_SUCURSALES} VALUES {valores_suc};")

    productos = [
        (1, "B001", "Pro Wireless Controller", "Sony", "Consoles", 249.9, 4.8, 1,
         "ecommerce/Video_Games/imagenes/1.jpg", "Wireless controller gaming console\nErgonomic grip & USB-C", "grid"),
        (2, "B002", "DualSense Charging Dock", "Sony", "Consoles", 129.0, 4.9, 1,
         "ecommerce/Video_Games/imagenes/2.jpg", "Fast wireless controller charger\nLED dock for console", "grid_b"),
        (3, "B003", "Pro Gaming Headset", "HyperX", "Consoles", 199.5, 4.5, 2,
         "ecommerce/Video_Games/imagenes/3.jpg", "Surround headset for wireless gaming console sessions", "circles"),
        (4, "B004", "Retro Cartridge Kit", "Nintendo", "Consoles", 149.0, 4.2, 3,
         "ecommerce/Video_Games/imagenes/4.jpg", "Classic pixel adventure game collection's edition", "stripes"),
        (5, "B005", "Mechanical RGB Keyboard", "Logitech", "PC", 320.0, 4.7, 2,
         "ecommerce/Video_Games/imagenes/5.jpg", "Tactile switches gaming keyboard with wireless receiver", "diamonds"),
        (6, "B006", "Arcade Fight Stick", "Hori", "Consoles", 85.0, 4.6, 1,
         "ecommerce/Video_Games/imagenes/6.jpg", "Tournament arcade stick compatible with console", "checker"),
    ]
    for p in productos:
        dibujar_patron(carpeta_media / p[8], p[10])

    valores_cat = ", ".join(
        "("
        + ", ".join([
            bd.numero_sql(p[0]), bd.texto_sql(p[1]), bd.texto_sql(p[2]),
            bd.texto_sql(p[3]), bd.texto_sql(p[4]), bd.numero_sql(p[5]),
            bd.numero_sql(p[6]), bd.numero_sql(p[7]), bd.texto_sql(p[8]),
            bd.texto_sql(p[9]),
        ])
        + ")"
        for p in productos
    )
    cols = "id, codigo, nombre, marca, categoria, precio, rating, sucursal_id, imagen, descripcion"
    correr(executor, f"INSERT INTO {config.TABLA_CATALOGO} ({cols}) VALUES {valores_cat};")

    cargadas = pipeline.cargar(executor.catalog[config.TABLA_CATALOGO], "imagen", config.DESCRIPTOR_VISUAL)
    assert cargadas == 6

    ordenes = [
        (1, 101, 1, "2025-01-10"), (2, 101, 2, "2025-01-10"),
        (3, 102, 1, "2025-01-11"), (4, 102, 2, "2025-01-11"),
        (5, 103, 1, "2025-01-12"), (6, 103, 2, "2025-01-12"), (7, 103, 3, "2025-01-12"),
        (8, 104, 1, "2025-01-13"), (9, 104, 3, "2025-01-13"),
        (10, 105, 4, "2025-01-14"), (11, 105, 5, "2025-01-14"),
    ]
    valores_ord = ", ".join(
        f"({bd.numero_sql(o[0])}, {bd.numero_sql(o[1])}, {bd.numero_sql(o[2])}, {bd.texto_sql(o[3])})"
        for o in ordenes
    )
    correr(executor, f"INSERT INTO {config.TABLA_ORDENES} VALUES {valores_ord};")


def crear_indices(executor):
    correr(
        executor,
        f"""
        CREATE INDEX {config.INDICE_CAT_CATEGORIA} ON {config.TABLA_CATALOGO} (categoria) USING BPLUS;
        CREATE INDEX {config.INDICE_CAT_SUCURSAL} ON {config.TABLA_CATALOGO} (sucursal_id) USING BPLUS;
        CREATE INDEX {config.INDICE_TEXTO} ON {config.TABLA_CATALOGO} (descripcion) USING FULLTEXT;
        CREATE INDEX {config.INDICE_VECTORES} ON {config.TABLA_CATALOGO} (emb) USING HNSW WITH (METRIC=cosine);
        CREATE INDEX {config.INDICE_ORD_USUARIO} ON {config.TABLA_ORDENES} (usuario_id) USING BPLUS;
        CREATE INDEX {config.INDICE_ORD_ITEM} ON {config.TABLA_ORDENES} (item_id) USING BPLUS;
        """,
    )


def verificar_consultas(executor):
    cocompra = correr(
        executor,
        f"""
        SELECT o2.item_id, COUNT(*)
        FROM {config.TABLA_ORDENES} AS o1
        JOIN {config.TABLA_ORDENES} AS o2 ON o1.usuario_id = o2.usuario_id
        WHERE o1.item_id = 1 AND o2.item_id != 1
        GROUP BY o2.item_id
        ORDER BY conteo DESC
        LIMIT {config.K_RECOMENDACIONES};
        """,
    )
    assert [(r["o2.item_id"], r["conteo"]) for r in cocompra["rows"]] == [(2, 3), (3, 2)]

    metadata = correr(
        executor,
        f"""
        SELECT id, nombre, categoria, precio, rating, sucursal_id, imagen
        FROM {config.TABLA_CATALOGO}
        WHERE categoria = 'Consoles' AND precio BETWEEN 100 AND 500 AND id != 1
        ORDER BY rating DESC
        LIMIT {config.K_RECOMENDACIONES};
        """,
    )
    assert [r["id"] for r in metadata["rows"]] == [2, 3, 4]

    visual = correr(
        executor,
        f"""
        SELECT id, nombre, SIMILARITY_SCORE() AS puntaje
        FROM {config.TABLA_CATALOGO}
        WHERE SIMILAR_TO('ecommerce/Video_Games/imagenes/1.jpg', k=3) AND id != 1
        USING HNSW WITH METRIC=cosine;
        """,
    )
    ids_visual = [r["id"] for r in visual["rows"]]
    assert 1 not in ids_visual and len(ids_visual) == 3
    assert any(p["op"] == "Vector Index Scan" for p in visual["plan"])

    texto = correr(
        executor,
        f"""
        SELECT id, nombre, SCORE() AS puntaje
        FROM {config.TABLA_CATALOGO}
        WHERE MATCH(descripcion, 'wireless controller gaming') AND id != 1
        USING BM25
        LIMIT 5;
        """,
    )
    ids_texto = [r["id"] for r in texto["rows"]]
    assert 1 not in ids_texto and len(ids_texto) >= 3 and ids_texto[0] == 2
    assert any(p["op"] == "Text Index Scan" for p in texto["plan"])

    espacial = correr(
        executor,
        f"""
        SELECT id, nombre, distrito
        FROM {config.TABLA_SUCURSALES}
        WHERE distancia(ubicacion, {bd.punto_sql(-12.1190, -77.0290)}) < 6000;
        """,
    )
    ids_suc = sorted(r["id"] for r in espacial["rows"])
    assert ids_suc == [1, 2]
    assert any(p["op"] == "Spatial Index Scan" and p["method"] == "RTREE-radius" for p in espacial["plan"])

    knn = correr(
        executor,
        f"""
        SELECT id, nombre, distrito, ubicacion
        FROM {config.TABLA_SUCURSALES}
        ORDER BY distancia(ubicacion, {bd.punto_sql(-12.1190, -77.0290)})
        LIMIT 2;
        """,
    )
    assert [r["id"] for r in knn["rows"]] == [1, 2]
    assert any(p["op"] == "Spatial Index Scan" and p["method"] == "RTREE-knn" for p in knn["plan"])

    # Rectángulo "zona visible" (sur, oeste, norte, este) como lo arma recomendador.sucursales_en_zona.
    sur, oeste, norte, este = -12.13, -77.06, -12.08, -76.99
    vertices = ((sur, oeste), (norte, oeste), (norte, este), (sur, este))
    poligono = "POLYGON(" + ", ".join(bd.punto_sql(la, lo) for la, lo in vertices) + ")"
    zona = correr(
        executor,
        f"SELECT id FROM {config.TABLA_SUCURSALES} WHERE intersecta(ubicacion, {poligono});",
    )
    assert sorted(r["id"] for r in zona["rows"]) == [1, 2]
    assert any(p["op"] == "Spatial Index Scan" and p["method"] == "RTREE-polygon" for p in zona["plan"])

    bloque = correr(
        executor,
        f"""
        SELECT id FROM {config.TABLA_CATALOGO}
        WHERE sucursal_id = 1 AND categoria = 'Consoles'
        ORDER BY rating DESC LIMIT 2;
        """,
    )
    assert [r["id"] for r in bloque["rows"]] == [2, 1]

    cercanos = correr(
        executor,
        f"""
        SELECT id, nombre
        FROM {config.TABLA_CATALOGO}
        WHERE sucursal_id IN {bd.lista_sql(ids_suc)} AND id != 1;
        """,
    )
    assert sorted(r["id"] for r in cercanos["rows"]) == [2, 3, 5, 6]


def cerrar_tablas(catalogo):
    for tabla in catalogo.values():
        tabla.cerrar()


def main():
    with tempfile.TemporaryDirectory(prefix="ecom_contrato_bd_") as carpeta_bd, \
            tempfile.TemporaryDirectory(prefix="ecom_contrato_media_") as carpeta_media:
        media = Path(carpeta_media)
        pipeline = FeaturePipeline(media, RAIZ_PROYECTO / "data" / "modelos")
        catalogo = {}
        try:
            executor = Executor(catalogo, data_dir=carpeta_bd, vectorizador=pipeline.vectorizar)
            crear_esquema(executor)
            sembrar_datos(executor, pipeline, media)
            crear_indices(executor)
            verificar_consultas(executor)
        finally:
            cerrar_tablas(catalogo)

        reabierto = _load_tables(carpeta_bd)
        try:
            executor_reabierto = Executor(
                reabierto, data_dir=carpeta_bd, vectorizador=pipeline.vectorizar
            )
            verificar_consultas(executor_reabierto)
        finally:
            cerrar_tablas(reabierto)

    print("OK: contrato SQL ecommerce contra motor BD2")


if __name__ == "__main__":
    main()
