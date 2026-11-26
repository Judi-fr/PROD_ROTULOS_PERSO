"""Seguridad de la cuenta: sesiones, navegadores conocidos, verificación en dos
pasos y cambio de email (ver
``docs/superpowers/specs/2026-11-25-recordarme-y-2fa-design.md``).

Nada de esto guarda un secreto en claro: el secreto TOTP va cifrado
(``apps.integrations.crypto``) y los códigos y tokens, hasheados. Se importan
desde ``models.py``.
"""

import uuid

from django.conf import settings
from django.db import models


class SessionRecord(models.Model):
    """Un inicio de sesión. Su id viaja como claim ``sid`` en el refresh y el
    access JWT (``sessions.tokens_for_session``) y sobrevive a la rotación, así
    que toda la cadena de refresh es la misma sesión. Cerrarla
    (``revoked_at``) deja afuera a ese navegador en su próximo request."""

    class Method(models.TextChoices):
        PASSWORD = "password", "Email y contraseña"
        GOOGLE = "google", "Google"
        REGISTER = "register", "Registro"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="auth_sessions")
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now_add=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=400, blank=True, default="")
    # Nombre legible ("Chrome en Windows"), lo que ve la persona.
    browser = models.CharField(max_length=80, blank=True, default="")
    # "Mantener la sesión iniciada": dura AUTH_REMEMBER_DAYS y no se cierra
    # por inactividad.
    remember = models.BooleanField(default=False)
    method = models.CharField(max_length=20, choices=Method.choices, default=Method.PASSWORD)
    # Cómo pasó el segundo paso ("" = no lo tenía o el navegador era de confianza).
    mfa_method = models.CharField(max_length=20, blank=True, default="")
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_reason = models.CharField(max_length=40, blank=True, default="")

    class Meta:
        ordering = ["-last_seen_at"]
        indexes = [models.Index(fields=["user", "revoked_at"])]

    def __str__(self):
        return f"Sesión {self.id} de {self.user_id}"

    @property
    def is_active(self):
        return self.revoked_at is None


class KnownDevice(models.Model):
    """Un navegador que la cuenta ya usó (cookie ``rotulos_device``, guardada
    hasheada). Sirve para el aviso de ingreso nuevo y para "no pedir el código
    en este navegador por 30 días" (``trusted_until``)."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="known_devices")
    device_hash = models.CharField(max_length=64)
    browser = models.CharField(max_length=80, blank=True, default="")
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now_add=True)
    trusted_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "device_hash"], name="known_device_unique")]


class UserMfa(models.Model):
    """La verificación en dos pasos de una persona: un método activo a la vez."""

    class Method(models.TextChoices):
        TOTP = "totp", "App autenticadora"
        EMAIL = "email", "Código por email"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="mfa")
    method = models.CharField(max_length=10, choices=Method.choices)
    secret_encrypted = models.TextField(blank=True, default="")
    # Mientras se activa: el secreto que todavía no se confirmó con un código.
    pending_secret_encrypted = models.TextField(blank=True, default="")
    enabled_at = models.DateTimeField(null=True, blank=True)
    # Último paso TOTP aceptado: el mismo código no sirve dos veces.
    last_totp_step = models.BigIntegerField(null=True, blank=True)

    @property
    def enabled(self):
        return self.enabled_at is not None


class MfaRecoveryCode(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="mfa_recovery_codes")
    code_hash = models.CharField(max_length=128)
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class MfaEmailCode(models.Model):
    class Purpose(models.TextChoices):
        LOGIN = "login", "Ingreso"
        SETUP = "setup", "Activación"
        REAUTH = "reauth", "Confirmar identidad"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="mfa_email_codes")
    purpose = models.CharField(max_length=10, choices=Purpose.choices)
    code_hash = models.CharField(max_length=128)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)


class EmailChangeRequest(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="email_changes")
    new_email = models.EmailField()
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    confirmed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
