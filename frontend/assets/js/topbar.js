// Barra superior compartida: las acciones de la página y, a la derecha, el
// buscador, los avisos y el menú de la cuenta (Mi cuenta, Mi actividad, Ayuda,
// Cerrar sesión). Desde 2026-11-18 la navegación es la barra lateral
// (app_sidebar.js), que este archivo carga: la marca y el selector de comercio
// pasaron allá; en pantallas angostas la barra lateral se abre con el botón de
// menú de esta barra.
//
// Estaba copiada en cada página: el mismo bloque HTML en 12 archivos y la
// misma función renderTopbar en 11 .js. Acá se escribe una sola vez; cada
// página solo pone:
//
//   <header class="topbar" id="appTopbar"></header>
//
// Las páginas ya no declaran links propios (data-links, quitados 2026-11-19):
// repetían lo que la barra lateral despliega bajo cada sección.
//
// Muestra el selector de comercio (una persona puede estar en varios).
//
// El botón "Cerrar sesión" lo pone esta barra siempre, dentro del menú de la
// cuenta, con el id logoutBtn de antes: cada página le sigue enganchando su
// listener (window.Auth.logout). Un link a dashboard.html o a lo que ya está en
// el menú de la cuenta no se repite entre las acciones.
//
// Los datos del usuario salen de la sesión guardada (window.Auth) para que la
// barra aparezca completa de entrada; cuando la página trae el usuario fresco
// del backend llama a window.AppTopbar.render(user) y se actualiza.
//
// Cargar DESPUÉS de config.js/auth.js y ANTES del script propio de la página.

(function () {

  function container() {
    return document.getElementById("appTopbar");
  }

  // El menú de la cuenta: lo personal, fuera de las acciones de la página.
  const ACCOUNT_LINKS = [
    { href: "organizacion.html", label: "Mi cuenta" },
    { href: "seguridad.html", label: "Seguridad" },
    { href: "mi_actividad.html", label: "Mi actividad" },
    { href: "ayuda.html", label: "Ayuda" },
  ];
  // Íconos de Phosphor (el juego único de la app, ver ui.css).
  const ICONS = { home: "house-simple", chevron: "caret-down", logout: "sign-out" };

  function icon(name) {
    return `<i class="ph ph-${ICONS[name]}" aria-hidden="true"></i>`;
  }

  const here = () => location.pathname.split("/").pop() || "index.html";
  const samePage = (href) => href.split("#")[0] === here();

  function build(node, user) {
    const email = (user && user.email) || "—";
    const name = (user && (user.display_name || user.full_name)) || (user && user.email) || "Usuario";
    // La foto que subió (perfil personal) gana sobre la de Google.
    const picture = user && (user.photo || user.picture);

    node.replaceChildren();
    node.classList.add("app-topbar");

    // Izquierda: en pantallas angostas, el botón que abre la barra lateral y la
    // marca (en escritorio la barra lateral ya está a la vista con la marca y el
    // selector de comercio, ver app_sidebar.js).
    const left = document.createElement("div");
    left.className = "topbar-left";
    const menuToggle = document.createElement("button");
    menuToggle.type = "button";
    menuToggle.className = "topbar-menu-toggle";
    menuToggle.setAttribute("aria-label", "Abrir el menú");
    menuToggle.setAttribute("aria-expanded", "false");
    menuToggle.setAttribute("aria-controls", "appSidebar");
    menuToggle.innerHTML = '<i class="ph ph-list" aria-hidden="true"></i>';
    menuToggle.addEventListener("click", () => window.AppSidebar && window.AppSidebar.open());
    left.appendChild(menuToggle);
    const home = document.createElement("a");
    home.className = "topbar-home";
    home.href = "dashboard.html";
    // La marca del producto (Human Log · Rótulos) es también el camino al inicio.
    home.title = "Human Log · Rótulos — ir al inicio";
    home.setAttribute("aria-label", "Rótulos: ir al inicio");
    home.innerHTML = `<img src="assets/images/favicon.svg" alt="" width="26" height="26"><span>Rótulos</span>`;
    left.appendChild(home);
    node.appendChild(left);

    // Medio: vacío a propósito (2026-11-19). Cada página declaraba sus links
    // (data-links) y repetían las funciones que la barra lateral ya despliega
    // bajo su sección; ahora la navegación es solo la barra lateral. El nav
    // queda como separador, así la cuenta sigue a la derecha.
    const actions = document.createElement("nav");
    actions.className = "topbar-actions";
    actions.setAttribute("aria-hidden", "true");
    node.appendChild(actions);

    // Derecha: la cuenta. "Cerrar sesión" conserva el id logoutBtn: cada
    // página le sigue enganchando su listener (window.Auth.logout).
    const account = document.createElement("div");
    account.className = "topbar-account";
    const trigger = document.createElement("button");
    trigger.type = "button";
    trigger.className = "topbar-account-btn";
    trigger.setAttribute("aria-haspopup", "menu");
    trigger.setAttribute("aria-expanded", "false");
    trigger.title = `${name} · ${email}`;
    const avatar = document.createElement("img");
    avatar.className = "avatar";
    avatar.id = "userAvatar";
    avatar.alt = "";
    // Sin foto, las iniciales de personAvatarUrl (utils.js). En muchas páginas
    // utils.js carga DESPUÉS que esta barra: entonces se pone al terminar de leer la página.
    const drawAvatar = () => { avatar.src = picture || personAvatarUrl({ ...(user || {}), display_name: name }); };
    if (picture || typeof personAvatarUrl === "function") drawAvatar();
    else document.addEventListener("DOMContentLoaded", drawAvatar, { once: true });
    const nameEl = document.createElement("span");
    nameEl.className = "topbar-user-name";
    nameEl.id = "userName";
    nameEl.textContent = name;
    trigger.append(avatar, nameEl);
    trigger.insertAdjacentHTML("beforeend", `<span class="topbar-chevron">${icon("chevron")}</span>`);

    const menu = document.createElement("div");
    menu.className = "topbar-menu";
    menu.setAttribute("role", "menu");
    menu.hidden = true;
    const who = document.createElement("div");
    who.className = "topbar-menu-who";
    const whoName = document.createElement("strong");
    whoName.textContent = name;
    const emailEl = document.createElement("span");
    emailEl.id = "userEmail";
    emailEl.textContent = email;
    who.append(whoName, emailEl);
    menu.appendChild(who);
    ACCOUNT_LINKS.forEach((link) => {
      const anchor = document.createElement("a");
      anchor.href = link.href;
      anchor.textContent = link.label;
      anchor.setAttribute("role", "menuitem");
      if (samePage(link.href)) anchor.setAttribute("aria-current", "page");
      menu.appendChild(anchor);
    });
    const logout = document.createElement("button");
    logout.className = "topbar-menu-logout";
    logout.id = "logoutBtn";
    logout.type = "button";
    logout.setAttribute("role", "menuitem");
    logout.innerHTML = `${icon("logout")}<span>Cerrar sesión</span>`;
    // La barra se vuelve a dibujar cuando la página trae el usuario fresco, y
    // el listener que la página le había puesto al botón viejo se perdía: el
    // botón cerraba la sesión solo a veces. Ahora lo hace la barra misma (el
    // listener de la página, si quedó en este botón, no se ejecuta además).
    logout.addEventListener("click", (event) => {
      event.stopImmediatePropagation();
      if (window.Auth && typeof window.Auth.logout === "function") window.Auth.logout();
    });
    menu.appendChild(logout);

    const setOpen = (open) => {
      menu.hidden = !open;
      trigger.setAttribute("aria-expanded", String(open));
      account.classList.toggle("is-open", open);
    };
    trigger.addEventListener("click", (event) => {
      event.stopPropagation();
      setOpen(menu.hidden);
      if (!menu.hidden) menu.querySelector("a, button")?.focus();
    });
    menu.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        setOpen(false);
        trigger.focus();
      }
    });
    document.addEventListener("click", (event) => {
      if (!account.contains(event.target)) setOpen(false);
    });
    account.append(trigger, menu);

    // "Buscar" (Ctrl+K): una función o un pedido desde cualquier pantalla
    // (command_palette.js, que se carga una sola vez).
    const search = document.createElement("button");
    search.type = "button";
    search.className = "topbar-search-btn";
    search.title = "Buscar una función o un pedido (Ctrl+K)";
    search.setAttribute("aria-label", "Buscar una función o un pedido");
    search.innerHTML = `<i class="ph ph-magnifying-glass" aria-hidden="true"></i><span>Buscar</span><kbd>${/Mac|iPhone|iPad/.test(navigator.platform) ? "⌘" : "Ctrl"} K</kbd>`;
    search.addEventListener("click", () => window.AppPalette && window.AppPalette.open());
    // La campana: los avisos del comercio (el punto lo pone app_sidebar.js).
    const bell = document.createElement("a");
    bell.className = "topbar-bell";
    bell.id = "topbarBell";
    bell.href = "notificaciones.html";
    bell.setAttribute("aria-label", "Avisos");
    bell.title = "Avisos";
    bell.innerHTML = '<i class="ph ph-bell" aria-hidden="true"></i>';
    account.prepend(search, bell);
    node.appendChild(account);
    loadScript("command_palette.js", "appPaletteScript", () => window.AppPalette);
    loadScript("app_sidebar.js", "appSidebarScript", () => window.AppSidebar);
  }

  // El buscador (command_palette.js) y la barra lateral (app_sidebar.js) viven
  // en su propio archivo, al lado de este; llevan la misma marca de versión
  // (?v=) que topbar.js para no quedar viejos en la caché.
  const SCRIPT_SRC = (document.currentScript && document.currentScript.src) || "";
  function loadScript(file, id, loaded) {
    if (loaded() || document.getElementById(id) || !SCRIPT_SRC) return;
    const url = new URL(file, SCRIPT_SRC);
    url.search = new URL(SCRIPT_SRC).search;
    const script = document.createElement("script");
    script.id = id;
    script.src = url.href;
    document.body.appendChild(script);
  }

  function render(user) {
    const node = container();
    if (!node) return;
    const current = user || (window.Auth && window.Auth.getCurrentUser()) || {};
    build(node, current);
    // La barra lateral se dibuja con el mismo usuario (si ya cargó; si no, lo
    // lee de acá al cargar).
    window.__topbarUser = user || null;
    if (window.AppSidebar) window.AppSidebar.render(user || null);
  }

  window.AppTopbar = { render };
  // La marca en la pestaña: "Mis pedidos · Human Log Rótulos".
  if (!document.title.includes("Human Log")) document.title = `${document.title} · Human Log Rótulos`;
  render();
})();
