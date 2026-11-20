import librosa
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

from .histograma import asignar_palabras
from .audio_features import MfccExtractor
from .extract_features import resolver_archivo


def vectores_por_ventana(lote, centroides, modelo, sr, hop_length, ventana=5.0, paso=2.5):
    if ventana <= 0 or paso <= 0:
        raise ValueError(f"ventana y paso deben ser positivos, llegaron {ventana} y {paso}")
    k = len(centroides)
    if len(lote) == 0:
        return np.empty(0), np.empty((k, 0), dtype=np.float32)
    palabras = asignar_palabras(lote.values, centroides)
    largo = max(1, int(librosa.time_to_frames(ventana, sr=sr, hop_length=hop_length)))
    avance = max(1, int(librosa.time_to_frames(paso, sr=sr, hop_length=hop_length)))
    largo = min(largo, len(palabras))
    marcos = librosa.util.frame(palabras, frame_length=largo, hop_length=avance)
    vectores = np.stack([modelo.transformar(np.bincount(columna, minlength=k)) for columna in marcos.T], axis=1)
    inicios = librosa.frames_to_time(np.arange(marcos.shape[1]) * avance, sr=sr, hop_length=hop_length)
    return inicios, vectores


def coincidencias(inicios_consulta, consulta, inicios, vectores, ventana=5.0):
    if len(inicios) == 0 or len(inicios_consulta) == 0:
        return {"ventanas": [], "mejor": None}
    
    similitud = cosine_similarity(vectores.T, consulta.T) 
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

def comparar_audios(colecciones, tabla, consulta, rutas, ventana=5.0, paso=2.5):

    modelo = colecciones._modelo(tabla)
    extraccion = next((e for e in colecciones.extracciones.values()
                       if e.vocabulario_id == modelo.vocabulario_id), None)
    if extraccion is None:
        raise ValueError(f"el vocabulario con el que se cargó '{tabla.name}' ya no está registrado")
    base = extraccion.extractor
    if not isinstance(base, MfccExtractor):
        raise ValueError(f"'{tabla.name}' no es una tabla de audio MFCC: comparar tramos necesita el tiempo de cada descriptor")
    completo = MfccExtractor(sr=base.sr, n_mfcc=base.n_mfcc, n_fft=base.n_fft,
                             hop_length=base.hop_length, include_c0=base.include_c0, max_seconds=None)

    calculadas = {}

    def ventanas_de(ruta):
        if ruta not in calculadas:
            lote = completo.extract(resolver_archivo(colecciones.carpeta, ruta))
            calculadas[ruta] = vectores_por_ventana(lote, extraccion.centroides, modelo,
                                                    completo.sr, completo.hop_length, ventana, paso)
        return calculadas[ruta]

    de_la_consulta = ventanas_de(consulta)
    return {
        "ventana": ventana,
        "paso": paso,
        "consulta": {"ruta": consulta, "ventanas": len(de_la_consulta[0])},
        "resultados": [{"ruta": ruta, **coincidencias(*de_la_consulta, *ventanas_de(ruta), ventana)} for ruta in rutas],
    }