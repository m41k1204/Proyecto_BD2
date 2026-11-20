const estado = {
  pagina: 1,
  limite: 12,
  modoRec: "hibrido",
  fusionRec: "score",
  itemActivo: null,
  busquedaActiva: false,
  pesos: { cocompra: 0.55, texto: 0.25, metadata: 0.12, visual: 0.08, espacial: 0.10 },
  ubicacion: null,
  zona: null,
  rectZona: null,
  sucursales: [],
  mapa: null,
  marcadorUsuario: null,
  circuloRadio: null,
  marcadoresSucursales: new Map(),
  semillaActual: null,
  recomendacionesActuales: [],
  sucursalesKnn: [],
  pedidoRec: 0,
  pedidoGrilla: 0,
  archivoBusqueda: null,
};

const NOMBRES_SENAL = {
  cocompra: "Co-compra",
  visual: "Visual (SIFT)",
  texto: "Texto (BM25)",
  bm25: "BM25",
  tf_idf: "TF-IDF",
  metadata: "Metadata",
  espacial: "Cercanía (R-Tree)",
};

const $estado = document.getElementById("estado");
const $formBusqueda = document.getElementById("form-busqueda");
const $consulta = document.getElementById("consulta");
const $modoBusqueda = document.getElementById("modo-busqueda");
const $archivoImagen = document.getElementById("archivo-imagen");
const $limpiarBusqueda = document.getElementById("limpiar-busqueda");
const $categoria = document.getElementById("categoria");
const $precioMin = document.getElementById("precio-min");
const $precioMax = document.getElementById("precio-max");
const $orden = document.getElementById("orden");
const $aplicarFiltros = document.getElementById("aplicar-filtros");
const $toggleMapa = document.getElementById("toggle-mapa");
const $panelMapa = document.getElementById("panel-mapa");
const $radio = document.getElementById("radio");
const $ubicacionDemo = document.getElementById("ubicacion-demo");
const $limpiarUbicacion = document.getElementById("limpiar-ubicacion");
const $filtrarZona = document.getElementById("filtrar-zona");
const $quitarZona = document.getElementById("quitar-zona");
const $ordenCercania = $orden.querySelector('option[value="cercania"]');
const $resumenEspacial = document.getElementById("resumen-espacial");
const $tituloCatalogo = document.getElementById("titulo-catalogo");
const $tiemposBusqueda = document.getElementById("tiempos-busqueda");
const $aviso = document.getElementById("aviso");
const $grilla = document.getElementById("grilla");
const $paginacion = document.getElementById("paginacion");
const $pagAnterior = document.getElementById("pag-anterior");
const $pagSiguiente = document.getElementById("pag-siguiente");
const $pagInfo = document.getElementById("pag-info");
const $detalleVacio = document.getElementById("detalle-vacio");
const $detalleContenido = document.getElementById("detalle-contenido");
const $semilla = document.getElementById("semilla");
const $modosRec = document.getElementById("modos-rec");
const $pesosPanel = document.getElementById("pesos-panel");
const $campoPesoEspacial = document.getElementById("campo-peso-espacial");
const $sliderEspacial = $pesosPanel.querySelector('input[data-peso="espacial"]');
const $fusionRec = document.getElementById("fusion-rec");
const $tiemposRec = document.getElementById("tiempos-rec");
const $listaRec = document.getElementById("lista-recomendaciones");
const $sqlCatalogo = document.getElementById("sql-catalogo");
const $sqlRec = document.getElementById("sql-rec");

function el(tag, clase, texto) {
  const nodo = document.createElement(tag);
  if (clase) nodo.className = clase;
  if (texto !== undefined && texto !== null) nodo.textContent = texto;
  return nodo;
}

function formatoPrecio(precio) {
  if (precio === null || precio === undefined) return "Sin precio";
  return "$" + Number(precio).toFixed(2);
}

function formatoDistancia(metros) {
  if (metros === null || metros === undefined) return "";
  return metros < 1000 ? `${Math.round(metros)} m` : `${(metros / 1000).toFixed(1)} km`;
}

function imagenProducto(ruta, alt) {
  const img = el("img");
  img.alt = alt || "Producto";
  img.loading = "lazy";
  if (ruta) img.src = "/media/" + ruta;
  img.addEventListener("error", () => {
    img.style.visibility = "hidden";
  });
  return img;
}

function paramsFiltros() {
  const params = new URLSearchParams();
  if ($categoria.value) params.set("categoria", $categoria.value);
  if ($precioMin.value !== "") params.set("precio_min", $precioMin.value);
  if ($precioMax.value !== "") params.set("precio_max", $precioMax.value);
  if (estado.ubicacion) {
    params.set("lat", estado.ubicacion.lat.toFixed(6));
    params.set("lon", estado.ubicacion.lon.toFixed(6));
    if ($radio.value) params.set("radio_m", $radio.value);
  }
  if (estado.zona) params.set("zona", textoZona());
  return params;
}

function textoZona() {
  const { sur, oeste, norte, este } = estado.zona;
  return [sur, oeste, norte, este].map((v) => v.toFixed(6)).join(",");
}

function botonTienda(p) {
  const suc = p.sucursal;
  const dist = p.distancia_m !== null && p.distancia_m !== undefined ? ` · ${formatoDistancia(p.distancia_m)}` : "";
  const boton = el("button", "enlace-tienda", `📍 ${suc.distrito}${dist}`);
  boton.type = "button";
  boton.title = `Ver ${suc.nombre} en el mapa`;
  boton.addEventListener("click", (ev) => {
    ev.stopPropagation();
    verTiendaEnMapa(suc.id);
  });
  return boton;
}

function textoPaso(paso) {
  let texto = paso.method ? `${paso.op} · ${paso.method}` : paso.op;
  if (paso.detail) texto += ` — ${paso.detail}`;
  if (paso.rows !== null && paso.rows !== undefined) texto += ` (${paso.rows} filas)`;
  return texto;
}

// Consultas reales enviadas al motor en esta petición, con el plan que ejecutó.
function pintarConsultas(panel, consultas) {
  const lista = panel.querySelector(".lista-sql");
  lista.replaceChildren();
  panel.hidden = !consultas || !consultas.length;
  if (panel.hidden) return;
  const msMotor = consultas.reduce((suma, c) => suma + (c.ms_motor ?? c.ms_total), 0);
  panel.querySelector("summary").textContent =
    `SQL y planes del motor BD2 · ${consultas.length} consultas · ${msMotor.toFixed(1)} ms en el motor`;
  consultas.forEach((c, i) => {
    const item = el("div", "consulta-sql");
    const tiempo = c.ms_motor !== null && c.ms_motor !== undefined ? `${c.ms_motor} ms motor · ` : "";
    item.appendChild(el("div", "tenue", `#${i + 1} · ${tiempo}${c.ms_total} ms total`));
    item.appendChild(el("pre", "", c.sql));
    const pasos = el("ol", "plan-sql");
    for (const paso of c.plan || []) pasos.appendChild(el("li", "", textoPaso(paso)));
    item.appendChild(pasos);
    lista.appendChild(item);
  });
}

function pintarTiempos(contenedor, tiempos) {
  contenedor.replaceChildren();
  if (!tiempos) return;
  for (const [clave, ms] of Object.entries(tiempos)) {
    const etiqueta = clave.replace(/_ms$/, "");
    contenedor.appendChild(el("span", "tiempo-chip", `${etiqueta}: ${ms} ms`));
  }
}

function pintarBadges(producto) {
  const wrap = el("div", "etiquetas");
  for (const [senal, pos] of Object.entries(producto.posiciones || {})) {
    let texto = `${NOMBRES_SENAL[senal] || senal} #${pos}`;
    if (senal === "cocompra" && producto.cocompras) {
      texto += ` (${producto.cocompras}×)`;
    }
    wrap.appendChild(el("span", `etiqueta ${senal}`, texto));
  }
  if (producto.distancia_m !== null && producto.distancia_m !== undefined) {
    wrap.appendChild(el("span", "etiqueta distancia", formatoDistancia(producto.distancia_m)));
  }
  return wrap;
}

function pintarGrilla(productos, mostrarBadges) {
  $grilla.replaceChildren();
  if (!productos.length) {
    $grilla.appendChild(el("p", "vacio", "No se encontraron productos con esos filtros."));
    return;
  }
  for (const p of productos) {
    const tarjeta = el("article", "tarjeta");
    tarjeta.dataset.id = String(p.id);
    if (estado.itemActivo === p.id) tarjeta.classList.add("seleccionada");
    tarjeta.appendChild(imagenProducto(p.imagen, p.nombre));
    tarjeta.appendChild(el("h3", "", p.nombre));
    const filaMeta = el("div", "meta-linea");
    filaMeta.appendChild(el("span", "precio", formatoPrecio(p.precio)));
    const ratingTxt = p.rating !== null && p.rating !== undefined ? `★ ${Number(p.rating).toFixed(1)}` : "Sin rating";
    filaMeta.appendChild(el("span", "", ratingTxt));
    tarjeta.appendChild(filaMeta);
    const pie = el("div", "meta-linea", p.marca || "");
    if (p.sucursal) pie.appendChild(botonTienda(p));
    tarjeta.appendChild(pie);
    if (mostrarBadges) tarjeta.appendChild(pintarBadges(p));
    tarjeta.addEventListener("click", () => seleccionarProducto(p.id));
    $grilla.appendChild(tarjeta);
  }
}

async function cargarEstado() {
  try {
    const res = await fetch("/api/estado");
    const data = await res.json();
    if (!data.motor) {
      $estado.textContent = "motor BD2 sin conexión";
      $estado.classList.add("mal");
      return;
    }
    $estado.classList.remove("mal");
    $estado.textContent = `${data.productos} productos · ${data.ordenes} órdenes · ${data.sucursales} tiendas`;
  } catch {
    $estado.textContent = "sin conexión";
    $estado.classList.add("mal");
  }
}

async function cargarCategorias() {
  const res = await fetch("/api/categorias");
  const lista = await res.json();
  for (const cat of lista) {
    const opt = el("option", "", `${cat.categoria} (${cat.productos})`);
    opt.value = cat.categoria;
    $categoria.appendChild(opt);
  }
}

function distanciaMetros(lat1, lon1, lat2, lon2) {
  const rad = Math.PI / 180;
  const dphi = (lat2 - lat1) * rad;
  const dlam = (lon2 - lon1) * rad;
  const a =
    Math.sin(dphi / 2) ** 2 +
    Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(dlam / 2) ** 2;
  return 2 * 6371000 * Math.asin(Math.sqrt(Math.min(1, Math.max(0, a))));
}

function actualizarControlEspacial() {
  const activa = Boolean(estado.ubicacion);
  $sliderEspacial.disabled = !activa;
  $campoPesoEspacial.classList.toggle("deshabilitado", !activa);
  $campoPesoEspacial.title = activa
    ? "Peso de cercanía (R-Tree k-NN)"
    : "Fija tu ubicación en el mapa para activar";
  $ordenCercania.disabled = !activa;
  if (!activa && $orden.value === "cercania") $orden.value = "rating";
  $quitarZona.hidden = !estado.zona;
}

function construirPopupTienda(sucursal, { topItems, esSemilla, knnSuc }) {
  const cont = el("div", "popup-tienda");
  cont.appendChild(el("strong", "", `${sucursal.nombre} (${sucursal.distrito})`));
  if (knnSuc) {
    cont.appendChild(el("div", "tenue", `k-NN cercano (R-Tree) · ${formatoDistancia(knnSuc.distancia_m)}`));
  } else if (estado.ubicacion && sucursal.lat !== null && sucursal.lon !== null) {
    const dist = distanciaMetros(estado.ubicacion.lat, estado.ubicacion.lon, sucursal.lat, sucursal.lon);
    cont.appendChild(el("div", "tenue", `A ${formatoDistancia(dist)}`));
  }
  if (esSemilla) {
    cont.appendChild(el("div", "tenue", "Producto seleccionado"));
  }
  if (topItems.length) {
    const lista = el("div");
    for (const item of topItems) {
      const boton = el("button", "popup-item", `#${item.pos} ${item.nombre}`);
      boton.type = "button";
      boton.addEventListener("click", () => seleccionarProducto(item.id));
      lista.appendChild(boton);
    }
    cont.appendChild(lista);
  }
  return cont;
}

function actualizarMarcadoresTiendas() {
  if (!estado.mapa || typeof window.L === "undefined") return;
  const porSucursal = new Map();
  estado.recomendacionesActuales.forEach((item, idx) => {
    const sid = item.sucursal ? item.sucursal.id : item.sucursal_id;
    if (!sid) return;
    if (!porSucursal.has(sid)) porSucursal.set(sid, []);
    porSucursal.get(sid).push({ pos: idx + 1, id: item.id, nombre: item.nombre });
  });
  const semillaSucId = estado.semillaActual
    ? (estado.semillaActual.sucursal ? estado.semillaActual.sucursal.id : estado.semillaActual.sucursal_id)
    : null;
  const knnMap = new Map((estado.sucursalesKnn || []).map((s) => [s.id, s]));

  for (const s of estado.sucursales) {
    if (s.lat === null || s.lon === null) continue;
    let marcador = estado.marcadoresSucursales.get(s.id);
    if (!marcador) {
      marcador = L.circleMarker([s.lat, s.lon], { bubblingMouseEvents: false }).addTo(estado.mapa).bindPopup("");
      estado.marcadoresSucursales.set(s.id, marcador);
    }
    const topItems = porSucursal.get(s.id) || [];
    const esSemilla = semillaSucId === s.id;
    const knnSuc = knnMap.get(s.id) || null;
    if (topItems.length) {
      marcador.setStyle({
        fillColor: "#22c55e",
        color: esSemilla ? "#f59e0b" : "#14532d",
        radius: 9 + Math.min(topItems.length, 5),
        weight: 3,
        fillOpacity: 0.9,
      });
      marcador.bringToFront();
    } else if (esSemilla) {
      marcador.setStyle({
        fillColor: "#f59e0b",
        color: "#b45309",
        radius: 10,
        weight: 2.5,
        fillOpacity: 0.9,
      });
      marcador.bringToFront();
    } else if (knnSuc) {
      marcador.setStyle({
        fillColor: "#14b8a6",
        color: "#115e59",
        radius: 8,
        weight: 2,
        fillOpacity: 0.85,
      });
    } else {
      marcador.setStyle({
        fillColor: "#94a3b8",
        color: "#475569",
        radius: 7,
        weight: 2,
        fillOpacity: 0.75,
      });
    }
    marcador.setPopupContent(construirPopupTienda(s, { topItems, esSemilla, knnSuc }));
  }
  if (estado.marcadorUsuario) estado.marcadorUsuario.bringToFront();
}

async function cargarSucursales() {
  const res = await fetch("/api/sucursales");
  estado.sucursales = await res.json();
  actualizarMarcadoresTiendas();
}

function inicializarMapa() {
  if (estado.mapa || typeof window.L === "undefined") {
    if (typeof window.L === "undefined") {
      document.getElementById("mapa").textContent = "Leaflet no pudo cargarse (sin red). Usa 'Usar Miraflores' para probar el filtro espacial.";
    }
    return;
  }
  const mapa = L.map("mapa").setView([-12.095, -77.035], 12);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "© OpenStreetMap",
  }).addTo(mapa);
  mapa.on("click", (ev) => fijarUbicacion(ev.latlng.lat, ev.latlng.lng));
  estado.mapa = mapa;
  actualizarMarcadoresTiendas();
  actualizarCapaUsuario();
}

function actualizarCapaUsuario() {
  if (!estado.mapa || typeof window.L === "undefined") return;
  if (estado.marcadorUsuario) {
    estado.mapa.removeLayer(estado.marcadorUsuario);
    estado.marcadorUsuario = null;
  }
  if (estado.circuloRadio) {
    estado.mapa.removeLayer(estado.circuloRadio);
    estado.circuloRadio = null;
  }
  if (estado.ubicacion) {
    const punto = [estado.ubicacion.lat, estado.ubicacion.lon];
    estado.marcadorUsuario = L.circleMarker(punto, { radius: 7, color: "#fff", weight: 2, fillColor: "#1f6feb", fillOpacity: 0.9, interactive: false }).addTo(estado.mapa);
    if ($radio.value) {
      estado.circuloRadio = L.circle(punto, { radius: Number($radio.value), color: "#1f6feb", fillOpacity: 0.12, interactive: false }).addTo(estado.mapa);
    }
  }
  if (estado.rectZona) {
    estado.mapa.removeLayer(estado.rectZona);
    estado.rectZona = null;
  }
  if (estado.zona) {
    const { sur, oeste, norte, este } = estado.zona;
    estado.rectZona = L.rectangle([[sur, oeste], [norte, este]], {
      color: "#7c3aed", weight: 2, dashArray: "6 4", fillOpacity: 0.05, interactive: false,
    }).addTo(estado.mapa);
  }
  actualizarMarcadoresTiendas();
}

function abrirPanelMapa() {
  $panelMapa.hidden = false;
  $toggleMapa.classList.add("activo");
  inicializarMapa();
  if (estado.mapa) setTimeout(() => estado.mapa.invalidateSize(), 50);
}

function verTiendaEnMapa(sucursalId) {
  abrirPanelMapa();
  $panelMapa.scrollIntoView({ behavior: "smooth", block: "start" });
  const suc = estado.sucursales.find((s) => s.id === sucursalId);
  const marcador = estado.marcadoresSucursales.get(sucursalId);
  if (!estado.mapa || !suc || suc.lat === null || !marcador) return;
  setTimeout(() => {
    estado.mapa.setView([suc.lat, suc.lon], 14);
    marcador.openPopup();
  }, 80);
}

function fijarZona(zona) {
  estado.zona = zona;
  actualizarControlEspacial();
  actualizarCapaUsuario();
  pintarResumenEspacial();
  recargarVistaActual();
}

function pintarResumenEspacial(enFiltro, enKnn) {
  const partes = [];
  if (estado.ubicacion) {
    const { lat, lon } = estado.ubicacion;
    const radioTxt = $radio.value ? `${Number($radio.value) / 1000} km` : "sin límite";
    partes.push(`Ubicación: (${lat.toFixed(3)}, ${lon.toFixed(3)}) · radio ${radioTxt}`);
  }
  if (estado.zona) partes.push("zona del mapa (R-Tree polygon)");
  const hayFiltro = estado.zona || (estado.ubicacion && $radio.value);
  if (hayFiltro && enFiltro !== undefined) {
    partes.push(estado.zona ? `${enFiltro} tiendas en el filtro` : `${enFiltro} en radio`);
  }
  if (enKnn !== undefined) partes.push(`${enKnn} en k-NN`);
  $resumenEspacial.textContent = partes.join(" · ");
}

function fijarUbicacion(lat, lon) {
  estado.ubicacion = { lat, lon };
  pintarResumenEspacial();
  actualizarControlEspacial();
  actualizarCapaUsuario();
  recargarVistaActual();
}

async function cargarCatalogo() {
  const pedido = ++estado.pedidoGrilla;
  estado.busquedaActiva = false;
  estado.archivoBusqueda = null;
  $limpiarBusqueda.hidden = true;
  $paginacion.hidden = false;
  $aviso.hidden = true;
  $tiemposBusqueda.replaceChildren();
  $tituloCatalogo.textContent = "Catálogo";

  const params = paramsFiltros();
  params.set("orden", $orden.value);
  params.set("limite", String(estado.limite));
  params.set("pagina", String(estado.pagina));

  const res = await fetch("/api/productos?" + params.toString());
  const data = await res.json();
  if (pedido !== estado.pedidoGrilla) return;
  if (!res.ok) {
    $aviso.textContent = data.detail || "Error al cargar catálogo";
    $aviso.hidden = false;
    return;
  }
  pintarGrilla(data.productos, false);
  pintarConsultas($sqlCatalogo, data.consultas);
  if (!estado.itemActivo) pintarResumenEspacial((data.sucursales_en_radio || []).length);
  $pagInfo.textContent = `Página ${data.pagina}`;
  $pagAnterior.disabled = data.pagina <= 1;
  $pagSiguiente.disabled = !data.hay_mas;
}

async function buscarTexto() {
  const q = $consulta.value.trim();
  if (!q) return cargarCatalogo();
  const pedido = ++estado.pedidoGrilla;
  estado.busquedaActiva = true;
  estado.archivoBusqueda = null;
  $limpiarBusqueda.hidden = false;
  $paginacion.hidden = true;
  $aviso.hidden = true;
  $tituloCatalogo.textContent = `Resultados para "${q}"`;

  const params = paramsFiltros();
  params.set("q", q);
  params.set("modo", $modoBusqueda.value);
  params.set("k", "16");

  const res = await fetch("/api/buscar?" + params.toString());
  const data = await res.json();
  if (pedido !== estado.pedidoGrilla) return;
  if (!res.ok) {
    $aviso.textContent = data.detail || "Error en la búsqueda";
    $aviso.hidden = false;
    return;
  }
  if (data.aviso) {
    $aviso.textContent = data.aviso;
    $aviso.hidden = false;
  }
  pintarTiempos($tiemposBusqueda, data.tiempos);
  pintarGrilla(data.productos, true);
  pintarConsultas($sqlCatalogo, data.consultas);
}

async function buscarPorArchivo(archivo) {
  const pedido = ++estado.pedidoGrilla;
  estado.busquedaActiva = true;
  estado.archivoBusqueda = archivo;
  $limpiarBusqueda.hidden = false;
  $paginacion.hidden = true;
  $aviso.hidden = true;
  $tituloCatalogo.textContent = `Búsqueda visual: ${archivo.name}`;

  const form = new FormData();
  form.append("archivo", archivo);
  form.append("k", "16");
  if ($categoria.value) form.append("categoria", $categoria.value);
  if ($precioMin.value !== "") form.append("precio_min", $precioMin.value);
  if ($precioMax.value !== "") form.append("precio_max", $precioMax.value);
  if (estado.ubicacion) {
    form.append("lat", String(estado.ubicacion.lat));
    form.append("lon", String(estado.ubicacion.lon));
    if ($radio.value) form.append("radio_m", $radio.value);
  }
  if (estado.zona) form.append("zona", textoZona());

  const res = await fetch("/api/buscar/imagen", { method: "POST", body: form });
  const data = await res.json();
  if (pedido !== estado.pedidoGrilla) return;
  if (!res.ok) {
    $aviso.textContent = data.detail || "No se pudo procesar la imagen";
    $aviso.hidden = false;
    estado.archivoBusqueda = null;
    return;
  }
  pintarTiempos($tiemposBusqueda, data.tiempos);
  pintarGrilla(data.productos, true);
  pintarConsultas($sqlCatalogo, data.consultas);
}

function pintarSemilla(p) {
  $semilla.replaceChildren();
  $semilla.appendChild(imagenProducto(p.imagen, p.nombre));
  const info = el("div");
  info.appendChild(el("h2", "", p.nombre));
  const detalles = [
    formatoPrecio(p.precio),
    p.rating !== null && p.rating !== undefined ? `★ ${Number(p.rating).toFixed(1)}` : null,
    p.marca,
    p.categoria,
    p.sucursal ? `${p.sucursal.nombre} (${p.sucursal.distrito})` : null,
    p.distancia_m !== null && p.distancia_m !== undefined ? formatoDistancia(p.distancia_m) : null,
  ].filter(Boolean).join(" · ");
  info.appendChild(el("div", "tenue", detalles));
  info.appendChild(el("p", "", p.descripcion || ""));
  $semilla.appendChild(info);
}

const ORDEN_SENALES = ["cocompra", "texto", "metadata", "visual", "espacial"];

function leyendaAportes(items) {
  const presentes = ORDEN_SENALES.filter((s) => items.some((i) => i.aportes && i.aportes[s]));
  const leyenda = el("div", "leyenda-aportes");
  leyenda.appendChild(el("span", "tenue", "Aporte al puntaje:"));
  for (const senal of presentes) {
    const etiqueta = el("span", "");
    etiqueta.appendChild(el("i", `muestra-senal ${senal}`));
    etiqueta.appendChild(document.createTextNode(NOMBRES_SENAL[senal]));
    leyenda.appendChild(etiqueta);
  }
  return leyenda;
}

// Ancho relativo al mejor puntaje del Top 10: los aportes suman el puntaje del ítem.
function barraAportes(item, maxPuntaje) {
  const total = Object.values(item.aportes).reduce((a, b) => a + b, 0) || 1;
  const fila = el("div", "aportes");
  const barra = el("div", "barra-aportes");
  const partes = [];
  for (const senal of ORDEN_SENALES) {
    const valor = item.aportes[senal];
    if (!valor) continue;
    const texto = `${NOMBRES_SENAL[senal]}: ${Math.round((valor / total) * 100)}%`;
    const segmento = el("span", `segmento ${senal}`);
    segmento.style.width = `${(valor / maxPuntaje) * 100}%`;
    segmento.title = texto;
    barra.appendChild(segmento);
    partes.push(texto);
  }
  barra.setAttribute("role", "img");
  barra.setAttribute("aria-label", "Aporte por señal: " + partes.join(", "));
  fila.appendChild(barra);
  fila.appendChild(el("span", "puntaje-rec", Number(item.puntaje).toFixed(3)));
  return fila;
}

function pintarRecomendaciones(items) {
  $listaRec.replaceChildren();
  if (!items.length) {
    $listaRec.appendChild(el("p", "vacio", "Sin recomendaciones para los filtros activos."));
    return;
  }
  const conAportes = items.some((i) => i.aportes);
  const maxPuntaje = Math.max(...items.map((i) => Number(i.puntaje) || 0)) || 1;
  if (conAportes) $listaRec.appendChild(leyendaAportes(items));
  for (const item of items) {
    const fila = el("article", "rec-item");
    fila.appendChild(imagenProducto(item.imagen, item.nombre));
    const cuerpo = el("div");
    cuerpo.appendChild(el("h4", "", item.nombre));
    const meta = [
      formatoPrecio(item.precio),
      item.rating !== null && item.rating !== undefined ? `★ ${Number(item.rating).toFixed(1)}` : null,
      item.categoria,
    ].filter(Boolean).join(" · ");
    const lineaMeta = el("div", "tenue", meta);
    if (item.sucursal) lineaMeta.appendChild(botonTienda(item));
    cuerpo.appendChild(lineaMeta);
    cuerpo.appendChild(pintarBadges(item));
    if (item.aportes) cuerpo.appendChild(barraAportes(item, maxPuntaje));
    fila.appendChild(cuerpo);
    fila.addEventListener("click", () => seleccionarProducto(item.id));
    $listaRec.appendChild(fila);
  }
}

async function seleccionarProducto(itemId) {
  estado.itemActivo = itemId;
  for (const tarjeta of $grilla.querySelectorAll(".tarjeta")) {
    tarjeta.classList.toggle("seleccionada", tarjeta.dataset.id === String(itemId));
  }
  await cargarRecomendaciones();
}

async function cargarRecomendaciones() {
  if (!estado.itemActivo) return;
  // Cada pedido invalida a los anteriores: una respuesta lenta no pisa a una más nueva
  // (otro producto, otros pesos, otra zona…).
  const pedido = ++estado.pedidoRec;
  $detalleVacio.hidden = true;
  $detalleContenido.hidden = false;
  $pesosPanel.hidden = estado.modoRec !== "hibrido";
  if (estado.modoRec === "espacial" && !estado.ubicacion) {
    abrirPanelMapa();
    $tiemposRec.replaceChildren();
    pintarConsultas($sqlRec, []);
    estado.recomendacionesActuales = [];
    estado.sucursalesKnn = [];
    actualizarMarcadoresTiendas();
    $listaRec.replaceChildren(
      el("p", "vacio", "Fija tu ubicación en el mapa (o pulsa 'Usar Miraflores') para recomendar por cercanía (R-Tree).")
    );
    const resSemilla = await fetch(`/api/productos/${estado.itemActivo}`);
    if (resSemilla.ok && pedido === estado.pedidoRec) {
      estado.semillaActual = await resSemilla.json();
      pintarSemilla(estado.semillaActual);
      actualizarMarcadoresTiendas();
    }
    return;
  }

  const params = paramsFiltros();
  params.set("modo", estado.modoRec);
  params.set("k", "10");
  if (estado.modoRec === "hibrido") {
    params.set("fusion", estado.fusionRec);
    params.set("w_cocompra", String(estado.pesos.cocompra));
    params.set("w_visual", String(estado.pesos.visual));
    params.set("w_texto", String(estado.pesos.texto));
    params.set("w_metadata", String(estado.pesos.metadata));
    if (estado.ubicacion) params.set("w_espacial", String(estado.pesos.espacial));
  }

  const res = await fetch(`/api/productos/${estado.itemActivo}/recomendaciones?` + params.toString());
  const data = await res.json();
  if (pedido !== estado.pedidoRec) return;
  if (!res.ok) {
    $listaRec.replaceChildren(el("p", "vacio", data.detail || "No se pudo recomendar."));
    pintarConsultas($sqlRec, []);
    return;
  }
  estado.semillaActual = data.semilla;
  estado.recomendacionesActuales = data.recomendaciones || [];
  estado.sucursalesKnn = data.sucursales_knn || [];
  // k-NN solo corre con la señal espacial activa; sin ella no hay conteo que mostrar
  pintarResumenEspacial((data.sucursales_en_radio || []).length, estado.sucursalesKnn.length || undefined);
  pintarSemilla(data.semilla);
  pintarTiempos($tiemposRec, data.tiempos);
  pintarRecomendaciones(data.recomendaciones);
  pintarConsultas($sqlRec, data.consultas);
  actualizarMarcadoresTiendas();
}

function recargarVistaActual() {
  if (estado.archivoBusqueda) {
    buscarPorArchivo(estado.archivoBusqueda);
  } else if (estado.busquedaActiva && $consulta.value.trim()) {
    buscarTexto();
  } else {
    estado.pagina = 1;
    cargarCatalogo();
  }
  if (estado.itemActivo) cargarRecomendaciones();
}

$formBusqueda.addEventListener("submit", (ev) => {
  ev.preventDefault();
  buscarTexto();
});

$limpiarBusqueda.addEventListener("click", () => {
  $consulta.value = "";
  cargarCatalogo();
});

$archivoImagen.addEventListener("change", () => {
  if ($archivoImagen.files && $archivoImagen.files[0]) {
    buscarPorArchivo($archivoImagen.files[0]);
    $archivoImagen.value = "";
  }
});

$aplicarFiltros.addEventListener("click", recargarVistaActual);
$orden.addEventListener("change", () => {
  if (!estado.busquedaActiva) {
    estado.pagina = 1;
    cargarCatalogo();
  }
});

$pagAnterior.addEventListener("click", () => {
  if (estado.pagina > 1) {
    estado.pagina -= 1;
    cargarCatalogo();
  }
});
$pagSiguiente.addEventListener("click", () => {
  estado.pagina += 1;
  cargarCatalogo();
});

$toggleMapa.addEventListener("click", () => {
  if ($panelMapa.hidden) {
    abrirPanelMapa();
  } else {
    $panelMapa.hidden = true;
    $toggleMapa.classList.remove("activo");
  }
});

$filtrarZona.addEventListener("click", () => {
  if (!estado.mapa) return;
  const b = estado.mapa.getBounds();
  const recortar = (v, lim) => Math.max(-lim, Math.min(lim, v));
  fijarZona({
    sur: recortar(b.getSouth(), 90),
    oeste: recortar(b.getWest(), 180),
    norte: recortar(b.getNorth(), 90),
    este: recortar(b.getEast(), 180),
  });
});
$quitarZona.addEventListener("click", () => fijarZona(null));

$ubicacionDemo.addEventListener("click", () => fijarUbicacion(-12.1190, -77.0290));
$limpiarUbicacion.addEventListener("click", () => {
  estado.ubicacion = null;
  estado.sucursalesKnn = [];
  pintarResumenEspacial();
  actualizarControlEspacial();
  actualizarCapaUsuario();
  recargarVistaActual();
});
$radio.addEventListener("change", () => {
  if (estado.ubicacion) fijarUbicacion(estado.ubicacion.lat, estado.ubicacion.lon);
});

$modosRec.addEventListener("click", (ev) => {
  const btn = ev.target.closest("button[data-modo]");
  if (!btn) return;
  estado.modoRec = btn.dataset.modo;
  for (const b of $modosRec.querySelectorAll("button")) {
    b.classList.toggle("activo", b === btn);
  }
  cargarRecomendaciones();
});

for (const slider of $pesosPanel.querySelectorAll("input[type='range']")) {
  slider.addEventListener("input", () => {
    const clave = slider.dataset.peso;
    estado.pesos[clave] = Number(slider.value);
    document.getElementById("val-" + clave).textContent = Number(slider.value).toFixed(2);
  });
  slider.addEventListener("change", cargarRecomendaciones);
}

$fusionRec.addEventListener("change", () => {
  estado.fusionRec = $fusionRec.value;
  cargarRecomendaciones();
});

actualizarControlEspacial();
Promise.all([cargarEstado(), cargarCategorias(), cargarSucursales()]).then(cargarCatalogo);
