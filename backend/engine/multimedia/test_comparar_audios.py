"""Prueba de punta a punta de la comparación por tramos: tabla real cargada con MFCC.

Se corre desde la carpeta backend:
    .venv/Scripts/python -m engine.multimedia.test_comparar_audios
"""
import json
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

from engine.multimedia.audio_features import MfccExtractor
from engine.multimedia.coincidencias import comparar_audios
from engine.multimedia.pipeline import FeaturePipeline
from engine.multimedia.quantization import Vocabulary, save_vocabulary
from engine.parser.executor import Executor
from engine.parser.scanner import Scanner
from engine.parser.sql_parser import Parser

SR = 22050


def tono(frecuencia, segundos=4.0):
    t = np.arange(int(segundos * SR)) / SR
    return (0.4 * (np.sin(2 * np.pi * frecuencia * t) + 0.5 * np.sin(2 * np.pi * 2.7 * frecuencia * t))).astype(np.float32)


def ejecutar(executor, sql):
    resultado = executor.run(Parser(Scanner(sql)).parse_program())[-1]
    assert "error" not in resultado, (sql, resultado)
    return resultado


def debe_fallar(funcion, caso):
    try:
        funcion()
    except ValueError:
        return
    raise AssertionError(f"debía fallar y no falló: {caso}")


def test_comparar_audios():
    extractor = MfccExtractor(max_seconds=30)
    with tempfile.TemporaryDirectory() as raiz:
        raiz = Path(raiz)
        media, modelos, datos = raiz / "media", raiz / "modelos" / "audio_mfcc", raiz / "datos"
        for carpeta in (media, modelos, datos):
            carpeta.mkdir(parents=True)

        # Tres "instrumentos" (tonos de 4 s). Consulta = A y luego C; otra = B y luego C
        a, b, c = tono(220), tono(440), tono(880)
        for nombre, senal in {"a": a, "b": b, "c": c}.items():
            sf.write(media / f"tono_{nombre}.wav", senal, SR)
        sf.write(media / "consulta.wav", np.concatenate([a, c]), SR)
        sf.write(media / "otra.wav", np.concatenate([b, c]), SR)
        sf.write(media / "tercera.wav", np.concatenate([a, b]), SR)

        # Vocabulario de prueba: una palabra por tono (el promedio de sus MFCC)
        centroides = tuple(tuple(float(x) for x in extractor.extract(media / f"tono_{n}.wav").values.mean(axis=0))
                           for n in "abc")
        save_vocabulary(Vocabulary(extractor.descriptor_id, extractor.dimension, centroides), modelos / "vocabulary.json")
        (modelos / "training.json").write_text(json.dumps({"specification": {"extractor": {
            "extractor": "mfcc", "normalization": "none", "sample_rate": SR, "n_mfcc": 13,
            "n_fft": 2048, "hop_length": 512, "include_c0": False, "max_seconds": 30.0}}}), encoding="utf-8")

        # Tabla real con las tres canciones: cada palabra aparece en 2 de 3, todas pesan lo mismo
        pipeline = FeaturePipeline(media, raiz / "modelos")
        catalogo = {}
        executor = Executor(catalogo, data_dir=str(datos), vectorizador=pipeline.vectorizar)
        ejecutar(executor, "CREATE TABLE canciones (id INT PRIMARY KEY, ruta VARCHAR(20), v VECTOR(3));")
        ejecutar(executor, "INSERT INTO canciones (id, ruta) VALUES (1, 'consulta.wav'), (2, 'otra.wav'), (3, 'tercera.wav');")
        pipeline.cargar(catalogo["canciones"], "ruta", extractor.descriptor_id)
        tabla = catalogo["canciones"]

        resultado = comparar_audios(pipeline, tabla, "consulta.wav", ["otra.wav", "consulta.wav"], ventana=2, paso=1)
        otra, propia = resultado["resultados"]
        assert resultado["consulta"]["ventanas"] == len(propia["ventanas"])

        # 1. "otra" se parece a la consulta en su segunda mitad (tono C), con el final de la consulta
        assert otra["mejor"]["inicio"] >= 4 and otra["mejor"]["consulta"] >= 4
        assert otra["mejor"]["similitud"] > 0.9
        # 2. Su primera mitad (tono B, que la consulta no tiene) casi no se parece
        assert otra["ventanas"][0]["similitud"] < 0.1
        # 3. La consulta contra sí misma: cada tramo se parece al máximo
        assert all(v["similitud"] > 0.99 for v in propia["ventanas"])

        # 4. Rutas fuera de la carpeta multimedia y ventanas inválidas se rechazan
        debe_fallar(lambda: comparar_audios(pipeline, tabla, "../fuera.wav", ["otra.wav"]), "ruta fuera")
        debe_fallar(lambda: comparar_audios(pipeline, tabla, "consulta.wav", ["otra.wav"], ventana=0), "ventana 0")

        for t in catalogo.values():
            t.cerrar()


if __name__ == "__main__":
    test_comparar_audios()
    print("OK: comparación por tramos con una tabla real")