// Resumen de la plataforma: el Inicio del admin (2026-11-19). Antes, un admin
// sin comercio entraba al panel y solo leía "No estás trabajando en ningún
// comercio". Los números salen de GET /admin/overview/ (cada bloque solo con
// el permiso de la pantalla a la que lleva) y el estado del sistema de la
// sonda pública /health/system/. Las piezas son las del Inicio del comerciante
// (dashboard.css, dashboard_week.js), así las dos pantallas se ven iguales.

(function () {
  const API = window.APP_CONFIG.API_BASE;
  const REFRESH_MS = 60 * 1000;

  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

  (function showToday() {
    const el = document.getElementById("overviewDate");
    if (el) el.textContent = new Date().toLocaleDateString("es-AR", { weekday: "long", day: "numeric", month: "long" });
  })();

  // Una línea chica con los 7 días, como en el Inicio del comerciante.
  function sparkline(values, label) {
    if (!Array.isArray(values) || values.length < 2 || !values.some(Boolean)) return "";
    const max = Math.max(...values) || 1;
    const step = 92 / (values.length - 1);
    const points = values.map((v, i) => `${(2 + i * step).toFixed(1)},${(27 - (v / max) * 24).toFixed(1)}`).join(" ");
    return `<svg class="today-spark" width="96" height="30" viewBox="0 0 96 30" role="img" aria-label="${escapeHtml(label)}: ${values.join(", ")}"><polyline points="${points}" fill="none" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"></polyline></svg>`;
  }

  function statCard(stat) {
    const link = document.createElement("a");
    const value = Number(stat.value) || 0;
    link.className = `today-stat${stat.alert ? " is-alert" : ""}${value ? "" : " is-zero"}`;
    link.href = stat.href;
    link.innerHTML = `<span class="today-stat-top">
        <span class="today-stat-icon"><i class="ph ph-${stat.icon}" aria-hidden="true"></i></span>
        <span class="today-stat-label">${escapeHtml(stat.label)}</span>
        <i class="ph ph-arrow-up-right today-stat-go" aria-hidden="true"></i>
      </span>
      <span class="today-stat-main">
        <span class="today-stat-value">${value}</span>
        ${sparkline(stat.line, stat.lineLabel)}
      </span>
      <span class="today-stat-hint">${escapeHtml(stat.hint)}</span>`;
    return link;
  }

  function renderStats(data) {
    const stats = [];
    if (data.people) {
      const p = data.people;
      stats.push({
        label: "Personas", icon: "users", value: p.total, href: "gestionuser.html",
        hint: `${plural(p.active_7d, "entró", "entraron")} en la semana · ${p.new_7d} ${p.new_7d === 1 ? "nueva" : "nuevas"}`,
      });
    }
    if (data.businesses) {
      const b = data.businesses;
      stats.push({
        label: "Comercios", icon: "storefront", value: b.open, href: "comercios.html",
        hint: `${b.new_7d} ${b.new_7d === 1 ? "nuevo" : "nuevos"} en la semana · ${plural(b.closed, "dado de baja", "dados de baja")}`,
      });
    }
    if (data.orders) {
      const o = data.orders;
      stats.push({
        label: "Pedidos hoy", icon: "package", value: o.today, href: "pedidos_admin.html",
        hint: `${o.last_7d} en los últimos 7 días`,
        line: (o.week || []).map((day) => Number(day.entered) || 0), lineLabel: "Pedidos que entraron por día",
      });
    }
    if (data.support) {
      const s = data.support;
      stats.push({
        label: "Soporte", icon: "chats", value: s.pending, href: "soporte_admin.html",
        hint: s.in_progress ? `Pendientes · ${s.in_progress} en curso` : "Mensajes pendientes", alert: s.pending > 0,
      });
    }
    document.getElementById("overviewStats").replaceChildren(...stats.map(statCard));
  }

  function todoItem({ icon, text, tone = "", action, href }) {
    const item = document.createElement("li");
    item.className = `todo-item${tone ? ` is-${tone}` : ""}`;
    item.innerHTML = `<i class="ph ph-${icon}" aria-hidden="true"></i>`;
    const body = document.createElement("span");
    body.className = "todo-body";
    const label = document.createElement("span");
    label.className = "todo-text";
    label.textContent = text;
    body.appendChild(label);
    item.appendChild(body);
    if (action && href) {
      const link = document.createElement("a");
      link.className = "btn btn-small btn-outline";
      link.href = href;
      link.textContent = action;
      item.appendChild(link);
    }
    return item;
  }

  // Lo que pide que alguien haga algo, lo más urgente primero. Sin nada, una
  // línea en verde: también es información.
  function renderTodo(data, health) {
    const items = [];
    if (health && health.status === "error") {
      items.push({ icon: "warning-octagon", tone: "danger", text: "Hay chequeos del sistema con error.", action: "Ver estado", href: "estado_sistema.html" });
    } else if (health && health.status === "warning") {
      items.push({ icon: "warning", tone: "warning", text: "Hay chequeos del sistema con advertencias.", action: "Ver estado", href: "estado_sistema.html" });
    }
    if (data.support && data.support.pending) {
      items.push({ icon: "chats", tone: "warning", text: `${plural(data.support.pending, "mensaje de soporte espera", "mensajes de soporte esperan")} respuesta.`, action: "Responder", href: "soporte_admin.html" });
    }
    if (data.orders && data.orders.stores_with_errors) {
      items.push({ icon: "storefront", tone: "warning", text: `${plural(data.orders.stores_with_errors, "tienda tiene", "tiendas tienen")} errores de conexión.` });
    }
    if (data.orders && data.orders.carrier_accounts_failing) {
      items.push({ icon: "truck", tone: "warning", text: `${plural(data.orders.carrier_accounts_failing, "cuenta de transportista quedó desactivada", "cuentas de transportista quedaron desactivadas")} por un error.` });
    }
    if (!items.length) {
      items.push({ icon: "check-circle", tone: "done", text: "Nada pendiente: el sistema anda y no hay mensajes sin responder." });
    }
    document.getElementById("todoList").replaceChildren(...items.map(todoItem));
    document.getElementById("todoBox").hidden = false;
  }

  async function systemHealth() {
    try {
      const response = await fetch(`${API}/health/system/`);
      return await response.json();
    } catch {
      return null;
    }
  }

  async function load() {
    try {
      const [response, health] = await Promise.all([window.Auth.apiFetch(`${API}/admin/overview/`), systemHealth()]);
      if (response.status === 403) {
        document.getElementById("overviewStats").replaceChildren();
        return; // applyPageAccess (utils.js) ya muestra "No tenés acceso".
      }
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      renderStats(data);
      if (data.orders && window.DashboardWeek) window.DashboardWeek.render(data.orders.week);
      renderTodo(data, health);
    } catch (err) {
      if (err && err.isSessionExpired) return;
      console.error("Resumen de la plataforma:", err);
      document.getElementById("overviewStats").replaceChildren();
      showMessage("No se pudo cargar el resumen. Probá de nuevo en un rato.");
    }
  }

  load();
  // Se actualiza solo cada minuto mientras la pestaña está a la vista.
  setInterval(() => {
    if (document.visibilityState === "visible") load();
  }, REFRESH_MS);
})();
