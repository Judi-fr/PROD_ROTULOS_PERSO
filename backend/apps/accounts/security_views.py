"""Seguridad de la propia cuenta (pantalla ``seguridad.html``): sesiones
abiertas. Ver ``docs/superpowers/specs/2026-11-25-recordarme-y-2fa-design.md``.

Todo es de la persona que llama (``request.user``): una sesión ajena es 404,
igual que si no existiera.
"""

from math import ceil

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import timedelta
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.services import record

from . import devices, mfa
from .login_flow import finish_login
from .models import LoginLockout
from .role_permissions import HasRolePermission
from .security_mail import mfa_disabled_mail, mfa_enabled_mail, recovery_code_used_mail
from .security_models import MfaEmailCode, SessionRecord, UserMfa
from .models import user_email_verified
from .sessions import active_session, revoke_all, revoke_session, touch
from apps.integrations.crypto import encrypt


def current_sid(request):
    token = getattr(request, "auth", None)
    return token.get("sid") if token is not None and hasattr(token, "get") else None


def session_row(session, current):
    return {
        "id": str(session.id),
        "browser": session.browser or "Navegador desconocido",
        "ip": session.ip,
        "created_at": session.created_at,
        "last_seen_at": session.last_seen_at,
        "remember": session.remember,
        "current": str(session.id) == str(current),
    }


class SessionListView(APIView):
    """GET /api/v1/auth/sessions/ — las sesiones abiertas de la persona."""

    def get_permissions(self):
        return [IsAuthenticated(), HasRolePermission("users.me.view")]

    def get(self, request):
        current = current_sid(request)
        sessions = SessionRecord.objects.filter(user=request.user, revoked_at__isnull=True).order_by("-last_seen_at")
        return Response([session_row(session, current) for session in sessions])


class SessionRevokeView(APIView):
    """POST /api/v1/auth/sessions/<id>/revoke/ — cierra una sesión propia."""

    def get_permissions(self):
        return [IsAuthenticated(), HasRolePermission("users.me.edit")]

    def post(self, request, session_id):
        try:
            session = SessionRecord.objects.get(pk=session_id, user=request.user, revoked_at__isnull=True)
        except (SessionRecord.DoesNotExist, ValidationError):
            return Response({"detail": "No encontramos esa sesión."}, status=status.HTTP_404_NOT_FOUND)
        revoke_session(session, "user")
        record(
            request,
            category="auth",
            action="auth.session_revoke",
            target=request.user,
            target_type="user",
            target_repr=request.user.email,
            changes={"session": {"from": session.browser, "to": None}},
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class SessionRevokeOthersView(APIView):
    """POST /api/v1/auth/sessions/revoke-others/ — cierra todas menos esta."""

    def get_permissions(self):
        return [IsAuthenticated(), HasRolePermission("users.me.edit")]

    def post(self, request):
        current = current_sid(request)
        closed = revoke_all(request.user, except_sid=current, reason="user")
        record(
            request,
            category="auth",
            action="auth.session_revoke",
            target=request.user,
            target_type="user",
            target_repr=request.user.email,
            changes={"closed": {"from": None, "to": closed}},
        )
        return Response({"closed": closed})


class SessionPingView(APIView):
    """POST /api/v1/auth/sessions/ping/ — "la persona está usando la app":
    mantiene viva una sesión sin "Recordarme" (auth.js lo manda como mucho
    cada 5 minutos mientras hay clics o teclas). No rota tokens."""

    def get_permissions(self):
        return [IsAuthenticated()]

    def post(self, request):
        session = getattr(request, "_rotulos_session", None) or active_session(current_sid(request))
        if session is not None:
            touch(session, activity=True)
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---- Segundo paso al entrar -----------------------------------------------

MFA_EXPIRED = {"detail": "Pasó mucho tiempo: entrá de nuevo.", "code": "mfa_expired"}
# Un código nuevo por email como mucho cada minuto y 10 por día por persona.
EMAIL_RESEND_SECONDS = 60
EMAIL_CODES_PER_DAY = 10


def _challenge_user(request):
    data = mfa.read_mfa_token(request.data.get("mfa_token"))
    if data is None:
        return None, None
    user = get_user_model().objects.filter(pk=data["user_id"], is_active=True).first()
    return (user, data) if user is not None and mfa.mfa_enabled(user) else (None, None)


def _locked_response(lockout):
    minutes = max(1, ceil(lockout.remaining_seconds() / 60))
    return Response(
        {"detail": f"Cuenta bloqueada por demasiados intentos fallidos. Probá de nuevo en aproximadamente {minutes} minuto(s)."},
        status=status.HTTP_423_LOCKED,
    )


class MfaVerifyView(APIView):
    """POST /api/v1/auth/2fa/verify/ {mfa_token, code, trust_browser} — el
    segundo paso de un ingreso. Un código mal cuenta para el mismo bloqueo
    que la contraseña (LoginLockout)."""

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "mfa_verify"

    def post(self, request):
        user, data = _challenge_user(request)
        if user is None:
            return Response(MFA_EXPIRED, status=status.HTTP_400_BAD_REQUEST)
        lockout, _ = LoginLockout.objects.get_or_create(user=user)
        if lockout.is_locked():
            return _locked_response(lockout)

        method = mfa.verify_second_factor(user, request.data.get("code"))
        if method is None:
            lockout.register_failure()
            record(
                request,
                actor=user,
                category="auth",
                action="auth.mfa_failed",
                target=user,
                target_type="user",
                target_repr=user.email,
                actor_email=user.email,
            )
            return Response({"detail": "El código no es correcto."}, status=status.HTTP_400_BAD_REQUEST)

        lockout.register_success()
        device = devices.current_device_id(request)
        if request.data.get("trust_browser") is True:
            devices.remember_device(user, request, device, trust=True)
        if method == "recovery":
            record(
                request,
                actor=user,
                category="auth",
                action="auth.recovery_code_used",
                target=user,
                target_type="user",
                target_repr=user.email,
                actor_email=user.email,
            )
            recovery_code_used_mail(user, mfa.recovery_codes_left(user))
        return finish_login(
            request, user, remember=data.get("remember"), method=data.get("method") or "password",
            mfa_method=method, skip_mfa=True,
        )


class MfaResendView(APIView):
    """POST /api/v1/auth/2fa/resend/ {mfa_token} — otro código por email."""

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "mfa_email"

    def post(self, request):
        user, _data = _challenge_user(request)
        if user is None:
            return Response(MFA_EXPIRED, status=status.HTTP_400_BAD_REQUEST)
        if mfa.config_of(user).method != UserMfa.Method.EMAIL:
            return Response({"detail": "Tu cuenta usa la app autenticadora."}, status=status.HTTP_400_BAD_REQUEST)
        now = timezone.now()
        recent = MfaEmailCode.objects.filter(user=user, purpose="login", created_at__gt=now - timedelta(seconds=EMAIL_RESEND_SECONDS))
        today = MfaEmailCode.objects.filter(user=user, created_at__gt=now - timedelta(days=1)).count()
        if recent.exists() or today >= EMAIL_CODES_PER_DAY:
            return Response(
                {"detail": "Esperá un minuto antes de pedir otro código."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        mfa.send_email_code(user, "login")
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---- Activar y administrar el segundo paso (seguridad.html) ----------------

METHOD_LABELS = {UserMfa.Method.TOTP: "App autenticadora", UserMfa.Method.EMAIL: "Código por email"}
BAD_CODE = {"detail": "El código no es correcto."}


class _OwnAccountView(APIView):
    """GET necesita ver la propia cuenta; lo demás, editarla."""

    def get_permissions(self):
        permission = "users.me.view" if self.request.method in ("GET", "HEAD") else "users.me.edit"
        return [IsAuthenticated(), HasRolePermission(permission)]

    def audit(self, request, action, **changes):
        record(
            request,
            category="auth",
            action=action,
            target=request.user,
            target_type="user",
            target_repr=request.user.email,
            changes={key: {"from": None, "to": value} for key, value in changes.items()} or None,
        )


def confirm_identity(user, code) -> str | None:
    """Para acciones delicadas (desactivar, códigos nuevos): un código de su
    método, uno de recuperación o uno que se pidió por email (``reauth``)."""
    method = mfa.verify_second_factor(user, code, email_purpose="reauth")
    if method is None and mfa.email_code_verify(user, code, "reauth"):
        method = "email"
    return method


class MfaStatusView(_OwnAccountView):
    """GET /api/v1/auth/2fa/"""

    def get(self, request):
        config = mfa.config_of(request.user)
        enabled = bool(config and config.enabled)
        return Response(
            {
                "enabled": enabled,
                "method": config.method if enabled else None,
                "recovery_codes_left": mfa.recovery_codes_left(request.user) if enabled else 0,
                "has_usable_password": request.user.has_usable_password(),
            }
        )


class MfaSetupView(_OwnAccountView):
    """POST /api/v1/auth/2fa/setup/ {method} — empieza a activarla. Con la
    app devuelve el QR y el secreto; con email manda un código. Queda activa
    recién con ``2fa/confirm/``."""

    def post(self, request):
        method = request.data.get("method")
        if method not in UserMfa.Method.values:
            return Response({"detail": "Elegí la app autenticadora o el código por email."}, status=status.HTTP_400_BAD_REQUEST)
        if mfa.mfa_enabled(request.user):
            return Response({"detail": "Ya la tenés activada: desactivala para cambiar de método."}, status=status.HTTP_400_BAD_REQUEST)
        config, _ = UserMfa.objects.get_or_create(user=request.user, defaults={"method": method})
        config.method = method
        config.last_totp_step = None
        if method == UserMfa.Method.TOTP:
            secret = mfa.new_totp_secret()
            config.pending_secret_encrypted = encrypt(secret)
            config.save()
            uri = mfa.provisioning_uri(request.user, secret)
            return Response({"method": method, "secret": secret, "otpauth_uri": uri, "qr": mfa.qr_data_url(uri)})
        if not user_email_verified(request.user):
            return Response({"detail": "Primero confirmá tu email."}, status=status.HTTP_403_FORBIDDEN)
        config.pending_secret_encrypted = ""
        config.save()
        mfa.send_email_code(request.user, "setup")
        return Response({"method": method, "email_hint": mfa.email_hint(request.user.email)})


class MfaConfirmView(_OwnAccountView):
    """POST /api/v1/auth/2fa/confirm/ {code} — la activa y devuelve los
    códigos de recuperación (la única vez que se ven)."""

    def post(self, request):
        config = mfa.config_of(request.user)
        if config is None or config.enabled:
            return Response({"detail": "Empezá de nuevo la activación."}, status=status.HTTP_400_BAD_REQUEST)
        code = request.data.get("code")
        if config.method == UserMfa.Method.TOTP:
            ok = mfa.totp_verify(config, code, pending=True)
        else:
            ok = mfa.email_code_verify(request.user, code, "setup")
        if not ok:
            return Response(BAD_CODE, status=status.HTTP_400_BAD_REQUEST)
        if config.method == UserMfa.Method.TOTP:
            config.secret_encrypted = config.pending_secret_encrypted
        config.pending_secret_encrypted = ""
        config.enabled_at = timezone.now()
        config.save()
        codes = mfa.new_recovery_codes(request.user)
        self.audit(request, "auth.mfa_enable", method=config.method)
        mfa_enabled_mail(request.user, METHOD_LABELS[config.method])
        return Response({"method": config.method, "recovery_codes": codes})


class MfaReauthEmailView(_OwnAccountView):
    """POST /api/v1/auth/2fa/reauth-email/ — un código por email para
    confirmar que sos vos (sirve aunque uses la app)."""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "mfa_email"

    def post(self, request):
        recent = MfaEmailCode.objects.filter(
            user=request.user, purpose="reauth", created_at__gt=timezone.now() - timedelta(seconds=EMAIL_RESEND_SECONDS)
        )
        if recent.exists():
            return Response({"detail": "Esperá un minuto antes de pedir otro código."}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        mfa.send_email_code(request.user, "reauth")
        return Response(status=status.HTTP_204_NO_CONTENT)


class MfaDisableView(_OwnAccountView):
    """POST /api/v1/auth/2fa/disable/ {code}"""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "mfa_verify"

    def post(self, request):
        if not mfa.mfa_enabled(request.user):
            return Response({"detail": "No la tenías activada."}, status=status.HTTP_400_BAD_REQUEST)
        if confirm_identity(request.user, request.data.get("code")) is None:
            return Response(BAD_CODE, status=status.HTTP_400_BAD_REQUEST)
        from .security_models import MfaRecoveryCode

        UserMfa.objects.filter(user=request.user).delete()
        MfaRecoveryCode.objects.filter(user=request.user).delete()
        devices.forget_trust(request.user)
        revoke_all(request.user, except_sid=current_sid(request), reason="mfa_disable")
        self.audit(request, "auth.mfa_disable")
        mfa_disabled_mail(request.user, by_admin=False)
        return Response({"detail": "Listo: tu cuenta ya no pide un código al entrar."})


class MfaRecoveryCodesView(_OwnAccountView):
    """POST /api/v1/auth/2fa/recovery-codes/ {code} — códigos nuevos (los
    anteriores dejan de servir)."""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "mfa_verify"

    def post(self, request):
        if not mfa.mfa_enabled(request.user):
            return Response({"detail": "Primero activá la verificación en dos pasos."}, status=status.HTTP_400_BAD_REQUEST)
        if confirm_identity(request.user, request.data.get("code")) is None:
            return Response(BAD_CODE, status=status.HTTP_400_BAD_REQUEST)
        codes = mfa.new_recovery_codes(request.user)
        self.audit(request, "auth.recovery_codes_regenerated")
        return Response({"recovery_codes": codes})
