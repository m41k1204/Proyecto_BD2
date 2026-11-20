"""Pruebas de la similitud por ventanas de tiempo entre dos audios.

Se corren desde la carpeta backend:
    .venv/Scripts/python -m engine.multimedia.test_coincidencias
"""
import numpy as np

from engine.multimedia.coincidencias import coincidencias, vectores_por_ventana
from engine.multimedia.histograma import ModeloTfIdf
from engine.multimedia.local_features import DescriptorBatch

# Vocabulario de juguete: 3 palabras en 2 dimensiones
CENTROIDES = np.array([[0, 0], [10, 0], [0, 10]], dtype=np.float32)
# Las 3 palabras aparecen en 1 de 3 canciones: todas pesan lo mismo (IDF = ln 3)
MODELO = ModeloTfIdf(3, [1, 1, 1])
# Un cuadro por segundo: sr = 1 muestra por segundo y cada cuadro avanza 1 muestra
SR, HOP = 1, 1


def cancion(palabras):
    """Cada descriptor es exactamente el centroide de su palabra."""
    return DescriptorBatch("juguete", 2, CENTROIDES[palabras], positions=np.arange(len(palabras), dtype=np.float32))


def ventanas(palabras, **opciones):
    return vectores_por_ventana(cancion(palabras), CENTROIDES, MODELO, SR, HOP, **opciones)


def debe_fallar(funcion, caso):
    try:
        funcion()
    except ValueError:
        return
    raise AssertionError(f"debía fallar y no falló: {caso}")


def test_ventanas():
    # 20 s: palabra 1 en los primeros 10 y palabra 2 en los últimos 10. Ventanas de 5 s sin solaparse
    inicios, vectores = ventanas([1] * 10 + [2] * 10, ventana=5, paso=5)
    assert inicios.tolist() == [0, 5, 10, 15]
    assert vectores.shape == (3, 4)                       # una columna por ventana, como espera librosa
    assert vectores[:, 0].argmax() == 1 and vectores[:, 3].argmax() == 2
    # Ventanas que se solapan: avanzan 2 s, así que caben (20 - 5) // 2 + 1 = 8
    inicios, _ = ventanas([1] * 10 + [2] * 10, ventana=5, paso=2)
    assert inicios.tolist() == [0, 2, 4, 6, 8, 10, 12, 14]
    # Una canción más corta que la ventana tiene una sola ventana
    inicios, _ = ventanas([0, 1, 2])
    assert inicios.tolist() == [0]
    # Sin descriptores (silencio): ninguna ventana
    vacio = DescriptorBatch("juguete", 2, np.empty((0, 2)), positions=np.empty((0, 1)))
    inicios, vectores = vectores_por_ventana(vacio, CENTROIDES, MODELO, SR, HOP)
    assert len(inicios) == 0 and vectores.shape == (3, 0)
    debe_fallar(lambda: ventanas([1] * 10, ventana=0), "ventana 0")
    debe_fallar(lambda: ventanas([1] * 10, paso=-1), "paso negativo")


def test_coincidencias():
    # Consulta: palabra 1 y luego 2. Otra canción: palabra 0 y luego la misma palabra 2
    consulta = ventanas([1] * 10 + [2] * 10, ventana=5, paso=5)
    otra = ventanas([0] * 10 + [2] * 10, ventana=5, paso=5)
    resultado = coincidencias(*consulta, *otra, ventana=5)

    assert [v["inicio"] for v in resultado["ventanas"]] == [0, 5, 10, 15]
    # La palabra 0 no aparece en la consulta: similitud 0
    assert [v["similitud"] for v in resultado["ventanas"]] == [0, 0, 1, 1]
    # Los tramos con palabra 2 se parecen al final de la consulta (desde el segundo 10)
    assert resultado["ventanas"][2]["consulta"] >= 10
    assert resultado["mejor"] == {"inicio": 10, "fin": 15, "consulta": 10, "similitud": 1}
    # Sin ventanas no hay mejor coincidencia
    assert coincidencias(*consulta, np.empty(0), np.empty((3, 0)))["mejor"] is None

def test_otra_mas_larga():
    # La otra canción tiene más ventanas (8) que la consulta (4): igual se comparan todas las parejas.
    # Sus primeros 30 s solo tienen la palabra 0, que la consulta no usa: similitud 0, no 1
    consulta = ventanas([1] * 10 + [2] * 10, ventana=5, paso=5)
    otra = ventanas([0] * 30 + [2] * 10, ventana=5, paso=5)
    resultado = coincidencias(*consulta, *otra, ventana=5)
    assert [v["similitud"] for v in resultado["ventanas"]] == [0, 0, 0, 0, 0, 0, 1, 1]

def test_silencio():
    # Una ventana cuyas palabras no tienen peso (vector en ceros) no rompe el cálculo: cuenta como 0
    sin_peso = ModeloTfIdf(3, [3, 3, 3])                  # palabras en todas las canciones: IDF = 0
    consulta = vectores_por_ventana(cancion([1] * 10), CENTROIDES, sin_peso, SR, HOP)
    otra = vectores_por_ventana(cancion([1] * 10), CENTROIDES, sin_peso, SR, HOP)
    resultado = coincidencias(*consulta, *otra)
    assert all(v["similitud"] == 0 for v in resultado["ventanas"])


def test_otra_mas_larga():
    # La otra canción tiene más ventanas (8) que la consulta (4): igual se comparan todas las parejas.
    # Sus primeros 30 s solo tienen la palabra 0, que la consulta no usa: similitud 0, no 1
    consulta = ventanas([1] * 10 + [2] * 10, ventana=5, paso=5)
    otra = ventanas([0] * 30 + [2] * 10, ventana=5, paso=5)
    resultado = coincidencias(*consulta, *otra, ventana=5)
    assert [v["similitud"] for v in resultado["ventanas"]] == [0, 0, 0, 0, 0, 0, 1, 1]

if __name__ == "__main__":
    test_ventanas()
    print("OK: ventanas de tiempo")
    test_coincidencias()
    print("OK: coincidencias entre tramos")
    test_otra_mas_larga()
    print("OK: canción más larga que la consulta")
    test_silencio()
    print("OK: ventanas en silencio")