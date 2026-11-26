// Segundo paso de un ingreso (verificar_ingreso.html). El login dejó el
// desafío en sessionStorage.mfaChallenge (startMfaChallenge, utils.js) y acá
// se manda el código a POST /auth/2fa/verify/. Ver apps/accounts/mfa.py.

(function () {
  const API_BASE = window.APP_CONFIG.API_BASE;
  const VERIFY_URL = `${API_BASE}/auth/2fa/verify/`;
  const RESEND_URL = `${API_BASE}/auth/2fa/resend/`;
  const RESEND_WAIT_SECONDS = 60;

  let challenge = null;
  try {
    challenge = JSON.parse(sessionStorage.getItem("mfaChallenge") || "null");
  } catch {
    challenge = null;
  }
  if (!challenge || !challenge.mfa_token) {
    window.location.replace("index.html");
    return;
  }

  const form = document.getElementById("mfaForm");
  const input = document.getElementById("mfaCode");
  const label = document.getElementById("mfaCodeLabel");
  const lead = document.getElementById("mfaLead");
  const useRecovery = document.getElementById("useRecovery");
  const resendRow = document.getElementById("resendRow");
  const resendBtn = document.getElementById("resendBtn");
  let recoveryMode = false;

  function setLead() {
    if (recoveryMode) {
      lead.textContent = "Escribí uno de los códigos de recuperación que guardaste (por ejemplo abcd-efgh). Cada uno sirve una sola vez.";
    } else if (challenge.method === "email") {
      lead.textContent = `Te mandamos un código de 6 números a ${challenge.email_hint || "tu email"}. Vence en 10 minutos.`;
    } else {
      lead.textContent = "Abrí tu app autenticadora (Google Authenticator, Authy…) y escribí el código de 6 números de Rótulos.";
    }
  }

  function setMode(recovery) {
    recoveryMode = recovery;
    input.value = "";
    input.inputMode = recovery ? "text" : "numeric";
    input.maxLength = recovery ? 9 : 6;
    input.autocomplete = recovery ? "off" : "one-time-code";
    label.textContent = recovery ? "Código de recuperación" : "Código";
    useRecovery.textContent = recovery ? "Usar el código de 6 números" : "Usar un código de recuperación";
    resendRow.hidden = recovery || challenge.method !== "email";
    setLead();
    input.focus();
  }

  function backToLogin(message) {
    sessionStorage.removeItem("mfaChallenge");
    appAlert(message, { tone: "info" }).then(() => window.location.replace("index.html" + (challenge.search || "")));
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const code = input.value.trim();
    if (!code) {
      showMessage(recoveryMode ? "Escribí un código de recuperación." : "Escribí el código de 6 números.");
      return;
    }
    try {
      const response = await fetch(
        VERIFY_URL,
        window.Auth.withSession({
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            mfa_token: challenge.mfa_token,
            code,
            trust_browser: document.getElementById("trustBrowser").checked,
          }),
        })
      );
      const data = await response.json().catch(() => ({}));
      if (data && data.code === "mfa_expired") {
        backToLogin("Pasó mucho tiempo: entrá de nuevo con tu email y contraseña.");
        return;
      }
      if (!response.ok) throw new Error(getErrorMessage(data, "El código no es correcto."));
      sessionStorage.removeItem("mfaChallenge");
      window.Auth.saveSession(data.user);
      window.location.replace(authLandingPage(data.user, challenge.search || ""));
    } catch (error) {
      showMessage(error.message || "No se pudo verificar el código.");
      input.select();
    }
  });

  useRecovery.addEventListener("click", () => setMode(!recoveryMode));

  let waitTimer = null;
  function startWait(seconds) {
    resendBtn.disabled = true;
    let left = seconds;
    resendBtn.textContent = `Mandármelo de nuevo (${left} s)`;
    clearInterval(waitTimer);
    waitTimer = setInterval(() => {
      left -= 1;
      if (left <= 0) {
        clearInterval(waitTimer);
        resendBtn.disabled = false;
        resendBtn.textContent = "Mandármelo de nuevo";
      } else {
        resendBtn.textContent = `Mandármelo de nuevo (${left} s)`;
      }
    }, 1000);
  }

  resendBtn.addEventListener("click", async () => {
    const response = await fetch(
      RESEND_URL,
      window.Auth.withSession({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mfa_token: challenge.mfa_token }),
      })
    ).catch(() => null);
    const data = response ? await response.json().catch(() => ({})) : {};
    if (data && data.code === "mfa_expired") {
      backToLogin("Pasó mucho tiempo: entrá de nuevo con tu email y contraseña.");
      return;
    }
    if (response && response.ok) {
      showMessage(`Te mandamos otro código a ${challenge.email_hint || "tu email"}.`, "success");
      startWait(RESEND_WAIT_SECONDS);
    } else {
      showMessage(getErrorMessage(data, "No se pudo mandar el código. Probá en un minuto."));
    }
  });

  setMode(false);
  if (challenge.method === "email") startWait(RESEND_WAIT_SECONDS);
})();
