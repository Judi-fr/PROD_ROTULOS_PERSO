"""Verificación en dos pasos: app autenticadora (TOTP) o código por email, más
códigos de recuperación. Ver
``docs/superpowers/specs/2026-11-25-recordarme-y-2fa-design.md``.

- **TOTP** (RFC 6238, lo que usan Google Authenticator, Authy…): SHA1, 6
  dígitos, pasos de 30 s, se acepta el paso anterior y el siguiente (reloj del
  celular corrido) y nunca el mismo paso dos veces. Implementado con la
  biblioteca estándar: es una cuenta corta y no justifica una dependencia.
- El secreto TOTP se guarda cifrado (``apps.integrations.crypto``); los
  códigos por email y de recuperación, como HMAC-SHA256 con la SECRET_KEY: son
  aleatorios (no los elige una persona), así que no necesitan un hash lento
  de contraseña, y se buscan por su hash.
- ``mfa_token``: lo que el login devuelve en vez de los tokens cuando falta el
  segundo paso. Firmado y con vencimiento corto; no da acceso a nada más que a
  ``2fa/verify/``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import secrets
import struct
import time
from datetime import timedelta
from urllib.parse import quote

from django.conf import settings
from django.core import signing
from django.core.mail import send_mail
from django.utils import timezone

from apps.common.mail import branded_html
from apps.integrations.crypto import decrypt

from .security_models import MfaEmailCode, MfaRecoveryCode, UserMfa

TOTP_DIGITS = 6
TOTP_STEP_SECONDS = 30
TOTP_DRIFT_STEPS = 1
ISSUER = "Human Log Rótulos"
EMAIL_CODE_MAX_ATTEMPTS = 5
# Sin 0/O, 1/l/I: se leen y se copian a mano.
RECOVERY_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
MFA_TOKEN_SALT = "accounts.mfa-login"


def code_hash(value: str) -> str:
    return hmac.new(settings.SECRET_KEY.encode(), f"mfa:{value}".encode(), hashlib.sha256).hexdigest()


# ---- TOTP -----------------------------------------------------------------


def new_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _key(secret: str) -> bytes:
    padded = secret.upper() + "=" * (-len(secret) % 8)
    return base64.b32decode(padded)


def _hotp(secret: str, counter: int) -> str:
    digest = hmac.new(_key(secret), struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(number % 10**TOTP_DIGITS).zfill(TOTP_DIGITS)


def totp_now(secret: str, at: float | None = None) -> str:
    moment = time.time() if at is None else at
    return _hotp(secret, int(moment // TOTP_STEP_SECONDS))


def _clean_code(code) -> str:
    return "".join(str(code or "").split())


def secret_of(config: UserMfa, *, pending: bool = False) -> str:
    raw = config.pending_secret_encrypted if pending else config.secret_encrypted
    return decrypt(raw) if raw else ""


def totp_verify(config: UserMfa, code, *, pending: bool = False) -> bool:
    """Valida un código de la app; guarda el paso usado para no aceptarlo dos
    veces. ``pending`` = contra el secreto que se está activando."""
    code = _clean_code(code)
    secret = secret_of(config, pending=pending)
    if not secret or len(code) != TOTP_DIGITS or not code.isdigit():
        return False
    current = int(time.time() // TOTP_STEP_SECONDS)
    for step in range(current - TOTP_DRIFT_STEPS, current + TOTP_DRIFT_STEPS + 1):
        if config.last_totp_step is not None and step <= config.last_totp_step:
            continue
        if hmac.compare_digest(_hotp(secret, step), code):
            UserMfa.objects.filter(pk=config.pk).update(last_totp_step=step)
            config.last_totp_step = step
            return True
    return False


def provisioning_uri(user, secret: str) -> str:
    label = quote(f"{ISSUER}:{user.email}", safe="")
    return f"otpauth://totp/{label}?secret={secret}&issuer={quote(ISSUER)}&digits={TOTP_DIGITS}&period={TOTP_STEP_SECONDS}"


def qr_data_url(uri: str) -> str:
    import qrcode

    image = qrcode.make(uri, box_size=6, border=2)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


# ---- Código por email -----------------------------------------------------

_EMAIL_SUBJECTS = {
    "login": "Tu código para entrar",
    "setup": "Tu código para activar la verificación en dos pasos",
    "reauth": "Tu código para confirmar que sos vos",
}


def send_email_code(user, purpose: str) -> None:
    """Manda un código nuevo de 6 dígitos (vence en MFA_EMAIL_CODE_MINUTES) y
    anula los anteriores del mismo propósito."""
    code = f"{secrets.randbelow(10**TOTP_DIGITS):0{TOTP_DIGITS}d}"
    minutes = settings.MFA_EMAIL_CODE_MINUTES
    MfaEmailCode.objects.filter(user=user, purpose=purpose, used_at__isnull=True).update(used_at=timezone.now())
    MfaEmailCode.objects.create(
        user=user,
        purpose=purpose,
        code_hash=code_hash(code),
        expires_at=timezone.now() + timedelta(minutes=minutes),
    )
    subject = _EMAIL_SUBJECTS.get(purpose, "Tu código")
    send_mail(
        subject=f"{subject} — Human Log · Rótulos",
        message=(
            f"Hola,\n\nTu código es: {code}\n\n"
            f"Vence en {minutes} minutos y sirve una sola vez.\n"
            "Si no lo pediste, alguien puede tener tu contraseña: cambiala.\n"
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        fail_silently=False,
        html_message=branded_html(
            heading=subject,
            paragraphs=[f"Tu código es: {code}", f"Vence en {minutes} minutos y sirve una sola vez."],
            footnote="Si no lo pediste, alguien puede tener tu contraseña: cambiala.",
        ),
    )


def _pending_email_code(user, purpose: str):
    return (
        MfaEmailCode.objects.filter(user=user, purpose=purpose, used_at__isnull=True, expires_at__gt=timezone.now())
        .order_by("-created_at")
        .first()
    )


def email_code_verify(user, code, purpose: str) -> bool:
    """Cada intento se "gasta" en la base ANTES de comparar (update
    condicional): pedidos en paralelo no pueden pasar el tope de intentos."""
    from django.db.models import F

    code = _clean_code(code)
    pending = _pending_email_code(user, purpose)
    if pending is None:
        return False
    claimed = MfaEmailCode.objects.filter(
        pk=pending.pk, used_at__isnull=True, attempts__lt=EMAIL_CODE_MAX_ATTEMPTS
    ).update(attempts=F("attempts") + 1)
    if not claimed:
        return False
    if not (code.isdigit() and hmac.compare_digest(code_hash(code), pending.code_hash)):
        return False
    used = MfaEmailCode.objects.filter(pk=pending.pk, used_at__isnull=True).update(used_at=timezone.now())
    return used == 1


# ---- Códigos de recuperación ---------------------------------------------


def _normalize_recovery(code) -> str:
    return "".join(ch for ch in str(code or "").lower() if ch.isalnum())


def _random_recovery_code() -> str:
    raw = "".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"


def new_recovery_codes(user) -> list[str]:
    """Genera los códigos (los anteriores dejan de servir) y los devuelve en
    claro: es la única vez que se ven."""
    codes = [_random_recovery_code() for _ in range(settings.MFA_RECOVERY_CODES)]
    MfaRecoveryCode.objects.filter(user=user).delete()
    MfaRecoveryCode.objects.bulk_create(
        [MfaRecoveryCode(user=user, code_hash=code_hash(_normalize_recovery(code))) for code in codes]
    )
    return codes


def recovery_code_verify(user, code) -> bool:
    normalized = _normalize_recovery(code)
    if len(normalized) != 8:
        return False
    used = MfaRecoveryCode.objects.filter(
        user=user, used_at__isnull=True, code_hash=code_hash(normalized)
    ).update(used_at=timezone.now())
    return used == 1


def recovery_codes_left(user) -> int:
    return MfaRecoveryCode.objects.filter(user=user, used_at__isnull=True).count()


# ---- Juntando todo --------------------------------------------------------


def config_of(user) -> UserMfa | None:
    return UserMfa.objects.filter(user=user).first()


def mfa_enabled(user) -> bool:
    return UserMfa.objects.filter(user=user, enabled_at__isnull=False).exists()


def verify_second_factor(user, code, *, email_purpose: str = "login") -> str | None:
    """``"totp"``/``"email"``/``"recovery"`` según con qué pasó, o ``None``.
    Un código con letras o guion va directo a los de recuperación."""
    config = config_of(user)
    if config is None or not config.enabled:
        return None
    cleaned = _clean_code(code)
    if cleaned.isdigit():
        if config.method == UserMfa.Method.TOTP and totp_verify(config, cleaned):
            return "totp"
        if config.method == UserMfa.Method.EMAIL and email_code_verify(user, cleaned, email_purpose):
            return "email"
        return None
    if recovery_code_verify(user, code):
        return "recovery"
    return None


def make_mfa_token(user, *, remember, method: str) -> str:
    return signing.dumps({"user_id": user.pk, "remember": remember, "method": method}, salt=MFA_TOKEN_SALT)


def read_mfa_token(token) -> dict | None:
    try:
        data = signing.loads(str(token or ""), salt=MFA_TOKEN_SALT, max_age=settings.MFA_TOKEN_MAX_AGE_SECONDS)
    except signing.BadSignature:
        return None
    return data if isinstance(data, dict) and data.get("user_id") else None


def email_hint(email: str) -> str:
    """"a***@gmail.com": para que la persona sepa a dónde fue el código."""
    local, _, domain = (email or "").partition("@")
    return f"{local[:1]}***@{domain}" if domain else "***"
