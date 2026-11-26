"""Verificación en dos pasos (docs/superpowers/specs/2026-11-25-recordarme-y-2fa-design.md, etapa 2)."""

import base64
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone

from apps.accounts import mfa
from apps.accounts.models import MfaEmailCode, MfaRecoveryCode, UserMfa

User = get_user_model()
PASSWORD = "Clave1234"

# Vector de prueba de RFC 6238 (SHA1): secreto ASCII "12345678901234567890",
# T = 59 s → 94287082; con 6 dígitos, 287082.
RFC_SECRET = base64.b32encode(b"12345678901234567890").decode()


def enable_totp(user, secret=RFC_SECRET):
    from apps.integrations.crypto import encrypt

    return UserMfa.objects.create(
        user=user, method="totp", secret_encrypted=encrypt(secret), enabled_at=timezone.now()
    )


class MfaCoreTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("ana@example.com", "ana@example.com", PASSWORD)

    def test_totp_matches_rfc6238_vector(self):
        self.assertEqual(mfa.totp_now(RFC_SECRET, at=59), "287082")

    def test_totp_accepts_one_step_drift(self):
        config = enable_totp(self.user)
        now = 10_000_000
        with mock.patch("apps.accounts.mfa.time.time", return_value=now):
            self.assertTrue(mfa.totp_verify(config, mfa.totp_now(RFC_SECRET, at=now - 30)))
            self.assertTrue(mfa.totp_verify(config, mfa.totp_now(RFC_SECRET, at=now + 30)))
            self.assertFalse(mfa.totp_verify(config, mfa.totp_now(RFC_SECRET, at=now + 90)))

    def test_totp_rejects_reused_step(self):
        config = enable_totp(self.user)
        now = 10_000_000
        code = mfa.totp_now(RFC_SECRET, at=now)
        with mock.patch("apps.accounts.mfa.time.time", return_value=now):
            self.assertTrue(mfa.totp_verify(config, code))
            self.assertFalse(mfa.totp_verify(config, code))

    def test_totp_ignores_spaces_and_rejects_garbage(self):
        config = enable_totp(self.user)
        now = 10_000_000
        code = mfa.totp_now(RFC_SECRET, at=now)
        with mock.patch("apps.accounts.mfa.time.time", return_value=now):
            self.assertFalse(mfa.totp_verify(config, "abc"))
            self.assertTrue(mfa.totp_verify(config, f" {code[:3]} {code[3:]} "))

    def test_email_code_single_use_and_expires(self):
        mfa.send_email_code(self.user, "login")
        self.assertEqual(len(mail.outbox), 1)
        code = next(word for word in mail.outbox[0].body.split() if word.isdigit() and len(word) == 6)
        self.assertTrue(mfa.email_code_verify(self.user, code, "login"))
        self.assertFalse(mfa.email_code_verify(self.user, code, "login"))

        mfa.send_email_code(self.user, "login")
        code = next(word for word in mail.outbox[1].body.split() if word.isdigit() and len(word) == 6)
        MfaEmailCode.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertFalse(mfa.email_code_verify(self.user, code, "login"))

    def test_email_code_is_per_purpose(self):
        mfa.send_email_code(self.user, "setup")
        code = next(word for word in mail.outbox[0].body.split() if word.isdigit() and len(word) == 6)
        self.assertFalse(mfa.email_code_verify(self.user, code, "login"))
        self.assertTrue(mfa.email_code_verify(self.user, code, "setup"))

    def test_email_code_locks_after_5_attempts(self):
        mfa.send_email_code(self.user, "login")
        code = next(word for word in mail.outbox[0].body.split() if word.isdigit() and len(word) == 6)
        wrong = "000000" if code != "000000" else "111111"
        for _ in range(5):
            self.assertFalse(mfa.email_code_verify(self.user, wrong, "login"))
        self.assertFalse(mfa.email_code_verify(self.user, code, "login"))

    def test_recovery_code_single_use_and_normalized(self):
        codes = mfa.new_recovery_codes(self.user)
        self.assertEqual(len(codes), 10)
        self.assertRegex(codes[0], r"^[a-z2-9]{4}-[a-z2-9]{4}$")
        messy = f"  {codes[0].upper().replace('-', ' ')} "
        self.assertTrue(mfa.recovery_code_verify(self.user, messy))
        self.assertFalse(mfa.recovery_code_verify(self.user, codes[0]))
        self.assertEqual(mfa.recovery_codes_left(self.user), 9)

    def test_new_recovery_codes_invalidate_old(self):
        old = mfa.new_recovery_codes(self.user)
        mfa.new_recovery_codes(self.user)
        self.assertFalse(mfa.recovery_code_verify(self.user, old[0]))
        self.assertEqual(MfaRecoveryCode.objects.filter(user=self.user).count(), 10)

    def test_verify_second_factor_tries_method_then_recovery(self):
        enable_totp(self.user)
        codes = mfa.new_recovery_codes(self.user)
        now = 10_000_000
        with mock.patch("apps.accounts.mfa.time.time", return_value=now):
            self.assertEqual(mfa.verify_second_factor(self.user, mfa.totp_now(RFC_SECRET, at=now)), "totp")
            self.assertEqual(mfa.verify_second_factor(self.user, codes[1]), "recovery")
            self.assertIsNone(mfa.verify_second_factor(self.user, "123"))

    def test_mfa_token_roundtrip_and_expiry(self):
        token = mfa.make_mfa_token(self.user, remember=True, method="password")
        data = mfa.read_mfa_token(token)
        self.assertEqual(data["user_id"], self.user.pk)
        self.assertIs(data["remember"], True)
        self.assertEqual(data["method"], "password")
        self.assertIsNone(mfa.read_mfa_token("basura"))
        with override_settings(MFA_TOKEN_MAX_AGE_SECONDS=-1):
            self.assertIsNone(mfa.read_mfa_token(token))

    def test_secret_is_stored_encrypted(self):
        config = enable_totp(self.user)
        self.assertNotIn(RFC_SECRET, config.secret_encrypted)
        self.assertEqual(mfa.secret_of(config), RFC_SECRET)

    def test_mfa_enabled(self):
        self.assertFalse(mfa.mfa_enabled(self.user))
        UserMfa.objects.create(user=self.user, method="totp")
        self.assertFalse(mfa.mfa_enabled(self.user))
        UserMfa.objects.filter(user=self.user).update(enabled_at=timezone.now())
        self.assertTrue(mfa.mfa_enabled(self.user))

    def test_provisioning_uri_and_qr(self):
        uri = mfa.provisioning_uri(self.user, RFC_SECRET)
        self.assertTrue(uri.startswith("otpauth://totp/"))
        self.assertIn(f"secret={RFC_SECRET}", uri)
        self.assertIn("ana%40example.com", uri)
        self.assertTrue(mfa.qr_data_url(uri).startswith("data:image/png;base64,"))


from django.contrib.auth.tokens import default_token_generator  # noqa: E402
from django.utils.encoding import force_bytes  # noqa: E402
from django.utils.http import urlsafe_base64_encode  # noqa: E402
from rest_framework.test import APITestCase  # noqa: E402

from apps.accounts.models import SessionRecord  # noqa: E402
from apps.audit.models import AuditLog  # noqa: E402

LOGIN = "/api/v1/auth/login/"
VERIFY = "/api/v1/auth/2fa/verify/"
RESEND = "/api/v1/auth/2fa/resend/"
COOKIE = {"HTTP_X_AUTH_MODE": "cookie"}
NOW = 10_000_000


def code_from_mail(message):
    return next(word for word in message.body.split() if word.isdigit() and len(word) == 6)


@override_settings(AUTH_COOKIE_SECURE=True, GOOGLE_CLIENT_ID="test-client")
class MfaLoginTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("ana@example.com", "ana@example.com", PASSWORD)

    def login(self, **headers):
        return self.client.post(LOGIN, {"email": "ana@example.com", "password": PASSWORD, "remember": True}, format="json", **headers)

    def challenge(self, **headers):
        response = self.login(**headers)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["mfa_required"])
        return response.data["mfa_token"]

    def test_login_with_mfa_returns_challenge_without_tokens(self):
        enable_totp(self.user)
        response = self.login(**COOKIE)
        self.assertTrue(response.data["mfa_required"])
        self.assertEqual(response.data["method"], "totp")
        for key in ("access", "refresh", "user"):
            self.assertNotIn(key, response.data)
        self.assertNotIn("rotulos_access", response.cookies)
        self.assertNotIn("rotulos_refresh", response.cookies)
        self.assertFalse(SessionRecord.objects.exists())
        self.assertFalse(AuditLog.objects.filter(action="auth.login_success").exists())

    def test_google_login_with_mfa_returns_challenge(self):
        enable_totp(self.user)
        claims = {"email": "ana@example.com", "email_verified": True}
        with mock.patch("apps.accounts.auth_views.id_token.verify_oauth2_token", return_value=claims):
            response = self.client.post("/api/v1/auth/google/", {"credential": "x"}, format="json")
        self.assertTrue(response.data["mfa_required"])
        self.assertNotIn("access", response.data)

    def test_verify_with_totp_issues_tokens_and_session_mfa_method(self):
        enable_totp(self.user)
        token = self.challenge()
        with mock.patch("apps.accounts.mfa.time.time", return_value=NOW):
            response = self.client.post(VERIFY, {"mfa_token": token, "code": mfa.totp_now(RFC_SECRET, at=NOW)}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn("access", response.data)
        session = SessionRecord.objects.get()
        self.assertEqual(session.mfa_method, "totp")
        self.assertTrue(session.remember)
        log = AuditLog.objects.get(action="auth.login_success")
        self.assertEqual(log.changes["2fa"]["to"], "totp")

    def test_email_method_sends_code_with_the_challenge(self):
        UserMfa.objects.create(user=self.user, method="email", enabled_at=timezone.now())
        response = self.login()
        self.assertEqual(response.data["method"], "email")
        self.assertEqual(response.data["email_hint"], "a***@example.com")
        code = code_from_mail(mail.outbox[-1])
        ok = self.client.post(VERIFY, {"mfa_token": response.data["mfa_token"], "code": code}, format="json")
        self.assertEqual(ok.status_code, 200, ok.data)

    def test_resend_only_for_email_method_and_not_too_often(self):
        UserMfa.objects.create(user=self.user, method="email", enabled_at=timezone.now())
        token = self.challenge()
        self.assertEqual(self.client.post(RESEND, {"mfa_token": token}, format="json").status_code, 429)
        MfaEmailCode.objects.update(created_at=timezone.now() - timedelta(minutes=2))
        self.assertEqual(self.client.post(RESEND, {"mfa_token": token}, format="json").status_code, 204)

        UserMfa.objects.update(method="totp")
        self.assertEqual(self.client.post(RESEND, {"mfa_token": token}, format="json").status_code, 400)

    def test_wrong_code_counts_toward_lockout(self):
        enable_totp(self.user)
        token = self.challenge()
        for _ in range(3):
            wrong = self.client.post(VERIFY, {"mfa_token": token, "code": "000000"}, format="json")
            self.assertEqual(wrong.status_code, 400)
        locked = self.client.post(VERIFY, {"mfa_token": token, "code": "000000"}, format="json")
        self.assertEqual(locked.status_code, 423)
        self.assertEqual(AuditLog.objects.filter(action="auth.mfa_failed").count(), 3)

    def test_expired_mfa_token_is_rejected(self):
        enable_totp(self.user)
        token = self.challenge()
        with override_settings(MFA_TOKEN_MAX_AGE_SECONDS=-1):
            response = self.client.post(VERIFY, {"mfa_token": token, "code": "123456"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["code"], "mfa_expired")

    def test_trusted_browser_skips_second_step_for_30_days(self):
        enable_totp(self.user)
        token = self.challenge()
        with mock.patch("apps.accounts.mfa.time.time", return_value=NOW):
            ok = self.client.post(
                VERIFY, {"mfa_token": token, "code": mfa.totp_now(RFC_SECRET, at=NOW), "trust_browser": True}, format="json"
            )
        self.assertEqual(ok.status_code, 200, ok.data)
        # La cookie del navegador sale con el desafío y la conserva el cliente.
        self.assertIn("rotulos_device", self.client.cookies)
        again = self.login()
        self.assertNotIn("mfa_required", again.data)
        self.assertIn("access", again.data)

        from apps.accounts.models import KnownDevice

        KnownDevice.objects.update(trusted_until=timezone.now() - timedelta(seconds=1))
        self.assertTrue(self.login().data["mfa_required"])

    def test_password_reset_does_not_disable_mfa(self):
        enable_totp(self.user)
        uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        reset = self.client.post(
            "/api/v1/auth/password-reset/confirm/",
            {"uid": uid, "token": default_token_generator.make_token(self.user), "new_password": "Nueva12345"},
            format="json",
        )
        self.assertEqual(reset.status_code, 200, reset.data)
        response = self.client.post(LOGIN, {"email": "ana@example.com", "password": "Nueva12345"}, format="json")
        self.assertTrue(response.data["mfa_required"])

    def test_recovery_code_login_sends_mail(self):
        enable_totp(self.user)
        codes = mfa.new_recovery_codes(self.user)
        token = self.challenge()
        before = len(mail.outbox)
        ok = self.client.post(VERIFY, {"mfa_token": token, "code": codes[0]}, format="json")
        self.assertEqual(ok.status_code, 200, ok.data)
        self.assertEqual(SessionRecord.objects.get().mfa_method, "recovery")
        recovery_mails = [m for m in mail.outbox[before:] if m.subject.startswith("Usaste un código de recuperación")]
        self.assertEqual(len(recovery_mails), 1)
        self.assertIn("Te quedan 9", recovery_mails[0].body)
        self.assertTrue(AuditLog.objects.filter(action="auth.recovery_code_used").exists())

    def test_user_without_mfa_login_response_unchanged(self):
        response = self.login()
        self.assertEqual(set(response.data), {"access", "refresh", "user"})

    def test_no_view_issues_tokens_without_second_factor(self):
        enable_totp(self.user)
        claims = {"email": "ana@example.com", "email_verified": True}
        with mock.patch("apps.accounts.auth_views.id_token.verify_oauth2_token", return_value=claims):
            google = self.client.post("/api/v1/auth/google/", {"credential": "x"}, format="json")
        password = self.login()
        bad = self.client.post(VERIFY, {"mfa_token": password.data["mfa_token"], "code": "000000"}, format="json")
        for response in (google, password, bad):
            self.assertNotIn("access", response.data)
            self.assertNotIn("rotulos_access", response.cookies)
        self.assertFalse(SessionRecord.objects.exists())


TWOFA = "/api/v1/auth/2fa/"


@override_settings(AUTH_COOKIE_SECURE=True)
class MfaSetupTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("ana@example.com", "ana@example.com", PASSWORD)
        self.admin = User.objects.create_user("jefe@example.com", "jefe@example.com", PASSWORD, is_staff=True)

    def auth(self, email="ana@example.com"):
        response = self.client.post(LOGIN, {"email": email, "password": PASSWORD, "remember": True}, format="json")
        self.assertIn("access", response.data, response.data)
        return {"HTTP_AUTHORIZATION": f"Bearer {response.data['access']}"}

    def enable_app(self, headers):
        setup = self.client.post(f"{TWOFA}setup/", {"method": "totp", "password": PASSWORD}, format="json", **headers)
        self.assertEqual(setup.status_code, 200, setup.data)
        with mock.patch("apps.accounts.mfa.time.time", return_value=NOW):
            confirm = self.client.post(
                f"{TWOFA}confirm/", {"code": mfa.totp_now(setup.data["secret"], at=NOW)}, format="json", **headers
            )
        self.assertEqual(confirm.status_code, 200, confirm.data)
        return setup.data["secret"], confirm.data["recovery_codes"]

    def test_totp_setup_needs_valid_code_to_enable(self):
        headers = self.auth()
        setup = self.client.post(f"{TWOFA}setup/", {"method": "totp", "password": PASSWORD}, format="json", **headers)
        self.assertTrue(setup.data["qr"].startswith("data:image/png;base64,"))
        self.assertIn(setup.data["secret"], setup.data["otpauth_uri"])
        self.assertFalse(mfa.mfa_enabled(self.user))
        bad = self.client.post(f"{TWOFA}confirm/", {"code": "000000"}, format="json", **headers)
        self.assertEqual(bad.status_code, 400)
        self.assertFalse(mfa.mfa_enabled(self.user))

    def test_confirm_returns_recovery_codes_once(self):
        headers = self.auth()
        _secret, codes = self.enable_app(headers)
        self.assertEqual(len(codes), 10)
        status_now = self.client.get(TWOFA, **headers).data
        self.assertEqual(status_now["method"], "totp")
        self.assertTrue(status_now["enabled"])
        self.assertEqual(status_now["recovery_codes_left"], 10)
        self.assertNotIn("recovery_codes", status_now)
        self.assertTrue(AuditLog.objects.filter(action="auth.mfa_enable").exists())
        self.assertEqual(mail.outbox[-1].subject.split(" — ")[0], "Activaste la verificación en dos pasos")

    def test_setup_twice_is_refused(self):
        headers = self.auth()
        self.enable_app(headers)
        again = self.client.post(f"{TWOFA}setup/", {"method": "email", "password": PASSWORD}, format="json", **headers)
        self.assertEqual(again.status_code, 400)

    def test_email_setup_requires_verified_email(self):
        from apps.accounts.models import EmailVerification

        EmailVerification.objects.create(user=self.user, token="t" * 20, is_verified=False)
        headers = {"HTTP_AUTHORIZATION": f"Bearer {RefreshToken_for(self.user)}"}
        response = self.client.post(f"{TWOFA}setup/", {"method": "email", "password": PASSWORD}, format="json", **headers)
        self.assertEqual(response.status_code, 403)

    def test_email_setup_sends_code_and_confirms(self):
        headers = self.auth()
        sent = self.client.post(f"{TWOFA}setup/", {"method": "email", "password": PASSWORD}, format="json", **headers)
        self.assertEqual(sent.status_code, 200, sent.data)
        code = code_from_mail(mail.outbox[-1])
        confirm = self.client.post(f"{TWOFA}confirm/", {"code": code}, format="json", **headers)
        self.assertEqual(confirm.status_code, 200, confirm.data)
        self.assertEqual(UserMfa.objects.get(user=self.user).method, "email")

    def test_disable_requires_code_and_closes_other_sessions(self):
        headers = self.auth()
        secret, codes = self.enable_app(headers)
        other = self.client.post(LOGIN, {"email": "ana@example.com", "password": PASSWORD}, format="json")
        self.assertTrue(other.data["mfa_required"])
        wrong = self.client.post(f"{TWOFA}disable/", {"code": "000000"}, format="json", **headers)
        self.assertEqual(wrong.status_code, 400)
        ok = self.client.post(f"{TWOFA}disable/", {"code": codes[0]}, format="json", **headers)
        self.assertEqual(ok.status_code, 200, ok.data)
        self.assertFalse(mfa.mfa_enabled(self.user))
        self.assertEqual(MfaRecoveryCode.objects.filter(user=self.user).count(), 0)
        self.assertTrue(AuditLog.objects.filter(action="auth.mfa_disable").exists())
        self.assertEqual(self.client.get(TWOFA, **headers).status_code, 200)

    def test_reauth_email_code_can_disable(self):
        headers = self.auth()
        self.enable_app(headers)
        sent = self.client.post(f"{TWOFA}reauth-email/", format="json", **headers)
        self.assertEqual(sent.status_code, 204)
        ok = self.client.post(f"{TWOFA}disable/", {"code": code_from_mail(mail.outbox[-1])}, format="json", **headers)
        self.assertEqual(ok.status_code, 200, ok.data)

    def test_regenerate_recovery_codes_invalidates_old(self):
        headers = self.auth()
        secret, codes = self.enable_app(headers)
        with mock.patch("apps.accounts.mfa.time.time", return_value=NOW + 60):
            response = self.client.post(
                f"{TWOFA}recovery-codes/", {"code": mfa.totp_now(secret, at=NOW + 60)}, format="json", **headers
            )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertNotIn(codes[0], response.data["recovery_codes"])
        self.assertFalse(mfa.recovery_code_verify(self.user, codes[0]))
        self.assertTrue(AuditLog.objects.filter(action="auth.recovery_codes_regenerated").exists())

    def test_admin_reset_2fa_audits_and_mails(self):
        enable_totp(self.user)
        headers = self.auth("jefe@example.com")
        response = self.client.post(f"/api/v1/users/{self.user.pk}/reset-2fa/", **headers)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(mfa.mfa_enabled(self.user))
        log = AuditLog.objects.get(action="auth.mfa_admin_reset")
        self.assertEqual(log.actor, self.admin)
        self.assertEqual(mail.outbox[-1].to, ["ana@example.com"])
        self.assertIn("administrador", mail.outbox[-1].body)

    def test_admin_reset_2fa_forbidden_without_users_edit(self):
        enable_totp(self.admin)
        plain = User.objects.create_user("pepe@example.com", "pepe@example.com", PASSWORD)
        self.assertTrue(plain)
        headers = self.auth("pepe@example.com")
        response = self.client.post(f"/api/v1/users/{self.admin.pk}/reset-2fa/", **headers)
        self.assertEqual(response.status_code, 403)

    def test_admin_cannot_reset_own_2fa_and_needs_it_enabled(self):
        headers = self.auth("jefe@example.com")
        self.assertEqual(self.client.post(f"/api/v1/users/{self.user.pk}/reset-2fa/", **headers).status_code, 400)
        enable_totp(self.admin)
        self.assertEqual(self.client.post(f"/api/v1/users/{self.admin.pk}/reset-2fa/", **headers).status_code, 400)

    def test_user_list_filter_mfa(self):
        enable_totp(self.user)
        headers = self.auth("jefe@example.com")
        rows = self.client.get("/api/v1/users/?mfa=1", **headers).data["results"]
        self.assertEqual([row["email"] for row in rows], ["ana@example.com"])
        self.assertTrue(rows[0]["mfa_enabled"])
        self.assertEqual(rows[0]["mfa_method"], "totp")
        others = self.client.get("/api/v1/users/?mfa=0", **headers).data["results"]
        self.assertNotIn("ana@example.com", [row["email"] for row in others])
        export = self.client.get("/api/v1/users/export/?mfa=1", **headers)
        self.assertIn(b"ana@example.com", export.content)
        self.assertNotIn(b"jefe@example.com", export.content)

    def test_secrets_and_codes_never_in_audit_or_payload(self):
        headers = self.auth()
        secret, codes = self.enable_app(headers)
        dumped = str(list(AuditLog.objects.values_list("changes", flat=True)))
        me = str(self.client.get(ME_URL, **headers).data)
        for value in [secret, *codes]:
            self.assertNotIn(value, dumped)
            self.assertNotIn(value, me)


ME_URL = "/api/v1/auth/me/"


def RefreshToken_for(user):  # noqa: N802
    from rest_framework_simplejwt.tokens import RefreshToken

    return RefreshToken.for_user(user).access_token
