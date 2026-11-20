import contextvars
import math
import re
import time
from contextlib import contextmanager

import requests

from config import URL_MOTOR


class ErrorMotor(Exception):
    pass


# Lista de la petición HTTP en curso (None fuera de registrar_consultas()).
_consultas = contextvars.ContextVar("consultas_motor", default=None)


@contextmanager
def registrar_consultas():
    """Junta el SQL, el plan ejecutado y los tiempos de cada filas() dentro del bloque."""
    lista = []
    token = _consultas.set(lista)
    try:
        yield lista
    finally:
        _consultas.reset(token)


def _validar_numero(valor, nombre):
    if isinstance(valor, bool):
        raise ValueError(f"{nombre} no admite booleanos")
    numero = float(valor)
    if not math.isfinite(numero):
        raise ValueError(f"{nombre} requiere valores finitos")
    return numero


def texto_sql(valor):
    if valor is None:
        return "NULL"
    limpio = str(valor).replace("\x00", "").replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
    return "'" + limpio.replace("'", "''") + "'"


def numero_sql(valor):
    if valor is None:
        return "NULL"
    _validar_numero(valor, "numero_sql")
    return str(valor)


def punto_sql(lat, lon):
    if lat is None or lon is None:
        return "NULL"
    lat_f = _validar_numero(lat, "punto_sql")
    lon_f = _validar_numero(lon, "punto_sql")
    if not (-90.0 <= lat_f <= 90.0 and -180.0 <= lon_f <= 180.0):
        raise ValueError("punto_sql requiere latitud en [-90, 90] y longitud en [-180, 180]")
    return f"POINT({lat_f:.6f}, {lon_f:.6f})"


def vector_sql(vector):
    partes = [format(_validar_numero(valor, "vector_sql"), ".6g") for valor in vector]
    if not partes:
        raise ValueError("vector_sql requiere al menos un componente")
    return "VECTOR(" + ", ".join(partes) + ")"


def lista_sql(valores):
    partes = []
    for valor in valores:
        if isinstance(valor, bool):
            raise ValueError("lista_sql no admite booleanos")
        partes.append(str(int(valor)))
    if not partes:
        raise ValueError("lista_sql requiere al menos un valor")
    return "(" + ", ".join(partes) + ")"


def ejecutar(sql):
    respuesta = requests.post(URL_MOTOR + "/api/query", json={"sql": sql}, timeout=1800)
    respuesta.raise_for_status()
    datos = respuesta.json()
    if "error" in datos:
        raise ErrorMotor(datos["error"])
    return datos


_PATRON_VECTOR = re.compile(r"VECTOR\(([^()]*)\)")


def _abreviar_vectores(sql):
    """El visor muestra 'VECTOR(a, b, c, … 4096 valores)' en vez de miles de números."""
    def corto(m):
        valores = m.group(1).split(", ")
        if len(valores) <= 8:
            return m.group(0)
        return f"VECTOR({', '.join(valores[:3])}, … {len(valores)} valores)"
    return _PATRON_VECTOR.sub(corto, sql)


def filas(sql):
    t0 = time.perf_counter()
    datos = ejecutar(sql)
    lista = _consultas.get()
    if lista is not None:
        lista.append({
            "sql": _abreviar_vectores(sql),
            "plan": datos.get("plan", []),
            "ms_motor": datos.get("elapsedMs"),
            "ms_total": round((time.perf_counter() - t0) * 1000, 1),
        })
    return datos.get("rows", [])


def cargar_caracteristicas(tabla, columna_ruta, descriptor_id):
    respuesta = requests.post(
        f"{URL_MOTOR}/api/tables/{tabla}/features",
        json={"path_column": columna_ruta, "descriptor_id": descriptor_id},
        timeout=1800,
    )
    respuesta.raise_for_status()
    datos = respuesta.json()
    if "error" in datos:
        raise ErrorMotor(datos["error"])
    return datos


def modelos_multimedia():
    respuesta = requests.get(f"{URL_MOTOR}/api/multimedia/models", timeout=30)
    respuesta.raise_for_status()
    return respuesta.json().get("models", [])


def tablas():
    respuesta = requests.get(URL_MOTOR + "/api/tables", timeout=60)
    respuesta.raise_for_status()
    return respuesta.json()


def disponible():
    try:
        respuesta = requests.get(URL_MOTOR + "/api/health", timeout=5)
        return respuesta.status_code == 200
    except requests.RequestException:
        return False
