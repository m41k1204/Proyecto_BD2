import os
from pathlib import Path

RAIZ_ECOM = Path(__file__).resolve().parent
RAIZ_PROYECTO = RAIZ_ECOM.parent

URL_MOTOR = os.environ.get("BD2_URL", "http://localhost:8000")
CARPETA_DATOS = Path(os.environ.get("ECOM_DATOS", RAIZ_PROYECTO / "data" / "ecommerce"))
CARPETA_MULTIMEDIA = Path(
    os.environ.get("BD2_MULTIMEDIA_DIR", RAIZ_PROYECTO / "data" / "multimedia")
)
SUBCARPETA_MULTIMEDIA = "ecommerce"

URL_DATASET = "https://huggingface.co/datasets/McAuley-Lab/Amazon-Reviews-2023/resolve/main"
URL_DATASET_UCSD = "https://mcauleylab.ucsd.edu/public_datasets/data/amazon_2023"
CATEGORIA_DATASET = os.environ.get("ECOM_CATEGORIA", "Video_Games")
LIMITE_PRODUCTOS = int(os.environ.get("ECOM_LIMITE", "1500"))
MAX_ORDENES = int(os.environ.get("ECOM_MAX_ORDENES", "25000"))

LARGOS_CATALOGO = {"codigo": 20, "nombre": 200, "marca": 80, "categoria": 80, "imagen": 255}
LARGOS_SUCURSALES = {"nombre": 100, "distrito": 60}

DESCRIPTOR_VISUAL = os.environ.get("ECOM_DESCRIPTOR", "sift:gray:max512:nf500")
DIMENSION = int(os.environ.get("ECOM_DIMENSION", "256"))
METODO_VECTORIAL = os.environ.get("ECOM_METODO_VECTORIAL", "HNSW")

K_CANDIDATOS = 30
K_RECOMENDACIONES = 10
RRF_K = 60
LOTE_INSERT = 40

PESOS_DEFECTO = {
    "cocompra": 0.55,
    "texto": 0.25,
    "metadata": 0.12,
    "visual": 0.08,
}
K_SUCURSALES_KNN = 3
ESCALA_ESPACIAL_M = 5000.0
PESO_ESPACIAL_DEFECTO = 0.10
FUSIONES = ("score", "rrf")
FUSION_DEFECTO = os.environ.get("ECOM_FUSION", "score")

TABLA_SUCURSALES = "sucursales"
TABLA_CATALOGO = "catalogo"
TABLA_ORDENES = "ordenes"

INDICE_CAT_CATEGORIA = "idx_cat_categoria"
INDICE_CAT_SUCURSAL = "idx_cat_sucursal"
INDICE_TEXTO = "ft_catalogo"
INDICE_VECTORES = "hnsw_catalogo"
INDICE_ORD_USUARIO = "idx_ord_usuario"
INDICE_ORD_ITEM = "idx_ord_item"

PUERTO = int(os.environ.get("ECOM_PUERTO", "8300"))
