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
        response = finish_login(
            request, user, remember=data.get("remember"), method=data.get("method") or "password",
            mfa_method=method, skip_mfa=True,
        )
        # Después de finish_login: así un navegador nuevo cuenta como nuevo
        # (y avisa) aunque además se lo marque de confianza.
        if request.data.get("trust_browser") is True:
            devices.remember_device(user, request, devices.current_device_id(request), trust=True)
        return response


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
    config = mfa.config_of(user)
    # Con el método por email, verify_second_factor ya probó el de "reauth":
    # probarlo de nuevo gastaría dos intentos por cada error.
    already_tried = config is not None and config.enabled and config.method == UserMfa.Method.EMAIL
    if method is None and not already_tried and mfa.email_code_verify(user, code, "reauth"):
        method = "email"
    return method


REAUTH_FAILED = {"detail": "Confirmá que sos vos: tu contraseña actual o un código."}


def require_reauth(request, *, allow_password: bool = True):
    """Antes de una acción delicada con una sesión ya abierta (activar el
    segundo paso, crear contraseña, cambiar el email…): la contraseña actual
    o un código (del segundo paso, de recuperación o el que se pide por
    email). Los errores cuentan para el mismo bloqueo que el login: con una
    sesión robada no se puede probar contraseñas o códigos sin límite.
    Devuelve ``None`` si está bien, o la respuesta de error."""
    user = request.user
    lockout, _ = LoginLockout.objects.get_or_create(user=user)
    if lockout.is_locked():
        return _locked_response(lockout)
    password = request.data.get("password") or ""
    code = request.data.get("code")
    ok = bool(allow_password and password and user.has_usable_password() and user.check_password(password))
    if not ok and code:
        ok = confirm_identity(user, code) is not None
    if not ok:
        lockout.register_failure()
        return Response(REAUTH_FAILED, status=status.HTTP_400_BAD_REQUEST)
    lockout.register_success()
    return None


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
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "mfa_verify"

    """POST /api/v1/auth/2fa/setup/ {method} — empieza a activarla. Con la
    app devuelve el QR y el secreto; con email manda un código. Queda activa
    recién con ``2fa/confirm/``."""

    def post(self, request):
        method = request.data.get("method")
        if method not in UserMfa.Method.values:
            return Response({"detail": "Elegí la app autenticadora o el código por email."}, status=status.HTTP_400_BAD_REQUEST)
        if mfa.mfa_enabled(request.user):
            return Response({"detail": "Ya la tenés activada: desactivala para cambiar de método."}, status=status.HTTP_400_BAD_REQUEST)
        # Con una sesión robada no se tiene que poder activar con el celular de
        # otro y dejar afuera al dueño.
        failed = require_reauth(request)
        if failed is not None:
            return failed
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
        failed = require_reauth(request, allow_password=False)
        if failed is not None:
            return failed
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
        failed = require_reauth(request, allow_password=False)
        if failed is not None:
            return failed
        codes = mfa.new_recovery_codes(request.user)
        self.audit(request, "auth.recovery_codes_regenerated")
        return Response({"recovery_codes": codes})


# ---- Historial de seguridad -------------------------------------------------

SECURITY_LOG_LIMIT = 30


class SecurityLogView(_OwnAccountView):
    """GET /api/v1/auth/me/security-log/ — los últimos eventos de seguridad de
    la propia cuenta: ingresos (también los fallidos con su email), bloqueos,
    contraseña, segundo paso y sesiones. El navegador legible, nunca el
    user agent crudo."""

    def get(self, request):
        from django.db.models import Q

        from apps.audit.models import AuditLog

        from .sessions import browser_label

        rows = (
            AuditLog.objects.filter(category="auth")
            .filter(Q(actor=request.user) | Q(actor__isnull=True, actor_email__iexact=request.user.email))
            .order_by("-created_at")[:SECURITY_LOG_LIMIT]
        )
        return Response(
            [
                {
                    "action": row.action,
                    "action_label": row.get_action_display(),
                    "actor_email": row.actor_email,
                    "created_at": row.created_at,
                    "ip": row.ip_address,
                    "browser": browser_label(row.user_agent) if row.user_agent else "",
                }
                for row in rows
            ]
        )


# ---- Contraseña para cuentas de Google -------------------------------------


class SetPasswordView(_OwnAccountView):
    """POST /api/v1/auth/me/set-password/ {new_password, new_password_confirm, code?}
    — quien entró siempre con Google crea una contraseña (sin la actual, que
    no tiene). Con el segundo paso activo pide su código."""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "mfa_verify"

    def post(self, request):
        from django.contrib.auth.password_validation import validate_password
        from django.core.exceptions import ValidationError as DjangoValidationError

        from .auth_views import validate_password_strength
        from .security_mail import password_changed_mail

        user = request.user
        if user.has_usable_password():
            return Response(
                {"detail": "Ya tenés una contraseña: cambiala desde Mi cuenta."}, status=status.HTTP_400_BAD_REQUEST
            )
        password = request.data.get("new_password") or ""
        if password != (request.data.get("new_password_confirm") or ""):
            return Response({"new_password_confirm": "Las contraseñas no coinciden."}, status=status.HTTP_400_BAD_REQUEST)
        error = validate_password_strength(password)
        if not error:
            try:
                validate_password(password, user=user)
            except DjangoValidationError as exc:
                error = " ".join(exc.messages)
        if error:
            return Response({"new_password": error}, status=status.HTTP_400_BAD_REQUEST)
        # Sin contraseña no hay con qué confirmar: un código (del segundo paso o
        # por email). Si no, una sesión robada crearía su propia contraseña.
        failed = require_reauth(request, allow_password=False)
        if failed is not None:
            return failed
        user.set_password(password)
        user.save(update_fields=["password"])
        revoke_all(user, except_sid=current_sid(request), reason="password")
        self.audit(request, "auth.password_set")
        password_changed_mail(user, "set")
        return Response({"detail": "Listo: ya podés entrar también con tu email y esta contraseña."})


# ---- Cambiar el email -------------------------------------------------------

EMAIL_CHANGES_PER_DAY = 5
EMAIL_CHANGE_SENT = {
    "detail": "Si ese email está disponible, te mandamos un enlace para confirmarlo. El cambio se hace recién al abrirlo."
}


def _token_hash(raw: str) -> str:
    import hashlib

    return hashlib.sha256(raw.encode()).hexdigest()


class ChangeEmailView(_OwnAccountView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "mfa_verify"

    """POST /api/v1/auth/me/change-email/ {new_email, password? | code?} —
    manda un enlace al email NUEVO; nada cambia hasta abrirlo. Un email que ya
    usa otra cuenta responde igual que uno libre (no se revela)."""

    def post(self, request):
        import secrets

        from django.conf import settings

        from .auth_views import normalize_email, validate_email_format
        from .security_mail import email_change_link_mail
        from .security_models import EmailChangeRequest

        user = request.user
        failed = require_reauth(request)
        if failed is not None:
            return failed
        new_email = normalize_email(request.data.get("new_email"))
        error = validate_email_format(new_email) if new_email else "Escribí el email nuevo."
        if error:
            return Response({"new_email": error}, status=status.HTTP_400_BAD_REQUEST)
        if new_email == normalize_email(user.email):
            return Response({"new_email": "Es el mismo email que ya usás."}, status=status.HTTP_400_BAD_REQUEST)
        since = timezone.now() - timedelta(days=1)
        if EmailChangeRequest.objects.filter(user=user, created_at__gte=since).count() >= EMAIL_CHANGES_PER_DAY:
            return Response({"detail": "Pediste muchos cambios hoy: probá mañana."}, status=status.HTTP_429_TOO_MANY_REQUESTS)

        taken = get_user_model().objects.filter(username__iexact=new_email).exists()
        if not taken:
            raw = secrets.token_urlsafe(32)
            hours = settings.EMAIL_CHANGE_HOURS
            # Los pedidos anteriores dejan de servir pero quedan, así cuentan
            # para el tope diario.
            EmailChangeRequest.objects.filter(user=user, confirmed_at__isnull=True, expires_at__gt=timezone.now()).update(
                expires_at=timezone.now()
            )
            EmailChangeRequest.objects.create(
                user=user, new_email=new_email, token_hash=_token_hash(raw), expires_at=timezone.now() + timedelta(hours=hours)
            )
            url = f"{settings.FRONTEND_URL.rstrip('/')}/confirmar_cambio_email.html?token={raw}"
            email_change_link_mail(new_email, url, hours)
        return Response(EMAIL_CHANGE_SENT, status=status.HTTP_202_ACCEPTED)


class ConfirmEmailChangeView(APIView):
    """POST /api/v1/auth/me/change-email/confirm/ {token} — el enlace del
    mail. Público: el token es la prueba (largo, de un solo uso, vence)."""

    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "mfa_verify"

    def post(self, request):
        from django.db import transaction

        from .models import EmailVerification
        from .security_mail import _mask, email_changed_old_mail
        from .security_models import EmailChangeRequest

        invalid = Response({"detail": "El enlace no es válido o ya venció. Pedí el cambio de nuevo."}, status=status.HTTP_400_BAD_REQUEST)
        raw = str(request.data.get("token") or "")
        if not raw:
            return invalid
        with transaction.atomic():
            change = (
                EmailChangeRequest.objects.select_for_update()
                .select_related("user")
                .filter(token_hash=_token_hash(raw), confirmed_at__isnull=True, expires_at__gt=timezone.now())
                .first()
            )
            if change is None:
                return invalid
            user = change.user
            if get_user_model().objects.filter(username__iexact=change.new_email).exclude(pk=user.pk).exists():
                return invalid
            old_email = user.email
            user.email = change.new_email
            user.username = change.new_email
            user.save(update_fields=["email", "username"])
            change.confirmed_at = timezone.now()
            change.save(update_fields=["confirmed_at"])
            # Abrir el enlace prueba que el email nuevo es suyo.
            EmailVerification.objects.filter(user=user, is_verified=False).update(is_verified=True, verified_at=timezone.now())
        revoke_all(user, reason="email_change")
        record(
            request,
            actor=user,
            category="auth",
            action="auth.email_change",
            target=user,
            target_type="user",
            target_repr=change.new_email,
            actor_email=change.new_email,
            changes={"email": {"from": _mask(old_email), "to": _mask(change.new_email)}},
        )
        email_changed_old_mail(old_email, change.new_email)
        return Response({"detail": "Listo: desde ahora entrás con tu email nuevo."})
