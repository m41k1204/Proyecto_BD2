# Documentación técnica — Sistema de recomendación e-commerce multimodal

Parte 5 · Opción B del proyecto BD2. Este documento explica **cómo funciona** el recomendador por dentro: de dónde salen los datos, cómo se calcula cada señal y qué índices del motor usa, cómo se fusionan y qué resultados dan los benchmarks. Para instalar, levantar y reproducir mediciones, ver [`README.md`](README.md).

---

## 1. Resumen

La tienda recomienda un **Top 10** para cada producto combinando cinco señales, cada una resuelta con una estructura distinta del motor BD2:

| Señal | Pregunta que responde | Estructura del motor | Parte del curso |
|---|---|---|---|
| **Co-compra** | ¿Qué compraron también quienes compraron este producto? | B+ (`ordenes.item_id`) + self-join + `GROUP BY` + top-N heapsort | Parte 1 |
| **Texto** | ¿Qué productos tienen una descripción parecida? | Índice invertido SPIMI con BM25 / TF-IDF | Parte 3 |
| **Visual** | ¿Qué productos se ven parecidos? | SIFT + K-Means BoVW + TF-IDF + HNSW coseno | Parte 4 |
| **Metadata** | ¿Qué productos de la misma categoría y precio están mejor valorados? | B+ (`catalogo.categoria`) + `ORDER BY rating` | Parte 1 |
| **Espacial** | ¿Qué productos hay en tiendas cerca de mí? | R-Tree (`sucursales.ubicacion`): radio, k-NN y polígono | Parte 2 |

Las señales se fusionan con **suma ponderada de puntajes normalizados** (por defecto) o con **Reciprocal Rank Fusion**, con pesos ajustables en vivo desde la interfaz.

Resultado principal (100 usuarios de test elegidos al azar, pesos calibrados solo en validación): el híbrido logra **Hit@10 = 0.61–0.63** con historial de compras, a la par de la co-compra sola y con más coherencia de categoría, y **0.34 en cold-start** (sin co-compras), igual que el texto, la mejor señal sola en ese escenario (sección 7).

---

## 2. Arquitectura

```text
navegador (web/: HTML + JS + Leaflet)
        │  HTTP/JSON
        ▼
servidor.py (FastAPI :8300) ── valida parámetros, guarda la foto subida, registra consultas
        │
        ▼
recomendador.py ── una función por señal + fusión + filtros espaciales
        │                         │
        │ SQL por HTTP            │ vectores de consulta (solo SIFT k=4096 y CLIP)
        ▼                         ▼
motor BD2 (backend/ :8001)    visuales.py (SIFT/TF-IDF del motor, open_clip)
  B+ · SPIMI · HNSW · R-Tree
  datos en data/runtime_ecommerce/
```

- **`cliente_bd.py`**: única puerta hacia el motor (`POST /api/query`). Arma literales SQL seguros (`texto_sql`, `numero_sql`, `punto_sql`, `vector_sql`, `lista_sql`), convierte errores del motor en `ErrorMotor` y, dentro de `registrar_consultas()`, anota el SQL, el plan y los tiempos de cada consulta de la petición en curso (aislado por petición con `ContextVar`).
- **`recomendador.py`**: toda la lógica de negocio. No guarda estado; cada llamada consulta al motor.
- **`visuales.py`**: calcula vectores de imagen para los modelos que el motor no tiene cargados (sección 4.2).
- **`ingesta.py`**: descarga el dataset, crea las tablas e índices y vectoriza las imágenes.
- **`evaluacion/evaluar.py`**: evaluación offline (sección 7).

`backend/` no se modifica: el recomendador solo usa el SQL y la API pública del motor.

### Flujo de una recomendación híbrida

1. `GET /api/productos/{id}/recomendaciones?modo=hibrido&...` → `servidor.py` valida filtros y pesos.
2. `recomendar()` lee la **semilla** (`SELECT ... WHERE id = ?`) y el mapa de sucursales.
3. Si hay filtro espacial (radio o zona), resuelve **qué tiendas** pasan el filtro con el R-Tree (`_resolver_espacial`) y lo convierte en `sucursal_id IN (...)` para todas las señales.
4. Ejecuta cada señal activa (peso > 0) pidiendo **30 candidatos** (`K_CANDIDATOS`).
5. Si hay ubicación, calcula la señal espacial **sobre los candidatos** de las demás señales.
6. Fusiona, ordena, corta en 10 y agrega a cada ítem su tienda, distancia, `posiciones` por señal y `aportes` al puntaje.

En una petición híbrida con ubicación el motor recibe ~9 consultas; el visor *SQL y planes* de la interfaz las muestra todas.

---

## 3. Datos

### 3.1 Dataset

**Amazon Reviews 2023** (McAuley Lab), categoría `Video_Games`:

- **Interacciones**: archivo `5core/rating_only` (usuarios e ítems con ≥ 5 reseñas). Se cuentan reseñas por ASIN y se toman los ~4,500 más populares como candidatos.
- **Metadata**: se lee en streaming hasta reunir candidatos con imagen válida; se descarga la miniatura de cada uno a `data/multimedia/ecommerce/Video_Games/imagenes/`.
- **Catálogo final**: **1,500 productos** con imagen, precio (puede faltar), rating, marca y categoría.

Transformaciones de la ingesta:

| Campo | Cómo se obtiene |
|---|---|
| `categoria` | 2.º y 3.º nivel de `categories` (p. ej. `Nintendo Switch > Games`); las categorías quedan **por plataforma** |
| `descripcion` | `title` + `store` + categoría + `features` + `description`, en un solo texto |
| `sucursal_id` | `crc32(codigo) % 8 + 1`: asignación determinista y pareja entre las 8 tiendas |
| `ordenes` | una orden por par (usuario, ítem) sin duplicados; solo usuarios con **≥ 2 ítems** del catálogo; máximo 25,000 → **24,999 órdenes** |
| `usuario_id` | numerado por cantidad de ítems, de mayor a menor (el usuario 1 es el que más compró) |

Las **8 sucursales** son puntos reales de Lima (Miraflores, San Isidro, Surco, San Borja, Barranco, Jesús María, San Miguel, Callao).

### 3.2 Tablas e índices en el motor

| Tabla | Columnas | Índices |
|---|---|---|
| `sucursales` | `id`, `nombre`, `distrito`, `ubicacion POINT` | B+ (`id`, agrupado) · **R-Tree** (`ubicacion`) |
| `catalogo` | `id`, `codigo`, `nombre`, `marca`, `categoria`, `precio`, `rating`, `sucursal_id`, `imagen`, `descripcion TEXT`, `emb VECTOR(256)` | B+ (`id`, `categoria`, `sucursal_id`) · **FULLTEXT** SPIMI (`descripcion`) · **HNSW** coseno (`emb`) |
| `ordenes` | `id`, `usuario_id`, `item_id`, `fecha DATE` | B+ (`id`, `usuario_id`, `item_id`) |
| `vis_sift4096`, `vis_clip` *(opcionales)* | columnas de `catalogo` con `emb VECTOR(4096)` / `VECTOR(512)` | B+ (`id`) · **HNSW** coseno (`emb`) |

Tras la carga se corre `ANALYZE` en cada tabla para que el planificador tenga estadísticas.

---

## 4. Señales

Todas las señales reciben los mismos filtros (categoría, rango de precio, tiendas permitidas) como cláusulas `WHERE` adicionales, y en recomendaciones excluyen a la semilla (`id != semilla`).

### 4.1 Co-compra (filtrado colaborativo)

*"Quienes compraron X también compraron Y"*. Es la señal más fuerte del sistema.

```sql
SELECT o2.item_id, COUNT(*) FROM ordenes AS o1
JOIN ordenes AS o2 ON o1.usuario_id = o2.usuario_id
WHERE o1.item_id = :semilla AND o2.item_id != :semilla
  [AND o1.usuario_id NOT IN (...)]              -- solo en evaluación: excluye test (y val al calibrar)
GROUP BY o2.item_id ORDER BY conteo DESC LIMIT 30;
```

- **Plan**: `Index Scan` por `idx_ord_item` (B+ sobre `ordenes.item_id`) para hallar a los compradores de la semilla → hash join con `ordenes` (`external-hash`) → `GROUP BY` por hash → **top-N heapsort** (mantiene solo los 30 mejores en memoria, sin ordenar todo).
- Luego se traen los datos de esos candidatos con `SELECT ... FROM catalogo WHERE id IN (...)` aplicando los filtros. Si hay filtros, la primera consulta pide `3k` pares para no quedarse corta tras filtrar.
- **Puntaje**: el conteo de co-compras.
- **Costo**: es la consulta más cara del sistema (~790 ms de las ~1,000 ms de una recomendación híbrida), por el join de `ordenes` consigo misma.
- **Hallazgo del planificador**: `WHERE id IN (...)` sobre `catalogo` se resuelve con **Sequential Scan** (~127 ms) en vez de usar el B+ de `id`. No se corrigió porque implica tocar `backend/`; cambiarlo por una consulta por id costaría lo mismo en idas y vueltas HTTP (~4 ms cada una).
- **Limitación**: no sirve en **cold-start** (producto o usuario sin historial): devuelve vacío y el resto de señales debe cubrir.

### 4.2 Visual (contenido de la imagen)

Busca productos cuya foto se parezca a la de la semilla, o a una foto subida por el usuario (búsqueda por foto). Hay **tres modelos visuales**, que se eligen con el parámetro `visual` o con el selector *Modelo visual* de la interfaz.

#### SIFT + Bag of Visual Words, k = 256 (modelo por defecto)

Es el pipeline que pide el enunciado (sección 2.4.1) y lo ejecuta **el propio motor**:

1. **Extracción** (`SiftExtractor`): la imagen pasa a escala de grises, se reduce a 512 px de lado máximo y se extraen hasta **500 descriptores SIFT** de 128 dimensiones.
2. **Cuantización**: cada descriptor se asigna a la "palabra visual" (centroide) más cercana de un vocabulario de **256 palabras**, entrenado con el **K-Means propio** (`scripts/entrenar_Kmeans.py`) sobre 100,000 descriptores del catálogo, 50 iteraciones y ningún grupo vacío. El vocabulario está en `data/modelos_ecommerce/fotos/`; lo carga el motor propio de la tienda (`:8001`, `BD2_MODELS_DIR=data/modelos_ecommerce`), separado del motor general para no pisar el vocabulario de la parte 4.
3. **Histograma + TF-IDF**: se cuenta cuántas veces aparece cada palabra y se pondera por su IDF en el catálogo → vector de 256 dimensiones guardado en `catalogo.emb`.
4. **Búsqueda**: índice **HNSW** con métrica coseno.

```sql
SELECT ..., SIMILARITY_SCORE() AS puntaje FROM catalogo
WHERE SIMILAR_TO('ecommerce/Video_Games/imagenes/B00ZSDTIGG.jpg', k=30) AND id != :semilla
USING HNSW WITH METRIC=cosine;
```

El motor recibe la **ruta** de la imagen y hace él mismo la extracción y el TF-IDF de la consulta (`Vector Index Scan · HNSW-cosine`, ~130 ms).

#### SIFT + BoVW, k = 4096

Mismo extractor y mismo K-Means propio, pero con un vocabulario de **4,096 palabras** (`data/modelos_ecommerce_k4096/`, convergió en 32 iteraciones sin grupos vacíos) y **TF sublineal** (`log1p` de los conteos). Como el motor solo carga un vocabulario a la vez, el vector lo calcula la app (`visuales.py`, reutilizando los módulos SIFT y TF-IDF del motor sin modificarlos) y el motor lo busca en `vis_sift4096` con `SIMILAR_TO(VECTOR(...), k=30)`.

#### CLIP ViT-B/32 (comparación con una red preentrenada)

Embedding de imagen de 512 dimensiones de CLIP (pesos `openai`, `open_clip` en CPU, sin GPU: ~80 ms por imagen). Es el único modelo preentrenado del sistema y es **opcional**: está para comparar contra SIFT. Se guarda en `vis_clip` y se consulta igual que k=4096.

#### Por qué se agregaron k=4096 y CLIP

Con k=256 la búsqueda por foto fallaba en casos claros:

- **Carátula de *Pokémon Shield***: la de *Pokémon Sword* quedaba en el puesto **273 de 1,500**. Comparando descriptores imagen contra imagen (sin vocabulario), los 5 productos más parecidos sí eran todos de Pokémon. El problema es el vocabulario: con 256 palabras cada una es un patrón genérico (bordes, esquinas) y todas las carátulas se parecen. La similitud coseno de cualquier par queda entre 0.4 y 0.64, sin un ganador claro.
- **Foto de un DualShock 4 negro**: devolvía **audífonos negros**; el DualShock blanco quedaba en el puesto **1,352**. Aquí falla el propio descriptor: el plástico liso da pocos puntos (206 contra los ~500 de una carátula), casi todos en la silueta, y SIFT describe la *dirección* del cambio de brillo. Un borde negro sobre blanco y uno blanco sobre blanco dan descriptores casi opuestos.

| Consulta | Producto buscado | SIFT k=256 | SIFT k=4096 | CLIP |
|---|---|---:|---:|---:|
| *Pokémon Shield* | *Pokémon Scarlet* | 32 | **1** | 176 |
| | *Pokémon Sword* | 273 | 184 | **10** |
| DualShock 4 negro | DualShock 4 blanco | 1,352 | 1,420 | **1** |
| | DualShock 4 gris | 429 | 349 | **2** |

*(Posición del producto en el ranking; consultas de prueba sueltas, no son una evaluación.)*

Conclusión: **SIFT reconoce la misma imagen o el mismo arte** (logos, marcos), y un vocabulario grande lo hace mucho más preciso. **CLIP reconoce la misma clase de objeto** aunque cambie el color o el ángulo. La evaluación con 100 casos está en la sección 7.5.

### 4.3 Texto (SPIMI con BM25 / TF-IDF)

La consulta es el texto de la semilla: `nombre + marca + categoría + descripción`, limpiado a palabras alfanuméricas y recortado a las **primeras 25 palabras** (`MAX_PALABRAS_TEXTO`), para que el costo no crezca con descripciones largas.

```sql
SELECT ..., SCORE() AS puntaje FROM catalogo
WHERE MATCH(descripcion, 'DualShock 4 Wireless Controller PlayStation ...') AND id != :semilla
USING BM25 LIMIT 30;
```

- **Índice**: `ft_catalogo`, índice invertido construido con **SPIMI** (bloques en memoria que se escriben y mezclan en disco), con stopwords y stemming del motor.
- **Ranking**: BM25 por defecto (satura la frecuencia de término y normaliza por largo del documento); TF-IDF coseno como alternativa en la búsqueda por texto.
- **Costo**: ~30 ms (`Text Index Scan · SPIMI-BM25`).
- Una consulta con solo stopwords devuelve una lista vacía (el motor no la rechaza). Si el motor falla (caído, error de SQL), el error **no se oculta**: `texto()` deja pasar `ErrorMotor` y la API responde 502. Antes se devolvía vacío, y la fusión repartía el peso del texto entre las otras señales sin avisar.

### 4.4 Metadata (atributos del producto)

Recomienda los productos mejor valorados de la **misma categoría** y en un **rango de precio parecido**:

1. Primera pasada: misma categoría y precio entre **0.5× y 1.8×** el de la semilla, `ORDER BY rating DESC LIMIT 30`. Puntaje = `rating / 5 + 0.2` (bono por estar en la banda de precio).
2. Si faltan candidatos, completa con la misma categoría sin banda de precio (puntaje `rating / 5`).

- **Plan**: `Index Scan` por `idx_cat_categoria` (B+) + **top-N heapsort** (~31 ms).
- Es la señal con mayor coherencia de categoría (Prec. Cat@10 = 0.98) pero baja precisión de compra: no distingue *qué* producto de la categoría interesa.

### 4.5 Espacial (R-Tree)

La ubicación del usuario (clic en el mapa) se usa de tres formas.

**a) Filtros** (aplican a catálogo, búsquedas y recomendaciones):

| Filtro | Consulta | Plan |
|---|---|---|
| Radio (`radio_m`) | `WHERE distancia(ubicacion, POINT(lat, lon)) < radio` | `RTREE-radius` |
| Zona visible del mapa (`zona=sur,oeste,norte,este`) | `WHERE intersecta(ubicacion, POLYGON(...))` | `RTREE-polygon` |

El resultado es un conjunto de tiendas que se aplica como `sucursal_id IN (...)` en todas las demás consultas. Con radio y zona a la vez se usa la intersección. `distancia` es Haversine, en metros.

**b) Señal de proximidad** en el híbrido: las **3 tiendas más cercanas** (`ORDER BY distancia(...) LIMIT 3`, plan `RTREE-knn`). Cada producto de esas tiendas recibe:

$$\text{puntaje}_{esp} = \frac{1}{1 + d / 5000\,\text{m}}$$

(1 a 0 m, 0.5 a 5 km). En el híbrido **no trae productos nuevos**: solo puntúa los candidatos que ya propusieron las otras señales, para acercar el Top 10 sin meter productos irrelevantes. En el modo *Cercanía*, en cambio, recorre esas 3 tiendas trayendo sus mejores productos por rating, primero de la misma categoría.

**c) Orden "Más cercanos"** del catálogo: `RTREE-knn` ordena las 8 tiendas y se trae cada tienda por `idx_cat_sucursal` con `ORDER BY rating DESC LIMIT n`, parando al llenar la página. Evita un `JOIN + ORDER BY distancia` que ordenaría todo el catálogo (sección 7.6).

---

## 5. Fusión híbrida

Cada señal entrega hasta 30 candidatos con un puntaje en su propia escala (conteos, coseno, BM25, rating…). Hay dos formas de combinarlos.

### 5.1 Suma ponderada de puntajes normalizados (`fusion=score`, por defecto)

$$\text{puntaje}(p) = \sum_{m} w_m \cdot \frac{s_m(p)}{\max_q s_m(q)}$$

- Cada señal se normaliza dividiendo por su máximo, así todas quedan en `[0, 1]`.
- **Co-compra** usa `log1p(conteo)` antes de normalizar, para que un ítem con muchas co-compras no aplaste al resto.
- **Espacial** ya está en `[0, 1]` y no se renormaliza (si se dividiera por el máximo, la tienda más cercana valdría 1 aunque esté lejos).
- Un producto que aparece en varias señales **suma** sus aportes.

### 5.2 Reciprocal Rank Fusion (`fusion=rrf`)

$$\text{puntaje}(p) = \sum_{m} \frac{w_m}{60 + \text{pos}_m(p)}$$

Solo usa la **posición** en cada lista, no el puntaje. Es robusta a escalas distintas, pero pierde información (estar 1.º por mucho o por poco vale lo mismo).

### 5.3 Pesos y desempates

- Pesos por defecto, **calibrados solo con los usuarios de val** (`evaluar.py --calibrar`, sección 7.2): **co-compra 0.80, texto 0.15, visual 0.05, metadata 0**, y **espacial 0.10** cuando hay ubicación. La metadata queda en 0 porque no mejora el NDCG@10 en validación; sigue disponible como modo propio y con su slider.
- Los pesos de las señales activas se **renormalizan para sumar 1**, así el usuario puede mover los sliders sin preocuparse de la suma. Una señal con peso 0 ni siquiera se consulta.
- Empates: mayor rating y luego menor `id` (resultado determinista).
- Cada recomendación devuelve `posiciones` (su puesto en cada señal) y `aportes` (cuánto sumó cada señal). La interfaz muestra los aportes como una **franja apilada por señal** bajo cada recomendación.

---

## 6. Búsquedas y observabilidad

- **Búsqueda por texto**: la misma consulta `MATCH ... USING BM25 | TF_IDF` de la sección 4.3, con el texto que escribe el usuario.
- **Búsqueda por foto**: el servidor recibe la imagen (máx. 10 MB), la normaliza a JPEG de 512 px en `data/multimedia/ecommerce/_consultas/`, ejecuta la señal visual con el modelo elegido y borra el archivo al terminar.
- **Puntaje de la búsqueda por foto**: es `SIMILARITY_SCORE()` con `METRIC=cosine`, que el motor define como `1 − distancia coseno` (1 = la misma imagen). La interfaz lo muestra junto a cada resultado. Con SIFT los valores son bajos aun entre productos parecidos; con CLIP son más altos.
- **Paginación de búsquedas**: `MATCH` y `SIMILAR_TO` devuelven los *k* mejores y no tienen `OFFSET`. Para la página *n* (12 por página), la web pide `k = n·12 + 1` y corta la página; el resultado extra indica si hay página siguiente. `/api/buscar` y `/api/buscar/imagen` aceptan hasta `k = 100` (`MAX_K_BUSQUEDA` en `servidor.py`), unas 8 páginas. La búsqueda activa se conserva al cambiar filtros o página, y los filtros (categoría, precio, radio, zona) se aplican dentro de la misma consulta.
- **Visor SQL y planes**: cada respuesta trae `consultas`, una lista de `{sql, plan, ms_motor, ms_total}` con todo lo que se envió al motor. Los vectores largos se abrevian (`VECTOR(a, b, c, … 4096 valores)`). Sirve para la demo y para ver qué consulta domina el tiempo.

---

## 7. Evaluación

### 7.1 Protocolo

`evaluacion/evaluar.py`, sobre los datos reales (1,500 productos, 24,999 órdenes):

1. Usuarios con ≥ 2 ítems distintos, repartidos **al azar** en **train 60 % / val 20 % / test 20 %** con una semilla fija. La partición es la misma en todas las corridas; la semilla de la evaluación solo elige los casos.
2. Por cada usuario de test (100 por corrida) se elige un ítem al azar como **semilla**; los **objetivos** son sus demás ítems.
3. La co-compra excluye las compras de los usuarios de test (`o1.usuario_id NOT IN (...)`), para no filtrar la respuesta.
4. **Cold-start** repite los mismos casos sin ninguna co-compra (se excluye a todos los usuarios).
5. Los **pesos del híbrido se calibran solo con val** (`--calibrar`), con la co-compra limitada a train. Test nunca participa en la elección de pesos.

| Métrica | Qué mide |
|---|---|
| Hit@10 | fracción de casos con al menos un objetivo en el Top 10 |
| Recall@5 / @10 | fracción de los objetivos del usuario presentes en el Top 5 / Top 10 |
| NDCG@10 | calidad del orden: premia objetivos en posiciones altas |
| MRR | promedio de `1 / posición` del primer objetivo |
| Prec. Cat@10 | fracción del Top 10 con la misma categoría que la semilla |

**Consideraciones al leer los números**:
- Un acierto significa "el usuario también compró ese producto". Eso favorece a la co-compra por diseño y mide solo de forma indirecta la similitud visual o de texto.
- Con 100 casos, diferencias de ±0.02 en Hit@10 están dentro del ruido.
- Las latencias de la evaluación **no** se reportan: el filtro `NOT IN` de usuarios (que la app no usa) encarece el self-join de co-compra. Las latencias reales están en la sección 7.6.

### 7.2 Calibración de pesos (`calibracion.csv`)

`evaluar.py --calibrar --muestras 1000` usa los **301 usuarios de val** (co-compra solo con train). Cada señal se consulta una vez por caso y se prueban las 1,771 combinaciones de pesos con paso 0.05 que suman 1. Se elige la de mayor **NDCG@10 promedio entre el escenario normal y cold-start**: optimizar solo el normal deja en 0 a todas las señales de contenido, porque ahí manda la co-compra.

| Pesos (co-compra / texto / visual / metadata) | NDCG@10 normal | NDCG@10 cold-start | Promedio | Puesto |
|---|---:|---:|---:|---:|
| **0.80 / 0.15 / 0.05 / 0** (elegidos) | **0.1362** | 0.0616 | **0.0989** | 1 |
| 0.75 / 0.15 / 0.05 / 0.05 | 0.1359 | 0.0607 | 0.0983 | 2 |
| 0.55 / 0.25 / 0.10 / 0.10 (cerca de los pesos manuales previos) | 0.1296 | 0.0612 | 0.0954 | 32 |

La superficie es **plana cerca del óptimo**: las 10 mejores combinaciones caen dentro de 0.002 de NDCG promedio. La metadata queda en 0 porque, con la co-compra como métrica de acierto, no aporta NDCG; su efecto se ve en la coherencia de categoría (abajo).

### 7.3 Resultados por señal e híbridos (test, semilla 42, `resumen.csv` y `resumen_cold_start.csv`)

| Escenario | Modo | Hit@10 | Recall@5 | Recall@10 | NDCG@10 | MRR | Prec. Cat@10 |
|---|---|---:|---:|---:|---:|---:|---:|
| **Normal** | co-compra | 0.60 | 0.0531 | 0.0830 | 0.1336 | 0.3235 | 0.304 |
| | visual (SIFT k=256) | 0.20 | 0.0113 | 0.0192 | 0.0281 | 0.0731 | 0.219 |
| | texto | 0.34 | 0.0243 | 0.0368 | 0.0634 | 0.1628 | 0.439 |
| | metadata | 0.15 | 0.0030 | 0.0143 | 0.0174 | 0.0351 | **1.000** |
| | híbrido RRF | **0.63** | 0.0526 | 0.0847 | **0.1366** | **0.3431** | 0.321 |
| | híbrido score | 0.61 | **0.0551** | **0.0855** | 0.1348 | 0.3225 | 0.323 |
| **Cold-start** | co-compra | 0.00 | 0 | 0 | 0 | 0 | 0 |
| | visual (SIFT k=256) | 0.20 | 0.0113 | 0.0192 | 0.0281 | 0.0731 | 0.219 |
| | texto | **0.34** | 0.0243 | **0.0368** | **0.0634** | **0.1628** | 0.439 |
| | metadata | 0.15 | 0.0030 | 0.0143 | 0.0174 | 0.0351 | **1.000** |
| | híbrido RRF | **0.34** | **0.0264** | **0.0368** | 0.0596 | 0.1446 | 0.440 |
| | híbrido score | **0.34** | **0.0264** | **0.0368** | 0.0619 | 0.1564 | 0.432 |

Semilla 123 (escenario normal, `semilla_123/resumen.csv`), mismos usuarios de test con otra semilla de producto:

| Modo | Hit@10 | Recall@5 | Recall@10 | NDCG@10 | MRR | Prec. Cat@10 |
|---|---:|---:|---:|---:|---:|---:|
| co-compra | 0.61 | **0.0549** | 0.0868 | **0.1471** | **0.3382** | 0.307 |
| visual (SIFT k=256) | 0.20 | 0.0087 | 0.0142 | 0.0253 | 0.0808 | 0.255 |
| texto | 0.40 | 0.0229 | 0.0428 | 0.0632 | 0.1762 | 0.419 |
| metadata | 0.24 | 0.0027 | 0.0177 | 0.0258 | 0.0601 | **1.000** |
| híbrido RRF | 0.62 | 0.0487 | **0.0889** | 0.1382 | 0.3010 | 0.327 |
| híbrido score | **0.63** | 0.0501 | 0.0866 | 0.1392 | 0.3294 | 0.344 |

**Pesos calibrados frente a los pesos manuales previos** (0.55 / 0.25 / 0.08 / 0.12), mismos casos de test (semilla 42), híbrido score:

| Pesos | Escenario | Hit@10 | NDCG@10 | MRR | Prec. Cat@10 |
|---|---|---:|---:|---:|---:|
| calibrados | normal | 0.61 | 0.1348 | 0.3225 | 0.323 |
| previos | normal | **0.66** | 0.1346 | 0.3105 | **0.404** |
| calibrados | cold-start | 0.34 | 0.0619 | 0.1564 | 0.432 |
| previos | cold-start | **0.40** | 0.0618 | 0.1578 | **0.598** |

**Lectura**:
1. **Con historial, el híbrido iguala a la co-compra** (Hit@10 0.61–0.63 contra 0.60–0.61; NDCG dentro del ruido) y sube la coherencia de categoría (+2–4 puntos). Con usuarios de test elegidos al azar ya no queda por debajo, como pasaba con el split anterior.
2. **En cold-start, el híbrido calibrado rinde como el texto solo** (Hit@10 0.34 en ambos): con visual 0.05 y metadata 0, al faltar la co-compra prácticamente solo queda el texto.
3. **Los pesos previos dan el mismo NDCG@10** en los dos escenarios, pero más Hit@10 (+0.05 y +0.06) y bastante más coherencia de categoría. La diferencia está en métricas que la calibración no optimiza: **elegir pesos es elegir una métrica**. Con NDCG@10 sobre "compró también", el contenido pesa poco. Si importa la cobertura en cold-start o la coherencia de categoría, conviene más peso a metadata y visual. Los pesos previos se eligieron mirando el split anterior, que comparte usuarios con este test, así que su ventaja no es una medición limpia.
4. **Score y RRF quedan empatados** con estos pesos: RRF gana en una semilla y score en la otra, siempre dentro del ruido.

### 7.4 Peso de la señal espacial (`resumen_espacial.csv`)

Mismos casos en híbrido score, con el usuario ubicado al azar en uno de 8 puntos reales de Lima:

| `w_espacial` | Hit@10 | Recall@10 | NDCG@10 | MRR | Prec. Cat@10 | Distancia media del Top 10 |
|---:|---:|---:|---:|---:|---:|---:|
| 0.00 | 0.61 | 0.0855 | **0.1348** | **0.3225** | 0.323 | 7.86 km |
| **0.10** | **0.62** | **0.0876** | 0.1302 | 0.2974 | **0.328** | 6.77 km |
| 0.25 | **0.62** | 0.0830 | 0.1212 | 0.2789 | 0.318 | 5.63 km |
| 0.50 | 0.58 | 0.0761 | 0.1070 | 0.2474 | 0.295 | 4.68 km |

El peso por defecto **0.10 acerca el Top 10 ~1.1 km** manteniendo Hit@10 y Recall@10, a cambio de bajar algo el orden (NDCG −0.005, MRR −0.025): los productos cercanos suben a los primeros puestos. Desde 0.50 cae todo. La fila `0.00` reproduce exactamente el híbrido score de la sección 7.3 (control).

### 7.5 Modelos visuales (`resumen_visuales.csv`)

| Modo | Hit@10 | Recall@10 | NDCG@10 | MRR | Prec. Cat@10 |
|---|---:|---:|---:|---:|---:|
| visual SIFT k=256 | 0.20 | 0.0192 | 0.0281 | 0.0731 | 0.219 |
| visual SIFT k=4096 | 0.27 | 0.0267 | 0.0397 | 0.1085 | **0.373** |
| visual CLIP | **0.38** | **0.0437** | **0.0671** | **0.1706** | 0.288 |
| híbrido score + SIFT k=256 | 0.61 | 0.0855 | 0.1348 | 0.3225 | 0.323 |
| híbrido score + SIFT k=4096 | **0.62** | **0.0858** | **0.1361** | **0.3285** | **0.324** |
| híbrido score + CLIP | **0.62** | 0.0847 | 0.1323 | 0.3093 | 0.322 |

1. **Como señal sola, ambos modelos nuevos superan a k=256**: Hit@10 sube de 0.20 a 0.27 (k=4096) y a 0.38 (CLIP), y el NDCG@10 de CLIP es más del doble.
2. **k=4096 tiene la mejor coherencia de categoría** (0.373 contra 0.288 de CLIP): las categorías son por plataforma, y SIFT reconoce el marco y el logo de la plataforma en la carátula. CLIP agrupa por concepto aunque cruce plataformas.
3. **En el híbrido las diferencias quedan dentro del ruido**, porque el peso visual es 0.05. El modelo visual importa sobre todo en la búsqueda por foto.
4. Costo (medido en una corrida previa, sin otra carga en la máquina): los tres rondan los 80–130 ms por consulta. La primera consulta con CLIP tarda ~3 s porque carga el modelo.

### 7.6 Latencias del motor

Consultas espaciales medidas con `EXPLAIN ANALYZE` sobre los datos de la tienda:

| Consulta | Plan | Motor |
|---|---|---:|
| Radio < 6 km (5 tiendas) | `Spatial Index Scan · RTREE-radius` | 0.63 ms |
| 3 tiendas más cercanas | `Spatial Index Scan · RTREE-knn` | 0.49 ms |
| Zona "Lima Moderna" (5 tiendas) | `Spatial Index Scan · RTREE-polygon` | 0.26 ms |
| Catálogo por cercanía con `JOIN + ORDER BY distancia`, página 4 | `Seq Scan(1500)` + `Hash Join` + `external k-way merge (47 runs)` | 294.53 ms |
| Catálogo por cercanía por bloques de tienda (`idx_cat_sucursal`), página 4 | `Index Scan` + `external k-way merge (5 runs)` | 16.55 ms |

Desde el cliente (con HTTP, `latencias_espaciales.csv`): radio 3.80 ms, k-NN 3.57 ms y polígono 3.83 ms en promedio. El orden por cercanía por bloques responde la página 1 en ≈ 33 ms, contra 200–300 ms del `JOIN + ORDER BY distancia`.

Reparto típico de una recomendación híbrida con ubicación (visor SQL):

| Consulta | Plan | Tiempo |
|---|---|---:|
| Self-join de co-compra | `BPLUS(item_id)` + `external-hash` + top-N heapsort | ~792 ms |
| Datos de los candidatos de co-compra | `Sequential Scan` (no usa el B+ de `id`) | ~127 ms |
| Visual | `HNSW-cosine` | ~133 ms |
| Texto | `SPIMI-BM25` | ~30 ms |
| Metadata | `BPLUS(categoria)` + top-N heapsort | ~31 ms |
| Radio y k-NN | `RTREE-radius`, `RTREE-knn` | ~1 ms c/u |

La co-compra concentra ~80 % del tiempo; el R-Tree es prácticamente gratis.

---

## 8. Decisiones de diseño y limitaciones

| Decisión | Motivo | Costo o limitación |
|---|---|---|
| Fusión por puntajes normalizados por defecto | Usa la magnitud del puntaje, no solo la posición; con los pesos calibrados empata con RRF (sección 7.3) | Depende de que la normalización por máximo sea representativa |
| `log1p` en co-compra | Evita que un ítem con muchas co-compras anule al resto | — |
| Señal espacial solo sobre candidatos | Acerca el Top 10 sin meter productos irrelevantes por estar cerca | No descubre productos nuevos en el híbrido |
| Filtro espacial resuelto antes, como `sucursal_id IN (...)` | Una sola consulta R-Tree sirve a todas las señales | — |
| 30 candidatos por señal | Equilibrio entre cobertura y costo | Un objetivo fuera del top 30 de toda señal no puede aparecer |
| Texto recortado a 25 palabras | Latencia estable (~30 ms) | Pierde parte de las descripciones largas |
| Vectores de k=4096 y CLIP calculados en la app | El motor solo carga un vocabulario a la vez | La app depende de OpenCV (y de torch para CLIP) |
| No tocar `backend/` | Regla del proyecto | `WHERE id IN (...)` sigue usando Sequential Scan |
| Sin escrituras desde la UI (sin compras en vivo) | Mantener los benchmarks reproducibles | La co-compra no aprende en línea |

Limitaciones generales:

- **Cold-start de producto**: un producto nuevo no tiene co-compras; depende de texto, metadata y visual (Hit@10 0.34 con los pesos calibrados; 0.40 con más peso a metadata y visual, sección 7.3).
- **SIFT y objetos sin textura**: con k=256 o k=4096, SIFT no encuentra el mismo objeto con otro color (sección 4.2). CLIP sí, a costa de un modelo preentrenado externo.
- **Métrica de compra como proxy**: Hit@10 no mide directamente la similitud visual ni textual; la coherencia de categoría y las pruebas manuales lo complementan.
- **Escala**: 1,500 productos y 25,000 órdenes. El self-join de co-compra crece con la popularidad del producto; a mayor escala convendría precalcular los pares de co-compra.

---

## 9. Mapa del código

| Archivo | Contenido |
|---|---|
| `config.py` | Pesos, constantes (`K_CANDIDATOS`, `ESCALA_ESPACIAL_M`…), nombres de tablas e índices, modelos visuales |
| `cliente_bd.py` | Cliente HTTP del motor, literales SQL seguros, registro de consultas |
| `recomendador.py` | Señales (`cocompra`, `visual`, `texto`, `metadata`, `espacial`), filtros espaciales, `fusionar`, `recomendar`, búsquedas y catálogo |
| `visuales.py` | Vectores SIFT k=4096 y CLIP calculados en la app |
| `ingesta.py` | Dataset → tablas → vectores → índices (`--visuales` para los modelos extra) |
| `servidor.py` | API FastAPI y validación de parámetros |
| `web/` | Interfaz: catálogo, búsquedas, mapa Leaflet, Top 10 con barras de aporte, visor SQL |
| `evaluacion/evaluar.py` | Evaluación offline (`--espacial`, `--visuales`) |
| `test_*.py` | Pruebas contra el `Executor` y el `FeaturePipeline` reales del motor |
