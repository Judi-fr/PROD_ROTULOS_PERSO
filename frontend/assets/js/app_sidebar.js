// Barra lateral del comerciante (2026-11-18, boceto aprobado por el usuario):
// la misma en todas sus páginas. La carga topbar.js (al lado de él, con su
// misma marca ?v=), así ninguna página la declara.
//
// Qué muestra lo decide el BACKEND (GET /auth/users/me/dashboard/ → `sidebar`,
// apps/accounts/dashboard_sections.build_sidebar, ya filtrado por permiso);
// acá solo se dibuja. Se guarda en sessionStorage por comercio para dibujarla
// al instante en la página siguiente y se refresca en segundo plano.
//
// Los números de Pedidos e Imprimir salen del resumen del día
// (GET /orders/summary/) y el punto de la campana de los avisos (GET /notices/),
// los dos solo con un comercio elegido (sin comercio esos endpoints responden
// no_team y auth.js mandaría a otra página).
//
// En pantallas angostas la barra se esconde y se abre con el botón de menú de
// la barra superior (body.sidebar-open).

(function () {
  const API = window.APP_CONFIG.API_BASE;
  const MENU_TTL_MS = 5 * 60 * 1000;
  const COUNTS_TTL_MS = 60 * 1000;

  const here = () => location.pathname.split("/").pop() || "index.html";
  const pageOf = (url) => String(url || "").split(/[?#]/)[0];

  function sessionUser() {
    return (window.Auth && window.Auth.getCurrentUser && window.Auth.getCurrentUser()) || {};
  }
  function teamKey(user) {
    return user && user.team ? String(user.team.id) : "none";
  }

  function readCache(key, ttl) {
    try {
      const data = JSON.parse(sessionStorage.getItem(key) || "null");
      if (data && Date.now() - data.at < ttl) return data.value;
    } catch {
      /* sin almacenamiento: se pide de nuevo */
    }
    return null;
  }
  function writeCache(key, value) {
    try {
      sessionStorage.setItem(key, JSON.stringify({ at: Date.now(), value }));
    } catch {
      /* sin almacenamiento: no pasa nada */
    }
  }

  async function getJson(url) {
    try {
      const response = await window.Auth.apiFetch(url);
      return response.ok ? await response.json() : null;
    } catch {
      return null;
    }
  }

  // --- Estado ---------------------------------------------------------------
  let items = null;
  let counts = null;
  let currentUser = null;
  // Estado de /health/system/ ("ok"/"warning"/"error"), solo para quien ve
  // "Estado del sistema" en Administración.
  let health = null;
  let healthAsked = false;
  // Secciones que la persona abrió o cerró con la flechita (key → abierta).
  const choices = new Map();

  function isActive(item) {
    const page = here();
    if (pageOf(item.url) === page) return true;
    if ((item.match || []).includes(page)) return true;
    return (item.links || []).some((link) => pageOf(link.url) === page);
  }

  function badgeFor(item) {
    if (!counts || !item.badge) return 0;
    if (item.badge === "orders") return (counts.to_print || 0) + (counts.to_dispatch || 0);
    if (item.badge === "print") return counts.to_print || 0;
    return 0;
  }

  function icon(name) {
    const i = document.createElement("i");
    i.className = `ph ph-${name}`;
    i.setAttribute("aria-hidden", "true");
    return i;
  }

  function buildItem(item) {
    const li = document.createElement("li");
    li.className = "sidebar-item";
    const active = isActive(item);
    if (active) li.classList.add("is-active");

    const row = document.createElement("div");
    row.className = "sidebar-row";
    const link = document.createElement("a");
    link.className = "sidebar-link";
    link.href = item.url;
    if (active) link.setAttribute("aria-current", "page");
    link.appendChild(icon(item.icon || "circle"));
    const label = document.createElement("span");
    label.className = "sidebar-label";
    label.textContent = item.label;
    link.appendChild(label);
    const badge = badgeFor(item);
    if (badge) {
      const count = document.createElement("span");
      count.className = "sidebar-badge";
      count.textContent = badge > 99 ? "99+" : String(badge);
      count.setAttribute("aria-label", `${badge} pendientes`);
      link.appendChild(count);
    }
    if ((item.links || []).some((entry) => pageOf(entry.url) === "estado_sistema.html")) addHealthDot(link);
    row.appendChild(link);

    // Las funciones de la sección: abiertas en la sección activa; cualquiera
    // se abre o cierra con la flechita (sin salir de la página).
    const links = item.links || [];
    let sub = null;
    if (links.length) {
      const show = choices.has(item.key) ? choices.get(item.key) : active;
      const toggle = document.createElement("button");
      toggle.type = "button";
      toggle.className = "sidebar-toggle";
      toggle.setAttribute("aria-expanded", String(show));
      toggle.setAttribute("aria-label", `${show ? "Ocultar" : "Ver"} las funciones de ${item.label}`);
      toggle.appendChild(icon("caret-down"));
      toggle.addEventListener("click", () => {
        choices.set(item.key, !show);
        draw();
      });
      row.appendChild(toggle);

      sub = document.createElement("ul");
      sub.className = "sidebar-sub";
      sub.hidden = !show;
      const full = location.pathname.split("/").pop() + location.search + location.hash;
      links.forEach((entry) => {
        const subLi = document.createElement("li");
        const anchor = document.createElement("a");
        anchor.href = entry.url;
        anchor.textContent = entry.label;
        if (pageOf(entry.url) === "estado_sistema.html") addHealthDot(anchor);
        const same = entry.url.includes("?") || entry.url.includes("#") ? entry.url === full : pageOf(entry.url) === here();
        if (same) anchor.setAttribute("aria-current", "page");
        subLi.appendChild(anchor);
        sub.appendChild(subLi);
      });
    }
    li.appendChild(row);
    if (sub) li.appendChild(sub);
    return li;
  }

  function draw() {
    const aside = ensureAside();
    const user = currentUser || sessionUser();
    aside.replaceChildren();

    const brand = document.createElement("a");
    brand.className = "sidebar-brand";
    brand.href = "dashboard.html";
    brand.setAttribute("aria-label", "Rótulos: ir al inicio");
    brand.innerHTML = '<img src="assets/images/favicon.svg" alt="" width="32" height="32"><span><strong>Rótulos</strong><small>Human Log</small></span>';

    const close = document.createElement("button");
    close.type = "button";
    close.className = "sidebar-close";
    close.setAttribute("aria-label", "Cerrar el menú");
    close.appendChild(icon("x"));
    close.addEventListener("click", () => setOpen(false));

    const head = document.createElement("div");
    head.className = "sidebar-head";
    head.append(brand, close);

    const team = document.createElement("div");
    team.className = "sidebar-team";
    if (typeof renderTeamSwitcher === "function") renderTeamSwitcher(team, user);

    const search = document.createElement("button");
    search.type = "button";
    search.className = "sidebar-search";
    search.innerHTML = `<i class="ph ph-magnifying-glass" aria-hidden="true"></i><span>Buscar</span><kbd>${/Mac|iPhone|iPad/.test(navigator.platform) ? "⌘" : "Ctrl"} K</kbd>`;
    search.addEventListener("click", () => {
      setOpen(false);
      if (window.AppPalette) window.AppPalette.open();
    });

    const nav = document.createElement("nav");
    nav.className = "sidebar-nav";
    nav.setAttribute("aria-label", "Menú principal");
    const title = document.createElement("span");
    title.className = "sidebar-section-title";
    title.textContent = "Menú";
    const main = document.createElement("ul");
    main.className = "sidebar-list";
    const bottom = document.createElement("ul");
    bottom.className = "sidebar-list sidebar-list-bottom";
    (items || [{ key: "home", label: "Inicio", icon: "house-simple", url: "dashboard.html", links: [] }]).forEach((item) => {
      (item.place === "bottom" ? bottom : main).appendChild(buildItem(item));
    });
    nav.append(title, main);

    const foot = document.createElement("div");
    foot.className = "sidebar-foot";
    foot.appendChild(bottom);
    const who = document.createElement("a");
    who.className = "sidebar-user";
    who.href = "organizacion.html";
    who.title = "Mi cuenta";
    const avatar = document.createElement("img");
    avatar.alt = "";
    avatar.className = "sidebar-avatar";
    const name = user.display_name || user.full_name || user.email || "Mi cuenta";
    if (typeof personAvatarUrl === "function") avatar.src = personAvatarUrl({ ...user, display_name: name });
    const text = document.createElement("span");
    const strong = document.createElement("strong");
    strong.textContent = name;
    const role = document.createElement("small");
    role.textContent = user.team ? (user.team.role === "owner" ? "Dueño del comercio" : "Equipo del comercio") : "Mi cuenta";
    text.append(strong, role);
    who.append(avatar, text);
    foot.appendChild(who);

    aside.append(head, team, search, nav, foot);
    updateBell();
  }

  // Un punto rojo (error) o ámbar (advertencia) en "Estado del sistema" y en
  // su sección cuando algo falla, así el admin no depende solo del mail de
  // alerta. Lo hacía admin_sidebar.js (quitado 2026-11-19). La sonda pública
  // /health/system/ no trae detalles; a lo sumo una vez por minuto.
  function addHealthDot(node) {
    if (!health || !health.status || !["error", "warning"].includes(health.status)) return;
    const failing = Object.values(health.checks || {}).filter((value) => value === health.status).length;
    const what = health.status === "error" ? "con error" : "con advertencia";
    const label = `${failing || "Un"} chequeo${failing === 1 ? "" : "s"} ${what}`;
    const dot = document.createElement("span");
    dot.className = `sidebar-alert sidebar-alert-${health.status}`;
    dot.title = label;
    dot.setAttribute("aria-label", label);
    node.appendChild(dot);
  }

  async function loadHealth() {
    if (healthAsked) return;
    const wanted = (items || []).some((item) => (item.links || []).some((entry) => pageOf(entry.url) === "estado_sistema.html"));
    if (!wanted) return;
    healthAsked = true;
    const cached = readCache("appSidebarHealth", COUNTS_TTL_MS);
    if (cached) {
      health = cached;
    } else {
      try {
        const response = await fetch(`${API}/health/system/`);
        health = await response.json();
        writeCache("appSidebarHealth", health);
      } catch {
        return;
      }
    }
    draw();
  }

  function ensureAside() {
    let aside = document.getElementById("appSidebar");
    if (!aside) {
      aside = document.createElement("aside");
      aside.id = "appSidebar";
      aside.className = "app-sidebar";
      document.body.prepend(aside);
      const backdrop = document.createElement("div");
      backdrop.className = "sidebar-backdrop";
      backdrop.addEventListener("click", () => setOpen(false));
      document.body.prepend(backdrop);
      document.body.classList.add("has-app-sidebar");
      document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && document.body.classList.contains("sidebar-open")) setOpen(false);
      });
    }
    return aside;
  }

  function setOpen(open) {
    document.body.classList.toggle("sidebar-open", open);
    const toggle = document.querySelector(".topbar-menu-toggle");
    if (toggle) toggle.setAttribute("aria-expanded", String(open));
    if (open) document.querySelector("#appSidebar .sidebar-link")?.focus();
  }

  function updateBell() {
    const bell = document.getElementById("topbarBell");
    if (!bell || !counts) return;
    const n = counts.notices || 0;
    bell.classList.toggle("has-news", n > 0);
    bell.setAttribute("aria-label", n ? `Avisos (${n})` : "Avisos");
  }

  async function loadMenu(user) {
    const key = `appSidebar:${teamKey(user)}`;
    const cached = readCache(key, MENU_TTL_MS);
    if (cached) {
      items = cached;
      draw();
      loadHealth();
      return;
    }
    const data = await getJson(`${API}/auth/users/me/dashboard/`);
    if (data && Array.isArray(data.sidebar)) {
      items = data.sidebar;
      writeCache(key, items);
      draw();
      loadHealth();
    }
  }

  async function loadCounts(user) {
    if (!user || !user.team) return;
    const key = `appSidebarCounts:${teamKey(user)}`;
    const cached = readCache(key, COUNTS_TTL_MS);
    if (cached) {
      counts = cached;
      draw();
      return;
    }
    const perms = Array.isArray(user.permissions) ? user.permissions : null;
    const [summary, notices] = await Promise.all([
      !perms || perms.includes("orders.view") ? getJson(`${API}/orders/summary/`) : null,
      getJson(`${API}/notices/`),
    ]);
    counts = {
      to_print: summary ? summary.to_print : 0,
      to_dispatch: summary ? summary.to_dispatch : 0,
      notices: Array.isArray(notices) ? notices.length : 0,
    };
    writeCache(key, counts);
    draw();
  }

  // Lo llama topbar.js cada vez que dibuja la barra superior (con el usuario
  // fresco cuando la página lo trae).
  function render(user) {
    const fresh = user || sessionUser();
    const changedTeam = currentUser && teamKey(currentUser) !== teamKey(fresh);
    currentUser = fresh;
    if (changedTeam) {
      items = null;
      counts = null;
    }
    draw();
    if (!window.Auth || !window.Auth.hasSession()) return;
    if (!items) loadMenu(fresh);
    if (!counts) loadCounts(fresh);
  }

  window.AppSidebar = { render, open: () => setOpen(true), close: () => setOpen(false) };
  render(window.__topbarUser || null);
})();
