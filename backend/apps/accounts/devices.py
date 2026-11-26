"""Navegadores que una cuenta ya usó (``KnownDevice``).

Cada navegador lleva una cookie HttpOnly de larga vida, ``rotulos_device``,
con un id aleatorio (en la base solo su SHA-256). Sirve para:

- "No pedir el código en este navegador por 30 días" (``trusted_until``).
- El aviso por mail de ingreso desde un navegador nuevo (etapa 3).

La cookie no autentica nada por sí sola: solo saltea el segundo paso a quien
ADEMÁS puso bien la contraseña (o entró con Google).
"""

from __future__ import annotations

import hashlib
import re
import secrets
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from .security_models import KnownDevice
from .sessions import browser_label

COOKIE_NAME = "rotulos_device"
COOKIE_PATH = "/api/v1/auth/"
_VALID_ID = re.compile(r"^[A-Za-z0-9_-]{20,64}$")


def new_device_id() -> str:
    return secrets.token_urlsafe(24)


def device_hash(device_id: str) -> str:
    return hashlib.sha256(device_id.encode()).hexdigest()


def device_id(request) -> str | None:
    raw = request.COOKIES.get(COOKIE_NAME) if request is not None else None
    return raw if raw and _VALID_ID.match(raw) else None


def current_device_id(request) -> str:
    """El id de este navegador: el de su cookie, o uno nuevo que se entrega
    con la respuesta (``ensure_device_cookie``)."""
    chosen = getattr(request, "_rotulos_device_id", None) or device_id(request) or new_device_id()
    request._rotulos_device_id = chosen
    return chosen


def ensure_device_cookie(request, response):
    chosen = getattr(request, "_rotulos_device_id", None)
    if chosen and chosen != device_id(request):
        response.set_cookie(
            COOKIE_NAME,
            chosen,
            max_age=settings.AUTH_DEVICE_COOKIE_DAYS * 24 * 3600,
            path=COOKIE_PATH,
            domain=settings.AUTH_COOKIE_DOMAIN or None,
            secure=settings.AUTH_COOKIE_SECURE,
            httponly=True,
            samesite=settings.AUTH_COOKIE_SAMESITE,
        )
    return response


def is_trusted(user, device: str | None) -> bool:
    if not device:
        return False
    return KnownDevice.objects.filter(
        user=user, device_hash=device_hash(device), trusted_until__gt=timezone.now()
    ).exists()


def remember_device(user, request, device: str, *, trust: bool = False) -> tuple[KnownDevice, bool]:
    """Registra el navegador (o actualiza cuándo se lo vio) y, si se pidió,
    lo marca de confianza por MFA_TRUST_DAYS. Devuelve ``(fila, era_nuevo)``."""
    now = timezone.now()
    user_agent = (request.META.get("HTTP_USER_AGENT") or "") if request is not None else ""
    row, created = KnownDevice.objects.get_or_create(
        user=user, device_hash=device_hash(device), defaults={"browser": browser_label(user_agent)}
    )
    updates = {"last_seen_at": now}
    if trust:
        updates["trusted_until"] = now + timedelta(days=settings.MFA_TRUST_DAYS)
    KnownDevice.objects.filter(pk=row.pk).update(**updates)
    for field, value in updates.items():
        setattr(row, field, value)
    return row, created


def forget_trust(user) -> None:
    KnownDevice.objects.filter(user=user, trusted_until__isnull=False).update(trusted_until=None)


# Como mucho tantos avisos de "navegador nuevo" por persona y por día: alguien
# que borra las cookies seguido no tiene que llenarse el correo.
NEW_DEVICE_MAILS_PER_DAY = 5


def notify_new_device(user, request, session) -> None:
    """Primer ingreso de la cuenta desde este navegador: queda en la auditoría
    y, con tope por día, le llega un mail a la persona."""
    from apps.audit.models import AuditLog
    from apps.audit.services import record

    from .security_mail import new_device_mail

    since = timezone.now() - timedelta(days=1)
    sent_today = AuditLog.objects.filter(actor=user, action="auth.new_device", created_at__gte=since).count()
    record(
        request,
        actor=user,
        category="auth",
        action="auth.new_device",
        target=user,
        target_type="user",
        target_repr=user.email,
        actor_email=user.email,
        changes={"browser": {"from": None, "to": session.browser}},
    )
    if sent_today < NEW_DEVICE_MAILS_PER_DAY:
        new_device_mail(user, session)
