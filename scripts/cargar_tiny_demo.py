import csv
import json
import time
import urllib.request
from pathlib import Path

API = "http://localhost:8000"
RAIZ = Path(__file__).resolve().parent.parent
MANIFIESTO = RAIZ / "data" / "multimedia" / "tiny-imagenet-200" / "manifest.csv"
TABLA = "imagenes"
CLASES = ["computer keyboard", "abacus", "spider web", "school bus", "brain coral",
          "monarch", "picket fence", "pretzel", "orange", "steel arch bridge"]
LOTE = 500


def enviar(ruta, cuerpo):
    pedido = urllib.request.Request(API + ruta, data=json.dumps(cuerpo).encode("utf-8"),
                                    headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(pedido) as respuesta:
        datos = json.loads(respuesta.read())
    if "error" in datos:
        raise SystemExit(f"Error en {ruta}: {datos['error']}")
    return datos


def sql(texto):
    return enviar("/api/query", {"sql": texto})


filas = []
with open(MANIFIESTO, encoding="utf-8") as archivo:
    for fila in csv.DictReader(archivo):
        if fila["split"] == "train" and fila["clase"] in CLASES:
            filas.append((len(filas) + 1, fila["ruta"], fila["clase"]))
print(f"{len(filas)} imágenes de {len(CLASES)} clases")

inicio = time.time()
sql(f"CREATE TABLE {TABLA} (id INT PRIMARY KEY, ruta VARCHAR(100), clase VARCHAR(30), v VECTOR(256));")
for i in range(0, len(filas), LOTE):
    valores = ", ".join(f"({numero}, '{ruta}', '{clase}')" for numero, ruta, clase in filas[i:i + LOTE])
    sql(f"INSERT INTO {TABLA} (id, ruta, clase) VALUES {valores};")
print(f"Filas insertadas en {time.time() - inicio:.0f} s")

inicio = time.time()
datos = enviar(f"/api/tables/{TABLA}/features", {"path_column": "ruta", "descriptor_id": "sift:gray:max512:nf500"})
print(f"Features de {datos['rowsLoaded']} imágenes en {time.time() - inicio:.0f} s")

sql(f"CREATE INDEX idx_{TABLA} ON {TABLA} (v) USING HNSW WITH (METRIC=cosine);")
print("Índice HNSW creado. Ya puedes consultar desde la app.")