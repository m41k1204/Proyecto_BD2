import librosa
import numpy as np

from .histograma import asignar_palabras


def vectores_por_ventana(lote, centroides, modelo, sr, hop_length, ventana=5.0, paso=2.5):
    if ventana <= 0 or paso <= 0:
        raise ValueError(f"ventana y paso deben ser positivos, llegaron {ventana} y {paso}")
    k = len(centroides)
    if len(lote) == 0:
        return np.empty(0), np.empty((k, 0), dtype=np.float32)
    palabras = asignar_palabras(lote.values, centroides)          # una palabra por cuadro MFCC
    largo = max(1, int(librosa.time_to_frames(ventana, sr=sr, hop_length=hop_length)))
    avance = max(1, int(librosa.time_to_frames(paso, sr=sr, hop_length=hop_length)))
    largo = min(largo, len(palabras))                             # canción más corta que la ventana
    marcos = librosa.util.frame(palabras, frame_length=largo, hop_length=avance)  # (largo, ventanas)
    vectores = np.stack([modelo.transformar(np.bincount(columna, minlength=k)) for columna in marcos.T], axis=1)
    inicios = librosa.frames_to_time(np.arange(marcos.shape[1]) * avance, sr=sr, hop_length=hop_length)
    return inicios, vectores


def coincidencias(inicios_consulta, consulta, inicios, vectores, ventana=5.0):
    if len(inicios) == 0 or len(inicios_consulta) == 0:
        return {"ventanas": [], "mejor": None}
    # filas: ventanas de la canción; columnas: ventanas de la consulta
    distancia = librosa.segment.cross_similarity(consulta, vectores, metric="cosine", mode="distance", full=True)
    similitud = np.nan_to_num(1.0 - distancia, nan=0.0)          # silencio: coseno indefinido, cuenta como 0
    pareja = similitud.argmax(axis=1)
    valores = similitud[np.arange(len(inicios)), pareja]
    mejor = int(valores.argmax())
    return {
        "ventanas": [
            {"inicio": round(float(t), 2), "similitud": round(float(s), 3), "consulta": round(float(inicios_consulta[q]), 2)}
            for t, s, q in zip(inicios, valores, pareja)
        ],
        "mejor": {
            "inicio": round(float(inicios[mejor]), 2),
            "fin": round(float(inicios[mejor] + ventana), 2),
            "consulta": round(float(inicios_consulta[pareja[mejor]]), 2),
            "similitud": round(float(valores[mejor]), 3),
        },
    }