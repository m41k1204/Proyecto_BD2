# Recomendador E-commerce Multimodal

Tienda en línea con sistema de recomendación híbrido (**Opción B · Parte 5**) construida **100 % sobre los algoritmos e índices propios del motor BD2**, sin modelos preentrenados externos. Solo consume la API REST del motor: no modifica `backend/` ni `rag/`.

Avance, resultados de evaluación y pendientes: [`PROGRESO.md`](PROGRESO.md).

```text
navegador (Leaflet + UI) ─► servidor.py (:8300) ─► recomendador.py ─► motor BD2 (:8000)
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

## Señales y fusión híbrida (Top 10)

1. **Co-compra**: self-join sobre `ordenes` + `GROUP BY o2.item_id` + `ORDER BY conteo DESC` (*"quienes compraron X también compraron Y"*).
2. **Visual**: `SIMILAR_TO('<ruta_relativa>', k=30) USING HNSW WITH METRIC=cosine` con el pipeline propio del motor (`SiftExtractor` + vocabulario K-Means BoVW + TF-IDF de `POST /api/tables/catalogo/features`).
3. **Texto**: `MATCH(descripcion, '...') USING BM25 LIMIT 30` (SPIMI propio del motor).
4. **Metadata**: misma `categoria` y rango de `precio`, ordenados por `rating DESC`.
5. **Espacial (opcional al fijar ubicación)**: filtro por radio (`RTREE-radius` vía `distancia(...) < radio`) y señal de proximidad (`RTREE-knn` vía `ORDER BY distancia(...) LIMIT 3`) en `sucursales`, integradas en la fusión híbrida (`espacial`, peso por defecto `0.10`) y destacadas en el mapa Leaflet para las tiendas del Top 10.
   - **Zona visible del mapa** (`RTREE-polygon`): el botón *Filtrar zona visible* envía `zona=sur,oeste,norte,este`; el servidor valida el rectángulo y el motor consulta `WHERE intersecta(ubicacion, POLYGON(...))`. Se combina con el radio (intersección) y filtra catálogo, búsquedas y recomendaciones.
   - **Orden `Más cercanos (R-Tree)`** (`orden=cercania`, requiere ubicación): `RTREE-knn` ordena las tiendas y cada bloque sale por `idx_cat_sucursal` con `ORDER BY rating DESC LIMIT n`, sin `JOIN` ni sort externo de todo el catálogo.
   - Los ítems del Top 10 en los popups del mapa son clicables, y el distrito de cada tarjeta (📍) centra y abre su tienda en el mapa.
6. **Visor SQL y planes**: cada respuesta del catálogo, búsquedas y recomendaciones trae `consultas` (SQL real enviado al motor, plan ejecutado y tiempos), que la UI muestra en un panel desplegable *SQL y planes del motor BD2* bajo la grilla y bajo el Top 10.
7. **Fusión**: configurable en vivo desde la UI entre **scores normalizados** ($\sum_m w_m \cdot \text{score\_norm}_m$, por defecto con pesos calibrados `cocompra: 0.55`, `texto: 0.25`, `metadata: 0.12`, `visual: 0.08`) y **Reciprocal Rank Fusion** ($\sum_m \frac{w_m}{60 + \text{pos}_m}$).

## Interfaz web

- **Catálogo** paginado con filtros de categoría y precio, y orden por rating, precio, id o **Más cercanos (R-Tree)** (habilitado al fijar ubicación).
- **Búsqueda por texto** (`BM25` o `TF-IDF` sobre SPIMI) y **búsqueda por foto** (SIFT + BoVW + HNSW). La búsqueda por foto se repite sola al cambiar filtros, radio o zona.
- **Mapa de tiendas (Leaflet)**: clic en el mapa fija tu ubicación; selector de radio (3/6/12 km o sin límite); *Usar Miraflores*; *Filtrar zona visible (R-Tree)* / *Quitar zona*. Colores: verde = tiendas con productos del Top 10, naranja = tienda del producto seleccionado, verde azulado = 3 más cercanas (k-NN), gris = otras. El popup de cada tienda lista sus ítems `#1..#10`, clicables.
- **Detalle y Top 10**: estrategias Híbrido, Co-compra, Visual, Texto, Metadata y Cercanos; sliders de peso por señal y selector de fusión (scores normalizados o RRF). Cada recomendación muestra etiquetas con su posición en cada señal, el botón `📍 Distrito · distancia` (centra el mapa en su tienda) y, en Híbrido, una **barra de aporte por señal** con el puntaje total.
- **Visor SQL y planes**: paneles desplegables *SQL y planes del motor BD2* bajo la grilla y bajo el Top 10, con cada consulta enviada al motor, su plan ejecutado y sus tiempos.
- Tiempos por señal (`*_ms`) y resumen espacial (`ubicación · radio · N en radio · M en k-NN`) en la parte superior.

## API (`servidor.py`)

| Endpoint | Parámetros principales | Devuelve |
|---|---|---|
| `GET /api/estado` | — | motor disponible, extractor, conteos de tablas |
| `GET /api/categorias`, `GET /api/sucursales` | — | listas para filtros y mapa |
| `GET /api/productos` | `categoria`, `precio_min`, `precio_max`, `orden` (`rating`, `precio_asc`, `precio_desc`, `id`, `cercania`), `limite`, `pagina` | `productos`, `hay_mas`, `sucursales_en_radio`, `consultas` |
| `GET /api/productos/{id}` | `lat`, `lon` | detalle del producto con su tienda y distancia |
| `GET /api/productos/{id}/recomendaciones` | `modo` (`hibrido`, `cocompra`, `visual`, `texto`, `metadata`, `espacial`), `fusion` (`score`, `rrf`), `k`, `w_cocompra`, `w_visual`, `w_texto`, `w_metadata`, `w_espacial` | `semilla`, `recomendaciones` (con `posiciones`, `aportes`, `puntaje`, `distancia_m`), `tiempos`, `sucursales_en_radio`, `sucursales_knn`, `consultas` |
| `GET /api/buscar` | `q`, `modo` (`bm25`, `tf_idf`), `k` | `productos`, `tiempos`, `sucursales_en_radio`, `consultas` |
| `POST /api/buscar/imagen` | `archivo` (≤ 10 MB), `k` (form) | `productos`, `tiempos`, `sucursales_en_radio`, `consultas` |

Filtros espaciales comunes (catálogo, búsquedas y recomendaciones):

- `lat`, `lon` (juntos) y `radio_m` (> 0, requiere `lat`/`lon`) → `RTREE-radius`.
- `zona=sur,oeste,norte,este` en grados → `RTREE-polygon`; debe cumplir `sur < norte` en `[-90, 90]` y `oeste < este` en `[-180, 180]` con valores finitos (si no, **400**). Con radio y zona a la vez se usan las tiendas que cumplen ambos.
- `orden=cercania` y `modo=espacial` requieren `lat`/`lon` (si no, **400**).
- `sucursales_en_radio` lista las tiendas que pasan **todo** el filtro espacial (radio y/o zona).
- `consultas`: lista de `{sql, plan, ms_motor, ms_total}` con cada consulta enviada al motor durante la petición.

## Entorno

Usa el entorno `bd2` de micromamba (o `pnpm setup:ecommerce` para crear `ecommerce/.venv`). Todas las dependencias de `ecommerce/requirements.txt` (`fastapi`, `uvicorn`, `python-multipart`, `pillow`, `requests`, `numpy`) ya están en `bd2`.

## Ingesta (Amazon Reviews 2023)

Con el backend del motor levantado en `:8000`:

```bash
micromamba run -n bd2 uvicorn api.main:app --app-dir backend --port 8000
```

Ejecuta la ingesta (descarga interacciones `5core/rating_only`, lee metadata en streaming, descarga miniaturas a `data/multimedia/ecommerce/`, vectoriza con `POST /api/tables/catalogo/features` y construye los índices):

```bash
micromamba run -n bd2 python ecommerce/ingesta.py --limite 1500
```

*(Opcional)* Para entrenar un vocabulario visual K-Means BoVW específico para el catálogo e-commerce en una carpeta aparte (sin sobrescribir `data/modelos/fotos/`):

```bash
micromamba run -n bd2 python ecommerce/ingesta.py --limite 1500 --sin-cargar
micromamba run -n bd2 python scripts/entrenar_Kmeans.py --dataset data/multimedia/ecommerce/Video_Games/imagenes --salida data/modelos_ecommerce/fotos --tipo imagenes --max-lado 512 --normalizacion none --k 256 --semilla 42 --iteraciones 50
BD2_MODELS_DIR=data/modelos_ecommerce micromamba run -n bd2 uvicorn api.main:app --app-dir backend --port 8000
```

## Uso

Desde la raíz del repo, en dos terminales:

```bash
# 1) motor BD2 (:8000) con el vocabulario visual de ecommerce
BD2_MODELS_DIR=data/modelos_ecommerce micromamba run -n bd2 uvicorn api.main:app --app-dir backend --port 8000

# 2) tienda (:8300)
micromamba run -n bd2 uvicorn servidor:app --app-dir ecommerce --port 8300
```

Abre <http://localhost:8300> (tras cambios en `web/`, recarga con `Ctrl+Shift+R`). También figura en `mprocs.yaml` (`pnpm dev:ecommerce`).

> Con `pnpm dev` la tienda queda en `:8300`, pero el motor (`dev:backend`) arranca **sin** `BD2_MODELS_DIR` y usa el vocabulario de Caltech-101: para la búsqueda por foto levanta el motor con el comando 1) de arriba.

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

Evaluación offline (hold-out 80/20 de usuarios + escenario *cold-start* sin co-compras previas, mide Hit@10, Recall@5/10, NDCG@10, MRR, afinidad de categoría y latencias hacia `benchmarks/ecommerce_results/`):

```bash
micromamba run -n bd2 python ecommerce/evaluacion/evaluar.py --muestras 100
```

Benchmark espacial (solo esta parte): Hit@10 / NDCG@10 frente a la distancia media del Top 10 variando `w_espacial` (`0`, `0.10`, `0.25`, `0.50`) desde 8 puntos reales de Lima, más latencias de `RTREE-radius`, `RTREE-knn` y `RTREE-polygon` (`resumen_espacial.csv`, `detalle_espacial.csv`, `latencias_espaciales.csv`):

```bash
micromamba run -n bd2 python ecommerce/evaluacion/evaluar.py --espacial --muestras 100
```

Ambas evaluaciones necesitan el motor levantado con los datos reales (`data/runtime/`). Con 100 muestras, cada una tarda unos 7 min. Resultados y conclusiones en [`PROGRESO.md`](PROGRESO.md).

## Cómo hacer el benchmarking

### 1. Preparar

1. Datos reales cargados en `data/runtime/` (1,500 productos, 24,999 órdenes, 8 tiendas): si no están, correr la ingesta (sección *Ingesta*).
2. Levantar **solo el motor**, con el vocabulario de ecommerce (la tienda `:8300` no hace falta: `evaluar.py` llama al recomendador directamente):

   ```bash
   BD2_MODELS_DIR=data/modelos_ecommerce micromamba run -n bd2 uvicorn api.main:app --app-dir backend --port 8000
   ```

3. Condiciones para que los números sean comparables:
   - no escribir en `ordenes` ni en `catalogo` entre corridas (cambia la co-compra y los índices);
   - misma máquina, sin otras cargas pesadas, y `--muestras 100` como mínimo;
   - las latencias de la primera consulta incluyen caché fría; las medias de 100 casos lo diluyen, pero para latencias sueltas conviene repetir y descartar la primera.

### 2. Calidad de recomendación (normal + cold-start)

Protocolo de `evaluar.py`:

- Usuarios con ≥ 2 ítems distintos, ordenados por `usuario_id`: el 80 % primero es *train* y el resto *test*.
- Por cada usuario de test (barajados con `--semilla`) se elige un ítem al azar como **semilla**; los **objetivos** son sus demás ítems.
- La co-compra solo cuenta compras de usuarios de *train* (`max_usuario_id = corte_train`), así no se filtra la respuesta.
- **Cold-start** repite los mismos casos con `max_usuario_id = 0` (sin historial de co-compra).
- Se evalúan `cocompra`, `visual`, `texto`, `metadata`, `hibrido_rrf` e `hibrido_score`, todos con `k = 10`.

Cada semilla en su carpeta (si no, la segunda sobrescribe los CSV de la primera):

```bash
micromamba run -n bd2 python ecommerce/evaluacion/evaluar.py --muestras 100 --semilla 42  --salida benchmarks/ecommerce_results/semilla_42
micromamba run -n bd2 python ecommerce/evaluacion/evaluar.py --muestras 100 --semilla 123 --salida benchmarks/ecommerce_results/semilla_123
```

Archivos: `resumen.csv` / `resumen_cold_start.csv` (una fila por modo) y `detalle.csv` / `detalle_cold_start.csv` (una fila por caso). `--sin-cold-start` omite el segundo escenario y `--k` cambia el corte.

> Los CSV que hay hoy en `benchmarks/ecommerce_results/` (sin subcarpeta) son de la **semilla 42**; los de la semilla 123 se sobrescribieron y solo quedan en la tabla de `PROGRESO.md`.

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
q() { curl -s localhost:8000/api/query -H 'Content-Type: application/json' -d "{\"sql\": \"$1\"}" | jq -r '.rows[]["QUERY PLAN"]'; }

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
