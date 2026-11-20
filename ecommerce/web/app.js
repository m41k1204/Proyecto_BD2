import { icono, estrellas, hidratarIconos } from "./iconos.js";

const estado = {
  pagina: 1,
  limite: 12,
  modoRec: "hibrido",
  fusionRec: "score",
  modeloVisual: "sift256",
  itemActivo: null,
  pesos: { cocompra: 0.80, texto: 0.15, metadata: 0.0, visual: 0.05, espacial: 0.10 },
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
  // null = catálogo; {tipo: "texto", q, modo} o {tipo: "imagen", archivo}. Sobrevive a filtros y páginas.
  busqueda: null,
};

const NOMBRES_SENAL = {
  cocompra: "Co-compra",
  visual: "Imagen (SIFT k=256)", // se reescribe al cambiar #modelo-visual
  texto: "Texto (BM25)",
  bm25: "BM25",
  tf_idf: "TF-IDF",
  metadata: "Metadata",
  espacial: "Cercanía",
};

const $estado = document.getElementById("estado");
const $formBusqueda = document.getElementById("form-busqueda");
const $consulta = document.getElementById("consulta");
const $modoBusqueda = document.getElementById("modo-busqueda");
const $archivoImagen = document.getElementById("archivo-imagen");
const $limpiarBusqueda = document.getElementById("limpiar-busqueda");
const $consultaFoto = document.getElementById("consulta-foto");
const $fotoConsulta = document.getElementById("foto-consulta");
const $infoFoto = document.getElementById("info-foto");
const $categoria = document.getElementById("categoria");
const $precioMin = document.getElementById("precio-min");
const $precioMax = document.getElementById("precio-max");
const $orden = document.getElementById("orden");
const $botonFoto = document.getElementById("boton-foto");
const $textoUbicacion = document.getElementById("texto-ubicacion");
const $tituloRec = document.getElementById("titulo-rec");
const $preferencias = document.getElementById("preferencias");
const $botonPreferencias = document.getElementById("boton-preferencias");
const $resumenEstrategia = document.getElementById("resumen-estrategia");
const $cerrarDetalle = document.getElementById("cerrar-detalle");
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
const $modeloVisual = document.getElementById("modelo-visual");
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

// Precio de marketplace: centavos en superíndice, como en las vitrinas de Amazon o Mercado Libre.
function nodoPrecio(precio, clase = "precio") {
  const nodo = el("span", clase);
  if (precio === null || precio === undefined) {
    nodo.textContent = "Sin precio";
    nodo.classList.add("sin-precio");
    return nodo;
  }
  const [enteros, centavos] = Number(precio).toFixed(2).split(".");
  nodo.setAttribute("aria-label", "$" + enteros + "." + centavos);
  nodo.append(el("span", "moneda", "$"), enteros, el("sup", "", centavos));
  return nodo;
}

function nodoRating(rating) {
  const nodo = el("span", "rating");
  if (rating === null || rating === undefined) {
    nodo.appendChild(el("span", "tenue", "Sin valoraciones"));
    return nodo;
  }
  nodo.appendChild(el("span", "rating-numero", Number(rating).toFixed(1)));
  nodo.appendChild(estrellas(rating));
  return nodo;
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
  const boton = el("button", "enlace-tienda");
  boton.type = "button";
  boton.title = `Ver ${suc.nombre} en el mapa`;
  boton.append(icono("pin", 15), el("span", "", suc.distrito));
  if (p.distancia_m !== null && p.distancia_m !== undefined) {
    boton.appendChild(el("span", "distancia", formatoDistancia(p.distancia_m)));
  }
  boton.addEventListener("click", (ev) => {
    ev.stopPropagation();
    verTiendaEnMapa(suc.id);
  });
  return boton;
}

function textoPaso(paso) {
  let texto = paso.method ? `${paso.op} (${paso.method})` : paso.op;
  if (paso.detail) texto += `: ${paso.detail}`;
  if (paso.rows !== null && paso.rows !== undefined) texto += `, ${paso.rows} filas`;
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
    `SQL, planes y tiempos del motor: ${consultas.length} consultas, ${msMotor.toFixed(1)} ms en el motor`;
  consultas.forEach((c, i) => {
    const item = el("div", "consulta-sql");
    const tiempo = c.ms_motor !== null && c.ms_motor !== undefined ? `${c.ms_motor} ms en el motor, ` : "";
    item.appendChild(el("div", "tenue", `Consulta ${i + 1}: ${tiempo}${c.ms_total} ms en total`));
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
    const chip = el("span", "tiempo-chip");
    chip.append(el("span", "", clave.replace(/_ms$/, "")), el("strong", "", `${ms} ms`));
    contenedor.appendChild(chip);
  }
}


// SIMILARITY_SCORE() con METRIC=cosine es 1 - distancia coseno: 1 = misma imagen.
function barraSimilitud(puntaje) {
  const valor = Math.max(0, Math.min(1, Number(puntaje)));
  const fila = el("div", "similitud");
  const barra = el("div", "barra-similitud");
  const relleno = el("span");
  relleno.style.width = `${valor * 100}%`;
  barra.appendChild(relleno);
  barra.setAttribute("role", "img");
  barra.setAttribute("aria-label", `Similitud con tu foto: ${valor.toFixed(3)}`);
  fila.appendChild(el("span", "tenue", "Similitud"));
  fila.appendChild(barra);
  fila.appendChild(el("strong", "", valor.toFixed(3)));
  return fila;
}

function mostrarFotoConsulta(archivo) {
  if ($fotoConsulta.src) URL.revokeObjectURL($fotoConsulta.src);
  $fotoConsulta.removeAttribute("src");
  $consultaFoto.hidden = !archivo;
  if (!archivo) return;
  $fotoConsulta.src = URL.createObjectURL(archivo);
  $infoFoto.textContent = `${archivo.name}, comparada con ${$modeloVisual.selectedOptions[0].textContent}`;
}

function pintarGrilla(productos) {
  $grilla.replaceChildren();
  if (!productos.length) {
    const vacio = el("div", "vacio");
    vacio.appendChild(el("p", "", "No hay productos que coincidan."));
    vacio.appendChild(el("p", "tenue", "Prueba otras palabras, otra categoría, un rango de precio más amplio o quita la ubicación."));
    $grilla.appendChild(vacio);
    return;
  }
  const conSimilitud = estado.busqueda && estado.busqueda.tipo === "imagen";
  for (const p of productos) {
    const tarjeta = el("article", "tarjeta");
    tarjeta.dataset.id = String(p.id);
    if (estado.itemActivo === p.id) tarjeta.classList.add("seleccionada");
    const marco = el("div", "marco-imagen");
    marco.appendChild(imagenProducto(p.imagen, p.nombre));
    tarjeta.appendChild(marco);
    // El título es el control: Enter/Espacio y lectores de pantalla llegan al producto.
    const titulo = el("h3");
    const enlace = el("button", "titulo-producto", p.nombre);
    enlace.type = "button";
    titulo.appendChild(enlace);
    tarjeta.appendChild(titulo);
    tarjeta.appendChild(nodoRating(p.rating));
    tarjeta.appendChild(nodoPrecio(p.precio));
    if (p.marca) tarjeta.appendChild(el("span", "marca-producto", p.marca));
    if (p.sucursal) tarjeta.appendChild(botonTienda(p));
    if (conSimilitud && p.puntaje !== null && p.puntaje !== undefined) {
      tarjeta.appendChild(barraSimilitud(p.puntaje));
    }
    tarjeta.addEventListener("click", () => seleccionarProducto(p.id));
    $grilla.appendChild(tarjeta);
  }
}

async function cargarEstado() {
  try {
    const res = await fetch("/api/estado");
    const data = await res.json();
    if (!data.motor) {
      $estado.textContent = "Motor BD2 de la tienda apagado: inícialo con pnpm dev:backend-ecommerce (puerto 8001)";
      $estado.classList.add("mal");
      return;
    }
    $estado.classList.remove("mal");
    const miles = (n) => Number(n).toLocaleString("es-PE");
    $estado.textContent = `${miles(data.productos)} productos, ${miles(data.ordenes)} órdenes y ${miles(data.sucursales)} tiendas en el motor`;
    const cargados = new Set(data.modelos_visuales || []);
    for (const opt of $modeloVisual.options) {
      if (opt.value === "sift256") continue;
      opt.disabled = !cargados.has(opt.value);
      opt.title = opt.disabled ? "No está cargado: corre ingesta.py --visuales " + opt.value : "";
    }
  } catch {
    $estado.textContent = "Sin conexión con el servidor de la tienda";
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
    ? "Peso de la cercanía (k-NN del R-Tree)"
    : "Elige tu ubicación para activar";
  $ordenCercania.disabled = !activa;
  if (!activa && $orden.value === "cercania") $orden.value = "rating";
  $quitarZona.hidden = !estado.zona;
}

function construirPopupTienda(sucursal, { topItems, esSemilla, knnSuc }) {
  const cont = el("div", "popup-tienda");
  cont.appendChild(el("strong", "", `${sucursal.nombre} (${sucursal.distrito})`));
  if (knnSuc) {
    cont.appendChild(el("div", "tenue", `Entre las más cercanas (k-NN del R-Tree), a ${formatoDistancia(knnSuc.distancia_m)}`));
  } else if (estado.ubicacion && sucursal.lat !== null && sucursal.lon !== null) {
    const dist = distanciaMetros(estado.ubicacion.lat, estado.ubicacion.lon, sucursal.lat, sucursal.lon);
    cont.appendChild(el("div", "tenue", `A ${formatoDistancia(dist)}`));
  }
  if (esSemilla) {
    cont.appendChild(el("div", "tenue", "Aquí está el producto elegido"));
  }
  if (topItems.length) {
    const lista = el("div");
    for (const item of topItems) {
      const boton = el("button", "popup-item", `${item.pos}. ${item.nombre}`);
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
        fillColor: "#2e7d32",
        color: esSemilla ? "#e08600" : "#1b5e20",
        radius: 9 + Math.min(topItems.length, 5),
        weight: 3,
        fillOpacity: 0.9,
      });
      marcador.bringToFront();
    } else if (esSemilla) {
      marcador.setStyle({
        fillColor: "#e08600",
        color: "#8d4e00",
        radius: 10,
        weight: 2.5,
        fillOpacity: 0.9,
      });
      marcador.bringToFront();
    } else if (knnSuc) {
      marcador.setStyle({
        fillColor: "#0f9d8a",
        color: "#115e59",
        radius: 8,
        weight: 2,
        fillOpacity: 0.85,
      });
    } else {
      marcador.setStyle({
        fillColor: "#a3a8b0",
        color: "#5f646c",
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
      document.getElementById("mapa").textContent = "El mapa necesita internet. Sin él, pulsa Usar Miraflores para probar el filtro por cercanía.";
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
    estado.marcadorUsuario = L.circleMarker(punto, { radius: 8, color: "#fff", weight: 2.5, fillColor: "#D42A2F", fillOpacity: 1, interactive: false }).addTo(estado.mapa);
    if ($radio.value) {
      estado.circuloRadio = L.circle(punto, { radius: Number($radio.value), color: "#D42A2F", weight: 1.5, fillOpacity: 0.06, interactive: false }).addTo(estado.mapa);
    }
  }
  if (estado.rectZona) {
    estado.mapa.removeLayer(estado.rectZona);
    estado.rectZona = null;
  }
  if (estado.zona) {
    const { sur, oeste, norte, este } = estado.zona;
    estado.rectZona = L.rectangle([[sur, oeste], [norte, este]], {
      color: "#1558C0", weight: 2, dashArray: "6 4", fillOpacity: 0.05, interactive: false,
    }).addTo(estado.mapa);
  }
  actualizarMarcadoresTiendas();
}

function abrirPanelMapa() {
  $panelMapa.hidden = false;
  $toggleMapa.setAttribute("aria-expanded", "true");
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
    partes.push($radio.value ? `Tiendas a menos de ${Number($radio.value) / 1000} km` : "Todas las tiendas, sin límite de radio");
  }
  if (estado.zona) partes.push("solo en la zona filtrada del mapa");
  const hayFiltro = estado.zona || (estado.ubicacion && $radio.value);
  if (hayFiltro && enFiltro !== undefined) partes.push(`${enFiltro} tiendas dentro del filtro`);
  if (enKnn !== undefined) partes.push(`${enKnn} más cercanas usadas al recomendar`);
  $resumenEspacial.textContent = partes.join(", ");

  const $etiqueta = $toggleMapa.querySelector(".ubicacion-etiqueta");
  if (!estado.ubicacion) {
    $etiqueta.textContent = "Tiendas cerca de";
    $textoUbicacion.textContent = "Elegir ubicación";
  } else if ($radio.value) {
    $etiqueta.textContent = "Tiendas a menos de";
    $textoUbicacion.textContent = `${Number($radio.value) / 1000} km de ti`;
  } else {
    $etiqueta.textContent = "Tiendas cerca de";
    $textoUbicacion.textContent = "tu ubicación";
  }
}

function fijarUbicacion(lat, lon) {
  estado.ubicacion = { lat, lon };
  pintarResumenEspacial();
  actualizarControlEspacial();
  actualizarCapaUsuario();
  recargarVistaActual();
}

// Igual a MAX_K_BUSQUEDA del servidor.
const MAX_K_BUSQUEDA = 100;

// Las búsquedas por similitud no tienen OFFSET: se piden los primeros pagina*limite+1 y se corta la página.
function kBusqueda() {
  return Math.min(estado.pagina * estado.limite + 1, MAX_K_BUSQUEDA);
}

function paginaDeBusqueda(productos) {
  const desde = (estado.pagina - 1) * estado.limite;
  return {
    productos: productos.slice(desde, desde + estado.limite),
    hayMas: productos.length > desde + estado.limite,
  };
}

function prepararVista(titulo) {
  $limpiarBusqueda.hidden = !estado.busqueda;
  $aviso.hidden = true;
  $tituloCatalogo.textContent = titulo;
  // Una búsqueda ya viene ordenada por relevancia (BM25, TF-IDF o similitud de imagen).
  $orden.disabled = Boolean(estado.busqueda);
  $orden.title = estado.busqueda ? "Los resultados de una búsqueda se ordenan por relevancia" : "";
}

function mostrarAviso(texto) {
  $aviso.textContent = texto;
  $aviso.hidden = false;
}

function pintarPaginacion(pagina, hayMas) {
  $paginacion.hidden = pagina <= 1 && !hayMas;
  $pagInfo.textContent = `Página ${pagina}`;
  $pagAnterior.disabled = pagina <= 1;
  $pagSiguiente.disabled = !hayMas;
}

async function cargarCatalogo() {
  const pedido = ++estado.pedidoGrilla;
  mostrarFotoConsulta(null);
  prepararVista("Catálogo");
  $tiemposBusqueda.replaceChildren();

  const params = paramsFiltros();
  params.set("orden", $orden.value);
  params.set("limite", String(estado.limite));
  params.set("pagina", String(estado.pagina));

  const res = await fetch("/api/productos?" + params.toString());
  const data = await res.json();
  if (pedido !== estado.pedidoGrilla) return;
  if (!res.ok) {
    mostrarAviso(data.detail || "No se pudo cargar el catálogo. Revisa que el motor BD2 esté encendido.");
    return;
  }
  pintarGrilla(data.productos);
  pintarConsultas($sqlCatalogo, data.consultas);
  if (!estado.itemActivo) pintarResumenEspacial((data.sucursales_en_radio || []).length);
  pintarPaginacion(data.pagina, data.hay_mas);
}

async function buscarTexto() {
  const { q, modo } = estado.busqueda;
  const pedido = ++estado.pedidoGrilla;
  mostrarFotoConsulta(null);
  prepararVista(`Resultados para "${q}"`);

  const params = paramsFiltros();
  params.set("q", q);
  params.set("modo", modo);
  params.set("k", String(kBusqueda()));

  const res = await fetch("/api/buscar?" + params.toString());
  const data = await res.json();
  if (pedido !== estado.pedidoGrilla) return;
  if (!res.ok) {
    mostrarAviso(data.detail || "La búsqueda falló. Revisa que el motor BD2 esté encendido.");
    return;
  }
  if (data.aviso) mostrarAviso(data.aviso);
  const { productos, hayMas } = paginaDeBusqueda(data.productos);
  pintarTiempos($tiemposBusqueda, data.tiempos);
  pintarGrilla(productos);
  pintarConsultas($sqlCatalogo, data.consultas);
  pintarPaginacion(estado.pagina, hayMas);
}

async function buscarPorArchivo() {
  const { archivo } = estado.busqueda;
  const pedido = ++estado.pedidoGrilla;
  mostrarFotoConsulta(archivo);
  prepararVista("Parecidos a tu foto");

  const form = new FormData();
  form.append("archivo", archivo);
  form.append("k", String(kBusqueda()));
  form.append("visual", estado.modeloVisual);
  for (const [clave, valor] of paramsFiltros()) form.append(clave, valor);

  const res = await fetch("/api/buscar/imagen", { method: "POST", body: form });
  const data = await res.json();
  if (pedido !== estado.pedidoGrilla) return;
  if (!res.ok) {
    estado.busqueda = null;
    mostrarFotoConsulta(null);
    prepararVista("Catálogo");
    mostrarAviso(data.detail || "No se pudo leer la imagen. Prueba con un JPG o PNG de menos de 10 MB.");
    return;
  }
  const { productos, hayMas } = paginaDeBusqueda(data.productos);
  pintarTiempos($tiemposBusqueda, data.tiempos);
  pintarGrilla(productos);
  pintarConsultas($sqlCatalogo, data.consultas);
  pintarPaginacion(estado.pagina, hayMas);
}

function cargarVista() {
  if (!estado.busqueda) return cargarCatalogo();
  return estado.busqueda.tipo === "texto" ? buscarTexto() : buscarPorArchivo();
}

function pintarSemilla(p) {
  $semilla.replaceChildren();
  const marco = el("div", "marco-imagen");
  marco.appendChild(imagenProducto(p.imagen, p.nombre));
  const info = el("div", "semilla-info");
  info.appendChild(el("h2", "", p.nombre));
  if (p.marca) info.appendChild(el("span", "marca-producto", p.marca));
  info.appendChild(nodoRating(p.rating));
  info.appendChild(nodoPrecio(p.precio, "precio precio-grande"));
  const ficha = el("dl", "ficha");
  const agregar = (etiqueta, valor) => {
    const fila = el("div");
    fila.appendChild(el("dt", "", etiqueta));
    const dd = el("dd");
    dd.append(valor);
    fila.appendChild(dd);
    ficha.appendChild(fila);
  };
  if (p.categoria) agregar("Categoría", p.categoria);
  if (p.sucursal) agregar("Tienda", botonTienda(p));
  info.appendChild(ficha);
  $semilla.append(marco, info);
  if (p.descripcion) $semilla.appendChild(el("p", "descripcion", p.descripcion));
}

const ORDEN_SENALES = ["cocompra", "texto", "metadata", "visual", "espacial"];

const TITULOS_REC = {
  hibrido: "Recomendados para este producto",
  cocompra: "Quienes compraron esto también compraron",
  visual: "Se ven parecidos",
  texto: "Con una descripción parecida",
  metadata: "Misma categoría y precio parecido",
  espacial: "En tiendas cerca de ti",
};

function leyendaAportes(items) {
  const presentes = ORDEN_SENALES.filter((s) => items.some((i) => i.aportes && i.aportes[s]));
  const leyenda = el("div", "leyenda-aportes");
  leyenda.appendChild(el("span", "tenue", "La franja de color muestra qué pesó en cada recomendación:"));
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
    $listaRec.appendChild(
      el("p", "vacio", "Ningún producto cumple los filtros activos. Quita la categoría o el rango de precio para ver más.")
    );
    return;
  }
  const conAportes = items.some((i) => i.aportes);
  const maxPuntaje = Math.max(...items.map((i) => Number(i.puntaje) || 0)) || 1;
  if (conAportes) $listaRec.appendChild(leyendaAportes(items));
  for (const item of items) {
    const fila = el("article", "rec-item");
    const marco = el("div", "marco-imagen");
    marco.appendChild(imagenProducto(item.imagen, item.nombre));
    fila.appendChild(marco);
    const cuerpo = el("div", "rec-cuerpo");
    const titulo = el("h3");
    const enlace = el("button", "titulo-producto", item.nombre);
    enlace.type = "button";
    titulo.appendChild(enlace);
    cuerpo.appendChild(titulo);
    const linea = el("div", "rec-linea");
    linea.append(nodoPrecio(item.precio), nodoRating(item.rating));
    cuerpo.appendChild(linea);
    if (item.cocompras) {
      cuerpo.appendChild(el("span", "tenue", `Comprado junto ${item.cocompras} ${item.cocompras === 1 ? "vez" : "veces"}`));
    }
    if (item.sucursal) cuerpo.appendChild(botonTienda(item));
    fila.appendChild(cuerpo);
    if (item.aportes) fila.appendChild(barraAportes(item, maxPuntaje));
    fila.addEventListener("click", () => seleccionarProducto(item.id));
    $listaRec.appendChild(fila);
  }
}

const $vistaDetalle = document.getElementById("vista-detalle");
const pantallaAngosta = window.matchMedia("(max-width: 960px)");

async function seleccionarProducto(itemId) {
  estado.itemActivo = itemId;
  for (const tarjeta of $grilla.querySelectorAll(".tarjeta")) {
    tarjeta.classList.toggle("seleccionada", tarjeta.dataset.id === String(itemId));
  }
  // En pantallas angostas el detalle queda debajo de la grilla.
  if (pantallaAngosta.matches) $vistaDetalle.scrollIntoView({ block: "start" });
  await cargarRecomendaciones();
}

function deseleccionarProducto() {
  if (!estado.itemActivo) return;
  const anterior = $grilla.querySelector(".tarjeta.seleccionada .titulo-producto");
  estado.itemActivo = null;
  estado.pedidoRec++; // descarta una respuesta de recomendaciones que siga en camino
  estado.semillaActual = null;
  estado.recomendacionesActuales = [];
  estado.sucursalesKnn = [];
  for (const tarjeta of $grilla.querySelectorAll(".tarjeta.seleccionada")) tarjeta.classList.remove("seleccionada");
  $detalleContenido.hidden = true;
  $detalleVacio.hidden = false;
  pintarResumenEspacial();
  actualizarMarcadoresTiendas();
  if (anterior) anterior.focus();
}

async function cargarRecomendaciones() {
  if (!estado.itemActivo) return;
  // Cada pedido invalida a los anteriores: una respuesta lenta no pisa a una más nueva
  // (otro producto, otros pesos, otra zona…).
  const pedido = ++estado.pedidoRec;
  $detalleVacio.hidden = true;
  $detalleContenido.hidden = false;
  $tituloRec.textContent = TITULOS_REC[estado.modoRec];
  if (estado.modoRec === "espacial" && !estado.ubicacion) {
    abrirPanelMapa();
    $tiemposRec.replaceChildren();
    pintarConsultas($sqlRec, []);
    estado.recomendacionesActuales = [];
    estado.sucursalesKnn = [];
    actualizarMarcadoresTiendas();
    $listaRec.replaceChildren(
      el("p", "vacio", "Elige tu ubicación en el mapa, o pulsa Usar Miraflores, para ver productos de las tiendas más cercanas.")
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
  params.set("visual", estado.modeloVisual);
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
    $listaRec.replaceChildren(el("p", "vacio", data.detail || "No se pudieron calcular las recomendaciones. Revisa que el motor BD2 esté encendido."));
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

// Un filtro nuevo vuelve a la primera página de lo que se esté viendo (catálogo o búsqueda).
function recargarVistaActual() {
  estado.pagina = 1;
  cargarVista();
  if (estado.itemActivo) cargarRecomendaciones();
}

function irAPagina(pagina) {
  estado.pagina = pagina;
  cargarVista();
  $tituloCatalogo.scrollIntoView({ block: "nearest" });
}

$formBusqueda.addEventListener("submit", (ev) => {
  ev.preventDefault();
  const q = $consulta.value.trim();
  estado.busqueda = q ? { tipo: "texto", q, modo: $modoBusqueda.value } : null;
  estado.pagina = 1;
  cargarVista();
});

$modoBusqueda.addEventListener("change", () => {
  if (estado.busqueda && estado.busqueda.tipo === "texto") {
    estado.busqueda.modo = $modoBusqueda.value;
    recargarVistaActual();
  }
});

$limpiarBusqueda.addEventListener("click", () => {
  $consulta.value = "";
  estado.busqueda = null;
  recargarVistaActual();
});

$botonFoto.addEventListener("click", () => $archivoImagen.click());
$archivoImagen.addEventListener("change", () => {
  if ($archivoImagen.files && $archivoImagen.files[0]) {
    estado.busqueda = { tipo: "imagen", archivo: $archivoImagen.files[0] };
    $consulta.value = "";
    $archivoImagen.value = "";
    recargarVistaActual();
  }
});

for (const filtro of [$categoria, $precioMin, $precioMax]) {
  filtro.addEventListener("change", recargarVistaActual);
}
$orden.addEventListener("change", () => irAPagina(1));

$pagAnterior.addEventListener("click", () => {
  if (estado.pagina > 1) irAPagina(estado.pagina - 1);
});
$pagSiguiente.addEventListener("click", () => irAPagina(estado.pagina + 1));

$toggleMapa.addEventListener("click", () => {
  if ($panelMapa.hidden) {
    abrirPanelMapa();
  } else {
    $panelMapa.hidden = true;
    $toggleMapa.setAttribute("aria-expanded", "false");
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
    b.setAttribute("aria-checked", String(b === btn));
  }
  $pesosPanel.hidden = estado.modoRec !== "hibrido";
  $resumenEstrategia.textContent = btn.textContent;
  cargarRecomendaciones();
});

$cerrarDetalle.addEventListener("click", deseleccionarProducto);

document.addEventListener("keydown", (ev) => {
  if (ev.key !== "Escape" || ev.defaultPrevented) return;
  // Con las preferencias abiertas, Esc solo las cierra (lo hace el navegador por ser popover).
  if ($preferencias.matches(":popover-open")) return;
  // En el buscador, Esc borra el texto; no debe cerrar además el producto.
  if (ev.target.matches("input[type='search']")) return;
  deseleccionarProducto();
});

// El popover vive en la capa superior (encima del mapa); se ancla bajo el engranaje de la banda.
$preferencias.addEventListener("beforetoggle", (ev) => {
  if (ev.newState !== "open") return;
  const caja = $botonPreferencias.getBoundingClientRect();
  $preferencias.style.top = `${caja.bottom + 8}px`;
  $preferencias.style.right = `${Math.max(8, window.innerWidth - caja.right)}px`;
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

$modeloVisual.addEventListener("change", () => {
  estado.modeloVisual = $modeloVisual.value;
  NOMBRES_SENAL.visual = `Imagen (${$modeloVisual.selectedOptions[0].textContent})`;
  if (estado.busqueda && estado.busqueda.tipo === "imagen") recargarVistaActual();
  else if (estado.itemActivo) cargarRecomendaciones();
});

hidratarIconos();
actualizarControlEspacial();
Promise.all([cargarEstado(), cargarCategorias(), cargarSucursales()]).then(cargarCatalogo);
