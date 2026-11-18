// "Confirmá tu email" (confirmar_email.html): la pantalla de espera de una cuenta
// que todavía no abrió el enlace del correo. Mientras tanto el backend solo le
// deja ver su perfil, pedir el correo de nuevo y salir (authentication.py), y
// auth.js manda acá ante un 403 con code "email_not_verified".
//
// Cuando la cuenta queda confirmada (en esta pestaña con "Ya lo confirmé", o
// al volver a ella después de abrir el enlace en otra), sigue al panel.

(function () {
  const API = `${window.APP_CONFIG.API_BASE}/auth`;
  const ME_URL = `${API}/me/`;
  const RESEND_URL = `${API}/verify-email/resend/`;

  if (!window.Auth.hasSession()) {
    window.location.replace("index.html");
    return;
  }

  const emailEl = document.getElementById("confirmEmail");
  const stored = window.Auth.getCurrentUser() || {};
  if (stored.email) emailEl.textContent = stored.email;

  function goOn(user) {
    window.Auth.saveSession({ ...(window.Auth.getCurrentUser() || {}), ...user });
    const isAdmin = Boolean(user.is_staff || String(user.role || "").toLowerCase() === "admin");
    window.location.replace(isAdmin ? "gestionuser.html" : "dashboard.html");
  }

  // Lee el perfil: si ya está confirmada, sigue; si no, devuelve false.
  async function checkVerified() {
    const response = await window.Auth.apiFetch(ME_URL);
    const user = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(getErrorMessage(user, "No pudimos revisar tu cuenta. Probá de nuevo."));
    if (user.email) emailEl.textContent = user.email;
    if (user.email_verified !== false) {
      goOn(user);
      return true;
    }
    return false;
  }

  document.getElementById("checkBtn").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      if (!(await checkVerified())) {
        showMessage("Todavía no figura confirmado. Abrí el enlace del correo que te mandamos y volvé a tocar el botón.", "warning");
      }
    } catch (err) {
      if (!err.isSessionExpired) showMessage(err.message);
    } finally {
      button.disabled = false;
    }
  });

  document.getElementById("resendBtn").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      const response = await window.Auth.apiFetch(RESEND_URL, { method: "POST" });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(getErrorMessage(data, "No pudimos mandar el correo. Probá de nuevo en un rato."));
      showMessage(data.detail || "Te mandamos el correo de nuevo.", "success");
    } catch (err) {
      if (!err.isSessionExpired) showMessage(err.message);
    } finally {
      button.disabled = false;
    }
  });

  document.getElementById("otherAccountBtn").addEventListener("click", () => window.Auth.logout());

  // Confirmó en otra pestaña (el enlace del correo abre una nueva): al volver
  // acá sigue solo, sin tener que tocar nada.
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") checkVerified().catch(() => {});
  });
  checkVerified().catch(() => {});
})();
