// Íconos de la tienda dibujados con d3 (sin emojis ni fuentes de íconos): trazo redondeado de 1.8
// sobre una grilla de 24, en currentColor para heredar el color de la identidad.
const TRAZOS = {
  buscar(p) {
    p.moveTo(17, 10.5);
    p.arc(10.5, 10.5, 6.5, 0, 2 * Math.PI);
    p.moveTo(15.4, 15.4);
    p.lineTo(20.5, 20.5);
  },
  camara(p) {
    p.moveTo(5.5, 7.5);
    p.lineTo(8.2, 7.5);
    p.lineTo(9.7, 4.8);
    p.lineTo(14.3, 4.8);
    p.lineTo(15.8, 7.5);
    p.lineTo(18.5, 7.5);
    p.arcTo(21, 7.5, 21, 10, 2.5);
    p.lineTo(21, 17.5);
    p.arcTo(21, 20, 18.5, 20, 2.5);
    p.lineTo(5.5, 20);
    p.arcTo(3, 20, 3, 17.5, 2.5);
    p.lineTo(3, 10);
    p.arcTo(3, 7.5, 5.5, 7.5, 2.5);
    p.closePath();
    p.moveTo(15.5, 13.5);
    p.arc(12, 13.5, 3.5, 0, 2 * Math.PI);
  },
  pin(p) {
    p.moveTo(12, 21.5);
    p.bezierCurveTo(8.5, 17.8, 5.5, 14, 5.5, 10);
    p.arc(12, 10, 6.5, Math.PI, 2 * Math.PI);
    p.bezierCurveTo(18.5, 14, 15.5, 17.8, 12, 21.5);
    p.closePath();
    p.moveTo(14.5, 10);
    p.arc(12, 10, 2.5, 0, 2 * Math.PI);
  },
  anterior(p) {
    p.moveTo(14.5, 5.5);
    p.lineTo(8, 12);
    p.lineTo(14.5, 18.5);
  },
  siguiente(p) {
    p.moveTo(9.5, 5.5);
    p.lineTo(16, 12);
    p.lineTo(9.5, 18.5);
  },
  cerrar(p) {
    p.moveTo(6.5, 6.5);
    p.lineTo(17.5, 17.5);
    p.moveTo(17.5, 6.5);
    p.lineTo(6.5, 17.5);
  },
  // Ocho dientes alrededor de un eje: base en r=7.2, punta en r=9.6.
  engranaje(p) {
    const dientes = 8;
    for (let i = 0; i < dientes; i++) {
      const a = (i * 2 * Math.PI) / dientes;
      const puntos = [[7.2, a - 0.4], [9.6, a - 0.2], [9.6, a + 0.2], [7.2, a + 0.4]];
      puntos.forEach(([r, t], k) => {
        const x = 12 + r * Math.cos(t);
        const y = 12 + r * Math.sin(t);
        if (i === 0 && k === 0) p.moveTo(x, y);
        else p.lineTo(x, y);
      });
    }
    p.closePath();
    p.moveTo(15, 12);
    p.arc(12, 12, 3, 0, 2 * Math.PI);
  },
};

export function icono(nombre, tam = 20) {
  const p = d3.path();
  TRAZOS[nombre](p);
  const svg = d3
    .create("svg")
    .attr("class", `icono icono-${nombre}`)
    .attr("viewBox", "0 0 24 24")
    .attr("width", tam)
    .attr("height", tam)
    .attr("aria-hidden", "true")
    .attr("focusable", "false");
  svg
    .append("path")
    .attr("d", p.toString())
    .attr("fill", "none")
    .attr("stroke", "currentColor")
    .attr("stroke-width", 1.8)
    .attr("stroke-linecap", "round")
    .attr("stroke-linejoin", "round");
  return svg.node();
}

let idsRecorte = 0;

// Cinco estrellas grises y, encima, las mismas recortadas al ancho del rating (admite medias).
export function estrellas(rating, tam = 14) {
  const valor = Math.max(0, Math.min(5, Number(rating) || 0));
  const paso = tam + 2;
  const forma = d3.symbol(d3.symbolStar, tam * tam * 0.27)();
  const id = `recorte-estrellas-${++idsRecorte}`;
  const svg = d3
    .create("svg")
    .attr("class", "estrellas")
    .attr("viewBox", `0 0 ${paso * 5} ${tam}`)
    .attr("width", paso * 5)
    .attr("height", tam)
    .attr("role", "img")
    .attr("aria-label", `${valor.toFixed(1)} de 5 estrellas`);
  svg
    .append("clipPath")
    .attr("id", id)
    .append("rect")
    .attr("width", (valor / 5) * paso * 5)
    .attr("height", tam);
  const capas = [
    { clase: "estrellas-fondo", recorte: null },
    { clase: "estrellas-llenas", recorte: `url(#${id})` },
  ];
  for (const capa of capas) {
    svg
      .append("g")
      .attr("class", capa.clase)
      .attr("clip-path", capa.recorte)
      .selectAll("path")
      .data(d3.range(5))
      .join("path")
      .attr("d", forma)
      .attr("transform", (i) => `translate(${i * paso + tam / 2},${tam * 0.52})`);
  }
  return svg.node();
}

// Reemplaza cada <span data-icono="nombre"> del HTML estático por su SVG.
export function hidratarIconos(raiz = document) {
  for (const hueco of raiz.querySelectorAll("[data-icono]")) {
    hueco.replaceWith(icono(hueco.dataset.icono, Number(hueco.dataset.tam) || 20));
  }
}
