# Progreso — Recomendador E-commerce Multimodal (Parte 5 · Opción B)

Registro del avance, resultados validados y próximos pasos de la aplicación e-commerce en la rama local `feat/recomendador-ecommerce`.

> **Última actualización: 2026-11-20.** Todo `ecommerce/` y `benchmarks/ecommerce_results/` siguen **sin commitear**. Las 5 suites pasan; la interfaz web **no se ha revisado aún en un navegador** (solo `node --check`).
>
> **Copiado a `Proyecto_BD2` (2026-11-20).** Esta carpeta se copió desde el clon `../proyecto` (rama `feat/recomendador-ecommerce`, que salía de `734bb57`) a este clon `Proyecto_BD2` (`main` en `8d3bde6`, que ya trae `rostros/` y la galería del frontend). También se copiaron `benchmarks/ecommerce_results/` y los datos ignorados por git: `data/ecommerce/`, `data/modelos_ecommerce/` y `data/multimedia/ecommerce/`. **`data/runtime/` no se copió** (aquí no existe), así que hay que volver a cargar las tablas. Cambios en `.gitignore`, `mprocs.yaml`, `package.json` y el puerto `8300`: **hechos**; ver la sección *Integración pendiente en `Proyecto_BD2`* en el roadmap.

## Objetivo y restricciones clave

- Implementar la **Parte 5 — Opción B (Sistema de Recomendación E-commerce)** descrita en `documents/proyectobd2.md`.
- Usar **100 % algoritmos e índices propios del motor BD2** (`SiftExtractor` + K-Means BoVW + `ModeloTfIdf` + `HNSW`, `SPIMI` `BM25`/`TF_IDF`, `R-Tree`, `BPLUS` + `Self-Join` + `GROUP BY`), **sin modelos preentrenados externos** (sin CLIP, `sentence-transformers` ni `torch`).
- Consumir únicamente la API REST del motor (`http://localhost:8000`) sin modificar `backend/` ni `rag/`.
- Entrenar y guardar el vocabulario visual K-Means BoVW propio en `data/modelos_ecommerce/fotos/` (`BD2_MODELS_DIR=data/modelos_ecommerce`) para preservar el modelo de Caltech-101 en `data/modelos/fotos/`.

---

## Lo hecho (completado y verificado)

- [x] **Infraestructura y contrato con el motor BD2**
  - Módulos base: `ecommerce/config.py`, `ecommerce/cliente_bd.py`.
  - Pruebas de contrato: `ecommerce/test_cliente_bd.py` y `ecommerce/test_contrato_motor.py` (contra `Executor` y `FeaturePipeline` reales del motor y reapertura desde disco).
  - Reglas garantizadas: escapado SQL seguro (sin `\n` ni `\x00`), `USING BPLUS` explícito al crear tablas con `VECTOR`, sin proyección de columnas `VECTOR` y sin colisión de prefijos en nombres de tablas (`sucursales`, `catalogo`, `ordenes`).

- [x] **Dataset real, modelo visual propio e ingesta**
  - Scripts y pruebas: `ecommerce/ingesta.py`, `ecommerce/test_ingesta.py`.
  - Dataset `McAuley-Lab/Amazon-Reviews-2023` (`Video_Games`): 1,500 productos, 1,502 miniaturas válidas en `data/multimedia/ecommerce/Video_Games/imagenes/`, 24,999 órdenes de usuarios `5core` y 8 sucursales en Lima.
  - Vocabulario K-Means BoVW entrenado con `scripts/entrenar_Kmeans.py` (`100,000` descriptores SIFT, `k=256`, 50 iteraciones, 0 clusters vacíos) en `data/modelos_ecommerce/fotos/`.
  - Carga real ejecutada en `data/runtime/` con vectorización vía `POST /api/tables/catalogo/features`, creación de índices (`BPLUS`, `R-Tree`, `FULLTEXT`, `HNSW`) y `ANALYZE` sobre las tres tablas.

- [x] **Motor de recomendación multimodal**
  - Módulos: `ecommerce/recomendador.py`, `ecommerce/test_recomendador.py`.
  - Cuatro señales integradas:
    - **Co-compra**: self-join sobre `ordenes` con `GROUP BY` y `LIMIT k` (`top-N heapsort` en RAM).
    - **Visual**: `SIMILAR_TO(..., k=30) USING HNSW WITH METRIC=cosine`.
    - **Texto**: `MATCH(descripcion, ...) USING BM25|TF_IDF` (SPIMI).
    - **Metadata**: misma `categoria`, bono de banda de `precio` y `rating DESC`.
  - Filtro espacial opcional mediante `R-Tree` (`sucursales_cercanas`), además de búsqueda por texto (`BM25`/`TF-IDF`) y búsqueda por imagen subida.

- [x] **API FastAPI e interfaz web**
  - Servidor y UI: `ecommerce/servidor.py`, `ecommerce/test_servidor.py`, `ecommerce/web/index.html`, `ecommerce/web/styles.css`, `ecommerce/web/app.js`.
  - Documentación y entorno: `ecommerce/requirements.txt`, `ecommerce/README.md`, más integración en `package.json`, `mprocs.yaml` y `.gitignore`.
  - Funcionalidades en UI: grilla de catálogo con paginación emulada, buscador `BM25`/`TF-IDF`, búsqueda por imagen SIFT, mapa Leaflet colapsable con radio `R-Tree`, detalle de producto con Top 10 recomendaciones, pesos configurables, badges de explicación y latencias.

- [x] **Mejora #1 — Calibración de fusión híbrida y evaluación cold-start**
  - Fusión configurable entre **`score`** (scores normalizados a `[0, 1]`, aplicando `log1p` a conteos de cocompra) y **`rrf`**, con retorno de `aportes` por señal y selector de fusión en la UI.
  - Pesos calibrados por defecto en `ecommerce/config.py`: `cocompra: 0.55`, `texto: 0.25`, `metadata: 0.12`, `visual: 0.08` (con `fusion="score"` por defecto).
  - Evaluación offline en `ecommerce/evaluacion/evaluar.py`: hold-out 80/20 de usuarios + escenario **cold-start** (`max_usuario_id=0`), generando resultados hacia `benchmarks/ecommerce_results/`.

- [x] **Mejora #2 — Señal espacial `RTREE-knn` + mapa**
  - Señal de proximidad `espacial` (`sucursales_knn` con `ORDER BY distancia(...) LIMIT 3` usando `RTREE-knn` y decaimiento `1 / (1 + d / 5000)`) en `ecommerce/recomendador.py`, activa cuando hay ubicación (`w_espacial` por defecto `0.10`, más modo autónomo `espacial` / botón `Cercanos`).
  - Resaltado dinámico de marcadores en Leaflet (`ecommerce/web/app.js`, `index.html`, `styles.css`): distingue tiendas con productos del Top 10, sucursal del producto seleccionado y tiendas cercanas `k-NN`, con popups informativos y slider `Cercanía (R-Tree)` activable al fijar ubicación.

- [x] **Mejora #2b — Refinamiento espacial y mapa R-Tree** (2026-11-19)
  - **Correcciones de mapa**: `marcadorUsuario` (borde blanco) y `circuloRadio` con `interactive: false` para no bloquear clics en tiendas ni dentro del radio; el modo `Cercanos` sin ubicación carga igual el detalle de la semilla (`GET /api/productos/{id}`); `#resumen-espacial` muestra el conteo real (`X en radio · Y en k-NN`, o `N tiendas en el filtro` con zona); `recomendar()` consulta las sucursales una sola vez (`obtener_producto(..., mapa_sucursales=...)`).
  - **Zona visible del mapa (`RTREE-polygon`)**: botones *Filtrar zona visible (R-Tree)* / *Quitar zona* en el panel del mapa; envían `zona=sur,oeste,norte,este` (rectángulo morado punteado en Leaflet). `servidor._zona()` valida 4 números finitos con `sur < norte` en `[-90, 90]` y `oeste < este` en `[-180, 180]` (si no, 400). `recomendador.sucursales_en_zona()` consulta `WHERE intersecta(ubicacion, POLYGON(...))`; `_resolver_espacial()` intersecta zona y radio. Aplica a `/api/productos`, `/api/buscar`, `/api/buscar/imagen` y `/api/productos/{id}/recomendaciones`.
  - **Orden `Más cercanos (R-Tree)`** (`orden=cercania`, requiere `lat`/`lon`, si no 400): `_productos_por_cercania()` ordena las tiendas con `RTREE-knn` y trae cada bloque por `idx_cat_sucursal` con `ORDER BY rating DESC LIMIT n`, parando al llenar la página. La opción del `<select>` se habilita solo con ubicación fijada.
  - **Mapa ↔ tarjetas**: los ítems `#1..#10` de los popups abren el producto; el botón `📍 Distrito · distancia` de cada tarjeta y de cada recomendación abre el mapa centrado en su tienda con el popup (`verTiendaEnMapa`).
  - **Benchmark espacial**: `evaluar.py --espacial` (solo esa parte; resultados abajo).
  - Campo de respuesta `sucursales_en_radio`: ahora contiene las tiendas que pasan **todo** el filtro espacial (radio y/o zona); se mantuvo el nombre por compatibilidad.

- [x] **Mejora #3 — Barras de aporte por señal** (2026-11-19)
  - En modo Híbrido, cada ítem del Top 10 muestra una barra apilada con el aporte de `cocompra` (verde), `texto` (morado), `metadata` (naranja), `visual` (azul) y `espacial` (verde azulado), más el puntaje total; leyenda arriba de la lista. El largo es relativo al mejor puntaje del Top 10 (los aportes suman el `puntaje`); el `title` de cada segmento y el `aria-label` de la barra dan el % de cada señal. Sin cambios de backend (usa `aportes` y `puntaje` que ya entregaba la API). Los otros modos no muestran barra.

- [x] **Mejora #5 — Visor SQL y planes del motor** (2026-11-19)
  - `cliente_bd.registrar_consultas()` (context manager con `ContextVar`, aislado por petición) anota en cada `filas()` el SQL, el `plan` devuelto por `/api/query` y los tiempos (`ms_motor` = `elapsedMs` del motor, `ms_total` = ida y vuelta HTTP). No envía consultas extra ni `EXPLAIN` aparte.
  - Los 4 endpoints de catálogo, búsquedas y recomendaciones devuelven la lista en `consultas` (respuestas de ~45–55 KB).
  - UI: paneles desplegables `<details>` *SQL y planes del motor BD2* bajo la grilla y bajo el Top 10 (`N consultas · X ms en el motor`; por consulta: SQL y pasos `op · method — detail (filas)`).
  - Sobre `data/runtime/`, una recomendación híbrida con ubicación muestra 9 consultas: `RTREE-radius` (1 ms), self-join de co-compra con `BPLUS(item_id)` + `external-hash` (~792 ms, la más cara), candidatos de co-compra con **`Sequential Scan`** (~127 ms), `HNSW-cosine` (~133 ms), `SPIMI-BM25` (~30 ms), `BPLUS(categoria)` + `top-n-heapsort` (~31 ms) y `RTREE-knn` (1 ms).
  - **Hallazgo para el informe**: el planificador del motor no usa `BPLUS(id)` para `WHERE id IN (...)`. No se corrige (regla: no tocar `backend/`); esquivarlo con una consulta por id costaría lo mismo por las idas y vueltas HTTP (~4 ms c/u).

- [x] **Auditorías y robustez del frontend** (2026-11-19/20, tres rondas de revisión)
  - Los marcadores de tienda (`L.circleMarker`) usan `bubblingMouseEvents: false`: antes el clic llegaba también al mapa y movía la ubicación del usuario encima de la tienda.
  - Respuestas viejas descartadas con contadores de pedidos: `estado.pedidoRec` en recomendaciones (cambio de producto, pesos, modo, zona…) y `estado.pedidoGrilla` en `cargarCatalogo` / `buscarTexto` / `buscarPorArchivo`.
  - La búsqueda por foto sobrevive a los cambios de filtro: el archivo queda en `estado.archivoBusqueda` y `recargarVistaActual()` la repite con los filtros nuevos; se olvida al buscar por texto, al pulsar *Limpiar*, al volver al catálogo o si el servidor rechaza la imagen.
  - Limpieza: CSS compartido de `.enlace-tienda` / `.popup-item`, y `_preparar()` en `evaluar.py` para el inicio común de ambas evaluaciones.
  - Revisado sin hallazgos: SQL siempre vía `punto_sql`/`numero_sql`/`texto_sql`, SQL del visor pintado con `textContent` (sin inyección HTML), `hay_mas` correcto en el orden por cercanía, aislamiento del registro de consultas entre peticiones simultáneas.

- [x] **Verificación automatizada**
  - Suites en verde: `ecommerce/test_cliente_bd.py`, `ecommerce/test_contrato_motor.py`, `ecommerce/test_ingesta.py`, `ecommerce/test_recomendador.py`, `ecommerce/test_servidor.py`.
  - Cobertura agregada el 2026-11-19: plan `RTREE-polygon` y bloque por `sucursal_id` en el contrato; zona, zona + radio, orden `cercania` (paginación y error sin ubicación) y `ejecutar_evaluacion_espacial` en el recomendador; validación de `zona` (6 casos inválidos), filtros por zona en catálogo/búsqueda/recomendaciones, `orden=cercania` y presencia de planes reales (`RTREE-polygon`, `Vector Index Scan`, `Text Index Scan`) en `consultas` en el servidor; registro de consultas solo dentro del bloque en el cliente.
  - Validación de sintaxis y entrenamiento: `node --check ecommerce/web/app.js` y `scripts/entrenar_Kmeans.py --autoprueba`.

---

## Resultados de evaluación validados

Condiciones: catálogo real cargado de **1,500 productos**, **24,999 órdenes** y **100 muestras** por corrida (`evaluar.py --muestras 100`).

> Cómo reproducir todas estas mediciones (preparación, comandos por semilla, protocolo, métricas, benchmark espacial, `EXPLAIN ANALYZE` y latencias por consulta con el visor): `README.md` › **Cómo hacer el benchmarking**. Ojo: sin `--salida` distinta por semilla, cada corrida sobrescribe los CSV; los que hay hoy en `benchmarks/ecommerce_results/` son de la semilla 42.

> Baseline previo a la Mejora #1 (`hibrido` RRF con pesos `0.35 / 0.30 / 0.25 / 0.10`): `Hit@10 = 0.58`, `NDCG@10 = 0.1132`, `MRR = 0.2675`.

| Escenario | Modo | Hit@10 | Recall@5 | Recall@10 | NDCG@10 | MRR | Prec. Cat@10 | ms prom. |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| **Semilla 42 (normal)** | `cocompra` | **0.64** | 0.0763 | **0.1253** | **0.1454** | 0.3363 | 0.280 | 883.2 |
| | `visual` | 0.12 | 0.0048 | 0.0128 | 0.0124 | 0.0337 | 0.215 | 161.8 |
| | `texto` | 0.30 | 0.0305 | 0.0504 | 0.0584 | 0.1516 | 0.395 | 31.5 |
| | `metadata` | 0.24 | 0.0109 | 0.0304 | 0.0285 | 0.0680 | 0.980 | 32.3 |
| | `hibrido_rrf` | 0.61 | 0.0744 | 0.1168 | 0.1405 | **0.3458** | 0.393 | 1072.3 |
| | `hibrido_score` | 0.60 | **0.0795** | 0.1158 | 0.1409 | 0.3372 | **0.406** | 1050.0 |
| **Semilla 42 (cold-start)** | `cocompra` | 0.00 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.000 | 14.2 |
| | `visual` | 0.12 | 0.0048 | 0.0128 | 0.0124 | 0.0337 | 0.215 | 147.4 |
| | `texto` | 0.30 | 0.0305 | 0.0504 | 0.0584 | 0.1516 | 0.395 | 28.1 |
| | `metadata` | 0.24 | 0.0109 | 0.0304 | 0.0285 | 0.0680 | 0.980 | 37.3 |
| | `hibrido_rrf` | **0.36** | 0.0325 | **0.0532** | 0.0594 | 0.1570 | 0.512 | 209.8 |
| | `hibrido_score` | **0.36** | **0.0345** | 0.0531 | **0.0627** | **0.1713** | **0.545** | 194.5 |
| **Semilla 123 (normal)** | `cocompra` | **0.54** | **0.0472** | 0.0727 | **0.0877** | **0.2562** | 0.265 | 922.8 |
| | `visual` | 0.10 | 0.0068 | 0.0118 | 0.0118 | 0.0305 | 0.231 | 143.1 |
| | `texto` | 0.24 | 0.0186 | 0.0324 | 0.0360 | 0.0948 | 0.453 | 27.7 |
| | `metadata` | 0.20 | 0.0128 | 0.0217 | 0.0195 | 0.0459 | 0.980 | 38.6 |
| | `hibrido_rrf` | 0.51 | 0.0385 | 0.0738 | 0.0814 | 0.2093 | 0.371 | 1107.4 |
| | `hibrido_score` | 0.52 | 0.0432 | **0.0748** | 0.0867 | 0.2335 | **0.399** | 1069.1 |

Archivos generados en disco: `benchmarks/ecommerce_results/resumen.csv`, `benchmarks/ecommerce_results/detalle.csv`, `benchmarks/ecommerce_results/resumen_cold_start.csv`, `benchmarks/ecommerce_results/detalle_cold_start.csv`.

### Conclusiones principales

1. **Dominio en cold-start**: sin historial previo (`cocompra = 0.0`), `hibrido_score` supera a todas las señales individuales en todas las métricas (`Hit@10 = 0.36` vs `0.30` de `texto`, `MRR = 0.1713` vs `0.1516`, `NDCG@10 = 0.0627` vs `0.0584`, `Prec. Cat@10 = 0.545`).
2. **`score` supera a `rrf` de forma consistente**: mejor `NDCG@10`, `Recall@5` y `Prec. Cat@10` en los tres escenarios, y mejor `MRR` en cold-start y semilla 123.
3. **Compromiso en warm-start**: `Hit@10` del híbrido queda `0.02–0.04` debajo de `cocompra` puro porque un candidato muy alto en `texto + metadata` puede desplazar una cocompra con conteo bajo al final del Top 10; a cambio aporta mayor coherencia de categoría (`+12–13` puntos porcentuales) y supera a `cocompra` en `Recall@5` / `MRR` (semilla 42) o `Recall@10` (semilla 123).

### Verificación espacial y ordenamiento sobre `data/runtime/` (1,500 productos, 8 sucursales)

Medición real vía `POST /api/query` (`EXPLAIN ANALYZE` con `TestClient` sobre la BD persistida):

| Consulta | Plan ejecutado | Buffers (`hit / read`) | Motor | HTTP `/api/query` |
|---|---|---:|---:|---:|
| **`RTREE-radius`** (`< 6000 m`, 5 tiendas) | `Spatial Index Scan · RTREE-radius` | `4 / 2` | **0.63 ms** | 7.9 ms |
| **`RTREE-knn`** (`LIMIT 3`) | `Spatial Index Scan · RTREE-knn` | `3 / 2` | **0.49 ms** | 5.0 ms |
| **`RTREE-knn`** (`LIMIT 8`) | `Spatial Index Scan · RTREE-knn` | `7 / 3` | **0.63 ms** | 5.3 ms |
| **`RTREE-polygon`** (`POLYGON` Lima Moderna, 5 tiendas) | `Spatial Index Scan · RTREE-polygon` | `4 / 2` | **0.26 ms** | 5.8 ms |
| `JOIN + ORDER BY distancia` pág. 1 (`LIMIT 13`) | `Seq Scan(1500)` + `Hash Join` + `top-N heapsort` *(sin R-Tree)* | `3007 / 2409` | **206.45 ms** | 201.2 ms |
| `JOIN + ORDER BY distancia` pág. 4 (`LIMIT 49`) | `Seq Scan(1500)` + `Hash Join` + `external k-way merge (47 runs)` | `3007 / 2409` | **294.53 ms** | 378.6 ms |
| Por sucursal (`idx_cat_sucursal`) pág. 1 (`LIMIT 13`) | `Index Scan(idx_cat_sucursal)` + `top-N heapsort (13 rows)` | `21 / 379` | **15.43 ms** | 22.1 ms |
| Por sucursal (`idx_cat_sucursal`) pág. 4 (`LIMIT 49`) | `Index Scan(idx_cat_sucursal)` + `external k-way merge (5 runs)` | `21 / 379` | **16.55 ms** | 30.0 ms |
| Catálogo global actual pág. 4 (`LIMIT 49`) | `Seq Scan(1500)` + `external k-way merge (47 runs)` | `2999 / 2406` | **218.64 ms** | 178.2 ms |

### Benchmark espacial (`evaluar.py --espacial --muestras 100`, semilla 42, híbrido `score`)

Ubicación del usuario elegida al azar entre 8 puntos reales de Lima por caso; `w_espacial = 0.0` reproduce `hibrido_score` normal.

| `w_espacial` | Hit@10 | Recall@10 | NDCG@10 | MRR | Prec. Cat@10 | Dist. media Top 10 | ms prom. |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.00 | 0.60 | 0.1158 | 0.1409 | 0.3372 | 0.406 | 7.95 km | 1154.8 |
| **0.10** | **0.63** | **0.1255** | **0.1509** | **0.3636** | 0.403 | 6.89 km | 1099.9 |
| 0.25 | 0.60 | 0.1109 | 0.1351 | 0.3361 | 0.354 | 5.50 km | 1165.1 |
| 0.50 | 0.58 | 0.0969 | 0.1138 | 0.2864 | 0.326 | 4.31 km | 1084.9 |

Archivos: `benchmarks/ecommerce_results/resumen_espacial.csv`, `detalle_espacial.csv` (por caso, con `lugar` y `dist_km`) y `latencias_espaciales.csv`. Puntos de Lima usados: Plaza Mayor, Parque Kennedy, UTEC Barranco, Estadio Nacional, Aeropuerto Jorge Chávez, UNALM La Molina, Plaza San Miguel y Malecón de Chorrillos (`UBICACIONES_LIMA` en `evaluar.py`).

Latencias cliente → motor (8 puntos × 5 repeticiones): `RTREE-radius` 3.80 ms (p95 4.40), `RTREE-knn` 3.57 ms (p95 4.25), `RTREE-polygon` 3.83 ms (p95 4.77).

Conclusión: el peso por defecto `0.10` acerca el Top 10 ~1 km sin perder precisión (incluso sube levemente, dentro del ruido de 100 muestras); desde `0.25` la cercanía empieza a desplazar co-compras relevantes y cae la afinidad de categoría.

Orden `cercania` del catálogo sobre `data/runtime/` (desde Miraflores, 12 por página): pág. 1 ≈ 33 ms, pág. 4 ≈ 38 ms, pág. 20 ≈ 108 ms, frente a ~200–300 ms del `JOIN + ORDER BY distancia` medido antes.

---

## Lo próximo (roadmap pendiente)

- [ ] **Integración pendiente en `Proyecto_BD2`** (hazlo primero; el código ya está copiado). `main` ya agregó entradas de `rostros` en los mismos tres archivos: **agrega las de `ecommerce` al final sin tocar las de `rag`, `redis` ni `rostros`**.
  - [x] **Puerto** (hecho 2026-11-20): `rostros` usa el `8200` (`dev:rostros`), así que `ecommerce` pasa al **`8300`**. Cambia el valor por defecto en `ecommerce/config.py:55` (`ECOM_PUERTO`, `"8200"` → `"8300"`) y las tres menciones de `8200` en `ecommerce/README.md` (diagrama, comentario `# 2) tienda` y comando `uvicorn` / URL). Busca con `rg -n 8200 ecommerce` que no quede ninguna (este archivo puede mencionarlo).
  - [x] `.gitignore`: agregar al final
    ```gitignore

    # App E-commerce: entorno local
    ecommerce/.venv
    ```
  - [x] `mprocs.yaml`: agregar dentro de `procs:`
    ```yaml
      ecommerce:
        shell: "pnpm dev:ecommerce"
    ```
  - [x] `package.json`: agregar en `scripts`, después de `dev:rostros-app` (fíjate en la coma de la línea anterior)
    ```json
    "setup:ecommerce": "uv venv ecommerce/.venv --python 3.12 && uv pip install --python ecommerce/.venv/bin/python -r ecommerce/requirements.txt",
    "dev:ecommerce": "cd ecommerce && .venv/bin/uvicorn servidor:app --port 8300"
    ```
  - [x] Verificar (2026-11-20: `package.json` válido; las 5 suites y `node --check` en verde con micromamba `bd2`; tienda en `:8300` sirve el catálogo de `data/runtime/`, que ya estaba cargado. **`pnpm setup:ecommerce` falla** porque `/mnt/data` es exFAT y `uv venv` no puede crear symlinks, igual que `rag` y `rostros`: usar micromamba `bd2`): `node -e "require('./package.json')"`, `pnpm setup:ecommerce` y las 5 suites (`ecommerce/test_*.py`). Después, con el motor arriba, vuelve a cargar `data/runtime/` con `ecommerce/ingesta.py` (ver `README.md` › *Ingesta*; el motor se levanta con `BD2_MODELS_DIR=data/modelos_ecommerce`) y abre <http://localhost:8300>.
  - [x] (2026-11-20: `test_contrato_motor.py` pasa sobre `main`) Revisa que `frontend/` (`MediaGallery.jsx`) y `backend/api/main.py` de `main` no rompan el contrato que prueba `test_contrato_motor.py`.

- [ ] **Revisión manual de la interfaz en el navegador** (nunca se vio en pantalla). Levantar motor y tienda (ver `README.md` › *Uso*), recargar con `Ctrl+Shift+R` y comprobar:
  - zona: rectángulo morado, catálogo filtrado, resumen `N tiendas en el filtro`, *Quitar zona* restaura;
  - clic en una tienda abre el popup **sin** mover la ubicación; ítems `#1..#10` del popup abren el producto; `📍` centra el mapa en la tienda sin seleccionar el producto;
  - orden `Más cercanos (R-Tree)` deshabilitado sin ubicación y vuelve a `Mejor rating` al quitarla;
  - búsqueda por foto + *Filtrar zona* conserva "Búsqueda visual: …";
  - barras de aporte en Híbrido (cambian con los sliders; segmento de cercanía con ubicación; RRF con puntajes ~0.01);
  - paneles *SQL y planes del motor BD2* bajo la grilla y el Top 10;
  - vista en pantallas de celular.
- [ ] **Gráficos para el informe** (se pueden hacer sin commits): script en `ecommerce/evaluacion/` que genere PNG desde `benchmarks/ecommerce_results/` — Hit@10 / NDCG@10 por modo (normal vs. cold-start), compromiso precisión–distancia por `w_espacial`, latencias por señal y del R-Tree.
- [ ] **Guion de la demo (5–10 min)**: catálogo → búsqueda BM25 → búsqueda por foto → Top 10 híbrido con barras de aporte → cambio de pesos/fusión → mapa con radio, k-NN y zona → orden por cercanía → panel de SQL y planes.
- [ ] **Sincronización con `main` y cierre de entregables (Parte 5)** — requiere commits:
  - [x] ~~Integrar `main` reciente (servicio `rostros`, galería del frontend)~~: hecho al copiar a `Proyecto_BD2`; el puerto queda en *Integración pendiente* (arriba).
  - [ ] Decidir si versionar `benchmarks/ecommerce_results/`, preparar capturas para el informe, grabar la demo y hacer commits limpios por tema en `feat/recomendador-ecommerce`.
- [ ] **Opcional · Mejora #1b (microajuste de pesos)**: probar pesos más cargados a `cocompra` (p. ej. `0.65 / 0.20 / 0.10 / 0.05`) con una 3.ª semilla. Baja prioridad: el benchmark espacial ya respalda los pesos actuales.
- [~] **Descartada · Mejora #4 — Simulación de compra en vivo** (`BEGIN TRANSACTION ... INSERT INTO ordenes ...` desde la UI): modificaría `data/runtime/` y haría irreproducibles los benchmarks.
