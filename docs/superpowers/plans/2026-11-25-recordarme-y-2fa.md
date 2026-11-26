# Recordarme, verificación en dos pasos y seguridad de la cuenta — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sesiones con nombre y "Recordarme", verificación en dos pasos (app o email) con códigos de recuperación,
avisos por mail de seguridad, gestión de sesiones y las 12 mejoras de comodidad del diseño.

**Architecture:** Una sesión (`SessionRecord`) por inicio de sesión; su id (`sid`) y si es recordada (`remember`)
viajan como claims del refresh/access JWT y sobreviven a la rotación. Todo ingreso (contraseña, Google, segundo paso)
termina en UNA función, `login_flow.finish_login`, que decide si pide el segundo paso o entrega tokens, crea la
sesión, registra el dispositivo y audita. La autenticación (`JWTAuthenticationWithPasswordPolicy`) y el refresh
rechazan un `sid` cerrado o inactivo.

**Tech Stack:** Django 5 + DRF + simplejwt (rotación + blacklist), `qrcode` (ya instalado), `apps.integrations.crypto`
(Fernet) para el secreto TOTP, `django.core.signing` para el `mfa_token`, HTML/CSS/JS planos.

**Spec:** `docs/superpowers/specs/2026-11-25-recordarme-y-2fa-design.md` (leerlo entero antes de empezar).

## Global Constraints

- Todo desde `backend/` con el venv: `cd backend && source venv/bin/activate`. Tests: `python manage.py test <label>`.
- **No commitear, pushear ni pullear** salvo que el usuario lo pida (CLAUDE.md). Los pasos "Checkpoint" corren
  la suite del área en vez de commitear.
- Código, nombres, endpoints y tests en inglés; todo texto que ve el usuario en español rioplatense (como el resto).
- Después de cada migración: `python manage.py makemigrations --check` limpio y `python manage.py migrate` en la base
  local.
- Nunca modificar tests existentes para que pasen. Las vistas nuevas de acceso público llevan
  `permission_classes = [AllowAny]` explícito y un throttle propio.
- Nunca guardar en claro ni loguear ni auditar: secreto TOTP, códigos (email, TOTP, recuperación), `mfa_token`,
  tokens de cambio de email. Secreto TOTP cifrado con `apps.integrations.crypto`; códigos de recuperación y de email
  hasheados (`django.contrib.auth.hashers.make_password`/`check_password`).
- Mails con `apps.common.mail.branded_html` + cuerpo de texto plano, nunca a usuarios internos
  (`teams.internal_users_q()`), con throttle por persona/día.
- Frontend: una página por función; helpers compartidos en `assets/js/utils.js`; estilos con los tokens de `ui.css`
  (sin hex/fuentes/tamaños a mano); íconos Phosphor; `<body data-requires="...">` en páginas nuevas con permiso;
  `appConfirm`/`appAlert`, nunca `confirm()`/`alert()`; texto de terceros con `escapeHtml`/`textContent`.
- Defaults (settings en `config/settings/base.py`, sobreescribibles por `.env`): `AUTH_REMEMBER_DAYS=30`,
  `AUTH_SESSION_HOURS=12`, `AUTH_IDLE_MINUTES=30`, `MFA_TOKEN_MAX_AGE_SECONDS=300`, `MFA_EMAIL_CODE_MINUTES=10`,
  `MFA_TRUST_DAYS=30`, `MFA_RECOVERY_CODES=10`, `AUTH_DEVICE_COOKIE_DAYS=365`, `EMAIL_CHANGE_HOURS=24`; throttles
  `mfa_verify` (10/min), `mfa_email` (1/min por usuario + 10/día), `new_device_mail` (5/día por usuario),
  `email_change` (5/día por usuario).
- Clientes Bearer (sin `X-Auth-Mode: cookie`) y la suite existente: sin `remember` en el body, todo igual que hoy
  (refresh 7 días). Un usuario SIN segundo paso entra exactamente como hoy (mismo JSON).
- Al terminar cada etapa: `python manage.py test apps.accounts apps.audit` verde, `flake8` limpio,
  `node frontend/tools/check_frontend.mjs` limpio. Al final: suite completa + e2e (`frontend/e2e`).

## Review Focus

1. **Un camino que esquiva el segundo paso**: `GoogleAuthView`, `RegisterView` (cuenta nueva no tiene 2FA: ok) y
   cualquier vista que llame `auth_response` directo. Esperado: con 2FA activo, ningún token sin código. Test en Task 6:
   `test_no_view_issues_tokens_without_second_factor` recorre login, google (mock) y verify.
2. **Token viejo sin `sid`** (sesiones abiertas antes del deploy). Esperado: siguen andando hasta vencer y "cerrar todas"
   igual los mata. Test en Task 2: `test_legacy_token_without_sid_still_authenticates_until_revoke_all`.
3. **Dos pestañas refrescando a la vez** con la sesión recordada. Esperado: la rotación no baja los 30 días ni duplica la
   sesión. Test en Task 3: `test_rotation_keeps_remember_lifetime_and_sid`.
4. **Reloj del celular corrido** (TOTP del paso anterior/siguiente) y **el mismo código usado dos veces**. Esperado: ±1
   paso aceptado, reuso rechazado. Test en Task 5.
5. **Email nuevo que ya existe / mayúsculas distintas** al cambiar email. Esperado: mensaje genérico, nada cambia, el
   email se normaliza con `normalize_email`. Test en Task 13.

---

## Etapa 1 — Sesiones, Recordarme, inactividad y cierres

### File Structure (etapa 1)

- Create `backend/apps/accounts/security_models.py`: `SessionRecord`, `KnownDevice`, `UserMfa`, `MfaRecoveryCode`,
  `MfaEmailCode`, `EmailChangeRequest` (todos los modelos de esta feature; importados al final de `models.py` como
  `team_models`). Se crean todos en la Task 1 para tener UNA migración de modelos.
- Create `backend/apps/accounts/sessions.py`: crear, emitir tokens, validar, tocar y revocar sesiones; nombre legible
  del navegador.
- Create `backend/apps/accounts/login_flow.py`: `finish_login` (Task 2 la versión sin 2FA; Task 6 le suma el 2FA).
- Create `backend/apps/accounts/security_views.py`: vistas propias de seguridad (sesiones, 2FA, contraseña, email, log).
- Modify `auth_views.py`, `auth_cookies.py`, `authentication.py`, `urls.py`, `user_admin_views.py`,
  `config/settings/base.py`, `apps/audit/models.py`.
- Tests nuevos en `backend/apps/accounts/tests/test_sessions.py`.

### Task 1: Modelos y migraciones

**Files:**
- Create: `backend/apps/accounts/security_models.py`
- Modify: `backend/apps/accounts/models.py` (import al final, como `team_models`)
- Modify: `backend/apps/audit/models.py` (acciones nuevas + `ACTION_CATEGORIES`)
- Create: migraciones `accounts/0039_account_security.py`, `audit/0013_security_actions.py`
- Test: `backend/apps/accounts/tests/test_sessions.py`

**Interfaces — Produces:**
- `SessionRecord(id: UUID pk default uuid4, user FK CASCADE related_name="auth_sessions", created_at, last_seen_at,
  ip: GenericIPAddressField null, user_agent: CharField(400), browser: CharField(80), remember: bool,
  method: CharField(20) — "password"|"google"|"register", mfa_method: CharField(20, blank) — ""|"totp"|"email"|"recovery",
  revoked_at: null, revoked_reason: CharField(40, blank))`; property `is_active`.
- `KnownDevice(user FK CASCADE, device_hash CharField(64), browser, first_seen_at, last_seen_at, trusted_until null)`,
  unique `(user, device_hash)`.
- `UserMfa(user OneToOne CASCADE related_name="mfa", method "totp"|"email", secret_encrypted TextField blank,
  enabled_at null, last_totp_step BigInteger null, pending_secret_encrypted TextField blank)`; `enabled` = `enabled_at`
  no nulo.
- `MfaRecoveryCode(user FK CASCADE, code_hash, used_at null, created_at)`.
- `MfaEmailCode(user FK CASCADE, purpose "login"|"setup"|"reauth", code_hash, expires_at, used_at null, attempts int)`.
- `EmailChangeRequest(user FK CASCADE, new_email, token_hash, expires_at, confirmed_at null, created_at)`.
- Acciones de auditoría (categoría `auth`, label en español): `auth.mfa_enable` "Verificación en dos pasos activada",
  `auth.mfa_disable` "…desactivada", `auth.mfa_admin_reset` "…quitada por un administrador", `auth.mfa_failed`
  "Código de verificación incorrecto", `auth.recovery_code_used` "Código de recuperación usado",
  `auth.recovery_codes_regenerated` "Códigos de recuperación nuevos", `auth.session_revoke` "Sesión cerrada",
  `auth.new_device` "Ingreso desde un navegador nuevo", `auth.email_change` "Cambio de email",
  `auth.password_set` "Contraseña creada".

- [ ] **Step 1:** Test `SecurityModelsTests.test_user_session_defaults` (crear sesión → `is_active` True, id UUID;
  `revoked_at` seteado → False) y `test_new_audit_actions_have_category` (cada acción nueva está en `ACTION_CATEGORIES`
  con `Category.AUTH`).
- [ ] **Step 2:** Correr `python manage.py test apps.accounts.tests.test_sessions` → FAIL (import).
- [ ] **Step 3:** Escribir modelos, import en `models.py`, acciones en audit; `makemigrations accounts audit`; `migrate`.
- [ ] **Step 4:** Tests PASS; `makemigrations --check` sin cambios.
- [ ] **Step 5:** Regenerar el ERD: `python manage.py erd_mermaid --output ../docs/erd.md`.

### Task 2: Sesiones en tokens, refresh, autenticación y logout

**Files:**
- Create: `backend/apps/accounts/sessions.py`, `backend/apps/accounts/login_flow.py`
- Modify: `auth_views.py` (`tokens_for_user`, `auth_response`, `LoginView`, `GoogleAuthView`, `RegisterView`,
  `LogoutView`, `blacklist_all_refresh_tokens`, `ChangePasswordView`, `PasswordResetConfirmView`,
  `CookieTokenRefreshView`), `authentication.py`, `auth_cookies.py`
- Test: `test_sessions.py`

**Interfaces — Produces (`sessions.py`):**
- `browser_label(user_agent: str) -> str` — "Chrome en Windows", "Safari en iPhone", "Firefox en Linux",
  "Navegador desconocido"; solo regex sobre el UA, sin librerías.
- `start_session(user, request, *, remember: bool, method: str, mfa_method: str = "") -> SessionRecord`.
- `tokens_for_session(session: SessionRecord) -> dict[str, str]` — `{"access", "refresh"}` con claims `sid` (str) y
  `remember` (bool) en ambos; vida del refresh: `AUTH_REMEMBER_DAYS` si remember, `AUTH_SESSION_HOURS` si
  `remember is False` y el ingreso vino en modo cookie, el default de simplejwt (7 días) si no vino `remember`.
  Guarda la vida elegida en el claim `life` (segundos) para que la rotación la respete.
- `active_session(sid: str | None) -> SessionRecord | None` — None si no existe, cerrada, o (no recordada y
  `last_seen_at` más vieja que `AUTH_IDLE_MINUTES`; en ese caso la cierra con reason `"idle"`).
- `touch(session, *, activity: bool)` — actualiza `last_seen_at` como mucho una vez por minuto, solo si `activity`.
- `revoke_session(session, reason: str)`; `revoke_all(user, *, except_sid: str | None = None, reason: str)` — cierra
  sesiones Y blacklistea todos los `OutstandingToken` (reemplaza el cuerpo de `blacklist_all_refresh_tokens`, que queda
  como alias para no romper imports).
- `login_flow.finish_login(request, user, *, remember: bool | None, method: str, picture: str = "") -> Response` —
  en esta tarea: `start_session` + `tokens_for_session` + `update_last_login` + `user_payload` + `deliver_tokens(..., remember=...)`.
  `auth_response` queda para compatibilidad pero los tres ingresos llaman a `finish_login`. El audit `auth.login_success`
  se mueve adentro de `finish_login` (con `changes={"remember": bool}`).
- `auth_cookies.set_auth_cookies(response, *, access=None, refresh=None, refresh_max_age: int | None | "session")` —
  `"session"` = cookie sin `max_age`; `deliver_tokens(request, response, *, remember: bool | None = None)`.
- Autenticación: `JWTAuthenticationWithPasswordPolicy.authenticate` — si el token trae `sid` y
  `active_session(sid)` es None → `AuthenticationFailed({"detail": "La sesión se cerró: volvé a iniciar sesión.",
  "code": "session_closed"})`. Token sin `sid` → como hoy. Cachear por request (`request._rotulos_session`).
- Refresh: serializer propio `SessionTokenRefreshSerializer(TokenRefreshSerializer)` usado por
  `CookieTokenRefreshView`: valida `active_session(sid)` (401 "session_closed" + borra cookies), rota respetando
  `life` (`refresh.set_exp(lifetime=timedelta(seconds=life))`), `touch(session, activity=request.data.get("active") is True)`.
  Cookie de salida: `"session"` si `remember` es False, `life` si no.
- Logout: `revoke_session(sid del refresh, "logout")` además del blacklist.
- Cambio de contraseña y reset: `revoke_all(user, except_sid=<sid actual o None>, reason="password")`.

- [ ] **Step 1: Tests** en `SessionTokenTests`:
  `test_login_creates_session_with_browser_label` (UA de Chrome/Windows → `browser == "Chrome en Windows"`, `method == "password"`),
  `test_tokens_carry_sid_and_remember`, `test_remember_cookie_has_30_day_max_age` (cookie refresh `max-age` = 2592000),
  `test_not_remembered_cookie_is_session_cookie` (sin `max-age`/`expires`) and token exp ≈ 12 h,
  `test_bearer_login_without_remember_keeps_7_days`,
  `test_rotation_keeps_remember_lifetime_and_sid` (refresh dos veces: mismo `sid`, exp ≈ ahora + 30 d),
  `test_revoked_session_rejects_access_immediately` (revocar → GET `/auth/me/` 401 code `session_closed`),
  `test_revoked_session_rejects_refresh_and_clears_cookies`,
  `test_idle_non_remembered_session_is_closed_on_refresh` (last_seen = ahora − 31 min → 401; recordada → 200),
  `test_refresh_without_active_flag_does_not_extend_idle`,
  `test_logout_closes_its_session`, `test_password_change_closes_other_sessions_only`,
  `test_password_reset_closes_all_sessions`,
  `test_legacy_token_without_sid_still_authenticates_until_revoke_all`,
  `test_google_and_register_create_sessions` (método `google`/`register`).
- [ ] **Step 2:** Correr → FAIL.
- [ ] **Step 3:** Implementar `sessions.py`, `login_flow.py` y los cambios listados; settings `AUTH_REMEMBER_DAYS`,
  `AUTH_SESSION_HOURS`, `AUTH_IDLE_MINUTES`.
- [ ] **Step 4:** `python manage.py test apps.accounts.tests.test_sessions apps.accounts.tests.test_auth_cookies apps.accounts.tests.test_accounts apps.accounts.tests.test_email_required` → PASS (los existentes sin tocar).

### Task 3: Endpoints de sesiones propias y del admin; desactivar cierra todo

**Files:**
- Modify: `security_views.py` (create), `urls.py`, `user_admin_views.py`, `apps/accounts/models.py`
  (`LoginLockout.register_failure`: al bloquear, `revoke_all(user, reason="lockout")`)
- Test: `test_sessions.py`

**Interfaces — Produces:**
- `GET /api/v1/auth/sessions/` (`users.me.view`) → `[{id, browser, ip, created_at, last_seen_at, remember, current: bool}]`
  solo activas, ordenadas por `last_seen_at` desc.
- `POST /api/v1/auth/sessions/<uuid>/revoke/` (`users.me.edit`) → 204; ajena → 404. Audita `auth.session_revoke`.
- `POST /api/v1/auth/sessions/revoke-others/` (`users.me.edit`) → `{"closed": n}`; cierra todo menos la actual y
  borra `trusted_until` de todos los `KnownDevice` del usuario.
- `POST /api/v1/users/<id>/revoke-sessions/` (`@action` en `UserAdminViewSet`, `users.edit`) → `{"closed": n}`,
  audita con el admin como actor; sobre sí mismo → 400.
- Desactivar (status inactive, bulk-actions deactivate) y borrar → `revoke_all(user, reason="deactivated")`.

- [ ] **Step 1: Tests** `SessionApiTests`: `test_list_marks_current_and_hides_revoked`,
  `test_cannot_revoke_someone_elses_session` (404), `test_revoke_others_keeps_current`,
  `test_admin_revoke_sessions_requires_users_edit` (403 sin permiso), `test_admin_cannot_revoke_own_sessions` (400),
  `test_deactivating_user_closes_sessions_at_once` (el otro cliente → 401 en su próximo request),
  `test_lockout_closes_sessions`.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** PASS + `apps.accounts` completo verde.

### Task 4: Frontend etapa 1 — Recordarme, inactividad, `seguridad.html` (sesiones) y admin

**Files:**
- Modify: `frontend/index.html` (casilla + manda `remember` en login y Google), `frontend/assets/js/auth.js`
  (inactividad), `frontend/assets/js/topbar.js` (entrada "Seguridad" en el menú de la cuenta, entre "Mi cuenta" y
  "Mi actividad"), `frontend/gestionuser.html` + su JS (acción "Cerrar todas sus sesiones"),
  `frontend/assets/js/utils.js` (`IN_PAGE_TOOLS`: "Seguridad de la cuenta", "Sesiones abiertas")
- Create: `frontend/seguridad.html`, `frontend/assets/js/seguridad.js`, `frontend/assets/css/seguridad.css`
- Test: `backend/apps/accounts/tests/test_frontend_contracts.py` (agregar), e2e `frontend/e2e/tests/acceso.spec.js`

**Interfaces:**
- Casilla `#rememberMe` "Mantener la sesión iniciada", desmarcada por defecto; su último valor en
  `localStorage.rememberMe` ("1"/"0"). Body de login/google: `remember: true|false`.
- `auth.js`: `Auth.markActivity()` en `click`/`keydown`/`scroll` (throttle 15 s) escribe `localStorage.lastActivityAt`;
  el refresh manda `{"active": true}` si hubo actividad desde el último refresh. Solo si `user.session_remember === false`
  (el `user_payload` suma `session_remember` y `session_id`): un temporizador compara `lastActivityAt`; a los 29 min
  muestra un `<dialog>` "Tu sesión se va a cerrar en 1 minuto" con "Seguir conectado" (marca actividad y refresca); a los
  30 min hace `Auth.logout()` y lleva a `index.html?motivo=inactividad` (el login muestra "Cerramos tu sesión por
  inactividad."). Entre pestañas por el evento `storage`. Los `setInterval` de refresco automático no llaman `markActivity`.
- `seguridad.html` (`data-requires="users.me.view"`): esta tarea solo pinta el bloque "Sesiones abiertas" (lista,
  "Cerrar", "Cerrar todas las demás" con `appConfirm`); los otros bloques llegan en tareas siguientes como
  `<section>` propias.

- [ ] **Step 1:** Test de contrato `test_security_page_and_remember_checkbox_exist` (index.html tiene `id="rememberMe"`,
  `seguridad.html` existe con `data-requires`, topbar.js nombra `seguridad.html`).
- [ ] **Step 2:** e2e `"recordarme desmarcado: la cookie de sesión no tiene vencimiento"` y
  `"cerrar las otras sesiones deja afuera al otro navegador"` (dos contextos de Playwright).
- [ ] **Step 3:** Implementar. **Step 4:** `node frontend/tools/check_frontend.mjs`, contrato y e2e verdes.
- [ ] **Step 5:** Verificar en el navegador (preview `frontend` + backend): login con/sin casilla, aviso de inactividad
  con `AUTH_IDLE_MINUTES=2` en `.env` local, cerrar sesión desde otra ventana.

**Checkpoint etapa 1:** `python manage.py test apps.accounts apps.audit`, `flake8`, check del frontend.

---

## Etapa 2 — Verificación en dos pasos

### Task 5: Núcleo del segundo paso (`mfa.py`)

**Files:**
- Create: `backend/apps/accounts/mfa.py`
- Test: `backend/apps/accounts/tests/test_mfa.py`

**Interfaces — Produces:**
- `totp_now(secret: str, at: float | None = None) -> str` y `totp_verify(user_mfa, code: str) -> bool` — RFC 6238
  (SHA1, 6 dígitos, 30 s, ventana ±1); rechaza un paso `<= last_totp_step` y lo actualiza. Implementación propia con
  `hmac`/`base64` (sin dependencia nueva).
- `new_totp_secret() -> str` (base32, 20 bytes); `provisioning_uri(user, secret) -> str`
  (`otpauth://totp/Human%20Log%20R%C3%B3tulos:<email>?secret=…&issuer=Human%20Log%20R%C3%B3tulos`);
  `qr_data_url(uri) -> str` (PNG base64 con `qrcode`).
- `send_email_code(user, purpose: str) -> None` (6 dígitos, `MFA_EMAIL_CODE_MINUTES`, invalida los anteriores del mismo
  propósito, mail "Tu código para entrar: 123456"); `email_code_verify(user, code, purpose) -> bool` (un solo uso, vencido
  → False, máx 5 intentos por código).
- `new_recovery_codes(user) -> list[str]` (borra los anteriores; `MFA_RECOVERY_CODES` códigos `xxxx-xxxx` del alfabeto
  sin `0O1lI`); `recovery_code_verify(user, code) -> bool` (normaliza mayúsculas/guiones/espacios; marca `used_at`);
  `recovery_codes_left(user) -> int`.
- `verify_second_factor(user, code: str) -> str | None` → `"totp"`/`"email"`/`"recovery"` o None; prueba el método del
  usuario y después recuperación (un código con guion o de 8 caracteres va directo a recuperación).
- `make_mfa_token(user, *, remember, method) -> str` / `read_mfa_token(token) -> dict | None`
  (`signing.dumps(..., salt="accounts.mfa-login")`, `MFA_TOKEN_MAX_AGE_SECONDS`).
- `mfa_enabled(user) -> bool`.

- [ ] **Step 1: Tests** `MfaCoreTests`: `test_totp_matches_rfc6238_vector` (secreto RFC `12345678901234567890` en base32,
  t=59 → últimos 6 dígitos de `94287082` = `287082`), `test_totp_accepts_one_step_drift`,
  `test_totp_rejects_reused_step`, `test_email_code_single_use_and_expires`, `test_email_code_locks_after_5_attempts`,
  `test_recovery_code_single_use_and_normalized` (`" abcd-efgh "` ≡ `"ABCDEFGH"`), `test_new_recovery_codes_invalidate_old`,
  `test_mfa_token_expires` (con `override_settings(MFA_TOKEN_MAX_AGE_SECONDS=0)` / time travel),
  `test_secret_is_stored_encrypted` (el valor en la columna ≠ secreto).
- [ ] **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** PASS.

### Task 6: El ingreso pide el segundo paso

**Files:**
- Modify: `login_flow.py`, `auth_views.py` (Login y Google pasan `remember`/`method` y respetan la respuesta de
  `finish_login`), `security_views.py`, `urls.py`
- Create: `backend/apps/accounts/devices.py` (solo lo que necesita el "navegador de confianza"; el aviso es Task 9)
- Test: `test_mfa.py`

**Interfaces:**
- `devices.device_id(request) -> str | None` (cookie `rotulos_device`), `devices.ensure_device_cookie(response, device_id)`,
  `devices.is_trusted(user, device_id) -> bool`, `devices.trust(user, device_id, request)`,
  `devices.forget_trust(user)`.
- `finish_login(...)`: si `mfa_enabled(user)` y no `is_trusted` → `200 {"mfa_required": true, "mfa_token", "method",
  "email_hint": "m***@gmail.com"}` (sin tokens, sin `last_login`, sin audit de éxito; con método email ya manda el
  código). Si no → como Task 2. Nuevo kwarg `mfa_method=""` que pasa a `start_session` y a `changes` del audit.
- `POST /api/v1/auth/2fa/verify/` (AllowAny, throttle `mfa_verify`) `{mfa_token, code, trust_browser}`: token inválido →
  400 `{"code": "mfa_expired"}`; bloqueo activo → 423 como el login; código mal → `LoginLockout.register_failure()`,
  audit `auth.mfa_failed`, 400 "El código no es correcto."; ok → `register_success`, `trust` si se pidió, si fue de
  recuperación audit `auth.recovery_code_used` + mail, y `finish_login(..., mfa_method=…, skip_mfa=True)`.
- `POST /api/v1/auth/2fa/resend/` (AllowAny, throttle `mfa_email`) `{mfa_token}` → 204 (solo método email; otro → 400).
- El reset de contraseña NO toca `UserMfa`; `revoke_all` llama a `devices.forget_trust`.

- [ ] **Step 1: Tests** `MfaLoginTests`: `test_login_with_mfa_returns_challenge_without_tokens` (ni cookies ni
  `access`), `test_google_login_with_mfa_returns_challenge` (mock de la verificación del id token como en los tests de
  Google existentes), `test_verify_with_totp_issues_tokens_and_session_mfa_method`,
  `test_wrong_code_counts_toward_lockout` (3 mal → 423), `test_expired_mfa_token_is_rejected`,
  `test_trusted_browser_skips_second_step_for_30_days`, `test_password_reset_does_not_disable_mfa`,
  `test_recovery_code_login_sends_mail`, `test_user_without_mfa_login_response_unchanged` (mismas claves que hoy),
  `test_no_view_issues_tokens_without_second_factor`.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** PASS.

### Task 7: Activar, desactivar, códigos de recuperación y rescate del admin (API)

**Files:**
- Modify: `security_views.py`, `urls.py`, `user_admin_views.py`, `serializers.py` (usuario del admin: `mfa_enabled`,
  `mfa_method`), `user_admin_views._get_*_filter` (filtro `?mfa=1|0`, también en `export`)
- Create: `backend/apps/accounts/security_mail.py` (todos los mails de seguridad, uno por función)
- Test: `test_mfa.py`

**Interfaces:**
- `GET /auth/2fa/` → `{enabled, method, recovery_codes_left, has_usable_password}`.
- `POST /auth/2fa/setup/ {method}`: `totp` → `{secret, otpauth_uri, qr}` (guarda en `pending_secret_encrypted`);
  `email` → manda código `setup` (exige email verificado) → 204. Ya activo → 400.
- `POST /auth/2fa/confirm/ {code}` → activa, audita `auth.mfa_enable` (`changes={"method": …}`), mail, devuelve
  `{"recovery_codes": [...]}` (única vez que se ven).
- `POST /auth/2fa/disable/ {code}` (código del método, de recuperación, o —para pedirlo— `POST /auth/2fa/reauth-email/`
  manda un código `reauth`): borra `UserMfa` y códigos, `forget_trust`, `revoke_all(except_sid=actual)`, audita, mail.
- `POST /auth/2fa/recovery-codes/ {code}` → `{"recovery_codes": [...]}`, audita `auth.recovery_codes_regenerated`.
- `POST /api/v1/users/<id>/reset-2fa/` (`users.edit`; sobre sí mismo 400; sin 2FA 400) → borra, `revoke_all`, audita
  `auth.mfa_admin_reset` (actor = admin), mail a la persona.
- `security_mail`: `mfa_enabled_mail`, `mfa_disabled_mail(by_admin: bool)`, `recovery_code_used_mail(left)`,
  `password_changed_mail(kind: "change"|"reset"|"set")`, `new_device_mail(session)`, `email_changed_old_mail`,
  `email_change_link_mail(request_obj, raw_token)`. Todas `(user, request=None)` + branded_html.

- [ ] **Step 1: Tests** `MfaSetupTests`: `test_totp_setup_needs_valid_code_to_enable`, `test_email_setup_requires_verified_email`,
  `test_confirm_returns_recovery_codes_once` (GET posterior no los trae), `test_disable_requires_code_and_closes_other_sessions`,
  `test_regenerate_recovery_codes_invalidates_old`, `test_admin_reset_2fa_audits_and_mails`,
  `test_admin_reset_2fa_forbidden_without_users_edit`, `test_admin_cannot_reset_own_2fa`,
  `test_user_list_filter_mfa` (`?mfa=1` solo los que lo tienen; export igual),
  `test_secrets_and_codes_never_in_audit_or_payload` (recorre `AuditLog.changes` y `user_payload`).
- [ ] **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** PASS.

### Task 8: Frontend del segundo paso

**Files:**
- Create: `frontend/verificar_ingreso.html`, `frontend/assets/js/verificar_ingreso.js`
- Modify: `frontend/index.html` y `frontend/register.html` (ante `mfa_required`: guardar `{mfa_token, method,
  email_hint, remember}` en `sessionStorage.mfaChallenge` e ir a `verificar_ingreso.html`), `seguridad.html`/`seguridad.js`
  (bloque "Verificación en dos pasos"), `gestionuser.html` + JS (indicador "2 pasos", filtro, acción "Quitar verificación
  en dos pasos" con `appConfirm`), `reportes.js` (Seguridad: % con 2FA y por método — ver Task 12 para el dato)
- Test: contrato + e2e

**Interfaces:**
- `verificar_ingreso.html` (sin `auth.js` de sesión; usa `acceso.css`): sin `sessionStorage.mfaChallenge` → vuelve a
  `index.html`. Campo `inputmode="numeric" autocomplete="one-time-code" maxlength="6"`, link "Usar un código de
  recuperación" (cambia el campo a texto `xxxx-xxxx`), "Mandármelo de nuevo" solo con método email (cuenta regresiva 60 s),
  casilla "No pedirlo en este navegador por 30 días", errores en `#pageMessage`. `mfa_expired` → vuelve al login con
  "Pasó mucho tiempo, entrá de nuevo." Éxito → mismo destino que el login (incluido `pendingJoinCode`/
  `pendingTiendanubePrint`).
- `seguridad.html` bloque 2FA: estado; "Activar" → elegir "App autenticadora" / "Código por email"; app: QR
  (`<img src=qr>`), secreto con "Copiar", campo de código; email: campo de código; al confirmar, los códigos de
  recuperación en una grilla con "Copiar todos" y "Descargar" (.txt `rotulos-codigos-recuperacion.txt`) y el aviso de
  que no se vuelven a mostrar; "Códigos que quedan: N" + "Generar códigos nuevos"; "Desactivar".

- [ ] **Step 1:** Contrato `test_mfa_pages_exist` y e2e `"activar la app autenticadora y entrar pidiendo el código"`
  (el test calcula el TOTP con `crypto` de Node a partir del secreto mostrado) y
  `"un código de recuperación sirve una sola vez"`.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** PASS + check del frontend.
- [ ] **Step 5:** Verificar en el navegador con una app TOTP real o el cálculo del e2e; capturas de las dos pantallas.

**Checkpoint etapa 2:** suite `apps.accounts apps.audit`, flake8, check frontend, e2e `acceso.spec.js` y `admin.spec.js`.

---

## Etapa 3 — Dispositivos, avisos, historial y último ingreso

### Task 9: Aviso de navegador nuevo y mail de contraseña cambiada

**Files:** Modify `devices.py`, `login_flow.py`, `auth_views.py` (cambio y reset de contraseña), `security_mail.py`;
Test `backend/apps/accounts/tests/test_security_notices.py`

**Interfaces:**
- `devices.register_login(user, request, response, session, *, method) -> bool` (True si era nuevo): crea/actualiza
  `KnownDevice`, setea la cookie `rotulos_device` (HttpOnly, `AUTH_DEVICE_COOKIE_DAYS`, path `/api/v1/auth/`), y si es
  nuevo y `method != "register"` y el usuario no es interno → `new_device_mail` (throttle `new_device_mail`) + audit
  `auth.new_device`. Llamado desde `finish_login` en cada ingreso completo.
- Cambio/reset de contraseña → `password_changed_mail(kind)`.

- [ ] **Step 1: Tests**: `test_first_login_from_new_browser_sends_one_mail` (segundo login con la cookie → no),
  `test_register_does_not_send_new_device_mail`, `test_new_device_mail_capped_per_day`,
  `test_browser_without_cookie_counts_as_new`, `test_password_change_and_reset_send_mail`,
  `test_no_mail_for_internal_users`.
- [ ] **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** PASS.

### Task 10: Historial de seguridad y último ingreso

**Files:** Modify `security_views.py`, `urls.py`, `auth_views.user_payload`; frontend `seguridad.html`/`seguridad.js`
(bloque "Actividad de seguridad"), `frontend/dashboard.html` + `assets/js/dashboard.js` (línea "Tu ingreso anterior");
Test `test_security_notices.py`

**Interfaces:**
- `GET /auth/me/security-log/` (`users.me.view`) → últimos 30 `AuditLog` con `category="auth"` y (`actor=user` o
  `actor_email=user.email` para los fallidos) → `[{action, action_label, created_at, ip, browser}]` (`browser` con
  `browser_label`; nunca el UA crudo).
- `user_payload` suma `previous_login: {at, browser} | null` = la sesión anterior a la actual (por `created_at`), y
  `session_id`/`session_remember` (Task 4 ya los usa).
- Inicio: "Tu ingreso anterior: <fecha relativa>, <browser> · Ver actividad" (link a `seguridad.html#actividad`), en
  `--muted`, oculto si es null.

- [ ] **Step 1: Tests**: `test_security_log_only_own_events`, `test_security_log_includes_failed_attempts_for_own_email`,
  `test_previous_login_is_the_session_before_current`. **Step 2:** FAIL. **Step 3:** Implementar. **Step 4:** PASS.

### Task 11: Textos: ayuda, privacidad, guía

**Files:** `frontend/ayuda.html` (dos preguntas: "¿Cómo activo la verificación en dos pasos?" y "Perdí el celular, ¿cómo
entro?"), `frontend/privacidad.html` (navegador, IP y dispositivos conocidos de las sesiones; para qué y cuánto se
guardan), `docs/guia-primer-cliente.md` si nombra el login.

- [ ] **Step 1:** Escribir. **Step 2:** `node frontend/tools/check_frontend.mjs`.

**Checkpoint etapa 3.**

---

## Etapa 4 — Contraseña para cuentas de Google y cambio de email

### Task 12: Crear contraseña (Google) y datos de 2FA para Reportes

**Files:** Modify `security_views.py`, `urls.py`, `user_admin_views._metrics_*` (+ `mfa_adoption`), `reportes.js`;
frontend `seguridad.html` (bloque "Contraseña": "Crear una contraseña" si no tiene usable, si no link al cambio en Mi
cuenta); Test `backend/apps/accounts/tests/test_account_changes.py`

**Interfaces:**
- `POST /auth/me/set-password/` (`users.me.edit`) `{new_password, new_password_confirm, code?}`: con contraseña usable →
  400; con 2FA → `code` obligatorio (`verify_second_factor`); valida con `validate_password_strength` + validators de Django;
  audita `auth.password_set`; `password_changed_mail("set")`; `revoke_all(except_sid=actual)`.
- `GET /users/metrics/` suma `mfa_adoption: {total, enabled, totp, email}` (personas, sin usuarios internos); Reportes →
  Seguridad lo muestra en `.report-kpis`.

- [ ] **Step 1: Tests**: `test_google_account_can_set_password`, `test_set_password_refused_when_already_has_one`,
  `test_set_password_requires_mfa_code_when_enabled`, `test_metrics_mfa_adoption_excludes_internal_users`.
- [ ] **Step 2–4:** FAIL → implementar → PASS.

### Task 13: Cambiar el email

**Files:** Modify `security_views.py`, `urls.py`; Create `frontend/confirmar_cambio_email.html` +
`assets/js/confirmar_cambio_email.js` (página pública del link); `seguridad.html` (bloque "Email"); Test
`test_account_changes.py`

**Interfaces:**
- `POST /auth/me/change-email/` (`users.me.edit`, throttle `email_change`) `{new_email, password?, code?}`: reautenticación
  = contraseña si tiene usable, si no código de 2FA, si no tiene ninguno un código `reauth` por email
  (`POST /auth/2fa/reauth-email/` sirve también acá). `new_email` con `normalize_email` + `validate_email_format`; igual al
  actual → 400; ocupado por otra cuenta → 202 igual que el éxito pero sin mandar link (no revela). Crea
  `EmailChangeRequest` (token aleatorio, hash, `EMAIL_CHANGE_HOURS`), manda `email_change_link_mail` al NUEVO con link a
  `<FRONTEND_URL>/confirmar_cambio_email.html?token=…` → 202.
- `POST /auth/me/change-email/confirm/` (AllowAny, throttle) `{token}`: vencido/usado/ocupado-desde-entonces → 400;
  ok → `email` y `username` = nuevo, marca verificado (crea/limpia `EmailVerification` como corresponda), audita
  `auth.email_change` (`changes={"email": {"from": masked, "to": masked}}`), `email_changed_old_mail` al viejo,
  `revoke_all(user, reason="email")` → 200 "Listo, entrá con tu email nuevo."
- La pantalla avisa antes de confirmar: "Si entrás con Google, después del cambio vas a tener que usar la cuenta de Google
  de tu email nuevo."

- [ ] **Step 1: Tests**: `test_change_email_requires_reauth`, `test_change_email_sends_link_only_to_new_address`,
  `test_email_not_changed_until_link_opened`, `test_confirm_changes_username_and_notifies_old_email`,
  `test_taken_email_is_not_revealed` (misma respuesta, sin mail, nada cambia), `test_email_change_normalizes_case`,
  `test_expired_change_link_rejected`, `test_confirm_closes_all_sessions`.
- [ ] **Step 2–4:** FAIL → implementar → PASS. **Step 5:** e2e `"cambiar el email con el link"` (mail a consola, el test lee
  el link del log como los otros e2e de mail).

**Checkpoint etapa 4.**

---

## Etapa 5 — Detalles del login

### Task 14: Medidor de contraseña, Mayúsculas y "cómo entró"

**Files:** Modify `frontend/assets/js/utils.js`, `frontend/assets/css/acceso.css` (o `ui.css` si se usa fuera del acceso),
`frontend/index.html`, `frontend/register.html`, `frontend/reset-password.html`, `frontend/organizacion.html` (cambio de
contraseña), `seguridad.html` (crear contraseña); Test contrato + e2e

**Interfaces (utils.js):**
- `attachPasswordMeter(input: HTMLInputElement, container: HTMLElement)`: barra de 3 niveles (`--danger-500` débil,
  `--warning-500` aceptable, `--accent-500` fuerte) y la lista de requisitos de `validate_password_strength` (8
  caracteres, una mayúscula, un número) tildados en vivo; "fuerte" = cumple todo y tiene 12+ caracteres o un símbolo.
  `aria-live="polite"`.
- `attachCapsLockWarning(input)`: con `getModifierState("CapsLock")` en `keydown`/`keyup` muestra "Tenés las mayúsculas
  activadas" debajo del campo. Se engancha solo a todo `input[type=password][data-reveal]` en las páginas de acceso.
- "Cómo entró": al terminar un login, `localStorage.lastLoginMethod = "password"|"google"`; en `index.html`, si es
  `google`, un texto "La última vez entraste con Google" arriba del botón de Google y el botón con clase de resaltado.
  Nunca se guarda el email.

- [ ] **Step 1:** Contrato `test_password_meter_and_caps_lock_helpers_exist` (utils.js define las dos funciones y las 5
  páginas las usan) y e2e `"el medidor marca lo que falta"`.
- [ ] **Step 2–4:** FAIL → implementar → PASS + check del frontend.
- [ ] **Step 5:** Verificar en el navegador a 375 px y en modo oscuro si la página lo tiene.

### Task 15: Documentación y cierre

**Files:** `CLAUDE.md` (sección nueva "Account security" bajo Auth & identity: sesiones/`sid`, `finish_login` como único
camino, 2FA, dispositivos, inactividad, endpoints, settings), `HELP_ME.md` (cómo destrabar a alguien: "Quitar
verificación en dos pasos" y "Cerrar todas sus sesiones"), `docs/erd.md` regenerado.

- [ ] **Step 1:** Escribir. **Step 2:** Suite completa `python manage.py test`, `flake8`, `node frontend/tools/check_frontend.mjs`,
  e2e completo (`cd frontend/e2e && npm test`). Todo verde.
- [ ] **Step 3:** Revisión final de la rama (requesting-code-review) antes de pedirle al usuario que decida el commit.
