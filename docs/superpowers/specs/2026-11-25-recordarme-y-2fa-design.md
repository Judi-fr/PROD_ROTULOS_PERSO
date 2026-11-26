# "Recordarme", verificación en dos pasos y más seguridad de la cuenta — diseño

Fecha: 2026-11-25. Estado: borrador para aprobar (incluye las 12 mejoras de comodidad elegidas el mismo día).

## Por qué

La app ya está publicada (https://rotulos.human-log.org) y maneja datos de compradores, tiendas conectadas y
cuentas de transportistas de cada comercio. Hoy una cuenta se protege solo con la contraseña (o Google) y el
bloqueo progresivo por intentos fallidos. El usuario pidió:

1. una casilla **"Recordarme"** en el login, y
2. más medidas de seguridad: **verificación en dos pasos**, más tres extras que eligió — **aviso por mail de
   ingreso desde un navegador nuevo**, **ver y cerrar sesiones abiertas** y **códigos de recuperación**.

## Decisiones del usuario (2026-11-25)

| Tema | Decisión |
|---|---|
| Recordarme | Mantiene la sesión: **marcada = 30 días**; **sin marcar = se cierra al cerrar el navegador** |
| Método del segundo paso | **Los dos, a elección**: app autenticadora (TOTP) o código por email; cada persona elige al activarla |
| Para quién | **Opcional para todos** (admin incluido), se activa desde la cuenta |
| Entrar con Google | Si la persona la activó, **también se pide el código** al entrar con Google |
| Mismo navegador | Casilla **"No pedirlo en este navegador por 30 días"** al poner el código |
| Perdió el celular y los códigos | **El admin se la desactiva** desde Usuarios: queda en auditoría y le llega un mail a la persona |
| Aviso de ingreso | Mail **solo cuando se entra desde un navegador que esa cuenta nunca usó** |
| Extras | Aviso por mail de ingreso nuevo, ver y cerrar sesiones, códigos de recuperación |

## Objetivos

- Que el comerciante en su PC propia no tenga que entrar todos los días, y que en una PC compartida (depósito)
  la sesión no quede abierta.
- Que robar o adivinar la contraseña no alcance para entrar a una cuenta que activó el segundo paso.
- Que la persona se entere si alguien entró desde otro lado y pueda echarlo.
- Que nadie quede afuera para siempre por perder el celular.

## No objetivos

- No es obligatoria para nadie (ni para el admin, ni la puede exigir el dueño a su equipo). Puede venir después.
- No se toca la autenticación de las otras puertas: API keys de ingesta, tokens del agente de impresión,
  callbacks firmados de tiendas, links firmados de impresión. Siguen como están.
- No SMS ni WhatsApp (cuestan plata y necesitan proveedor). No llaves físicas / passkeys por ahora.
- No geolocalización por IP (necesitaría un servicio externo y es dato personal extra).

## Anti-objetivos (fallaría aunque "ande")

- Que **algún camino de entrada se saltee el segundo paso**: email+contraseña, Google, registro, el link de
  "olvidé mi contraseña", o un refresh de una sesión cerrada.
- Que el **link de "olvidé mi contraseña" desactive el segundo paso** (sería la forma fácil de saltearlo:
  quien roba el mail resetea y entra).
- Que se pueda **adivinar el código** por fuerza bruta.
- Que un comerciante quede **bloqueado sin salida** (por eso el rescate del admin).
- Que el texto del secreto TOTP, los códigos o los tokens queden en logs, en la auditoría o en la respuesta de
  otra pantalla que no sea la de activación.

## Cómo funciona hoy (lo que hay que respetar)

- `LoginView`, `GoogleAuthView` y `RegisterView` terminan en `auth_response(user)` → `tokens_for_user` (access
  15 min, refresh 7 días con rotación + blacklist). En modo cookie (`X-Auth-Mode: cookie`) los tokens van en
  cookies HttpOnly (`auth_cookies.py`, `max_age` = vida del token) y se sacan del JSON.
- Bloqueo por intentos: `LoginLockout` (3 fallos → 1, 2, 4… min, tope 1 h), además del throttle `login`.
- Confirmar el email es obligatorio para cuentas del formulario (`email_not_verified`).
- Auditoría con `apps.audit.services.record`, acciones en `AuditLog.Action` + `ACTION_CATEGORIES`.
- Mails con `apps/common/mail.branded_html`. SMTP con cupo diario compartido.

## Diseño

### 1. Sesiones con nombre (base de todo lo demás)

Cada inicio de sesión crea una **sesión** (`SessionRecord`): persona, cuándo empezó, última actividad, navegador
legible ("Chrome en Windows", sacado del user agent), IP, si es "recordada", y cuándo se cerró. El refresh token
lleva el id de la sesión (`sid`) y si es recordada (`remember`) como claims; simplejwt los copia al rotar, así
que toda la cadena de refresh es la misma sesión.

- **Refresh**: si la sesión está cerrada → 401 "La sesión se cerró" y se borran las cookies. Se actualiza
  "última actividad" (como mucho una vez por minuto, para no escribir en cada refresh).
- **Access**: también lleva `sid`. *Decisión del diseño:* `JWTAuthenticationWithPasswordPolicy` rechaza un access
  de una sesión cerrada (una consulta por request, con el cache por request que ya usa la app), así "cerrar
  sesión en todos lados" echa al otro al instante y no 15 min después. Si se considera caro, el builder puede
  caer a "corta en el próximo refresh" y anotarlo.
- **Tokens viejos sin `sid`** (sesiones abiertas antes del cambio): siguen valiendo hasta vencer; no aparecen en
  la lista. "Cerrar todas" también los revoca (blacklist de todos los refresh, como el reset de contraseña).
- Logout cierra su sesión. Cambiar contraseña, reset de contraseña y desactivar el segundo paso cierran **todas
  las demás**.

### 2. Recordarme

Casilla "Mantener la sesión iniciada" en `index.html`, **desmarcada por defecto** (decisión del diseño: lo seguro
para la PC compartida; quien la marca una vez la ve marcada la próxima — se recuerda en localStorage solo la
preferencia, no el email).

- **Marcada**: refresh de 30 días (`AUTH_REMEMBER_DAYS`), cookie con `max_age` de 30 días. La rotación mantiene los
  30 días (hoy `set_exp()` al rotar volvería a 7: hay que respetar el claim `remember`).
- **Sin marcar**: la cookie del refresh va **sin `max_age`** (cookie de sesión: el navegador la borra al cerrarse) y
  el token dura `AUTH_SESSION_HOURS` (12 h, decisión del diseño: si el navegador "restaura pestañas" y guarda las
  cookies de sesión, igual vence en el día).
- El body sin `remember` (clientes por Bearer, la suite de tests) sigue con los 7 días de hoy.
- Google: el botón de Google respeta la misma casilla. Registro: entra sin recordar.

### 3. Verificación en dos pasos

**Activar** (pantalla nueva `seguridad.html`, ver Frontend):

- *App autenticadora*: el backend genera un secreto (guardado cifrado con `apps.integrations.crypto`, como los
  tokens de tienda), muestra el QR (`otpauth://totp/Human Log Rótulos:<email>?secret=…&issuer=Human Log Rótulos`,
  dibujado con `qrcode`, que ya está en requirements) y el secreto en texto para copiar. Se activa recién cuando la
  persona escribe un código válido. TOTP estándar: 6 dígitos, 30 s, SHA1, acepta ±1 paso. *Decisión del builder:*
  `pyotp` o una implementación propia de RFC 6238 con stdlib.
- *Código por email*: se manda un código de 6 dígitos al email de la cuenta y se activa al escribirlo. Requiere
  email verificado.
- Al activar (cualquiera de los dos) se generan **10 códigos de recuperación** (formato `xxxx-xxxx`, sin
  caracteres ambiguos), guardados **hasheados**, mostrados **una sola vez** con "Copiar" y "Descargar .txt". Se
  pueden regenerar (invalida los anteriores; pide un código).
- Una persona tiene **un** método activo; cambiar de método = desactivar y activar el otro.

**Al entrar** (email+contraseña o Google), si tiene el segundo paso activo y el navegador no es de confianza:

1. El login **no** entrega tokens: responde `200 {"mfa_required": true, "mfa_token", "method", "email_hint"}`.
   `mfa_token` es firmado (`django.core.signing`), dura 5 min, lleva el usuario, si pidió recordar y cómo entró.
   No cuenta como login exitoso todavía (ni `last_login`, ni auditoría de éxito).
2. Con método email, el backend **ya manda** el código al responder; hay "Mandármelo de nuevo" (throttle propio
   por usuario, p. ej. 1 cada 60 s y 10 por día, como los otros que mandan mail).
3. `POST /auth/2fa/verify/ {mfa_token, code, trust_browser}` → si el código (o un código de recuperación) es
   válido: tokens, sesión, auditoría `auth.login_success` con `changes: {"2fa": "totp"|"email"|"recovery"}`.
4. **Intentos**: cada código mal suma al mismo `LoginLockout` de la cuenta (3 fallos → bloqueo progresivo). El
   código por email vence a los 10 min y es de un solo uso; un código TOTP ya usado no se acepta dos veces.
5. Usar un código de recuperación lo gasta y manda un mail avisando ("Usaste un código de recuperación, te quedan
   N").

**Navegador de confianza**: si marcó "No pedirlo en este navegador por 30 días", se guarda en el dispositivo
conocido (abajo) `trusted_until`. Se borra toda la confianza al desactivar el segundo paso, al cambiar o resetear la
contraseña y al "cerrar todas las sesiones".

**Desactivar**: desde `seguridad.html`, pidiendo un código válido (app o email) o un código de recuperación — no la
contraseña, porque quien entra con Google no tiene. Mail de aviso a la persona. Cierra las demás sesiones.

**Rescate del admin**: en `gestionuser.html`, la fila/detalle del usuario muestra si tiene el segundo paso y el admin
(permiso `users.edit`, *decisión del diseño*: no hace falta uno nuevo) puede "Quitar verificación en dos pasos" con
confirmación. Audita `auth.mfa_admin_reset` con el admin como actor y manda mail a la persona ("Un administrador
desactivó…; si no lo pediste, escribí a soporte"). No se puede usar sobre uno mismo (se usa el camino normal).

**El reset de contraseña no toca el segundo paso**: después de resetear, entrar sigue pidiendo el código.

### 4. Dispositivos conocidos y aviso de ingreso nuevo

Una cookie HttpOnly de larga vida `rotulos_device` (id aleatorio, 1 año, path `/api/v1/auth/`) identifica al
navegador. `KnownDevice(user, device_hash, first_seen, last_seen, user_agent_label, trusted_until)`.

- En cada ingreso completo (después del segundo paso, si lo hay): si ese navegador no figura para esa persona →
  se crea y se manda el mail **"Nuevo ingreso a tu cuenta"**: cuándo, navegador, IP, y "Si no fuiste vos: cambiá la
  contraseña y cerrá las sesiones" con link a `seguridad.html`. No se manda en el primer ingreso de una cuenta
  recién creada (registro) ni para usuarios internos (`teams.internal_users_q`).
- Si no hay cookie (navegador sin cookies), cuenta como nuevo — *decisión del diseño*; el throttle de mails evita
  el spam (como mucho N avisos por día por persona).

### 5. Ver y cerrar sesiones

En `seguridad.html`: lista de sesiones abiertas (navegador, IP, inicio, última actividad, "Esta sesión", "Recordada")
con "Cerrar" en cada una y "Cerrar todas las demás". API `GET /auth/sessions/`, `POST /auth/sessions/<id>/revoke/`,
`POST /auth/sessions/revoke-others/`. Solo las propias. Auditado (`auth.session_revoke`).

### 6. Mejoras de comodidad (pedidas el 2026-11-25, todas incluidas)

**Acceso y contraseña**

- **Medidor de contraseña** en el registro, el reset y el cambio de contraseña: barra débil/aceptable/fuerte y la
  lista de requisitos que faltan (8 caracteres, una mayúscula, un número), en vivo. Las reglas son las de
  `validate_password_strength`; el backend sigue siendo quien decide (el medidor solo adelanta lo que va a decir).
  Va en `utils.js` para que lo usen las tres pantallas.
- **Aviso de Mayúsculas activadas** en todo campo de contraseña de las pantallas de acceso (`getModifierState`), en
  `utils.js`, junto al mostrar/ocultar (`data-reveal`) que ya existe.
- **Contraseña para cuentas de Google**: hoy quien se registró con Google no tiene contraseña usable y "Cambiar
  contraseña" le pide la actual, así que no puede crear una. En `seguridad.html`, si `has_usable_password` es
  falso: "Crear una contraseña" (nueva + repetir, mismas reglas), sin pedir la actual pero **pidiendo el código del
  segundo paso si lo tiene activo**. Endpoint `POST /auth/me/set-password/` (solo para cuentas sin contraseña
  usable; con contraseña → 400 y se usa el cambio normal). Mail de aviso como cualquier cambio de contraseña.
- **Recordar cómo entró**: el navegador guarda en localStorage solo el método (`password`|`google`), nunca el email.
  En `index.html`, si fue Google: "La última vez entraste con Google" y ese botón resaltado.

**La cuenta de cada persona**

- **Cambiar el email** (hoy no se puede): en `seguridad.html`, "Cambiar email" pide el email nuevo y **volver a
  confirmar la identidad** (contraseña, o el código del segundo paso; con Google sin contraseña ni segundo paso, un
  código al email actual). Se manda un link al email NUEVO (vence en 24 h, reusa el patrón de `EmailVerification`);
  recién al abrirlo cambia el email y el username (el email es el username). Al email VIEJO le llega un aviso "Tu
  email cambió a n***@… — si no fuiste vos, escribí a soporte". Un email ya usado por otra cuenta → error genérico
  sin revelar que existe (mismo criterio que el registro). Cierra las demás sesiones. Auditado `auth.email_change`.
  **Ojo con Google**: `GoogleAuthView` busca la cuenta por email, así que después del cambio "Continuar con Google"
  solo sirve con la cuenta de Google del email NUEVO (con la vieja crearía otra cuenta). La pantalla lo avisa antes de
  confirmar. Invitaciones pendientes dirigidas al email viejo no se migran.
- **Historial de seguridad**: en `seguridad.html`, los últimos 30 eventos de la propia cuenta de la categoría `auth`
  (ingresos con navegador e IP, intentos fallidos, bloqueos, cambios de contraseña/email/segundo paso, sesiones
  cerradas). `GET /auth/me/security-log/`, solo los propios, sin `user_agent` crudo (el nombre legible).
- **Último ingreso al entrar**: `user_payload` suma `previous_login` (fecha + navegador de la sesión anterior); Inicio
  muestra una línea discreta "Tu ingreso anterior: ayer 18:40, Chrome en Windows · Ver actividad" que lleva al
  historial. Se calcula de `SessionRecord`.
- **Mail al cambiar la contraseña**: cambio, reset y creación (cuentas de Google) mandan "Tu contraseña cambió" con
  fecha, navegador y "Si no fuiste vos: recuperá la cuenta" (link al reset).

**Sesiones y PC compartida**

- **Cierre por inactividad**: solo en sesiones SIN "Recordarme". A los **30 minutos** sin actividad del usuario
  (`AUTH_IDLE_MINUTES`; actividad = clic, tecla o scroll en cualquier pestaña de la app) se cierra la sesión. Al
  minuto 29 un aviso "Tu sesión se va a cerrar en 1 minuto" con "Seguir conectado". Lo coordina el frontend entre
  pestañas (`localStorage` + evento `storage`, en `auth.js`); el backend también lo hace cumplir: el refresh de una
  sesión no recordada cuya última actividad pasó el límite responde 401 (así no depende de que el navegador
  colabore). Las pantallas que se refrescan solas (Inicio, cola de impresión) NO cuentan como actividad.
- **Desactivar o bloquear a alguien cierra todo**: `users.deactivate`, el borrado y el bloqueo por intentos cierran
  todas sus sesiones al instante (con el chequeo de `sid` del punto 1).
- **El admin cierra sesiones**: en el detalle del usuario, "Cerrar todas sus sesiones" (`users.edit`), con
  confirmación, auditado `auth.session_revoke` con el admin como actor. No toca el segundo paso ni la contraseña.
- **El admin ve quién tiene el segundo paso**: columna/indicador y filtro "Verificación en dos pasos: sí/no" en
  `gestionuser.html` (y en la exportación), y en Reportes → Seguridad el porcentaje de personas con el segundo paso
  activo y por método.

### API nueva (bajo `/api/v1/auth/`, todas de la propia persona salvo la del admin)

- `POST login/` y `POST google/`: aceptan `remember`; pueden responder `mfa_required`.
- `POST 2fa/verify/`, `POST 2fa/resend/` (públicas: se autentican con el `mfa_token`; throttle).
- `GET 2fa/` (estado: activo, método, códigos de recuperación que quedan).
- `POST 2fa/setup/ {method}` (devuelve QR + secreto, o manda el mail), `POST 2fa/confirm/ {code}` (activa, devuelve
  los códigos de recuperación), `POST 2fa/disable/ {code}`, `POST 2fa/recovery-codes/ {code}` (regenera).
- `GET sessions/`, `POST sessions/<id>/revoke/`, `POST sessions/revoke-others/`.
- `POST me/set-password/`, `POST me/change-email/` + `POST me/change-email/confirm/ {token}`,
  `GET me/security-log/`.
- Admin: `POST /api/v1/users/<id>/reset-2fa/` y `POST /api/v1/users/<id>/revoke-sessions/` (`users.edit`); filtro
  `?mfa=1|0` en `GET /users/` y `/users/export/`.
- Permiso para las propias: `users.me.edit` (ya lo tiene todo el mundo). Todas las de escritura con el throttle que
  corresponda; las que mandan mail, con un throttle por usuario y por día como las de reset.

### Auditoría

Acciones nuevas en `AuditLog.Action` (categoría `auth`): `auth.mfa_enable`, `auth.mfa_disable`,
`auth.mfa_admin_reset`, `auth.mfa_failed`, `auth.recovery_code_used`, `auth.recovery_codes_regenerated`,
`auth.session_revoke`, `auth.new_device`, `auth.email_change`, `auth.password_set`. Nunca el secreto ni códigos en `changes`.

### Frontend

- `index.html`: casilla "Mantener la sesión iniciada" (también aplica al botón de Google).
- **Página nueva `verificar_ingreso.html`** + `assets/js/verificar_ingreso.js` (regla del proyecto: una página por
  función): recibe el `mfa_token` por `sessionStorage` (nunca en la URL), campo de 6 dígitos con
  `autocomplete="one-time-code"`, "Usar un código de recuperación", "Mandármelo de nuevo" (solo método email), la
  casilla de confianza, y vuelve al login si el token venció. Mismo estilo de acceso (`acceso.css`).
- **Página nueva `seguridad.html`** + `assets/js/seguridad.js`: tres bloques — Verificación en dos pasos (estado,
  activar con elección de método, QR/código, códigos de recuperación, desactivar), Sesiones abiertas, y el
  recordatorio de cambiar la contraseña (link a la sección de Mi cuenta). Enlazada desde el menú de la cuenta del
  topbar ("Seguridad"), desde Mi cuenta y desde el link de los mails. Sumarla a `IN_PAGE_TOOLS`/búsqueda.
- `gestionuser.html`: indicador "2 pasos" en el usuario y la acción "Quitar verificación en dos pasos".
- `ayuda.html`: dos preguntas frecuentes (cómo activarla; perdí el celular).
- `privacidad.html`: agregar que se guardan navegador e IP de las sesiones y los dispositivos conocidos.
- Los textos de los botones se nombran en `guia-primer-cliente.md`/FAQ si aparecen.

### Settings nuevos (con defaults, sobreescribibles desde `.env`)

`AUTH_REMEMBER_DAYS` (30), `AUTH_SESSION_HOURS` (12), `MFA_TOKEN_MAX_AGE_SECONDS` (300),
`MFA_EMAIL_CODE_MINUTES` (10), `MFA_TRUST_DAYS` (30), `MFA_RECOVERY_CODES` (10), `AUTH_DEVICE_COOKIE_DAYS` (365),
`AUTH_IDLE_MINUTES` (30), `EMAIL_CHANGE_HOURS` (24), throttles `mfa_verify`, `mfa_email`, `new_device_mail`, `email_change`.

### Pruebas que tienen que existir

- Cada camino de entrada con el segundo paso activo NO entrega tokens sin código: login, Google, refresh de una sesión
  cerrada, reset de contraseña + login.
- Código mal suma al bloqueo; código TOTP repetido rechazado; código por email vencido o ya usado rechazado; código de
  recuperación de un solo uso.
- Recordarme: cookie con/sin `max_age` y el claim que sobrevive a la rotación (30 días siguen siendo 30).
- Cerrar sesión: el otro navegador queda afuera en su próximo request.
- Aviso de navegador nuevo: se manda una vez, no en el registro.
- Admin quita el segundo paso: auditado, mail, no sobre sí mismo, sin permiso → 403.
- Nada del secreto/códigos en la auditoría ni en `user_payload`.
- Un e2e: activar con app (calculando el TOTP en el test) → salir → entrar pidiendo el código.
- Inactividad: el refresh de una sesión no recordada inactiva da 401; una recordada no. Cambio de email: no cambia
  hasta abrir el link, avisa al viejo, email ocupado no se revela. Crear contraseña solo sin contraseña usable.
  Desactivar a alguien lo deja afuera en su próximo request. Historial: solo eventos propios.

## Lo que queda a criterio del builder

- Librería TOTP (pyotp) o implementación propia; cómo cachear el chequeo de sesión por request.
- Nombre y forma exacta de los modelos (`SessionRecord`, `KnownDevice`, `UserMfa`, `MfaRecoveryCode`) y de las
  migraciones (más los permisos/acciones de auditoría que requieran).
- Cómo armar el nombre legible del navegador desde el user agent (sin librerías pesadas).
- Textos exactos de los mails (con `branded_html`) y de las pantallas, en el tono del resto de la app.

## Decisiones que tomé yo (no las pidió el usuario; revisar)

1. "Recordarme" arranca **desmarcada**; sin marcar, la sesión vence también a las **12 h** aunque el navegador
   guarde la cookie.
2. Cerrar una sesión corta **al instante** (chequeo del `sid` en cada request), no a los 15 min.
3. El segundo paso se desactiva con **un código**, no con la contraseña (por las cuentas de Google).
4. El rescate del admin usa el permiso existente **`users.edit`**.
5. Cambiar/resetear la contraseña cierra las **demás** sesiones y borra los navegadores de confianza, pero **no**
   desactiva el segundo paso.
6. Un navegador sin cookie de dispositivo cuenta como **nuevo** para el aviso (con tope de mails por día).
7. Los errores de código suman al **mismo bloqueo** que la contraseña.
8. Cambiar el email pide **volver a confirmar la identidad** y un link al email nuevo; el viejo recibe aviso.
9. Crear contraseña (cuentas de Google) y cerrar las sesiones de otro desde el admin usan permisos existentes
   (`users.me.edit` y `users.edit`).
10. La inactividad la hace cumplir también el backend en el refresh; las pantallas que se refrescan solas no cuentan
    como actividad.
11. "Recordar cómo entró" guarda solo el método, nunca el email.

## Tamaño

Es grande: conviene implementarlo en etapas que se puedan probar y subir por separado, en este orden — (1) sesiones
+ Recordarme + inactividad + cierres del admin, (2) segundo paso + códigos de recuperación + navegador de confianza +
rescate, (3) dispositivos conocidos + avisos por mail + historial + último ingreso, (4) contraseña para Google +
cambio de email, (5) medidor, Mayúsculas y "cómo entró". El plan define las etapas exactas.
