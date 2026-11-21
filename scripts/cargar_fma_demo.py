import os
import csv
import json
import time
import urllib.request
from pathlib import Path

# con docker compose el backend no publica el 8000: usar BD2_URL=http://localhost:8080 (nginx reenvía /api)
API = os.environ.get("BD2_URL", "http://localhost:8000")
RAIZ = Path(__file__).resolve().parent.parent
MULTIMEDIA = RAIZ / "data" / "multimedia"
MANIFIESTO = MULTIMEDIA / "audio" / "fma_small" / "manifest.csv"
TRACKS = MULTIMEDIA / "audio" / "fma_metadata" / "tracks.csv"
TABLA = "musica"
POR_GENERO = 25
LOTE = 500
DESCRIPTOR = "mfcc:sr22050:n13:fft2048:hop512:sinc0:dur30"


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


def generos():
    with open(TRACKS, encoding="utf-8", newline="") as archivo:
        lector = csv.reader(archivo)
        nivel1, nivel2, _ = next(lector), next(lector), next(lector)
        columna = next(i for i in range(len(nivel1)) if nivel1[i] == "track" and nivel2[i] == "genre_top")
        return {int(fila[0]): fila[columna] for fila in lector if fila[columna]}


genero_de = generos()
cuenta = {}
filas = []
with open(MANIFIESTO, encoding="utf-8") as archivo:
    for fila in csv.DictReader(archivo):
        genero = genero_de.get(int(fila["track_id"]))
        if genero is None or cuenta.get(genero, 0) >= POR_GENERO:
            continue
        if (MULTIMEDIA / fila["ruta"]).stat().st_size < 100_000:
            continue
        cuenta[genero] = cuenta.get(genero, 0) + 1
        filas.append((len(filas) + 1, fila["ruta"], genero))
print(f"{len(filas)} canciones por género: {cuenta}")

inicio = time.time()
sql(f"CREATE TABLE {TABLA} (id INT PRIMARY KEY, ruta VARCHAR(60), genero VARCHAR(20), v VECTOR(256));")
for i in range(0, len(filas), LOTE):
    valores = ", ".join(f"({numero}, '{ruta}', '{genero}')" for numero, ruta, genero in filas[i:i + LOTE])
    sql(f"INSERT INTO {TABLA} (id, ruta, genero) VALUES {valores};")
print(f"Filas insertadas en {time.time() - inicio:.0f} s")

inicio = time.time()
datos = enviar(f"/api/tables/{TABLA}/features", {"path_column": "ruta", "descriptor_id": DESCRIPTOR})
print(f"Features de {datos['rowsLoaded']} canciones en {time.time() - inicio:.0f} s")

sql(f"CREATE INDEX idx_{TABLA} ON {TABLA} (v) USING HNSW WITH (METRIC=cosine);")
print("Índice HNSW creado. Ya puedes consultar desde la app.")