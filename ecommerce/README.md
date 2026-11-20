# Recomendador E-commerce Multimodal

Tienda en línea con sistema de recomendación híbrido (**Opción B · Parte 5**) construida sobre los **algoritmos e índices propios del motor BD2**. No modifica `backend/` ni `rag/`: consume la API REST del motor y, para los modelos visuales extra (*SIFT k=4096* y *CLIP*), calcula los vectores en la app (con los módulos SIFT/TF-IDF del motor y `open_clip`) y deja al motor guardarlos, indexarlos con HNSW y buscarlos. CLIP es el único modelo preentrenado y es opcional: está como comparación frente a SIFT.

Funcionamiento interno de cada señal, la fusión y los resultados de evaluación: [`DOCUMENTACION_TECNICA.md`](DOCUMENTACION_TECNICA.md).

```text
navegador (Leaflet + UI) ─► servidor.py (:8300) ─► recomendador.py ─► motor BD2 de la tienda (:8001)
                                                                            │
                                              SIFT + K-Means BoVW + TF-IDF ─┤ (Parte 4)
                                              SPIMI (BM25 / TF-IDF)        ─┤ (Parte 3)
                                              R-Tree (POINT + Haversine)   ─┤ (Parte 2)
                                              B+ · Self-Join · Group By    ─┘ (Parte 1)
```

## Qué guarda el motor BD2

| Tabla | Columnas clave | Índices | Modalidad |
|---|---|---|---|
| `sucursales` | `id`, `nombre`, `distrito`, `ubicacion POINT` | `BPLUS` (`id`) + **R-Tree** (`ubicacion`) | Espacial |
| `catalogo` | `id`, `codigo`, `nombre`, `marca`, `categoria`, `precio`, `rating`, `sucursal_id`, `imagen`, `descripcion TEXT`, `emb VECTOR(256)` | `BPLUS` (`id`, `categoria`, `sucursal_id`), **`FULLTEXT`** (`descripcion`), **`HNSW`** coseno (`emb`) | Relacional + Texto + Multimedia |
| `ordenes` | `id`, `usuario_id`, `item_id`, `fecha DATE` | `BPLUS` (`id`, `usuario_id`, `item_id`) | Relacional (colaborativo) |
| `vis_sift4096`, `vis_clip` *(opcionales)* | mismas columnas que `catalogo`, con `emb VECTOR(4096)` / `VECTOR(512)` calculado en la app | `BPLUS` (`id`), **`HNSW`** coseno (`emb`) | Multimedia (modelos visuales extra) |

## Señales y fusión híbrida (Top 10)

1. **Co-compra**: self-join sobre `ordenes` + `GROUP BY o2.item_id` + `ORDER BY conteo DESC` (*"quienes compraron X también compraron Y"*).
2. **Visual**: `SIMILAR_TO('<ruta_relativa>', k=30) USING HNSW WITH METRIC=cosine` con el pipeline propio del motor (`SiftExtractor` + vocabulario K-Means BoVW + TF-IDF de `POST /api/tables/catalogo/features`).
   - **Modelo visual elegible** (`visual=sift256|sift4096|clip`, selector en la UI): `sift256` es lo anterior. `sift4096` usa el mismo SIFT con un vocabulario K-Means de 4096 palabras (`data/modelos_ecommerce_k4096/`) y TF-IDF sublineal; `clip` usa el embedding de imagen de CLIP ViT-B/32 en CPU. Ambos consultan su tabla con `SIMILAR_TO(VECTOR(...), k=30)`. SIFT encuentra bien *la misma imagen o el mismo arte*; CLIP encuentra *productos parecidos* (misma clase con otro color o ángulo).
3. **Texto**: `MATCH(descripcion, '...') USING BM25 LIMIT 30` (SPIMI propio del motor).
4. **Metadata**: misma `categoria` y rango de `precio`, ordenados por `rating DESC`.
5. **Espacial (opcional al fijar ubicación)**: filtro por radio (`RTREE-radius` vía `distancia(...) < radio`) y señal de proximidad (`RTREE-knn` vía `ORDER BY distancia(...) LIMIT 3`) en `sucursales`, integradas en la fusión híbrida (`espacial`, peso por defecto `0.10`) y destacadas en el mapa Leaflet para las tiendas del Top 10.
   - **Zona visible del mapa** (`RTREE-polygon`): el botón *Filtrar zona visible* envía `zona=sur,oeste,norte,este`; el servidor valida el rectángulo y el motor consulta `WHERE intersecta(ubicacion, POLYGON(...))`. Se combina con el radio (intersección) y filtra catálogo, búsquedas y recomendaciones.
   - **Orden `Más cercanos (R-Tree)`** (`orden=cercania`, requiere ubicación): `RTREE-knn` ordena las tiendas y cada bloque sale por `idx_cat_sucursal` con `ORDER BY rating DESC LIMIT n`, sin `JOIN` ni sort externo de todo el catálogo.
   - Los ítems del Top 10 en los popups del mapa son clicables, y el distrito de cada tarjeta (📍) centra y abre su tienda en el mapa.
6. **Visor SQL y planes**: cada respuesta del catálogo, búsquedas y recomendaciones trae `consultas` (SQL real enviado al motor, plan ejecutado y tiempos), que la UI muestra en un panel desplegable *SQL y planes del motor BD2* bajo la grilla y bajo el Top 10.
7. **Fusión**: configurable en vivo desde la UI entre **scores normalizados** ($\sum_m w_m \cdot \text{score\_norm}_m$, por defecto con pesos calibrados en validación `cocompra: 0.80`, `texto: 0.15`, `visual: 0.05`, `metadata: 0.0`) y **Reciprocal Rank Fusion** ($\sum_m \frac{w_m}{60 + \text{pos}_m}$).

## Interfaz web

Vitrina tipo marketplace (banda de marca, buscador grande, tarjetas sin caja) con el detalle y las recomendaciones en un panel lateral. Tipografía Rubik y d3 se sirven desde `web/vendor/`, así que la interfaz funciona sin internet salvo las teselas del mapa. No usa emojis: los íconos (lupa, cámara, ubicación, estrellas, flechas) se dibujan como SVG con d3 en `web/iconos.js`.

- **Catálogo** paginado con filtros de categoría y precio, y orden por rating, precio, orden de carga o **Más cercanos (R-Tree)** (habilitado al fijar ubicación). Los filtros se aplican al cambiarlos.
- **Búsqueda por texto** (`BM25` o `TF-IDF` sobre SPIMI, selector dentro del buscador) y **búsqueda por foto** (botón de cámara; SIFT + BoVW + HNSW, o CLIP). La búsqueda activa se conserva al cambiar filtros, página, radio, zona o modelo visual, y se pagina igual que el catálogo: la web pide al motor los primeros `página × 12 + 1` resultados (tope `MAX_K_BUSQUEDA = 100` en `servidor.py`) y corta la página. Mientras hay búsqueda, el orden es por relevancia y el selector de orden se desactiva. *Comparar fotos con* (en preferencias) elige `SIFT k=256`, `SIFT k=4096` o `CLIP` para la búsqueda por foto y para la señal de imagen del Top 10; las opciones sin tabla cargada aparecen deshabilitadas. En la búsqueda por foto, tu imagen queda fija sobre los resultados y cada producto muestra su similitud coseno.
- **Mapa de tiendas (Leaflet)**: se abre desde *Tiendas cerca de* en la banda. Clic en el mapa fija tu ubicación; selector de radio (3/6/12 km o sin límite); *Usar Miraflores*; *Filtrar por la zona visible* / *Quitar zona*. Colores: rojo = tu ubicación, verde = tiendas con recomendados, ámbar = tienda del producto elegido, turquesa = 3 más cercanas (k-NN), gris = otras. El popup de cada tienda lista sus recomendados `1..10`, clicables.
- **Preferencias** (engranaje de la banda, o el nombre de la estrategia junto al título del Top 10): panel flotante sobre la página, así que se ajusta sin cerrar el producto. Tiene la estrategia (Híbrido, Co-compra, Imagen, Texto, Metadata o Cercanía), la mezcla del híbrido (sliders de peso por señal y fusión por puntajes normalizados o RRF) y el modelo para comparar fotos. Se cierra con su X, con Esc o con un clic afuera.
- **Detalle y Top 10**: título según la estrategia (por ejemplo, *Quienes compraron esto también compraron*). La X del panel o Esc cierran el producto (si las preferencias están abiertas, Esc primero cierra esas). Cada recomendación muestra precio, rating, cuántas veces se compró junto al producto, su tienda (centra el mapa en ella) y, en Híbrido, una **franja de color por señal** con el puntaje total.
- **SQL, planes y tiempos del motor**: paneles plegables bajo la grilla y bajo el Top 10, con cada consulta enviada al motor, su plan ejecutado y los tiempos por señal (`*_ms`).

## API (`servidor.py`)

| Endpoint | Parámetros principales | Devuelve |
|---|---|---|
| `GET /api/estado` | — | motor disponible, extractor, conteos de tablas, `modelos_visuales` disponibles |
| `GET /api/categorias`, `GET /api/sucursales` | — | listas para filtros y mapa |
| `GET /api/productos` | `categoria`, `precio_min`, `precio_max`, `orden` (`rating`, `precio_asc`, `precio_desc`, `id`, `cercania`), `limite`, `pagina` | `productos`, `hay_mas`, `sucursales_en_radio`, `consultas` |
| `GET /api/productos/{id}` | `lat`, `lon` | detalle del producto con su tienda y distancia |
| `GET /api/productos/{id}/recomendaciones` | `modo` (`hibrido`, `cocompra`, `visual`, `texto`, `metadata`, `espacial`), `fusion` (`score`, `rrf`), `visual` (`sift256`, `sift4096`, `clip`), `k`, `w_cocompra`, `w_visual`, `w_texto`, `w_metadata`, `w_espacial` | `semilla`, `recomendaciones` (con `posiciones`, `aportes`, `puntaje`, `distancia_m`), `tiempos`, `sucursales_en_radio`, `sucursales_knn`, `consultas` |
| `GET /api/buscar` | `q`, `modo` (`bm25`, `tf_idf`), `k` | `productos`, `tiempos`, `sucursales_en_radio`, `consultas` |
| `POST /api/buscar/imagen` | `archivo` (≤ 10 MB), `k`, `visual` (form) | `productos`, `tiempos`, `sucursales_en_radio`, `consultas` |

Filtros espaciales comunes (catálogo, búsquedas y recomendaciones):

- `lat`, `lon` (juntos) y `radio_m` (> 0, requiere `lat`/`lon`) → `RTREE-radius`.
- `zona=sur,oeste,norte,este` en grados → `RTREE-polygon`; debe cumplir `sur < norte` en `[-90, 90]` y `oeste < este` en `[-180, 180]` con valores finitos (si no, **400**). Con radio y zona a la vez se usan las tiendas que cumplen ambos.
- `orden=cercania` y `modo=espacial` requieren `lat`/`lon` (si no, **400**).
- `sucursales_en_radio` lista las tiendas que pasan **todo** el filtro espacial (radio y/o zona).
- `consultas`: lista de `{sql, plan, ms_motor, ms_total}` con cada consulta enviada al motor durante la petición.

## Motor propio de la tienda (`:8001`)

La tienda usa **su propio motor BD2**, en el puerto `8001` y con sus datos en `data/runtime_ecommerce/`. El motor carga un solo vocabulario de fotos desde `BD2_MODELS_DIR`. El del catálogo (`data/modelos_ecommerce/`) no puede convivir con el de la parte 4 (`data/modelos/`, que además trae los de audio) en el motor general (`:8000`). Con un motor por vocabulario, cada uno conserva el suyo y la búsqueda por foto con SIFT k=256 la sigue haciendo el motor.

`config.py` apunta a `http://localhost:8001` por defecto (`BD2_URL` lo cambia). Así, la ingesta, la evaluación y la tienda usan ese motor sin más configuración.

Los vocabularios `data/modelos_ecommerce/fotos/vocabulary.json` (k=256) y `data/modelos_ecommerce_k4096/fotos/` (k=4096, con `tfidf_catalogo.json`) se versionan en git, como `data/modelos/`. No hace falta volver a entrenarlos.

## Entorno

`pnpm setup` (motor) y `pnpm setup:ecommerce` (crea `ecommerce/.venv` con `uv`). También sirve el entorno `bd2` de micromamba, que ya trae todo `ecommerce/requirements.txt` (`fastapi`, `uvicorn`, `python-multipart`, `pillow`, `requests`, `numpy`, `opencv-python-headless`). CLIP es opcional y va aparte en `ecommerce/requirements-clip.txt` (`torch` CPU + `open_clip_torch`); sus pesos (~350 MB) se descargan de Hugging Face la primera vez. Sin CLIP, el selector de modelos lo muestra deshabilitado.

## Ingesta (Amazon Reviews 2023)

Con el motor de la tienda levantado (`pnpm dev:backend-ecommerce`):

```bash
cd ecommerce
.venv/bin/python ingesta.py                       # ~2 min si las imágenes ya están descargadas
.venv/bin/python ingesta.py --visuales sift4096   # opcional: tabla del modelo k=4096 (~2 min)
.venv/bin/python ingesta.py --visuales clip       # opcional, requiere requirements-clip.txt (~2.5 min en CPU)
```

La ingesta descarga las interacciones `5core/rating_only`, lee la metadata en streaming, descarga las miniaturas a `data/multimedia/ecommerce/`, deja que el motor extraiga SIFT con `POST /api/tables/catalogo/features` y construye los índices. Es determinista: con los mismos archivos produce los mismos 1,500 productos y 24,999 órdenes.

*(Opcional)* Para volver a entrenar los vocabularios con el K-Means propio (k=4096 tarda ~35 min en CPU):

```bash
micromamba run -n bd2 python ecommerce/ingesta.py --limite 1500 --sin-cargar
micromamba run -n bd2 python scripts/entrenar_Kmeans.py --dataset data/multimedia/ecommerce/Video_Games/imagenes --salida data/modelos_ecommerce/fotos --tipo imagenes --max-lado 512 --normalizacion none --k 256 --semilla 42 --iteraciones 50
micromamba run -n bd2 python scripts/entrenar_Kmeans.py --dataset data/multimedia/ecommerce/Video_Games/imagenes --salida data/modelos_ecommerce_k4096/fotos --tipo imagenes --max-lado 512 --normalizacion none --k 4096 --semilla 42 --iteraciones 50
```

## Uso

```bash
pnpm dev:backend-ecommerce   # motor de la tienda (:8001)
pnpm dev:ecommerce           # tienda (:8300)
```

Abre <http://localhost:8300> (tras cambios en `web/`, recarga con `Ctrl+Shift+R`). `pnpm dev` levanta los dos junto con el resto del proyecto (`mprocs.yaml`).

Con micromamba, desde la raíz del repo:

```bash
BD2_DATA_DIR=data/runtime_ecommerce BD2_MODELS_DIR=data/modelos_ecommerce micromamba run -n bd2 uvicorn api.main:app --app-dir backend --port 8001
micromamba run -n bd2 uvicorn servidor:app --app-dir ecommerce --port 8300
```

## Docker

La tienda es un servicio opcional del `docker-compose.yml` (profile `ecommerce`), con su propio motor (`backend-ecommerce`). `docker compose up` sigue levantando solo el motor general y el frontend.

```bash
docker compose --profile ecommerce up -d --build
docker compose --profile ecommerce run --rm ecommerce python ingesta.py
docker compose --profile ecommerce run --rm ecommerce python ingesta.py --visuales sift4096
```

Abre <http://localhost:8300>.

- El motor de la tienda guarda sus tablas en el volumen `runtime_ecommerce`, así que la ingesta se corre una vez dentro de Docker.
- `data/ecommerce` y `data/multimedia` se montan en el contenedor: si el dataset y las imágenes ya están, la ingesta los reutiliza.
- La imagen no incluye CLIP (evita instalar `torch`); el selector lo muestra deshabilitado.

## Pruebas y evaluación

Todas las pruebas se ejecutan contra el `Executor` y el `FeaturePipeline` (`SIFT + K-Means + TF-IDF`) reales del motor BD2 sin conexión (no necesitan los servidores levantados). Cubren el contrato SQL con el motor (incluidos los planes `RTREE-radius`, `RTREE-knn` y `RTREE-polygon`), ingesta, señales y fusión, filtros por radio y zona, orden por cercanía, la API con sus validaciones y el registro de consultas del visor:

```bash
micromamba run -n bd2 python ecommerce/test_cliente_bd.py
micromamba run -n bd2 python ecommerce/test_contrato_motor.py
micromamba run -n bd2 python ecommerce/test_ingesta.py
micromamba run -n bd2 python ecommerce/test_recomendador.py
micromamba run -n bd2 python ecommerce/test_servidor.py
node --check ecommerce/web/app.js
```

Evaluación offline (partición aleatoria de usuarios train/val/test 60/20/20 + escenario *cold-start* sin co-compras previas, mide Hit@10, Recall@5/10, NDCG@10, MRR, afinidad de categoría y latencias hacia `benchmarks/ecommerce_results/`):

```bash
micromamba run -n bd2 python ecommerce/evaluacion/evaluar.py --muestras 100
```

Benchmark espacial (solo esta parte): Hit@10 / NDCG@10 frente a la distancia media del Top 10 variando `w_espacial` (`0`, `0.10`, `0.25`, `0.50`) desde 8 puntos reales de Lima, más latencias de `RTREE-radius`, `RTREE-knn` y `RTREE-polygon` (`resumen_espacial.csv`, `detalle_espacial.csv`, `latencias_espaciales.csv`):

```bash
micromamba run -n bd2 python ecommerce/evaluacion/evaluar.py --espacial --muestras 100
```

Comparación de modelos visuales (solo esta parte): `visual_*` (señal visual sola) e `hibrido_score_*` (híbrido con pesos por defecto) para `sift256`, `sift4096` y `clip` (`resumen_visuales.csv`, `detalle_visuales.csv`; requiere `ingesta.py --visuales sift4096,clip`):

```bash
micromamba run -n bd2 python ecommerce/evaluacion/evaluar.py --visuales --muestras 100
```

Ambas evaluaciones necesitan el motor de la tienda levantado con los datos reales (`data/runtime_ecommerce/`). Con 100 muestras, cada una tarda unos 7 min. Resultados y conclusiones en [`DOCUMENTACION_TECNICA.md`](DOCUMENTACION_TECNICA.md) § 7.

## Cómo hacer el benchmarking

### 1. Preparar

1. Datos reales cargados en `data/runtime_ecommerce/` (1,500 productos, 24,999 órdenes, 8 tiendas): si no están, correr la ingesta (sección *Ingesta*).
2. Levantar **solo el motor de la tienda** (la tienda `:8300` no hace falta: `evaluar.py` llama al recomendador directamente):

   ```bash
   pnpm dev:backend-ecommerce
   ```

3. Condiciones para que los números sean comparables:
   - no escribir en `ordenes` ni en `catalogo` entre corridas (cambia la co-compra y los índices);
   - misma máquina, sin otras cargas pesadas, y `--muestras 100` como mínimo;
   - las latencias de la primera consulta incluyen caché fría; las medias de 100 casos lo diluyen, pero para latencias sueltas conviene repetir y descartar la primera.

### 2. Calidad de recomendación (normal + cold-start)

Protocolo de `evaluar.py`:

- Usuarios con ≥ 2 ítems distintos, repartidos **al azar** en *train* 60 % / *val* 20 % / *test* 20 % con una semilla fija (`SEMILLA_PARTICION`). No se corta por rango de `usuario_id`, porque la ingesta numera a los usuarios de más a menos compras.
- `--semilla` solo elige los casos; la partición es la misma en todas las corridas, así ninguna semilla evalúa sobre usuarios de *val*.
- Por cada usuario de test se elige un ítem al azar como **semilla**; los **objetivos** son sus demás ítems.
- La co-compra excluye las compras de los usuarios de *test* (`o1.usuario_id NOT IN (...)`), así no se filtra la respuesta.
- **Cold-start** repite los mismos casos excluyendo a todos los usuarios (sin historial de co-compra).
- Se evalúan `cocompra`, `visual`, `texto`, `metadata`, `hibrido_rrf` e `hibrido_score`, todos con `k = 10`.

Los pesos de `PESOS_DEFECTO` (`config.py`) se calibran **solo con los usuarios de *val***, y la co-compra cuenta solo *train*. Cada señal se consulta una vez por caso y la grilla (paso 0.05, 1,771 combinaciones que suman 1) solo repite la fusión `score`. Se elige la de mayor NDCG@10 promedio entre el escenario normal y cold-start (optimizar solo el normal deja en 0 las señales de contenido); resultado en `calibracion.csv`:

```bash
micromamba run -n bd2 python ecommerce/evaluacion/evaluar.py --calibrar --muestras 1000   # todos los usuarios de val (301)
```

Cada semilla en su carpeta (si no, la segunda sobrescribe los CSV de la primera):

```bash
micromamba run -n bd2 python ecommerce/evaluacion/evaluar.py --muestras 100 --semilla 42  --salida benchmarks/ecommerce_results/semilla_42
micromamba run -n bd2 python ecommerce/evaluacion/evaluar.py --muestras 100 --semilla 123 --salida benchmarks/ecommerce_results/semilla_123
```

Archivos: `resumen.csv` / `resumen_cold_start.csv` (una fila por modo) y `detalle.csv` / `detalle_cold_start.csv` (una fila por caso). `--sin-cold-start` omite el segundo escenario y `--k` cambia el corte.

> Los CSV de `benchmarks/ecommerce_results/` (sin subcarpeta) son de la **semilla 42**; los de la semilla 123 están en `semilla_123/`.

| Métrica | Qué mide |
|---|---|
| `hit@10` | fracción de casos con al menos un objetivo en el Top 10 |
| `recall@5`, `recall@10` | fracción de los objetivos del usuario que aparecen en el Top 5 / Top 10 |
| `ndcg@10` | calidad del orden: premia objetivos en posiciones altas (1 = orden ideal) |
| `mrr` | promedio de `1 / posición` del primer objetivo (0 si no aparece) |
| `precision_cat@10` | fracción del Top 10 con la misma categoría que la semilla |
| `ms_promedio`, `ms_p95` | latencia de `recomendar()` por caso (cliente → motor, incluye HTTP) |

### 3. Benchmark espacial

```bash
micromamba run -n bd2 python ecommerce/evaluacion/evaluar.py --espacial --muestras 100 --semilla 42 --salida benchmarks/ecommerce_results/semilla_42
```

- Mismos casos que el punto 2 (misma semilla) en modo `hibrido_score`, con la ubicación del usuario elegida al azar (también con `--semilla`) entre 8 puntos reales de Lima (`UBICACIONES_LIMA`).
- Se repite para `w_espacial` = `0.0`, `0.10`, `0.25`, `0.50` (`PESOS_ESPACIAL_EVAL`); `0.0` debe reproducir `hibrido_score` del punto 2, y sirve de control.
- Además de las métricas anteriores, `dist_media_km` = distancia media del usuario a las tiendas del Top 10.
- Latencias del R-Tree: 8 puntos × 5 repeticiones de `RTREE-radius` (6 km), `RTREE-knn` (k = 3) y `RTREE-polygon` (rectángulo "Lima Moderna" `ZONA_LIMA_MODERNA`), medidas desde el cliente.
- Archivos: `resumen_espacial.csv`, `detalle_espacial.csv` (con `lugar` y `dist_km` por caso) y `latencias_espaciales.csv`.

### 4. Latencia de una consulta en el motor (`EXPLAIN ANALYZE`)

Para aislar el tiempo del motor (sin HTTP) y ver el plan, buffers y filas por nodo, enviar la consulta con `EXPLAIN ANALYZE` a `/api/query`. Ejemplos con los SQL que usa la app:

```bash
q() { curl -s localhost:8001/api/query -H 'Content-Type: application/json' -d "{\"sql\": \"$1\"}" | jq -r '.rows[]["QUERY PLAN"]'; }

q "EXPLAIN ANALYZE SELECT id FROM sucursales WHERE distancia(ubicacion, POINT(-12.119, -77.029)) < 6000;"
q "EXPLAIN ANALYZE SELECT id FROM sucursales ORDER BY distancia(ubicacion, POINT(-12.119, -77.029)) LIMIT 3;"
q "EXPLAIN ANALYZE SELECT id FROM sucursales WHERE intersecta(ubicacion, POLYGON(POINT(-12.13, -77.06), POINT(-12.08, -77.06), POINT(-12.08, -76.99), POINT(-12.13, -76.99)));"
q "EXPLAIN ANALYZE SELECT id, nombre FROM catalogo WHERE sucursal_id = 1 ORDER BY rating DESC LIMIT 49;"
```

Repetir cada consulta varias veces y anotar la mediana de `Execution Time`; la primera ejecución suele ser más lenta (caché fría).

### 5. Latencia por consulta de una petición real (visor)

Con la tienda también levantada (`:8300`), el campo `consultas` de cada respuesta trae el SQL, el plan y los tiempos de todas las consultas que hizo esa petición (`ms_motor` = tiempo dentro del motor, `ms_total` = ida y vuelta HTTP):

```bash
curl -s "localhost:8300/api/productos/10/recomendaciones?lat=-12.119&lon=-77.029&radio_m=6000" \
  | jq -r '.consultas[] | "\(.ms_motor) ms | \([.plan[] | .op + (if .method then ":" + .method else "" end)] | join(" > "))"'
```

Es lo mismo que muestra el panel *SQL y planes del motor BD2* de la interfaz. Sirve para ver qué consulta domina el tiempo (hoy, el self-join de co-compra).
