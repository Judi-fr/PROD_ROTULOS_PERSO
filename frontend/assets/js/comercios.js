// Comercios (comercios.html, admin con users.view; 2026-11-19): los comercios
// abiertos de la plataforma con su dueño, equipo, tiendas, pedidos y última
// actividad (GET /teams/directory/), y la ficha de cada uno en un diálogo
// (GET /teams/<id>/detail/). Solo lectura: lo que se cambia de un comercio
// sigue en Usuarios → Comercio del usuario.

(function () {
  const API = window.APP_CONFIG.API_BASE;
  const state = { search: "", problems: false, sort: "-created_at", page: 1 };
  let searchTimer = null;
  let requestId = 0;

  const byId = (id) => document.getElementById(id);
  const number = (n) => Number(n || 0).toLocaleString("es-AR");

  // "hace 3 días", "hoy"... para lo reciente; la fecha para lo viejo.
  function ago(value) {
    if (!value) return "Nunca";
    const date = new Date(value);
    const days = Math.floor((Date.now() - date.getTime()) / 86400000);
    if (days <= 0) return "Hoy";
    if (days === 1) return "Ayer";
    if (days < 30) return `Hace ${days} días`;
    return date.toLocaleDateString("es-AR", { day: "numeric", month: "short", year: "numeric" });
  }

  function shortDate(value) {
    return value ? new Date(value).toLocaleDateString("es-AR", { day: "numeric", month: "short", year: "numeric" }) : "—";
  }

  function storesCell(row) {
    if (!row.stores_active && !row.stores_error) return `<span class="biz-muted">Sin tiendas</span>`;
    const platforms = row.platforms.length ? escapeHtml(row.platforms.join(", ")) : "";
    const error = row.stores_error
      ? ` <span class="biz-flag" title="${row.stores_error} con errores de conexión"><i class="ph ph-warning" aria-hidden="true"></i>${row.stores_error} con errores</span>`
      : "";
    return `${number(row.stores_active)} <span class="biz-muted">${platforms}</span>${error}`;
  }

  function renderRows(rows) {
    const body = byId("bizBody");
    if (!rows.length) {
      body.innerHTML = adminEmptyRow(6, state.search || state.problems
        ? { icon: "search", title: "Ningún comercio coincide", text: "Probá con otra búsqueda o sacá el filtro." }
        : { icon: "store", title: "Todavía no hay comercios", text: "Cuando alguien cree el suyo, aparece acá." });
      return;
    }
    body.innerHTML = rows.map((row) => `
      <tr class="biz-row" data-id="${row.id}" tabindex="0" aria-label="Ver la ficha de ${escapeHtml(row.name)}">
        <td>
          <span class="biz-name">${escapeHtml(row.name)}</span>
          <span class="biz-owner">${escapeHtml(row.owner_email || "Sin dueño")}</span>
        </td>
        <td>${storesCell(row)}</td>
        <td class="is-num">${number(row.member_count)}</td>
        <td class="is-num">${number(row.orders_30d)} <span class="biz-muted">de ${number(row.orders_total)}</span></td>
        <td>${escapeHtml(ago(row.last_activity))}</td>
        <td>${escapeHtml(shortDate(row.created_at))}</td>
      </tr>`).join("");
  }

  function markSort() {
    document.querySelectorAll(".biz-sort").forEach((button) => {
      const key = button.dataset.sort;
      const th = button.closest("th");
      const dir = state.sort === key ? "ascending" : state.sort === `-${key}` ? "descending" : "none";
      th.setAttribute("aria-sort", dir);
      button.dataset.dir = dir;
    });
  }

  async function load() {
    const current = ++requestId;
    const params = new URLSearchParams({ sort: state.sort, page: String(state.page) });
    if (state.search) params.set("search", state.search);
    if (state.problems) params.set("problems", "1");
    try {
      const response = await window.Auth.apiFetch(`${API}/teams/directory/?${params}`);
      const data = await response.json().catch(() => ({}));
      if (current !== requestId) return; // llegó una respuesta más nueva
      if (!response.ok) throw new Error(getErrorMessage(data, "No se pudieron cargar los comercios."));
      renderRows(data.results || []);
      renderSimplePager("bizPager", "bizInfo", data.pagination, "comercios", (page) => {
        state.page = page;
        load();
      });
      markSort();
    } catch (err) {
      if (err && err.isSessionExpired) return;
      byId("bizBody").innerHTML = adminErrorRow(6, err.message);
    }
  }

  // --- La ficha ------------------------------------------------------------

  function section(title, inner) {
    return `<section class="biz-section"><h3>${escapeHtml(title)}</h3>${inner}</section>`;
  }

  function renderDetail(d) {
    const stats = `
      <dl class="biz-stats">
        <div><dt>Pedidos en 30 días</dt><dd>${number(d.orders_30d)}</dd></div>
        <div><dt>Pedidos en total</dt><dd>${number(d.orders_total)}</dd></div>
        <div><dt>Último pedido</dt><dd>${escapeHtml(ago(d.last_order_at))}</dd></div>
      </dl>`;
    const members = d.members.map((m) => `
      <li>
        <span><strong>${escapeHtml(m.name || m.email)}</strong><span class="biz-muted">${escapeHtml(m.email)}</span></span>
        <span class="biz-tag${m.role === "owner" ? " is-owner" : ""}">${escapeHtml(m.role === "owner" ? "Dueño" : m.profile)}</span>
        <span class="biz-muted">${m.last_login ? `Entró ${escapeHtml(ago(m.last_login).toLowerCase())}` : "Nunca entró"}</span>
      </li>`).join("");
    const stores = d.stores.length
      ? `<ul class="biz-list">${d.stores.map((s) => `
          <li>
            <span><strong>${escapeHtml(s.name)}</strong><span class="biz-muted">${escapeHtml(s.platform)}</span></span>
            <span class="biz-tag is-${escapeHtml(s.status)}">${escapeHtml(s.status_label)}</span>
            ${s.last_error ? `<span class="biz-error">${escapeHtml(s.last_error)}</span>` : ""}
          </li>`).join("")}</ul>`
      : `<p class="biz-muted">No conectó ninguna tienda.</p>`;
    const carriers = d.carriers.length
      ? `<ul class="biz-list">${d.carriers.map((c) => `
          <li>
            <span><strong>${escapeHtml(c.carrier)}</strong></span>
            <span class="biz-tag ${c.is_active ? "is-active" : "is-error"}">${c.is_active ? "Activa" : "Desactivada"}</span>
            ${c.last_error ? `<span class="biz-error">${escapeHtml(c.last_error)}</span>` : ""}
          </li>`).join("")}</ul>`
      : `<p class="biz-muted">Sin cuentas de transportista.</p>`;
    const manage = d.owner_id && canUseUserPermission("users.edit")
      ? `<a class="btn btn-outline btn-small" href="comercio_usuario.html?user=${d.owner_id}">Comercios del dueño</a>`
      : "";
    byId("bizDialogBody").innerHTML =
      stats +
      section(`Equipo (${d.members.length})`, `<ul class="biz-list">${members}</ul>`) +
      section(`Tiendas (${d.stores.length})`, stores) +
      section("Transportistas", carriers) +
      (manage ? `<div class="biz-dialog-foot">${manage}</div>` : "");
  }

  async function openDetail(id) {
    const dialog = byId("bizDialog");
    byId("bizDialogTitle").textContent = "Comercio";
    byId("bizDialogSub").textContent = "";
    byId("bizDialogBody").innerHTML = `<span class="app-skeleton" role="status" aria-label="Cargando…"><span></span><span></span><span></span></span>`;
    if (!dialog.open) dialog.showModal();
    try {
      const response = await window.Auth.apiFetch(`${API}/teams/${id}/detail/`);
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(getErrorMessage(data, "No se pudo cargar el comercio."));
      byId("bizDialogTitle").textContent = data.name;
      byId("bizDialogSub").textContent = `${data.owner_email || "Sin dueño"} · desde ${shortDate(data.created_at)}`;
      renderDetail(data);
    } catch (err) {
      if (err && err.isSessionExpired) return;
      byId("bizDialogBody").innerHTML = `<p class="page-message error">${escapeHtml(err.message)}</p>`;
    }
  }

  // --- Eventos ---------------------------------------------------------------

  byId("bizSearch").addEventListener("input", (event) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      state.search = event.target.value.trim();
      state.page = 1;
      load();
    }, 250);
  });
  byId("bizProblems").addEventListener("change", (event) => {
    state.problems = event.target.checked;
    state.page = 1;
    load();
  });
  // Un clic ordena, otro da vuelta el orden (los números arrancan de mayor a menor).
  document.querySelectorAll(".biz-sort").forEach((button) => {
    button.addEventListener("click", () => {
      const key = button.dataset.sort;
      const firstDesc = key !== "name";
      if (state.sort === key) state.sort = `-${key}`;
      else if (state.sort === `-${key}`) state.sort = key;
      else state.sort = firstDesc ? `-${key}` : key;
      state.page = 1;
      load();
    });
  });
  byId("bizBody").addEventListener("click", (event) => {
    const row = event.target.closest(".biz-row");
    if (row) openDetail(row.dataset.id);
  });
  byId("bizBody").addEventListener("keydown", (event) => {
    const row = event.target.closest(".biz-row");
    if (row && (event.key === "Enter" || event.key === " ")) {
      event.preventDefault();
      openDetail(row.dataset.id);
    }
  });
  const dialog = byId("bizDialog");
  byId("bizDialogClose").addEventListener("click", () => dialog.close());
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close();
  });

  if (canViewUsers()) load();
})();
