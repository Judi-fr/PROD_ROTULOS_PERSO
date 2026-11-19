// Inicio del comerciante (rediseño 2026-11-18, con barra lateral): los números
// del día, la semana, "Qué hacer ahora" y las estadísticas del período. La
// navegación es la barra lateral (app_sidebar.js, armada en el backend) y el
// buscador, Ctrl+K (command_palette.js). Sesión y apiFetch salen de assets/js/auth.js
// (window.Auth), compartido con el resto del frontend.

const API_BASE = `${window.APP_CONFIG.API_BASE}/auth`;
const DASHBOARD_URL = `${API_BASE}/users/me/dashboard/`;
const MY_INVITATIONS_URL = `${window.APP_CONFIG.API_BASE}/team/my-invitations/`;

const NOTICES_URL = `${window.APP_CONFIG.API_BASE}/notices/`;
const SUMMARY_URL = `${window.APP_CONFIG.API_BASE}/orders/summary/`;
const ONBOARDING_HIDDEN_KEY = "onboardingHidden";

const hasSession = () => window.Auth.hasSession();
const getCurrentUser = () => window.Auth.getCurrentUser();
const apiFetch = (url, options) => window.Auth.apiFetch(url, options);

function hasPermission(permission) {
  const permissions = getCurrentUser().permissions;
  return Array.isArray(permissions) && permissions.includes(permission);
}

function showMessage(text, type = "error") {
  const el = document.getElementById("dashboardMessage");
  if (!el) return;
  el.textContent = text;
  el.className = `dashboard-message ${type}`;
  el.style.display = "block";
}

// ---------------------------------------------------------------------------
// AVISOS: lo que se rompió en el comercio (apps/monitoring/notices.py). Los
// tres más nuevos acá; todos en notificaciones.html.
// ---------------------------------------------------------------------------
// ---------------------------------------------------------------------------
// BANDEJA DE TRABAJO: los números del día y "Qué hacer ahora". Junta el
// resumen de pedidos (GET /orders/summary/) con los avisos del comercio
// (GET /notices/): todo lo que espera al comerciante, en un solo lugar.
// ---------------------------------------------------------------------------
async function fetchJson(url) {
  try {
    const response = await apiFetch(url);
    return response.ok ? await response.json() : null;
  } catch (err) {
    if (!err || !err.isSessionExpired) console.error(`Error al leer ${url}:`, err);
    return null;
  }
}

const plural = (count, one, many) => `${count} ${count === 1 ? one : many}`;

// Cada número lleva a la pantalla donde se resuelve.
// Cada número abre su lista ya filtrada: "Para imprimir" con esos pedidos
// tildados (print_labels.js) y los demás como una vista de Mis pedidos
// (pedidos.js, ORDER_VIEWS), con los mismos filtros que cuenta el resumen.
const TO_PRINT_URL = "imprimir_rotulos.html?rotulo=sin_imprimir";
const TO_DISPATCH_URL = "pedidos.html?vista=para_despachar";
const ON_THE_WAY_URL = "pedidos.html?vista=en_camino";
const DELAYED_URL = "pedidos.html?vista=demorados";

// El panel se actualiza solo cada minuto mientras la pestaña está a la vista
// (y al volver a ella si pasó más de eso); un número que cambió se resalta.
const TODAY_REFRESH_MS = 60 * 1000;
let todayLoadedAt = 0;
let lastStats = null;

function renderTodayStats(summary, noticeCount) {
  const box = document.getElementById("todayStats");
  const problems = summary.shipment_problems + noticeCount;
  // La línea de cada número es lo que de verdad hay día por día (summary.week):
  // los pedidos que entraron y los que se despacharon en la semana.
  const week = Array.isArray(summary.week) ? summary.week : [];
  const entered = week.map((day) => Number(day.entered) || 0);
  const dispatched = week.map((day) => Number(day.dispatched) || 0);
  const sum = (values) => values.reduce((a, b) => a + b, 0);
  const stats = [
    { key: "to_print", label: "Para imprimir", hint: week.length ? `Entraron ${sum(entered)} en la semana` : "Sin rótulo todavía", icon: "printer", value: summary.to_print, href: TO_PRINT_URL, line: entered, lineLabel: "Pedidos que entraron por día" },
    { key: "to_dispatch", label: "Para despachar", hint: "Con el rótulo impreso", icon: "package", value: summary.to_dispatch, href: TO_DISPATCH_URL },
    { key: "on_the_way", label: "En camino", hint: week.length ? `Despachaste ${sum(dispatched)} en la semana` : "Despachados, sin entregar", icon: "truck", value: summary.on_the_way, href: ON_THE_WAY_URL, line: dispatched, lineLabel: "Pedidos despachados por día", tone: "info" },
    { key: "problems", label: "Con problemas", hint: "Envíos con novedad y avisos", icon: "warning-circle", value: problems, href: noticeCount ? "notificaciones.html" : "pedidos.html", alert: problems > 0 },
  ];
  const previous = lastStats;
  lastStats = Object.fromEntries(stats.map((stat) => [stat.key, Number(stat.value) || 0]));
  box.replaceChildren(
    ...stats.map((stat) => {
      const link = document.createElement("a");
      const changed = previous && previous[stat.key] !== lastStats[stat.key];
      const value = Number(stat.value) || 0;
      link.className = `today-stat${stat.alert ? " is-alert" : ""}${changed ? " is-changed" : ""}${value ? "" : " is-zero"}`;
      link.href = stat.href;
      link.innerHTML = `<span class="today-stat-top">
          <span class="today-stat-icon"><i class="ph ph-${stat.icon}" aria-hidden="true"></i></span>
          <span class="today-stat-label">${escapeHtml(stat.label)}</span>
          <i class="ph ph-arrow-up-right today-stat-go" aria-hidden="true"></i>
        </span>
        <span class="today-stat-main">
          <span class="today-stat-value">${value}</span>
          ${sparkline(stat.line, stat.lineLabel, stat.tone)}
        </span>
        <span class="today-stat-hint">${escapeHtml(stat.hint)}</span>`;
      return link;
    })
  );
  box.hidden = false;
}

// Una línea chica con los 7 días (sin ejes: el detalle está en "La semana").
function sparkline(values, label, tone) {
  if (!Array.isArray(values) || values.length < 2 || !values.some(Boolean)) return "";
  const max = Math.max(...values) || 1;
  const step = 92 / (values.length - 1);
  const points = values.map((v, i) => `${(2 + i * step).toFixed(1)},${(27 - (v / max) * 24).toFixed(1)}`).join(" ");
  return `<svg class="today-spark${tone ? ` is-${tone}` : ""}" width="96" height="30" viewBox="0 0 96 30" role="img" aria-label="${escapeHtml(label)}: ${values.join(", ")}"><polyline points="${points}" fill="none" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"></polyline></svg>`;
}

function todoItem({ icon, text, tone = "", action = "", href = "", primary = false, onHide = null, stores = [] }) {
  const item = document.createElement("li");
  item.className = `todo-item${tone ? ` is-${tone}` : ""}`;
  item.innerHTML = `<i class="ph ph-${icon}" aria-hidden="true"></i>`;
  const body = document.createElement("span");
  body.className = "todo-body";
  const label = document.createElement("span");
  label.className = "todo-text";
  label.textContent = text;
  body.appendChild(label);
  // Con varias tiendas, cuántos son de cada una; cada tienda abre su lista.
  if (stores.length) {
    const byStore = document.createElement("span");
    byStore.className = "todo-stores";
    stores.forEach((store) => {
      const link = document.createElement("a");
      link.href = store.href;
      link.textContent = `${store.name} ${store.count}`;
      byStore.appendChild(link);
    });
    body.appendChild(byStore);
  }
  item.appendChild(body);
  if (action && href) {
    const link = document.createElement("a");
    link.className = `btn btn-small ${primary ? "btn-primary" : "btn-outline"}`;
    link.href = href;
    link.textContent = action;
    item.appendChild(link);
  }
  if (onHide) {
    const hide = document.createElement("button");
    hide.type = "button";
    hide.className = "btn btn-small btn-ghost";
    hide.textContent = "Ocultar";
    hide.addEventListener("click", () => onHide(hide));
    item.appendChild(hide);
  }
  return item;
}

// "Ocultar" un aviso lo esconde para todo el comercio mientras dure el problema.
async function dismissNotice(notice, button) {
  button.disabled = true;
  try {
    const response = await apiFetch(`${NOTICES_URL}${notice.id}/dismiss/`, { method: "POST" });
    if (response.ok || response.status === 404) {
      await loadToday();
      return;
    }
    showMessage("No se pudo ocultar el aviso.");
  } catch (err) {
    if (!err || !err.isSessionExpired) showMessage("No se pudo ocultar el aviso.");
  }
  button.disabled = false;
}

async function loadToday() {
  const [summary, notices] = await Promise.all([
    hasPermission("orders.view") ? fetchJson(SUMMARY_URL) : null,
    fetchJson(NOTICES_URL),
  ]);
  const openNotices = Array.isArray(notices) ? notices : [];
  if (summary) {
    renderTodayStats(summary, openNotices.length);
    window.DashboardWeek.render(summary.week);
  }

  const items = [];
  // Primero lo demorado: es lo que el comprador ya está esperando.
  if (summary && summary.delayed) {
    items.push({
      icon: "clock-countdown",
      tone: "warning",
      text: `${plural(summary.delayed, "pedido espera", "pedidos esperan")} hace más de ${summary.delayed_days} días`,
      action: "Ver",
      href: DELAYED_URL,
    });
  }
  if (summary && summary.to_print) {
    items.push({
      icon: "printer",
      text: `${plural(summary.to_print, "pedido sin rótulo", "pedidos sin rótulo")}`,
      action: hasPermission("labels.batch") ? "Imprimir" : "",
      href: TO_PRINT_URL,
      stores: storeBreakdown(summary, "to_print", TO_PRINT_URL),
    });
  }
  if (summary && summary.to_dispatch) {
    items.push({
      icon: "truck",
      text: `${plural(summary.to_dispatch, "pedido con rótulo, listo", "pedidos con rótulo, listos")} para despachar`,
      action: hasPermission("orders.dispatch") ? "Despachar" : "",
      href: TO_DISPATCH_URL,
      stores: storeBreakdown(summary, "to_dispatch", TO_DISPATCH_URL),
    });
  }
  if (summary && summary.shipment_problems) {
    items.push({
      icon: "warning-circle",
      tone: "danger",
      text: `${plural(summary.shipment_problems, "envío con un problema", "envíos con un problema")} en el transportista`,
      action: "Ver",
      href: "pedidos.html",
    });
  }
  openNotices.forEach((notice) => {
    items.push({
      icon: "warning",
      tone: "warning",
      text: notice.title,
      action: notice.url ? "Revisar" : "",
      href: notice.url || "",
      onHide: (button) => dismissNotice(notice, button),
    });
  });
  // La primera acción es la principal; las demás, secundarias.
  const firstAction = items.find((item) => item.action);
  if (firstAction) firstAction.primary = true;

  const list = document.getElementById("todoList");
  list.replaceChildren(...items.map(todoItem));
  if (!items.length) {
    list.appendChild(todoItem({ icon: "check-circle", tone: "done", text: "Todo al día: no hay pedidos esperando ni avisos." }));
  }
  document.getElementById("todoBox").hidden = false;
  todayLoadedAt = Date.now();
  renderTodayUpdated();
}

// Desglose por tienda de un número del día (summary.by_store): solo cuando
// los pedidos vienen de más de una tienda, cada una con su lista (&tienda=).
function storeBreakdown(summary, key, url) {
  const rows = (summary.by_store || []).filter((row) => row[key] > 0);
  if (rows.length < 2) return [];
  return rows.map((row) => ({
    name: row.name,
    count: row[key],
    href: `${url}&tienda=${encodeURIComponent(row.store)}`,
  }));
}

function renderTodayUpdated() {
  const label = document.getElementById("todayUpdated");
  if (!label || !todayLoadedAt) return;
  const minutes = Math.floor((Date.now() - todayLoadedAt) / 60000);
  label.textContent = minutes < 1 ? "Actualizado recién" : `Actualizado hace ${minutes} min`;
}

async function refreshToday() {
  if (document.visibilityState !== "visible" || !todayLoadedAt) return;
  if (Date.now() - todayLoadedAt < TODAY_REFRESH_MS - 1000) return;
  try {
    await loadToday();
  } catch (err) {
    /* sin conexión un momento: se reintenta en la próxima vuelta */
  }
}

setInterval(refreshToday, TODAY_REFRESH_MS);
setInterval(renderTodayUpdated, 15 * 1000);
document.addEventListener("visibilitychange", refreshToday);

// ---------------------------------------------------------------------------
// ESTADÍSTICAS DEL PERÍODO (GET /orders/stats/?days=7|30|90): despacho en
// 24 h, transportistas y destinos. El backend manda solo los bloques que el
// miembro puede ver (allowed); sin ninguno responde 403 y la fila no aparece.
// El período elegido queda en este navegador (el mismo que Estadísticas).
// ---------------------------------------------------------------------------
const STATS_URL = `${window.APP_CONFIG.API_BASE}/orders/stats/`;
const STATS_DAYS_KEY = "statsDays";
const formatNumber = (value) => (value === null || value === undefined ? "—" : Number(value).toLocaleString("es-AR"));

function savedDays() {
  try {
    const days = Number(localStorage.getItem(STATS_DAYS_KEY));
    return [7, 30, 90].includes(days) ? days : 30;
  } catch (err) {
    return 30;
  }
}

function setupPeriodSwitch() {
  const box = document.getElementById("periodSwitch");
  if (!box || box.dataset.ready) return;
  box.dataset.ready = "1";
  box.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-days]");
    if (!button) return;
    const days = Number(button.dataset.days);
    try {
      localStorage.setItem(STATS_DAYS_KEY, String(days));
    } catch (err) {
      /* sin almacenamiento: vale para esta visita */
    }
    loadStats(days);
  });
  loadStats(savedDays());
}

async function loadStats(days) {
  document.querySelectorAll("#periodSwitch button").forEach((button) => {
    button.setAttribute("aria-pressed", String(Number(button.dataset.days) === days));
  });
  const data = await fetchJson(`${STATS_URL}?days=${days}`);
  const allowed = (data && data.allowed) || [];
  document.getElementById("statsRow").hidden = !allowed.length;
  document.getElementById("periodSwitch").hidden = !allowed.length;
  if (!allowed.length) return;
  const period = `Pedidos de los últimos ${days} días`;
  renderDispatch(allowed.includes("dispatch") ? data.dispatch : null, period);
  renderCarriers(allowed.includes("carriers") ? data.carriers : null, days);
  renderBuyers(allowed.includes("buyers") ? data.buyers : null, days);
}

function renderDispatch(stats, period) {
  const card = document.getElementById("dispatchCard");
  card.hidden = !stats;
  if (!stats) return;
  document.getElementById("dispatchSub").textContent = period;
  const gauge = document.getElementById("dispatchGauge");
  const foot = document.getElementById("dispatchFoot");
  if (!stats.shipped) {
    gauge.innerHTML = '<p class="stat-empty">Todavía no despachaste pedidos de este período.</p>';
    foot.replaceChildren();
    return;
  }
  const pct = Math.max(0, Math.min(100, Number(stats.within_24h) || 0));
  const arc = Math.PI * 80;
  gauge.innerHTML = `<svg width="200" height="112" viewBox="0 0 200 112" role="img" aria-label="${pct} % de los pedidos despachados en menos de 24 horas">
      <path class="gauge-track" d="M20 100 A80 80 0 0 1 180 100" fill="none" stroke-width="16" stroke-linecap="round"></path>
      ${pct > 0 ? `<path class="gauge-value" d="M20 100 A80 80 0 0 1 180 100" fill="none" stroke-width="16" stroke-linecap="round" stroke-dasharray="${((arc * pct) / 100).toFixed(1)} ${arc.toFixed(1)}"></path>` : ""}
    </svg><span class="gauge-number">${pct} %</span>`;
  foot.innerHTML = `<div><dt>Mediana</dt><dd>${formatNumber(stats.median_hours)} h</dd></div>
    <div><dt>En 48 h</dt><dd>${formatNumber(stats.within_48h)} %</dd></div>
    <div><dt>Esperando</dt><dd>${formatNumber(stats.waiting)}</dd></div>`;
}

function renderCarriers(rows, days) {
  const card = document.getElementById("carriersCard");
  card.hidden = !rows;
  if (!rows) return;
  document.getElementById("carriersSub").textContent = `Envíos de los últimos ${days} días`;
  const box = document.getElementById("carriersTable");
  if (!rows.length) {
    box.innerHTML = '<p class="stat-empty">Sin envíos en este período.</p>';
    return;
  }
  box.innerHTML = `<table class="carrier-table">
      <thead><tr><th scope="col">Transportista</th><th scope="col">Envíos</th><th scope="col">Entregados</th><th scope="col">Días a entregar</th><th scope="col">Con problemas</th></tr></thead>
      <tbody>${rows
        .map(
          (row) => `<tr>
          <th scope="row">${escapeHtml(row.carrier)}</th>
          <td>${formatNumber(row.shipped)}</td>
          <td>${formatNumber(row.delivered)}</td>
          <td>${row.avg_delivery_days === null ? "—" : formatNumber(row.avg_delivery_days)}</td>
          <td class="${row.problems ? "is-problem" : ""}">${formatNumber(row.problems)}</td>
        </tr>`
        )
        .join("")}</tbody></table>`;
}

function renderBuyers(buyers, days) {
  const card = document.getElementById("buyersCard");
  card.hidden = !buyers;
  if (!buyers) return;
  document.getElementById("buyersSub").textContent = `Pedidos por provincia, últimos ${days} días`;
  const list = document.getElementById("buyersBars");
  const states = (buyers.states || []).slice(0, 5);
  if (!states.length) {
    list.innerHTML = '<li class="stat-empty">Sin pedidos en este período.</li>';
    return;
  }
  const max = Math.max(...states.map((row) => row.count)) || 1;
  list.replaceChildren(
    ...states.map((row) => {
      const item = document.createElement("li");
      item.innerHTML = `<span class="state-name"></span><span class="state-count">${formatNumber(row.count)}</span>
        <span class="state-track" aria-hidden="true"><span style="width:${Math.round((row.count / max) * 100)}%"></span></span>`;
      item.querySelector(".state-name").textContent = row.name;
      return item;
    })
  );
}

// ---------------------------------------------------------------------------
// PRIMEROS PASOS: solo para el dueño de un comercio que no terminó de
// armarlo. "Ocultar" queda en este navegador (es una comodidad, no un dato).
// ---------------------------------------------------------------------------
function onboardingHidden() {
  try {
    return localStorage.getItem(ONBOARDING_HIDDEN_KEY) === "1";
  } catch (err) {
    return false;
  }
}

function renderOnboarding(onboarding) {
  const box = document.getElementById("onboardingBox");
  if (!box) return;
  if (!onboarding || onboarding.done >= onboarding.total || onboardingHidden()) {
    box.hidden = true;
    return;
  }
  box.innerHTML = "";
  const head = document.createElement("div");
  head.className = "onboarding-head";
  const title = document.createElement("h2");
  title.textContent = `Primeros pasos · ${onboarding.done} de ${onboarding.total}`;
  const hide = document.createElement("button");
  hide.type = "button";
  hide.className = "onboarding-hide";
  hide.textContent = "Ocultar";
  hide.addEventListener("click", () => {
    try {
      localStorage.setItem(ONBOARDING_HIDDEN_KEY, "1");
    } catch (err) {
      /* sin almacenamiento: solo se oculta por ahora */
    }
    box.hidden = true;
  });
  head.append(title, hide);

  const progress = document.createElement("div");
  progress.className = "onboarding-progress";
  progress.setAttribute("role", "progressbar");
  progress.setAttribute("aria-valuemin", "0");
  progress.setAttribute("aria-valuemax", String(onboarding.total));
  progress.setAttribute("aria-valuenow", String(onboarding.done));
  progress.innerHTML = `<span style="width:${Math.round((onboarding.done / onboarding.total) * 100)}%"></span>`;

  const list = document.createElement("ol");
  list.className = "onboarding-steps";
  onboarding.steps.forEach((step) => {
    const item = document.createElement("li");
    item.className = step.done ? "done" : "";
    const icon = step.done ? "check-circle" : "circle";
    item.innerHTML = `<i class="ph ph-${icon}" aria-hidden="true"></i>`;
    if (step.done) {
      const label = document.createElement("span");
      label.textContent = step.label;
      item.appendChild(label);
    } else {
      // Mismo renglón que los hechos (no un botón con borde, que dejaba la
      // fila despareja): solo el color y la flecha dicen que falta.
      const link = document.createElement("a");
      link.className = "onboarding-link";
      link.href = step.url;
      link.textContent = step.label;
      link.insertAdjacentHTML("beforeend", ' <i class="ph ph-arrow-right" aria-hidden="true"></i>');
      item.appendChild(link);
    }
    list.appendChild(item);
  });
  box.append(head, progress, list);
  // Sin tienda todavía: probar con pedidos inventados y llegar a imprimir el
  // primer rótulo en un minuto (POST /orders/sample/, utils.js).
  const storeStep = onboarding.steps.find((step) => step.key === "store");
  if (storeStep && !storeStep.done && sessionHasPermission("orders.create_manual")) {
    const offer = document.createElement("p");
    offer.className = "onboarding-sample";
    offer.innerHTML = '<i class="ph ph-flask" aria-hidden="true"></i><span>¿Querés probar antes de conectar tu tienda?</span>';
    const button = document.createElement("button");
    button.type = "button";
    button.className = "btn btn-outline btn-small";
    button.textContent = "Probar con pedidos de ejemplo";
    button.addEventListener("click", async () => {
      button.disabled = true;
      button.textContent = "Cargando…";
      try {
        await createSampleOrders();
        window.location.href = "imprimir_rotulos.html?rotulo=sin_imprimir";
      } catch (err) {
        if (err.isSessionExpired) return;
        showMessage(err.message);
        button.disabled = false;
        button.textContent = "Probar con pedidos de ejemplo";
      }
    });
    offer.appendChild(button);
    box.appendChild(offer);
  }
  box.hidden = false;
}

// ---------------------------------------------------------------------------
// RESUMEN RÁPIDO: último pedido propio (reusa /api/v1/orders/, ya ordenado
// -created_at por Order.Meta.ordering — no hace falta un endpoint nuevo).
// Si el usuario no tiene el permiso orders.view, ni se intenta pedir.
// No hay bloque de "último rótulo": todavía no existe backend de generación
// de rótulos (apps.labels sigue sin modelos/urls, ver dashboard_views.py),
// así que no hay de dónde traer ese dato sin inventarlo.
// ---------------------------------------------------------------------------
// Si alguien invitó a este usuario a su comercio, se lo dice acá: es lo
// primero que ve al entrar (ver invitaciones.html).
async function loadInvitationNotice() {
  try {
    const response = await apiFetch(MY_INVITATIONS_URL);
    if (!response.ok) return;
    const invitations = await response.json();
    if (!Array.isArray(invitations) || !invitations.length) return;
    const notice = document.getElementById("invitationNotice");
    const names = invitations.map((item) => `«${item.team_name}»`).join(", ");
    notice.textContent = `Te invitaron a trabajar en ${names}. `;
    const link = document.createElement("a");
    link.href = "invitaciones.html";
    link.textContent = invitations.length === 1 ? "Ver la invitación" : "Ver las invitaciones";
    notice.appendChild(link);
    notice.hidden = false;
  } catch (err) {
    if (!err || !err.isSessionExpired) console.error("Error al leer las invitaciones:", err);
  }
}

// El panel trae el comercio actual y la lista de comercios recién leídos: la
// sesión guardada de la pestaña se pone al día (otra pestaña o el dueño pudo
// haberlos cambiado).
function keepStoredTeams(data) {
  const stored = getCurrentUser();
  if (!stored || !stored.id) return;
  const next = { ...stored, team: data.team || null, teams: data.teams || [] };
  if (JSON.stringify(next.team) !== JSON.stringify(stored.team) || JSON.stringify(next.teams) !== JSON.stringify(stored.teams)) {
    window.Auth.saveSession(next);
  }
}

async function loadDashboard() {
  try {
    const response = await apiFetch(DASHBOARD_URL);
    if (!response.ok) {
      showMessage("No se pudo cargar el panel. Intentá de nuevo más tarde.");
      return;
    }
    const data = await response.json();
    // Sin comercio no hay nada del trabajo del comercio: a crear uno o
    // sumarse. El admin entra igual (la administración no necesita comercio).
    // Quien administra la plataforma (admin o su personal) tiene por Inicio el
    // resumen de la plataforma (build_sidebar).
    if (!data.team && Array.isArray(data.sidebar) && data.sidebar.some((item) => item.key === "home" && item.url === "resumen_plataforma.html")) {
      window.location.replace("resumen_plataforma.html");
      return;
    }
    if (!data.team && !(data.user && data.user.is_admin)) {
      window.location.replace("comercio_inicio.html");
      return;
    }
    keepStoredTeams(data);
    if (data.team) {
      document.getElementById("dashboardTitle").textContent = `Hoy en ${data.team.display_name || data.team.name}`;
    }
    // La barra compartida con el usuario fresco y su comercio (topbar.js). El
    // usuario del panel no trae la lista de permisos: sale de la sesión
    // guardada, que la barra necesita para no ofrecer "Administración" de más.
    window.AppTopbar.render({ ...getCurrentUser(), ...(data.user || {}), team: data.team, teams: data.teams });
    renderOnboarding(data.onboarding);
    loadInvitationNotice();
    if (!data.team) {
      document.getElementById("noTeamNotice").hidden = false;
      return;
    }
    loadToday();
    setupPeriodSwitch();
    renderSampleOrdersNotice(document.getElementById("sampleNotice"), { onChange: () => window.location.reload() });
  } catch (err) {
    if (!err || !err.isSessionExpired) {
      console.error("Error al cargar el dashboard:", err);
      showMessage("No se pudo cargar el panel. Intentá de nuevo más tarde.");
    }
  }
}

// ---------------------------------------------------------------------------
// Logout: misma lógica que admin_common.js (window.Auth.logout).
// ---------------------------------------------------------------------------

if (!hasSession()) {
  window.location.replace("index.html");
} else {
  loadDashboard();
}

// La fecha de hoy sobre el título ("martes 11 de noviembre").
(function showToday() {
  const el = document.getElementById("dashboardDate");
  if (!el) return;
  el.textContent = new Date().toLocaleDateString("es-AR", { weekday: "long", day: "numeric", month: "long" });
})();
