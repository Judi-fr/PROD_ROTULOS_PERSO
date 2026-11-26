// Piezas de Reportes (2026-11-19): números destacados, columnas por mes y
// barras horizontales, con el mismo dibujo que "La semana" del Inicio
// (dashboard_week.js): SVG sin librerías, columnas finas con la punta
// redondeada, grilla tenue, el detalle de cada mes al pasar el mouse o con el
// teclado, leyenda con 2+ series y la misma información en una tabla plegada.
// Antes Reportes eran barras de <span> con style="width:N%" y tablas de meses
// en cero.
//
// Colores: una serie va en el verde de la app (--accent-500); dos, verde y azul
// (--info-500), el mismo par ya validado para daltonismo en el Inicio. Los
// textos nunca van en el color de la serie.

(function () {
  const SVG_NS = "http://www.w3.org/2000/svg";
  const HEIGHT = 190;
  const PAD = { top: 12, right: 8, bottom: 26, left: 34 };
  const BAR_MAX = 26;
  const BAR_GAP = 2;
  const RADIUS = 4;
  const TONES = ["accent", "info"];

  function svg(tag, attrs = {}) {
    const node = document.createElementNS(SVG_NS, tag);
    Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, value));
    return node;
  }

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  // Tope del eje en un número redondo: 1, 2, 5, 10, 20, 50...
  function niceMax(value) {
    if (value <= 4) return Math.max(value, 1);
    const power = 10 ** Math.floor(Math.log10(value));
    return [1, 2, 5, 10].find((candidate) => candidate * power >= value) * power;
  }

  function barPath(x, y, width, height) {
    const r = Math.min(RADIUS, width / 2, height);
    return `M${x},${y + height}V${y + r}Q${x},${y} ${x + r},${y}H${x + width - r}Q${x + width},${y} ${x + width},${y + r}V${y + height}Z`;
  }

  function formatNumber(value) {
    return Number(value || 0).toLocaleString("es-AR");
  }

  function emptyState(text) {
    const box = el("div", "report-empty");
    box.innerHTML = '<i class="ph ph-chart-bar" aria-hidden="true"></i>';
    box.appendChild(el("span", "", text));
    return box;
  }

  // --- Números destacados -------------------------------------------------
  // items: [{label, value, hint?, icon?, tone?: "alert"}]; value ya formateado
  // o un número.
  function kpis(container, items) {
    if (!container) return;
    container.replaceChildren(
      ...items.map((item) => {
        const box = el("div", `report-kpi${item.tone === "alert" ? " is-alert" : ""}`);
        const top = el("span", "report-kpi-top");
        if (item.icon) {
          const icon = el("span", "report-kpi-icon");
          icon.innerHTML = `<i class="ph ph-${item.icon}" aria-hidden="true"></i>`;
          top.appendChild(icon);
        }
        top.appendChild(el("span", "report-kpi-label", item.label));
        box.appendChild(top);
        box.appendChild(el("span", "report-kpi-value", typeof item.value === "number" ? formatNumber(item.value) : String(item.value)));
        if (item.hint) box.appendChild(el("span", "report-kpi-hint", item.hint));
        return box;
      })
    );
  }

  // --- Columnas por mes ---------------------------------------------------
  // spec: {points: [{label, long}], series: [{label, values}], description, empty}
  const drawn = new WeakMap();

  function columns(container, spec) {
    if (!container) return;
    const points = spec.points || [];
    const series = (spec.series || []).slice(0, TONES.length);
    const total = series.reduce((sum, serie) => sum + serie.values.reduce((a, b) => a + (Number(b) || 0), 0), 0);
    if (!points.length || !total) {
      container.replaceChildren(emptyState(spec.empty || "Sin movimiento en el período."));
      return;
    }

    const parts = [];
    if (series.length > 1) {
      const legend = el("ul", "report-legend");
      legend.setAttribute("aria-label", "Referencias");
      series.forEach((serie, index) => {
        const item = el("li");
        item.appendChild(el("i", `report-key is-${TONES[index]}`));
        item.appendChild(document.createTextNode(serie.label));
        legend.appendChild(item);
      });
      parts.push(legend);
    }
    const wrap = el("div", "report-chart-wrap");
    const chart = el("div", "report-chart");
    const tooltip = el("div", "report-tooltip");
    tooltip.setAttribute("role", "status");
    tooltip.hidden = true;
    wrap.append(chart, tooltip);
    parts.push(wrap);
    parts.push(table(points, series));
    container.replaceChildren(...parts);

    const draw = () => drawColumns(chart, tooltip, points, series, spec.description || "");
    draw();
    // Redibuja si cambia el ancho (otra pestaña, ventana más angosta).
    if (window.ResizeObserver) {
      const previous = drawn.get(container);
      if (previous) previous.disconnect();
      let lastWidth = chart.clientWidth;
      const observer = new ResizeObserver(() => {
        if (chart.clientWidth === lastWidth || !chart.isConnected) return;
        lastWidth = chart.clientWidth;
        draw();
      });
      observer.observe(chart);
      drawn.set(container, observer);
    }
  }

  function drawColumns(chart, tooltip, points, series, description) {
    const width = chart.clientWidth || 560;
    const top = niceMax(Math.max(...series.flatMap((serie) => serie.values.map((v) => Number(v) || 0))));
    const plotW = width - PAD.left - PAD.right;
    const plotH = HEIGHT - PAD.top - PAD.bottom;
    const band = plotW / points.length;
    const barW = Math.max(4, Math.min(BAR_MAX, (band * 0.6 - BAR_GAP * (series.length - 1)) / series.length));
    const groupW = barW * series.length + BAR_GAP * (series.length - 1);
    const y = (value) => PAD.top + plotH - (value / top) * plotH;

    const root = svg("svg", { width, height: HEIGHT, viewBox: `0 0 ${width} ${HEIGHT}`, role: "img" });
    root.setAttribute("aria-label", description);

    const ticks = top <= 1 ? [0, top] : [0, top / 2, top];
    ticks.forEach((tick) => {
      const ty = y(tick);
      root.appendChild(svg("line", { x1: PAD.left, x2: width - PAD.right, y1: ty, y2: ty, class: tick ? "report-gridline" : "report-base" }));
      const label = svg("text", { x: PAD.left - 6, y: ty + 4, class: "report-axis", "text-anchor": "end" });
      label.textContent = Number.isInteger(tick) ? formatNumber(tick) : "";
      root.appendChild(label);
    });

    // Con muchos meses en poco ancho, se rotula uno de cada dos.
    const every = band < 44 ? 2 : 1;
    points.forEach((point, index) => {
      const center = PAD.left + band * index + band / 2;
      const group = svg("g", { class: "report-point", tabindex: "0" });
      group.setAttribute("aria-label", `${point.long}: ${series.map((serie) => `${serie.label.toLowerCase()} ${serie.values[index] || 0}`).join(", ")}`);
      group.appendChild(svg("rect", { x: center - band / 2, y: PAD.top, width: band, height: plotH, class: "report-hit" }));
      series.forEach((serie, serieIndex) => {
        const value = Number(serie.values[index]) || 0;
        if (!value) return;
        const x = center - groupW / 2 + serieIndex * (barW + BAR_GAP);
        group.appendChild(svg("path", { d: barPath(x, y(value), barW, y(0) - y(value)), class: `report-bar is-${TONES[serieIndex]}` }));
      });
      if ((points.length - 1 - index) % every === 0) {
        const label = svg("text", { x: center, y: HEIGHT - 8, class: "report-axis", "text-anchor": "middle" });
        label.textContent = point.label;
        group.appendChild(label);
      }
      const show = () => showTooltip(chart, tooltip, point, series, index, center, band);
      group.addEventListener("pointerenter", show);
      group.addEventListener("focus", show);
      group.addEventListener("pointerleave", () => (tooltip.hidden = true));
      group.addEventListener("blur", () => (tooltip.hidden = true));
      root.appendChild(group);
    });
    chart.replaceChildren(root);
  }

  function showTooltip(chart, tooltip, point, series, index, center, band) {
    const rows = series.map((serie, serieIndex) => {
      const row = el("span", "report-tip-row");
      row.appendChild(el("i", `report-key is-${TONES[serieIndex]}`));
      row.appendChild(el("b", "", formatNumber(serie.values[index])));
      row.appendChild(document.createTextNode(` ${serie.label.toLowerCase()}`));
      return row;
    });
    tooltip.replaceChildren(el("strong", "", point.long), ...rows);
    tooltip.hidden = false;
    const toRight = center < chart.clientWidth / 2;
    const left = toRight ? center + band / 2 + 4 : center - band / 2 - 4 - tooltip.offsetWidth;
    tooltip.style.left = `${Math.max(0, Math.min(left, chart.clientWidth - tooltip.offsetWidth))}px`;
  }

  function table(points, series) {
    const details = el("details", "report-table");
    details.appendChild(el("summary", "", "Ver como tabla"));
    const tableEl = el("table");
    const head = el("tr");
    head.appendChild(Object.assign(el("th", "", "Mes"), { scope: "col" }));
    series.forEach((serie) => head.appendChild(Object.assign(el("th", "", serie.label), { scope: "col" })));
    const thead = el("thead");
    thead.appendChild(head);
    const tbody = el("tbody");
    points.forEach((point, index) => {
      const row = el("tr");
      row.appendChild(el("td", "", point.long));
      series.forEach((serie) => row.appendChild(el("td", "", formatNumber(serie.values[index]))));
      tbody.appendChild(row);
    });
    tableEl.append(thead, tbody);
    details.appendChild(tableEl);
    return details;
  }

  // --- Barras horizontales --------------------------------------------------
  // items: [{label, count}]; el valor va escrito al lado de cada barra.
  function bars(container, items, { empty = "Sin datos todavía.", max = 10 } = {}) {
    if (!container) return;
    const rows = (items || []).filter((item) => Number(item.count) > 0).slice(0, max);
    if (!rows.length) {
      container.replaceChildren(emptyState(empty));
      return;
    }
    const top = Math.max(...rows.map((item) => Number(item.count)));
    const list = el("ul", "report-bars");
    rows.forEach((item) => {
      const row = el("li", "report-bar-row");
      const label = el("span", "report-bar-label", item.label);
      label.title = item.label;
      const track = el("span", "report-bar-track");
      const fill = el("span", "report-bar-fill");
      fill.style.setProperty("--w", `${Math.max(2, (Number(item.count) / top) * 100)}%`);
      track.appendChild(fill);
      row.append(label, track, el("span", "report-bar-value", formatNumber(item.count)));
      row.title = `${item.label}: ${formatNumber(item.count)}`;
      list.appendChild(row);
    });
    container.replaceChildren(list);
  }

  // --- Tabla simple ---------------------------------------------------------
  // columns: [{label, value(row), numeric?}]
  function simpleTable(container, columnsSpec, rows, { empty = "Sin datos todavía." } = {}) {
    if (!container) return;
    if (!rows || !rows.length) {
      container.replaceChildren(emptyState(empty));
      return;
    }
    const tableEl = el("table", "report-data");
    const head = el("tr");
    columnsSpec.forEach((col) => head.appendChild(Object.assign(el("th", col.numeric ? "is-num" : "", col.label), { scope: "col" })));
    const thead = el("thead");
    thead.appendChild(head);
    const tbody = el("tbody");
    rows.forEach((row) => {
      const tr = el("tr");
      columnsSpec.forEach((col) => {
        const value = col.value(row);
        tr.appendChild(el("td", col.numeric ? "is-num" : "", value === null || value === undefined ? "—" : String(value)));
      });
      tbody.appendChild(tr);
    });
    tableEl.append(thead, tbody);
    const scroll = el("div", "report-table-scroll");
    scroll.appendChild(tableEl);
    container.replaceChildren(scroll);
  }

  window.ReportCharts = { kpis, columns, bars, table: simpleTable, formatNumber };
})();
