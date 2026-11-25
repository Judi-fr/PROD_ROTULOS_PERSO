// Seguridad de la cuenta (seguridad.html): sesiones abiertas. Ver
// docs/superpowers/specs/2026-11-25-recordarme-y-2fa-design.md. Los bloques
// del segundo paso, el historial y el email se suman como otras <section>.

(function () {
  const API_BASE = window.APP_CONFIG.API_BASE;
  const SESSIONS_URL = `${API_BASE}/auth/sessions/`;
  const apiFetch = (url, options) => window.Auth.apiFetch(url, options);

  const list = document.getElementById("sessionList");
  const revokeOthersBtn = document.getElementById("revokeOthersBtn");

  function relative(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "-";
    const minutes = Math.round((Date.now() - date.getTime()) / 60000);
    if (minutes < 2) return "ahora";
    if (minutes < 60) return `hace ${minutes} min`;
    return formatDateTime(value);
  }

  function sessionItem(row) {
    const li = document.createElement("li");
    li.className = "session-item" + (row.current ? " is-current" : "");

    const icon = document.createElement("i");
    icon.className = `ph ph-${/iPhone|Android|iPad/.test(row.browser) ? "device-mobile" : "desktop"}`;
    icon.setAttribute("aria-hidden", "true");

    const info = document.createElement("div");
    info.className = "session-info";
    const name = document.createElement("strong");
    name.textContent = row.browser;
    if (row.current) {
      const tag = document.createElement("span");
      tag.className = "session-tag";
      tag.textContent = "Esta sesión";
      name.append(" ", tag);
    }
    const meta = document.createElement("span");
    meta.className = "session-meta";
    const parts = [`Última actividad: ${relative(row.last_seen_at)}`, `Desde ${formatDateTime(row.created_at)}`];
    if (row.ip) parts.push(`IP ${row.ip}`);
    parts.push(row.remember ? "Sesión mantenida" : "Se cierra sola");
    meta.textContent = parts.join(" · ");
    info.append(name, meta);

    li.append(icon, info);
    if (!row.current) {
      const close = document.createElement("button");
      close.type = "button";
      close.className = "btn btn-ghost btn-small";
      close.textContent = "Cerrar";
      close.addEventListener("click", () => revokeOne(row));
      li.append(close);
    }
    return li;
  }

  async function load() {
    try {
      const response = await apiFetch(SESSIONS_URL);
      const rows = await response.json().catch(() => []);
      if (!response.ok) throw new Error(getErrorMessage(rows, "No se pudieron leer tus sesiones."));
      list.replaceChildren(...rows.map(sessionItem));
      revokeOthersBtn.hidden = !rows.some((row) => !row.current);
    } catch (error) {
      if (error.isSessionExpired) return;
      showMessage(error.message);
    }
  }

  async function revokeOne(row) {
    const ok = await appConfirm(`¿Cerrar la sesión de ${row.browser}? Esa computadora o celular va a tener que volver a entrar.`, {
      confirmLabel: "Cerrar sesión",
      danger: true,
    });
    if (!ok) return;
    const response = await apiFetch(`${SESSIONS_URL}${row.id}/revoke/`, { method: "POST" });
    if (response.ok) {
      showMessage(`Cerramos la sesión de ${row.browser}.`, "success");
    } else {
      const data = await response.json().catch(() => ({}));
      showMessage(getErrorMessage(data, "No se pudo cerrar esa sesión."));
    }
    load();
  }

  // ---- Verificación en dos pasos ------------------------------------------
  const MFA_URL = `${API_BASE}/auth/2fa/`;
  const METHOD_LABELS = { totp: "la app autenticadora", email: "un código por email" };
  const el = (id) => document.getElementById(id);
  let shownCodes = [];

  function showMfaPanel(name) {
    ["mfaOff", "mfaSetup", "mfaCodes", "mfaOn"].forEach((id) => {
      el(id).hidden = id !== name;
    });
  }

  async function mfaPost(path, body) {
    const response = await apiFetch(`${MFA_URL}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    const data = response.status === 204 ? {} : await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(getErrorMessage(data, "No se pudo hacer el cambio."));
    return data;
  }

  async function loadMfa() {
    try {
      const response = await apiFetch(MFA_URL);
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(getErrorMessage(data, "No se pudo leer la verificación en dos pasos."));
      el("mfaBadge").hidden = !data.enabled;
      el("mfaBadge").textContent = "Activa";
      if (data.enabled) {
        const left = Number(data.recovery_codes_left || 0);
        el("mfaStatusText").textContent =
          `Activa con ${METHOD_LABELS[data.method] || data.method}. Te ${left === 1 ? "queda 1 código" : `quedan ${left} códigos`} de recuperación.`;
        showMfaPanel("mfaOn");
      } else {
        showMfaPanel("mfaOff");
      }
    } catch (error) {
      if (!error.isSessionExpired) showMessage(error.message);
    }
  }

  function showCodes(codes) {
    shownCodes = codes;
    el("mfaCodeList").replaceChildren(
      ...codes.map((code) => {
        const li = document.createElement("li");
        li.textContent = code;
        return li;
      })
    );
    el("mfaBadge").hidden = false;
    showMfaPanel("mfaCodes");
  }

  document.querySelectorAll("[data-mfa-method]").forEach((button) =>
    button.addEventListener("click", async () => {
      const method = button.dataset.mfaMethod;
      try {
        const data = await mfaPost("setup/", { method });
        el("mfaTotpSetup").hidden = method !== "totp";
        el("mfaEmailSetup").hidden = method !== "email";
        if (method === "totp") {
          el("mfaQr").src = data.qr;
          el("mfaSecret").textContent = data.secret;
        } else {
          el("mfaEmailSetup").textContent = `Te mandamos un código a ${data.email_hint}. Escribilo abajo para activarla.`;
        }
        el("mfaSetupCode").value = "";
        showMfaPanel("mfaSetup");
        el("mfaSetupCode").focus();
      } catch (error) {
        if (!error.isSessionExpired) showMessage(error.message);
      }
    })
  );

  el("copySecret").addEventListener("click", () => copyText(el("mfaSecret").textContent, "Copiamos la clave."));

  el("mfaSetup").addEventListener("submit", async (event) => {
    event.preventDefault();
    const code = el("mfaSetupCode").value.trim();
    if (!code) {
      showMessage("Escribí el código de 6 números.");
      return;
    }
    try {
      const data = await mfaPost("confirm/", { code });
      showMessage("Listo: desde ahora te vamos a pedir un código al entrar.", "success");
      showCodes(data.recovery_codes || []);
    } catch (error) {
      if (!error.isSessionExpired) showMessage(error.message);
    }
  });

  el("mfaSetupCancel").addEventListener("click", () => {
    el("mfaQr").removeAttribute("src");
    el("mfaSecret").textContent = "";
    loadMfa();
  });

  function codesText() {
    return "Códigos de recuperación de Human Log · Rótulos\nCada uno sirve una sola vez.\n\n" + shownCodes.join("\n") + "\n";
  }

  el("copyCodes").addEventListener("click", () => copyText(codesText(), "Copiamos los códigos."));
  el("downloadCodes").addEventListener("click", () => {
    const link = document.createElement("a");
    link.href = URL.createObjectURL(new Blob([codesText()], { type: "text/plain;charset=utf-8" }));
    link.download = "rotulos-codigos-recuperacion.txt";
    link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  });
  el("codesDone").addEventListener("click", () => {
    shownCodes = [];
    el("mfaCodeList").replaceChildren();
    loadMfa();
  });

  function manageCode() {
    const code = el("mfaManageCode").value.trim();
    if (!code) {
      showMessage("Escribí un código de tu app, de recuperación o el que te mandamos por email.");
      el("mfaManageCode").focus();
      return null;
    }
    return code;
  }

  el("mfaReauthEmail").addEventListener("click", async () => {
    try {
      await mfaPost("reauth-email/");
      showMessage("Te mandamos un código por email. Vence en 10 minutos.", "success");
      el("mfaManageCode").focus();
    } catch (error) {
      if (!error.isSessionExpired) showMessage(error.message);
    }
  });

  el("mfaRegenerate").addEventListener("click", async () => {
    const code = manageCode();
    if (!code) return;
    const ok = await appConfirm("¿Generar códigos de recuperación nuevos? Los anteriores van a dejar de servir.", {
      confirmLabel: "Generar nuevos",
    });
    if (!ok) return;
    try {
      const data = await mfaPost("recovery-codes/", { code });
      el("mfaManageCode").value = "";
      showMessage("Estos son tus códigos nuevos.", "success");
      showCodes(data.recovery_codes || []);
    } catch (error) {
      if (!error.isSessionExpired) showMessage(error.message);
    }
  });

  el("mfaDisable").addEventListener("click", async () => {
    const code = manageCode();
    if (!code) return;
    const ok = await appConfirm(
      "¿Desactivar la verificación en dos pasos? Tu cuenta va a quedar protegida solo por la contraseña, y se van a cerrar tus otras sesiones.",
      { confirmLabel: "Desactivar", danger: true }
    );
    if (!ok) return;
    try {
      const data = await mfaPost("disable/", { code });
      el("mfaManageCode").value = "";
      showMessage(data.detail || "Desactivada.", "success");
      loadMfa();
      load();
    } catch (error) {
      if (!error.isSessionExpired) showMessage(error.message);
    }
  });

  revokeOthersBtn.addEventListener("click", async () => {
    const ok = await appConfirm("¿Cerrar todas las sesiones menos esta? Las otras computadoras y celulares van a tener que volver a entrar.", {
      confirmLabel: "Cerrar las demás",
      danger: true,
    });
    if (!ok) return;
    const response = await apiFetch(`${SESSIONS_URL}revoke-others/`, { method: "POST" });
    const data = await response.json().catch(() => ({}));
    if (response.ok) {
      const closed = Number(data.closed || 0);
      showMessage(closed === 1 ? "Cerramos 1 sesión." : `Cerramos ${closed} sesiones.`, "success");
    } else {
      showMessage(getErrorMessage(data, "No se pudieron cerrar las sesiones."));
    }
    load();
  });

  loadMfa();
  load();
})();
