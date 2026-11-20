import io
import math
import sys
import time
import uuid
from pathlib import Path

RAIZ_ECOM = Path(__file__).resolve().parent
if str(RAIZ_ECOM) not in sys.path:
    sys.path.insert(0, str(RAIZ_ECOM))

import requests
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image

import cliente_bd as bd
import recomendador
import visuales
from config import (
    CARPETA_MULTIMEDIA,
    CATEGORIA_DATASET,
    DESCRIPTOR_VISUAL,
    DIMENSION,
    FUSION_DEFECTO,
    K_RECOMENDACIONES,
    MODELO_VISUAL_DEFECTO,
    PESO_ESPACIAL_DEFECTO,
    PESOS_DEFECTO,
    PUERTO,
    SUBCARPETA_MULTIMEDIA,
    TABLA_CATALOGO,
    TABLA_ORDENES,
    TABLA_SUCURSALES,
    TABLAS_VISUALES,
)

MAX_IMAGEN_BYTES = 10 * 1024 * 1024
# La web pagina las búsquedas pidiendo pagina*limite+1 resultados; tope para que no recorra todo el índice.
MAX_K_BUSQUEDA = 100

CARPETA_MULTIMEDIA.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Recomendador E-commerce BD2")
app.mount("/static", StaticFiles(directory=RAIZ_ECOM / "web"), name="static")
app.mount("/media", StaticFiles(directory=CARPETA_MULTIMEDIA), name="media")


def _conteo(tabla):
    filas = bd.filas(f"SELECT COUNT(*) FROM {tabla};")
    return filas[0]["conteo"] if filas else 0


def _zona(zona):
    """Valida 'sur,oeste,norte,este' (grados) como rectángulo con área: el R-Tree lo usa como POLYGON."""
    try:
        sur, oeste, norte, este = (float(v) for v in zona.split(","))
    except ValueError as error:
        raise HTTPException(status_code=400, detail="zona debe ser 'sur,oeste,norte,este'") from error
    if not all(math.isfinite(v) for v in (sur, oeste, norte, este)):
        raise HTTPException(status_code=400, detail="zona requiere valores finitos")
    if not (-90.0 <= sur < norte <= 90.0 and -180.0 <= oeste < este <= 180.0):
        raise HTTPException(
            status_code=400,
            detail="zona inválida: requiere sur < norte en [-90, 90] y oeste < este en [-180, 180]",
        )
    return (sur, oeste, norte, este)


def _filtros(categoria, precio_min, precio_max, lat, lon, radio_m, zona=None):
    if (lat is None) != (lon is None):
        raise HTTPException(status_code=400, detail="lat y lon deben enviarse juntos")
    if radio_m is not None:
        if lat is None or lon is None:
            raise HTTPException(status_code=400, detail="radio_m requiere lat y lon")
        if radio_m <= 0:
            raise HTTPException(status_code=400, detail="radio_m debe ser mayor a cero")
    if lat is not None and not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        raise HTTPException(status_code=400, detail="coordenadas fuera de rango")
    if precio_min is not None and precio_min < 0:
        raise HTTPException(status_code=400, detail="precio_min no puede ser negativo")
    if precio_max is not None and precio_max < 0:
        raise HTTPException(status_code=400, detail="precio_max no puede ser negativo")
    if precio_min is not None and precio_max is not None and precio_min > precio_max:
        raise HTTPException(status_code=400, detail="precio_min no puede superar a precio_max")
    return {
        "categoria": categoria or None,
        "precio_min": precio_min,
        "precio_max": precio_max,
        "lat": lat,
        "lon": lon,
        "radio_m": radio_m,
        "zona": _zona(zona) if zona else None,
    }


@app.get("/")
def inicio():
    return FileResponse(RAIZ_ECOM / "web" / "index.html")


@app.get("/api/estado")
def estado():
    salida = {
        "motor": bd.disponible(),
        "extractor": DESCRIPTOR_VISUAL,
        "dimension": DIMENSION,
        "categoria": CATEGORIA_DATASET,
        "productos": 0,
        "sucursales": 0,
        "ordenes": 0,
        "modelos_visuales": [],
    }
    if not salida["motor"]:
        return salida
    try:
        salida["productos"] = _conteo(TABLA_CATALOGO)
        salida["sucursales"] = _conteo(TABLA_SUCURSALES)
        salida["ordenes"] = _conteo(TABLA_ORDENES)
        cargadas = {tabla["name"] for tabla in bd.tablas()}
        salida["modelos_visuales"] = [
            m for m in visuales.modelos_instalados() if TABLAS_VISUALES[m] in cargadas
        ]
    except (bd.ErrorMotor, requests.RequestException):
        pass
    return salida


@app.get("/api/categorias")
def categorias():
    try:
        return recomendador.listar_categorias()
    except bd.ErrorMotor:
        return []


@app.get("/api/sucursales")
def sucursales():
    try:
        return recomendador.listar_sucursales()
    except bd.ErrorMotor:
        return []


@app.get("/api/productos")
def productos(
    categoria: str | None = Query(default=None),
    precio_min: float | None = Query(default=None, ge=0.0),
    precio_max: float | None = Query(default=None, ge=0.0),
    orden: str = Query(default="rating"),
    limite: int = Query(default=24, ge=1, le=100),
    pagina: int = Query(default=1, ge=1),
    lat: float | None = Query(default=None),
    lon: float | None = Query(default=None),
    radio_m: float | None = Query(default=None),
    zona: str | None = Query(default=None),
):
    filtros = _filtros(categoria, precio_min, precio_max, lat, lon, radio_m, zona)
    try:
        with bd.registrar_consultas() as consultas:
            salida = recomendador.listar_productos(
                categoria=filtros["categoria"],
                precio_min=filtros["precio_min"],
                precio_max=filtros["precio_max"],
                orden=orden,
                limite=limite,
                pagina=pagina,
                lat=filtros["lat"],
                lon=filtros["lon"],
                radio_m=filtros["radio_m"],
                zona=filtros["zona"],
            )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except bd.ErrorMotor as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    salida["consultas"] = consultas
    return salida


@app.get("/api/productos/{item_id}")
def detalle_producto(
    item_id: int,
    lat: float | None = Query(default=None),
    lon: float | None = Query(default=None),
):
    _filtros(None, None, None, lat, lon, None)
    try:
        item = recomendador.obtener_producto(item_id, lat=lat, lon=lon)
    except bd.ErrorMotor as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    if item is None:
        raise HTTPException(status_code=404, detail=f"producto {item_id} no encontrado")
    return item


@app.get("/api/productos/{item_id}/recomendaciones")
def recomendaciones_producto(
    item_id: int,
    modo: str = Query(default="hibrido"),
    fusion: str = Query(default=FUSION_DEFECTO),
    visual: str = Query(default=MODELO_VISUAL_DEFECTO),
    k: int = Query(default=K_RECOMENDACIONES, ge=1, le=30),
    w_cocompra: float | None = Query(default=None, ge=0.0, le=10.0),
    w_visual: float | None = Query(default=None, ge=0.0, le=10.0),
    w_texto: float | None = Query(default=None, ge=0.0, le=10.0),
    w_metadata: float | None = Query(default=None, ge=0.0, le=10.0),
    w_espacial: float | None = Query(default=None, ge=0.0, le=10.0),
    categoria: str | None = Query(default=None),
    precio_min: float | None = Query(default=None, ge=0.0),
    precio_max: float | None = Query(default=None, ge=0.0),
    lat: float | None = Query(default=None),
    lon: float | None = Query(default=None),
    radio_m: float | None = Query(default=None),
    zona: str | None = Query(default=None),
):
    filtros = _filtros(categoria, precio_min, precio_max, lat, lon, radio_m, zona)
    pesos = None
    personalizados = {
        "cocompra": w_cocompra,
        "visual": w_visual,
        "texto": w_texto,
        "metadata": w_metadata,
        "espacial": w_espacial,
    }
    if any(valor is not None for valor in personalizados.values()):
        base_pesos = {**PESOS_DEFECTO, "espacial": PESO_ESPACIAL_DEFECTO}
        pesos = {
            clave: (valor if valor is not None else base_pesos[clave])
            for clave, valor in personalizados.items()
        }
    t0 = time.perf_counter()
    try:
        with bd.registrar_consultas() as consultas:
            salida = recomendador.recomendar(
                item_id, modo=modo, k=k, pesos=pesos, filtros=filtros, fusion=fusion, modelo_visual=visual
            )
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except bd.ErrorMotor as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    salida["tiempos"]["total_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    salida["consultas"] = consultas
    return salida


@app.get("/api/buscar")
def buscar_por_texto(
    q: str = Query(..., min_length=1),
    modo: str = Query(default="bm25"),
    k: int = Query(default=K_RECOMENDACIONES, ge=1, le=MAX_K_BUSQUEDA),
    categoria: str | None = Query(default=None),
    precio_min: float | None = Query(default=None, ge=0.0),
    precio_max: float | None = Query(default=None, ge=0.0),
    lat: float | None = Query(default=None),
    lon: float | None = Query(default=None),
    radio_m: float | None = Query(default=None),
    zona: str | None = Query(default=None),
):
    consulta = q.strip()
    if not consulta:
        raise HTTPException(status_code=400, detail="la consulta no puede estar vacía")
    filtros = _filtros(categoria, precio_min, precio_max, lat, lon, radio_m, zona)
    t0 = time.perf_counter()
    try:
        with bd.registrar_consultas() as consultas:
            salida = recomendador.buscar_texto(consulta, modo=modo, k=k, filtros=filtros)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except bd.ErrorMotor as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    salida["tiempos"]["total_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    salida["consultas"] = consultas
    return salida


@app.post("/api/buscar/imagen")
async def buscar_por_imagen(
    archivo: UploadFile = File(...),
    k: int = Form(default=K_RECOMENDACIONES, ge=1, le=MAX_K_BUSQUEDA),
    categoria: str | None = Form(default=None),
    precio_min: float | None = Form(default=None),
    precio_max: float | None = Form(default=None),
    lat: float | None = Form(default=None),
    lon: float | None = Form(default=None),
    radio_m: float | None = Form(default=None),
    zona: str | None = Form(default=None),
    visual: str = Form(default=MODELO_VISUAL_DEFECTO),
):
    filtros = _filtros(categoria, precio_min, precio_max, lat, lon, radio_m, zona)
    if visual not in TABLAS_VISUALES:
        raise HTTPException(status_code=400, detail=f"modelo visual desconocido '{visual}'")
    contenido = await archivo.read(MAX_IMAGEN_BYTES + 1)
    if not contenido:
        raise HTTPException(status_code=400, detail="archivo vacío")
    if len(contenido) > MAX_IMAGEN_BYTES:
        raise HTTPException(status_code=413, detail="la imagen excede 10 MB")

    carpeta_consultas = CARPETA_MULTIMEDIA / SUBCARPETA_MULTIMEDIA / "_consultas"
    carpeta_consultas.mkdir(parents=True, exist_ok=True)
    nombre = f"{uuid.uuid4().hex}.jpg"
    destino = carpeta_consultas / nombre
    ruta_rel = f"{SUBCARPETA_MULTIMEDIA}/_consultas/{nombre}"

    try:
        with Image.open(io.BytesIO(contenido)) as cruda:
            with cruda.convert("RGB") as rgb:
                rgb.thumbnail((512, 512))
                rgb.save(destino, format="JPEG", quality=85)
    except Exception as error:
        destino.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="imagen inválida o corrupta") from error

    t0 = time.perf_counter()
    try:
        with bd.registrar_consultas() as consultas:
            salida = recomendador.buscar_imagen(ruta_rel, k=k, filtros=filtros, modelo_visual=visual)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except bd.ErrorMotor as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    finally:
        destino.unlink(missing_ok=True)
    salida["tiempos"]["total_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    salida["consultas"] = consultas
    return salida


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=PUERTO)
