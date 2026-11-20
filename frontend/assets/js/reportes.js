// ---------------------------------------------------------------------------
// REPORTES: usuarios, seguridad, pedidos y soporte/actividad de toda la
// plataforma. Rehecho el 2026-11-19: cada pestaña lleva arriba los números del
// período y debajo columnas por mes, barras y tablas (report_charts.js, el
// mismo dibujo que el Inicio). Antes eran barras de <span> con el ancho en
// style y tablas con un renglón por mes aunque fuera todo cero.
// El cálculo viene hecho del backend; acá solo se dibuja.
// ---------------------------------------------------------------------------
const METRICS_URL = `${window.APP_CONFIG.API_BASE}/users/metrics/`;
const ORDERS_METRICS_URL = `${window.APP_CONFIG.API_BASE}/orders/metrics/`;
const SUPPORT_METRICS_URL = `${window.APP_CONFIG.API_BASE}/support-messages/metrics/`;
const AUDIT_METRICS_URL = `${window.APP_CONFIG.API_BASE}/audit/metrics/`;

const RC = window.ReportCharts;
const byId = (id) => document.getElementById(id);
const plural = (n, one, many) => `${RC.formatNumber(n)} ${n === 1 ? one : many}`;

// Con coma decimal y sin ",0" de más, como se escribe acá ("12,5 %", "0 %").
function formatDecimal(value) {
  return Number(value).toLocaleString("es-AR", { maximumFractionDigits: 1 });
}

function formatPercent(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  return `${formatDecimal(value)} %`;
}

function formatHours(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  const hours = Number(value);
  // Más de dos días se lee mejor en días.
  return hours >= 48 ? `${formatDecimal(hours / 24)} días` : `${formatDecimal(hours)} h`;
}

function formatDays(value) {
  const days = Math.round(value);
  return `${days} ${days === 1 ? "día" : "días"}`;
}

// Los meses del período, del más viejo al actual ("2026-06"...), para que cada
// gráfico tenga todos los meses aunque el backend omita los que están en cero.
function periodMonths(count) {
  const now = new Date();
  return Array.from({ length: count }, (_, index) => {
    const date = new Date(now.getFullYear(), now.getMonth() - (count - 1 - index), 1);
    return { key: `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`, date };
  });
}

function monthPoints(months) {
  return months.map(({ date }) => ({
    label: date.toLocaleDateString("es-AR", { month: "short" }).replace(".", ""),
    long: date.toLocaleDateString("es-AR", { month: "long", year: "numeric" }).replace(/^./, (c) => c.toUpperCase()),
  }));
}

// Una serie por mes a partir de filas {month, <campo>} del backend.
function monthValues(months, rows, field = "count") {
  const map = new Map((rows || []).map((row) => [String(row.month).slice(0, 7), Number(row[field]) || 0]));
  return months.map(({ key }) => map.get(key) || 0);
}

const sum = (values) => values.reduce((a, b) => a + b, 0);

function setLoading(ids) {
  ids.forEach((id) => {
    const el = byId(id);
    if (el) el.innerHTML = `<span class="app-skeleton" role="status" aria-label="Cargando…"><span></span><span></span><span></span></span>`;
  });
}

function showPanelNote(name, text) {
  const note = byId(`${name}Note`);
  if (!note) return;
  note.textContent = text || "";
  note.hidden = !text;
}

// --- Usuarios y Seguridad (GET /users/metrics/) ----------------------------

const USER_IDS = ["chartSignups", "barsRoles", "tableRetention", "barsAuth"];
const SECURITY_IDS = ["chartLockouts", "tableVerification", "tableFailed"];

function renderUsers(data, months) {
  const active = data.active_users || {};
  const signups = monthValues(months, data.active_vs_inactive_by_month, "signups");
  const deactivations = monthValues(months, data.active_vs_inactive_by_month, "deactivations");
  const age = data.account_age || {};
  RC.kpis(byId("usersKpis"), [
    { label: "Activos en 30 días", icon: "user-check", value: active.last_30_days ?? 0, hint: `${RC.formatNumber(active.last_7_days ?? 0)} en 7 días · ${RC.formatNumber(active.last_90_days ?? 0)} en 90` },
    { label: "Altas en el período", icon: "user-plus", value: sum(signups), hint: plural(sum(deactivations), "baja", "bajas") },
    { label: "Nunca entraron", icon: "user-minus", value: active.never_logged_in ?? 0, hint: "Cuentas sin ningún ingreso" },
    { label: "Antigüedad promedio", icon: "calendar-blank", value: age.average_days != null ? formatDays(age.average_days) : "—", hint: "Desde que se creó la cuenta" },
  ]);

  RC.columns(byId("chartSignups"), {
    points: monthPoints(months),
    series: [{ label: "Altas", values: signups }, { label: "Bajas", values: deactivations }],
    description: "Altas y bajas de cuentas por mes",
    empty: "No hubo altas ni bajas en el período.",
  });

  RC.bars(byId("barsRoles"), (data.role_distribution || []).map((row) => ({ label: translateRole(row.label), count: row.count })));

  RC.table(
    byId("tableRetention"),
    [
      { label: "Mes de registro", value: (r) => monthPoints([{ date: new Date(`${r.month}-01T12:00:00`) }])[0].long },
      { label: "Se registraron", value: (r) => RC.formatNumber(r.cohort_size), numeric: true },
      { label: "Volvieron", value: (r) => RC.formatNumber(r.returned), numeric: true },
      { label: "Retención", value: (r) => formatPercent(r.retention_rate), numeric: true },
    ],
    (data.retention || []).filter((row) => row.cohort_size > 0),
    { empty: "Nadie se registró en el período." }
  );

  const auth = data.auth_method || {};
  RC.bars(byId("barsAuth"), [
    { label: "Email y contraseña", count: auth.local ?? 0 },
    { label: "Google", count: auth.google ?? 0 },
  ]);
}

function renderSecurity(data, months) {
  const verification = data.email_verification || {};
  const verified = verification.verified ?? 0;
  const unverified = verification.unverified ?? 0;
  const lockouts = monthValues(months, data.lockouts_by_month);
  const pending = data.pending_password_change ?? 0;
  RC.kpis(byId("securityKpis"), [
    { label: "Email verificado", icon: "envelope-simple-open", value: verified + unverified ? formatPercent((verified / (verified + unverified)) * 100) : "—", hint: `${plural(unverified, "sin verificar", "sin verificar")} · ${plural(verification.expired_token ?? 0, "link vencido", "links vencidos")}` },
    { label: "Bloqueos en el período", icon: "lock-simple", value: sum(lockouts), hint: "Por contraseñas equivocadas", tone: sum(lockouts) ? "alert" : "" },
    { label: "Cambio de contraseña pendiente", icon: "key", value: pending, hint: "Deben cambiarla al entrar" },
  ]);

  RC.columns(byId("chartLockouts"), {
    points: monthPoints(months),
    series: [{ label: "Bloqueos", values: lockouts }],
    description: "Cuentas bloqueadas por mes",
    empty: "No hubo bloqueos en el período.",
  });

  RC.table(
    byId("tableVerification"),
    [
      { label: "Método", value: (r) => (r.auth_method === "google" ? "Google" : "Email y contraseña") },
      { label: "Verificados", value: (r) => RC.formatNumber(r.verified), numeric: true },
      { label: "Sin verificar", value: (r) => RC.formatNumber(r.unverified), numeric: true },
    ],
    data.auth_method_email_verification
  );

  RC.table(
    byId("tableFailed"),
    [
      { label: "Cuenta", value: (r) => r.email },
      { label: "Intentos fallidos", value: (r) => RC.formatNumber(r.failed_attempts), numeric: true },
      { label: "Bloqueada ahora", value: (r) => (r.is_locked ? "Sí" : "No") },
    ],
    (data.top_failed_attempts || []).filter((row) => row.failed_attempts > 0),
    { empty: "Ninguna cuenta con intentos fallidos." }
  );
}

// --- Pedidos (GET /orders/metrics/) -----------------------------------------

const ORDER_IDS = ["chartOrders", "barsStatus", "tableTimes", "barsCancelledFrom", "barsStates", "barsCities", "tableTopUsers"];

function renderOrders(data, months) {
  const orders = monthValues(months, data.orders_by_month);
  const cancellation = data.cancellation_rate || {};
  const withOrders = data.users_with_orders || {};
  RC.kpis(byId("ordersKpis"), [
    { label: "Pedidos en el período", icon: "package", value: sum(orders), hint: `${RC.formatNumber(cancellation.total_orders ?? 0)} en total` },
    { label: "Cancelados", icon: "x-circle", value: formatPercent(cancellation.rate), hint: plural(cancellation.cancelled_count ?? 0, "pedido cancelado", "pedidos cancelados") },
    { label: "Cuentas con pedidos", icon: "storefront", value: withOrders.count ?? 0, hint: `${formatPercent(withOrders.percentage)} de ${RC.formatNumber(withOrders.total_users ?? 0)}` },
  ]);

  RC.columns(byId("chartOrders"), {
    points: monthPoints(months),
    series: [{ label: "Pedidos", values: orders }],
    description: "Pedidos por mes",
    empty: "No entraron pedidos en el período.",
  });

  RC.bars(byId("barsStatus"), ((data.orders_by_status || {}).funnel || []).map((row) => ({ label: row.label, count: row.count })));

  RC.table(
    byId("tableTimes"),
    [
      { label: "De → a", value: (r) => r.transition },
      { label: "Promedio", value: (r) => formatHours(r.average_hours), numeric: true },
      { label: "Pedidos", value: (r) => RC.formatNumber(r.sample_size), numeric: true },
    ],
    (data.avg_time_between_statuses || []).filter((row) => row.sample_size > 0),
    { empty: "Todavía no hay pedidos que hayan cambiado de estado." }
  );

  RC.bars(byId("barsCancelledFrom"), (cancellation.prior_status_breakdown || []).map((row) => ({ label: row.label, count: row.count })), { empty: "No hay pedidos cancelados." });

  const location = data.orders_by_location || {};
  RC.bars(byId("barsStates"), (location.by_state || []).map((row) => ({ label: row.state || "Sin provincia", count: row.count })));
  RC.bars(byId("barsCities"), (location.by_city || []).map((row) => ({ label: row.city || "Sin ciudad", count: row.count })));

  RC.table(
    byId("tableTopUsers"),
    [
      { label: "Cuenta", value: (r) => r.email },
      { label: "Pedidos", value: (r) => RC.formatNumber(r.count), numeric: true },
      { label: "Último pedido", value: (r) => formatDateTime(r.last_order_at), numeric: true },
    ],
    data.top_users_by_orders
  );
}

// --- Soporte y actividad (GET /support-messages/metrics/ + /audit/metrics/) ---

const SUPPORT_IDS = ["chartSupport", "barsSupportStatus", "chartLogins", "barsActors", "barsActions"];

function renderSupport(supportData, auditData, months) {
  const messages = monthValues(months, supportData.support_by_month);
  const logins = monthValues(months, auditData.login_events, "success");
  const failed = monthValues(months, auditData.login_events, "failed");
  const response = supportData.avg_response_time || {};
  RC.kpis(byId("supportKpis"), [
    { label: "Mensajes de soporte", icon: "chats", value: sum(messages), hint: "En el período" },
    { label: "Tiempo de respuesta", icon: "timer", value: formatHours(response.average_hours), hint: response.sample_size ? `Promedio de ${plural(response.sample_size, "respuesta", "respuestas")}` : "Todavía sin respuestas" },
    { label: "Ingresos", icon: "sign-in", value: sum(logins), hint: plural(sum(failed), "intento fallido", "intentos fallidos") },
  ]);

  RC.columns(byId("chartSupport"), {
    points: monthPoints(months),
    series: [{ label: "Mensajes", values: messages }],
    description: "Mensajes de soporte por mes",
    empty: "No llegaron mensajes en el período.",
  });
  RC.bars(byId("barsSupportStatus"), (supportData.support_by_status || []).map((row) => ({ label: row.label, count: row.count })), { empty: "No hay mensajes." });

  RC.columns(byId("chartLogins"), {
    points: monthPoints(months),
    series: [{ label: "Correctos", values: logins }, { label: "Fallidos", values: failed }],
    description: "Inicios de sesión correctos y fallidos por mes",
    empty: "No hubo ingresos en el período.",
  });

  const activity = auditData.admin_activity || {};
  RC.bars(byId("barsActors"), (activity.by_actor || []).map((row) => ({ label: row.actor_email || "Sin cuenta", count: row.count })), { empty: "Sin acciones de administración." });
  RC.bars(byId("barsActions"), (activity.by_action || []).map((row) => ({ label: actionLabel(row.action), count: row.count })), { empty: "Sin acciones de administración.", max: 12 });
}

// --- Carga -------------------------------------------------------------------

function getReportsMonths() {
  return Number(byId("reportsMonthsSelect")?.value || 6);
}

async function getJson(url) {
  const response = await apiFetch(url);
  const data = await response.json().catch(() => ({}));
  if (response.status === 403) throw new Error("No tenés permisos para ver estos reportes.");
  if (!response.ok) throw new Error(getErrorMessage(data, "No se pudieron cargar los reportes."));
  return data;
}

async function loadUsersAndSecurity(count, months) {
  setLoading([...USER_IDS, ...SECURITY_IDS]);
  try {
    const data = await getJson(`${METRICS_URL}?months=${count}`);
    showPanelNote("usuarios", "");
    showPanelNote("seguridad", "");
    renderUsers(data, months);
    renderSecurity(data, months);
  } catch (err) {
    if (err.isSessionExpired) return;
    console.error("Reportes de usuarios:", err);
    showPanelNote("usuarios", err.message);
    showPanelNote("seguridad", err.message);
    [...USER_IDS, ...SECURITY_IDS].forEach((id) => byId(id)?.replaceChildren());
  }
}

async function loadOrders(count, months) {
  setLoading(ORDER_IDS);
  try {
    const data = await getJson(`${ORDERS_METRICS_URL}?months=${count}`);
    showPanelNote("pedidos", "");
    renderOrders(data, months);
  } catch (err) {
    if (err.isSessionExpired) return;
    console.error("Reportes de pedidos:", err);
    showPanelNote("pedidos", err.message);
    ORDER_IDS.forEach((id) => byId(id)?.replaceChildren());
  }
}

async function loadSupportActivity(count, months) {
  setReportsTabAvailable("soporte", true);
  setLoading(SUPPORT_IDS);
  await loadAuditActionsCatalog();
  try {
    const [supportData, auditData] = await Promise.all([
      getJson(`${SUPPORT_METRICS_URL}?months=${count}`).catch(() => ({})),
      getJson(`${AUDIT_METRICS_URL}?months=${count}`).catch(() => ({})),
    ]);
    showPanelNote("soporte", "");
    renderSupport(supportData, auditData, months);
  } catch (err) {
    if (err.isSessionExpired) return;
    console.error("Reportes de soporte:", err);
    showPanelNote("soporte", "No se pudieron cargar los reportes de soporte.");
  }
}

async function loadMetrics() {
  const count = getReportsMonths();
  const months = periodMonths(count);
  await Promise.all([loadUsersAndSecurity(count, months), loadOrders(count, months), loadSupportActivity(count, months)]);
}

// Pestañas: un bloque por vez. La elegida queda en el #hash, así un recargo o
// un link vuelve a la misma.
const REPORTS_DEFAULT_TAB = "usuarios";

function reportsTabButton(name) {
  return document.querySelector(`.reports-tab[data-tab="${name}"]`);
}

function showReportsTab(name) {
  const button = reportsTabButton(name);
  if (!button || button.hidden) name = REPORTS_DEFAULT_TAB;
  document.querySelectorAll(".reports-tab").forEach((tab) => {
    const active = tab.dataset.tab === name;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", active ? "true" : "false");
  });
  document.querySelectorAll(".reports-panel").forEach((panel) => {
    panel.hidden = panel.dataset.panel !== name;
  });
}

function setReportsTabAvailable(name, available) {
  const button = reportsTabButton(name);
  if (!button) return;
  button.hidden = !available;
  // La pestaña pedida por el #hash puede aparecer recién ahora.
  showReportsTab(window.location.hash.slice(1) || REPORTS_DEFAULT_TAB);
}

document.querySelectorAll(".reports-tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    history.replaceState(null, "", `#${tab.dataset.tab}`);
    showReportsTab(tab.dataset.tab);
  });
});
showReportsTab(window.location.hash.slice(1) || REPORTS_DEFAULT_TAB);

// "Actualizar" dice que está trabajando y cuándo terminó, como en Estado del sistema.
async function refreshReports() {
  const button = document.getElementById("reportsRefreshBtn");
  button.disabled = true;
  button.textContent = "Actualizando…";
  await loadMetrics();
  button.disabled = false;
  button.textContent = "Actualizar";
  const time = new Date().toLocaleTimeString("es-AR", { hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
  const stamp = document.getElementById("reportsUpdatedAt");
  if (stamp) stamp.textContent = `Actualizado a las ${time}`;
}

document.getElementById("reportsRefreshBtn")?.addEventListener("click", refreshReports);
document.getElementById("reportsMonthsSelect")?.addEventListener("change", () => loadMetrics());

// ---------------------------------------------------------------------------
// Esta pantalla tiene su propio permiso, "reports.view" (migración 0029): se
// pueden dar los reportes sin dar la lista de usuarios ni la auditoría.
// ---------------------------------------------------------------------------
function bootstrap() {
  if (!canUseUserPermission("reports.view")) {
    window.location.replace("dashboard.html");
    return;
  }
  loadMetrics();
}

bootstrap();
