"""El único final de un ingreso: email+contraseña, Google y registro terminan
en ``finish_login``. Abre la sesión (``sessions.py``), entrega los tokens
(en cookies o en el cuerpo, ver ``auth_cookies.py``) y audita el ingreso.

Que haya UN solo final es lo que garantiza que una regla nueva del ingreso
(el segundo paso, el aviso de navegador nuevo) no se pueda esquivar entrando
por otra puerta.
"""

from __future__ import annotations

from rest_framework import status as http_status
from rest_framework.response import Response

from apps.audit.services import record

from . import devices, mfa
from .auth_cookies import deliver_tokens
from .sessions import issue_tokens


def parse_remember(value) -> bool | None:
    """``remember`` del cuerpo: True/False si vino, ``None`` si no (clientes de
    la API y tests: todo como antes)."""
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "on", "yes", "si", "sí")
    return bool(value)


def finish_login(
    request,
    user,
    *,
    remember: bool | None,
    method: str,
    picture: str = "",
    extra: dict | None = None,
    status_code: int = http_status.HTTP_200_OK,
    audit: bool = True,
    mfa_method: str = "",
    skip_mfa: bool = False,
) -> Response:
    """Con la verificación en dos pasos activa (y un navegador que no es de
    confianza) NO entrega tokens: responde el desafío (``mfa_challenge``) y
    el ingreso termina en ``2fa/verify/``, que vuelve a llamar acá con
    ``skip_mfa``."""
    from .auth_views import user_payload

    device = devices.current_device_id(request)
    if not skip_mfa and mfa.mfa_enabled(user) and not devices.is_trusted(user, device):
        return mfa_challenge(request, user, remember=remember, method=method)

    session, tokens = issue_tokens(user, request, remember=remember, method=method, mfa_method=mfa_method)
    request._rotulos_session = session
    if audit:
        changes = {"remember": {"from": None, "to": bool(remember)}}
        if mfa_method:
            changes["2fa"] = {"from": None, "to": mfa_method}
        record(
            request,
            actor=user,
            category="auth",
            action="auth.login_success",
            target=user,
            target_type="user",
            target_repr=user.email,
            actor_email=user.email,
            changes=changes,
        )
    _row, is_new = devices.remember_device(user, request, device)
    # El registro es, por definición, el primer navegador: no se avisa.
    if is_new and method != "register":
        devices.notify_new_device(user, request, session)
    body = {**(extra or {}), **tokens, "user": user_payload(user, picture, request)}
    response = deliver_tokens(request, Response(body, status=status_code), remember=remember)
    return devices.ensure_device_cookie(request, response)


def mfa_challenge(request, user, *, remember, method: str) -> Response:
    """Lo que responde un ingreso al que le falta el código. Con el método por
    email, el código sale ya."""
    config = mfa.config_of(user)
    if config.method == config.Method.EMAIL:
        try:
            mfa.send_email_code(user, "login")
        except Exception:  # noqa: BLE001 — sin mail igual se puede usar un código de recuperación
            pass
    body = {
        "mfa_required": True,
        "mfa_token": mfa.make_mfa_token(user, remember=remember, method=method),
        "method": config.method,
        "email_hint": mfa.email_hint(user.email) if config.method == config.Method.EMAIL else "",
    }
    return devices.ensure_device_cookie(request, Response(body))
