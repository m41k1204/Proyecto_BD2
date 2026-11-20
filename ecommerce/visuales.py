"""Vectores visuales que calcula la app para los modelos que el motor no tiene cargados.

- sift256: lo vectoriza el motor (SIMILAR_TO por ruta); aquí no se toca.
- sift4096: reutiliza SIFT, la cuantización y el TF-IDF del motor con un vocabulario más grande.
- clip: embedding de imagen de CLIP en CPU (open_clip, pesos preentrenados).

El motor solo guarda los vectores, indexa con HNSW y busca: SIMILAR_TO(VECTOR(...)).
"""
import importlib.util
import sys
import threading

import numpy as np

from config import CARPETA_MODELO_SIFT4096, CARPETA_MULTIMEDIA, MODELO_CLIP, RAIZ_PROYECTO

if str(RAIZ_PROYECTO / "backend") not in sys.path:
    sys.path.insert(0, str(RAIZ_PROYECTO / "backend"))

RUTA_VOCABULARIO_SIFT4096 = CARPETA_MODELO_SIFT4096 / "vocabulary.json"
RUTA_TFIDF_SIFT4096 = CARPETA_MODELO_SIFT4096 / "tfidf_catalogo.json"
DIMENSION_CLIP = 512

_candado = threading.Lock()
_cache = {}


def _cargado(nombre, fabrica):
    # Carga perezosa y una sola vez aunque lleguen peticiones simultáneas.
    with _candado:
        if nombre not in _cache:
            _cache[nombre] = fabrica()
        return _cache[nombre]


def _sift4096():
    def fabrica():
        from engine.multimedia.local_features import SiftExtractor
        from engine.multimedia.quantization import load_vocabulary

        extractor = SiftExtractor()
        vocabulario = load_vocabulary(RUTA_VOCABULARIO_SIFT4096)
        if vocabulario.descriptor_id != extractor.descriptor_id:
            raise ValueError(
                f"el vocabulario k=4096 es de '{vocabulario.descriptor_id}' y el extractor es '{extractor.descriptor_id}'"
            )
        return extractor, np.asarray(vocabulario.centroids, dtype=np.float32)

    return _cargado("sift4096", fabrica)


def _tfidf_sift4096():
    from engine.multimedia.histograma import ModeloTfIdf

    return _cargado("tfidf4096", lambda: ModeloTfIdf.abrir(str(RUTA_TFIDF_SIFT4096)))


def _clip():
    def fabrica():
        import open_clip
        import torch

        modelo, _, preprocesar = open_clip.create_model_and_transforms(MODELO_CLIP[0], pretrained=MODELO_CLIP[1])
        modelo.eval()
        return torch, modelo, preprocesar

    return _cargado("clip", fabrica)


def histograma_sift4096(ruta):
    from engine.multimedia.histograma import construir_histograma

    extractor, centroides = _sift4096()
    return construir_histograma(extractor.extract(ruta).values, centroides)


def ajustar_tfidf_sift4096(histogramas, sublineal=True):
    """Ajusta el IDF sobre el catálogo (lo hace la ingesta) y lo deja listo para las consultas."""
    from engine.multimedia.histograma import ModeloTfIdf

    modelo = ModeloTfIdf.ajustar(histogramas, sublineal=sublineal)
    modelo.guardar(str(RUTA_TFIDF_SIFT4096))
    with _candado:
        _cache["tfidf4096"] = modelo
    return modelo


def vectores_clip(rutas, lote=64):
    from PIL import Image

    torch, modelo, preprocesar = _clip()
    salida = []
    for inicio in range(0, len(rutas), lote):
        imagenes = []
        for ruta in rutas[inicio:inicio + lote]:
            with Image.open(ruta) as imagen:
                imagenes.append(preprocesar(imagen.convert("RGB")))
        with torch.no_grad():
            v = modelo.encode_image(torch.stack(imagenes))
        salida.append(torch.nn.functional.normalize(v, dim=-1).numpy().astype(np.float32))
    return np.concatenate(salida) if salida else np.zeros((0, DIMENSION_CLIP), dtype=np.float32)


def vector(modelo_visual, ruta_relativa):
    """Vector de consulta para una imagen bajo la carpeta multimedia (la misma que ve el motor)."""
    ruta = CARPETA_MULTIMEDIA / ruta_relativa
    if not ruta.is_file():
        raise ValueError(f"imagen no encontrada: {ruta_relativa}")
    if modelo_visual == "sift4096":
        return _tfidf_sift4096().transformar(histograma_sift4096(ruta))
    if modelo_visual == "clip":
        return vectores_clip([ruta])[0]
    raise ValueError(f"el modelo visual '{modelo_visual}' no se vectoriza en la app")


def modelos_instalados():
    """Modelos cuyos archivos o dependencias están en esta máquina (sift256 depende solo del motor)."""
    salida = ["sift256"]
    if RUTA_VOCABULARIO_SIFT4096.is_file() and RUTA_TFIDF_SIFT4096.is_file() and importlib.util.find_spec("cv2"):
        salida.append("sift4096")
    if importlib.util.find_spec("open_clip") and importlib.util.find_spec("torch"):
        salida.append("clip")
    return salida
