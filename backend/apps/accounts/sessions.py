"""Sesiones con nombre (``SessionRecord``) y "Recordarme".

Cada inicio de sesión es una fila; su id viaja como claim ``sid`` en el
refresh y el access JWT, junto con ``remember`` (si la persona marcó
"Mantener la sesión iniciada") y ``life`` (la vida en segundos del refresh).
simplejwt copia los claims al rotar, así que toda la cadena de refresh es la
misma sesión; ``life`` es lo que permite que la rotación respete los 30 días
de una sesión recordada (su ``set_exp()`` volvería a los 7 del default).

Cerrar una sesión deja afuera a ese navegador en su próximo request
(``authentication.py`` y el refresh consultan ``active_session``). Los
tokens viejos, sin ``sid``, siguen valiendo hasta vencer; ``revoke_all``
también los revoca (blacklist de todos los refresh de la persona).
"""

from __future__ import annotations

import re
from datetime import timedelta

import base64
import json

from django.conf import settings
from django.core.exceptions import ValidationError
from django.contrib.auth.models import update_last_login
from django.utils import timezone
from rest_framework_simplejwt.settings import api_settings as jwt_settings
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken

from .security_models import KnownDevice, SessionRecord

# Cada cuánto, como mucho, se escribe ``last_seen_at`` (para no escribir en
# cada refresh de cada pestaña).
TOUCH_EVERY = timedelta(minutes=1)

_BROWSERS = (
    (re.compile(r"Edg(e|A|iOS)?/"), "Edge"),
    (re.compile(r"OPR/|Opera"), "Opera"),
    (re.compile(r"SamsungBrowser/"), "Samsung Internet"),
    (re.compile(r"Firefox/|FxiOS/"), "Firefox"),
    (re.compile(r"Chrome/|CriOS/|Chromium/"), "Chrome"),
    (re.compile(r"Safari/"), "Safari"),
)
_SYSTEMS = (
    (re.compile(r"iPhone"), "iPhone"),
    (re.compile(r"iPad"), "iPad"),
    (re.compile(r"Android"), "Android"),
    (re.compile(r"Windows"), "Windows"),
    (re.compile(r"CrOS"), "ChromeOS"),
    (re.compile(r"Mac OS X|Macintosh"), "Mac"),
    (re.compile(r"Linux"), "Linux"),
)


def browser_label(user_agent: str) -> str:
    """"Chrome en Windows", "Safari en iPhone"… para mostrarle a la persona."""
    user_agent = user_agent or ""
    browser = next((name for pattern, name in _BROWSERS if pattern.search(user_agent)), "")
    system = next((name for pattern, name in _SYSTEMS if pattern.search(user_agent)), "")
    if browser and system:
        return f"{browser} en {system}"
    return browser or system or "Navegador desconocido"


def _client_ip(request):
    from apps.audit.services import _extract_ip

    return _extract_ip(request)


def _user_agent(request):
    return ((request.META.get("HTTP_USER_AGENT") if request is not None else "") or "")[:400]


def start_session(user, request, *, remember: bool, method: str, mfa_method: str = "") -> SessionRecord:
    user_agent = _user_agent(request)
    return SessionRecord.objects.create(
        user=user,
        ip=_client_ip(request),
        user_agent=user_agent,
        browser=browser_label(user_agent),
        remember=bool(remember),
        method=method,
        mfa_method=mfa_method,
    )


def refresh_lifetime(remember: bool | None) -> timedelta:
    """Vida del refresh: 30 días recordada, 12 h sin recordar, y el default de
    simplejwt (7 días) cuando el cliente no dijo nada (API, tests)."""
    if remember is True:
        return timedelta(days=settings.AUTH_REMEMBER_DAYS)
    if remember is False:
        return timedelta(hours=settings.AUTH_SESSION_HOURS)
    return jwt_settings.REFRESH_TOKEN_LIFETIME


def tokens_for_session(session: SessionRecord, remember: bool | None) -> dict[str, str]:
    """``remember`` es lo que pidió el cliente (``None`` = no dijo nada); la
    sesión guarda solo si quedó recordada."""
    lifetime = refresh_lifetime(remember)
    refresh = RefreshToken.for_user(session.user)
    refresh.set_exp(lifetime=lifetime)
    refresh["sid"] = str(session.id)
    # None = el cliente no eligió (API, tests): la cookie queda como siempre.
    refresh["remember"] = remember
    refresh["life"] = int(lifetime.total_seconds())
    # El OutstandingToken lo creó for_user ANTES de estos claims: se guarda el
    # token final (la blacklist, logout y revoke_all lo buscan por su texto y
    # leen su sid) y su vida real.
    OutstandingToken.objects.filter(jti=refresh[jwt_settings.JTI_CLAIM]).update(
        token=str(refresh), expires_at=timezone.now() + lifetime
    )
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


def issue_tokens(user, request, *, remember: bool | None, method: str, mfa_method: str = ""):
    """Abre la sesión y devuelve ``(session, tokens)``. Marca el último ingreso
    (``update_last_login``, ver ``auth_views.tokens_for_user``)."""
    update_last_login(None, user)
    # Solo quien eligió NO mantenerla (la casilla del login) tiene una sesión
    # que se cierra por inactividad; un cliente que no dijo nada (API) sigue
    # como antes.
    session = start_session(user, request, remember=remember is not False, method=method, mfa_method=mfa_method)
    return session, tokens_for_session(session, remember)


# El navegador es quien mide la inactividad al minuto (auth.js) y avisa que
# hay actividad como mucho cada PING_EVERY; el servidor la hace cumplir con
# este margen encima, para no cerrarle la sesión antes a quien la estuvo usando.
IDLE_GRACE = timedelta(minutes=5)


def _idle_limit():
    return timedelta(minutes=settings.AUTH_IDLE_MINUTES) + IDLE_GRACE


def active_session(sid) -> SessionRecord | None:
    """La sesión si sigue abierta; ``None`` si no existe, se cerró o (sin
    "Recordarme") pasó ``AUTH_IDLE_MINUTES`` sin actividad, en cuyo caso la
    cierra con motivo ``idle``."""
    if not sid:
        return None
    try:
        session = SessionRecord.objects.select_related("user").get(pk=sid)
    except (SessionRecord.DoesNotExist, ValueError, TypeError, ValidationError):
        # Un sid roto es "no hay sesión".
        return None
    if not session.is_active:
        return None
    if not session.remember and session.last_seen_at < timezone.now() - _idle_limit():
        revoke_session(session, "idle")
        return None
    return session


def touch(session: SessionRecord, *, activity: bool) -> None:
    """Marca actividad (como mucho una vez por minuto). Un refresh que no viene
    de una acción de la persona (``activity`` False) no la mantiene viva."""
    if not activity:
        return
    now = timezone.now()
    if session.last_seen_at > now - TOUCH_EVERY:
        return
    SessionRecord.objects.filter(pk=session.pk).update(last_seen_at=now)
    session.last_seen_at = now


def revoke_session(session: SessionRecord, reason: str) -> None:
    if session.revoked_at is not None:
        return
    now = timezone.now()
    SessionRecord.objects.filter(pk=session.pk, revoked_at__isnull=True).update(revoked_at=now, revoked_reason=reason)
    session.revoked_at = now
    session.revoked_reason = reason


def revoke_all(user, *, except_sid=None, reason: str) -> int:
    """Cierra todas las sesiones de la persona salvo ``except_sid``, saca la
    confianza de sus navegadores y manda a la blacklist sus refresh vigentes
    (también los viejos, sin ``sid``) menos los de la sesión que se queda.
    Devuelve cuántas sesiones cerró."""
    sessions = SessionRecord.objects.filter(user=user, revoked_at__isnull=True)
    if except_sid:
        sessions = sessions.exclude(pk=except_sid)
    closed = sessions.update(revoked_at=timezone.now(), revoked_reason=reason)
    KnownDevice.objects.filter(user=user, trusted_until__isnull=False).update(trusted_until=None)
    alive = OutstandingToken.objects.filter(user=user, blacklistedtoken__isnull=True, expires_at__gt=timezone.now())
    for token in alive:
        if except_sid and _sid_of(token.token) == str(except_sid):
            continue
        BlacklistedToken.objects.get_or_create(token=token)
    return closed


def _sid_of(raw_token: str):
    """El ``sid`` de un JWT guardado, sin verificar la firma: solo sirve para
    saber a qué sesión pertenece un token que nosotros mismos emitimos."""
    try:
        payload = raw_token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload)).get("sid")
    except (IndexError, ValueError, AttributeError):
        return None


def session_fields(request) -> dict:
    """``session_id``/``session_remember`` de la sesión de esta request, para
    ``user_payload``: la recién abierta en un ingreso, o la del token."""
    session = getattr(request, "_rotulos_session", None) if request is not None else None
    if session is not None:
        return {
            "session_id": str(session.id),
            "session_remember": bool(session.remember),
            "session_idle_minutes": settings.AUTH_IDLE_MINUTES,
        }
    token = getattr(request, "auth", None) if request is not None else None
    sid = token.get("sid") if token is not None and hasattr(token, "get") else None
    if not sid:
        return {"session_id": None, "session_remember": None, "session_idle_minutes": settings.AUTH_IDLE_MINUTES}
    return {
        "session_id": sid,
        "session_remember": bool(token.get("remember")),
        "session_idle_minutes": settings.AUTH_IDLE_MINUTES,
    }
