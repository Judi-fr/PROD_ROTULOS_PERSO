// Confirmar el cambio de email (confirmar_cambio_email.html): el token llega en
// la URL del mail y se manda a POST /auth/me/change-email/confirm/. Sin sesión.

(async function () {
  const lead = document.getElementById("changeLead");
  const token = new URLSearchParams(window.location.search).get("token") || "";
  // El token no queda en el historial ni en la barra.
  window.history.replaceState(null, "", window.location.pathname);
  if (!token) {
    lead.textContent = "Al enlace le falta una parte. Abrilo de nuevo desde el mail.";
    return;
  }
  try {
    const response = await fetch(`${window.APP_CONFIG.API_BASE}/auth/me/change-email/confirm/`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(getErrorMessage(data, "El enlace no es válido o ya venció."));
    lead.textContent = "Tu cuenta ya usa el email nuevo. Por seguridad cerramos tus sesiones: entrá de nuevo con ese email.";
    showMessage(data.detail || "Listo.", "success");
    try {
      localStorage.removeItem("user");
    } catch {
      // Sin storage no hay sesión guardada que limpiar.
    }
  } catch (error) {
    lead.textContent = "No pudimos confirmar el cambio.";
    showMessage(error.message || "No se pudo confirmar el cambio.");
  }
})();
