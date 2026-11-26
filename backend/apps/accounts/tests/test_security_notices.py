"""Avisos de seguridad por mail, historial y último ingreso
(docs/superpowers/specs/2026-11-25-recordarme-y-2fa-design.md, etapa 3)."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework.test import APITestCase

from apps.accounts.auth_views import make_reset_token
from apps.accounts.models import KnownDevice, SessionRecord  # noqa: F401
from apps.audit.models import AuditLog

User = get_user_model()
PASSWORD = "Clave1234"
LOGIN = "/api/v1/auth/login/"
CHROME = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/158.0 Safari/537.36"


def new_device_mails():
    return [message for message in mail.outbox if message.subject.startswith("Nuevo ingreso a tu cuenta")]


@override_settings(AUTH_COOKIE_SECURE=True)
class NewDeviceMailTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("ana@example.com", "ana@example.com", PASSWORD)

    def login(self, email="ana@example.com"):
        response = self.client.post(
            LOGIN, {"email": email, "password": PASSWORD, "remember": True}, format="json", HTTP_USER_AGENT=CHROME
        )
        self.assertEqual(response.status_code, 200, response.data)
        return response

    def test_first_login_from_new_browser_sends_one_mail(self):
        self.login()
        self.assertEqual(len(new_device_mails()), 1)
        self.assertIn("Chrome en Windows", new_device_mails()[0].body)
        self.assertTrue(AuditLog.objects.filter(action="auth.new_device").exists())
        self.login()  # mismo navegador: la cookie rotulos_device quedó en el cliente
        self.assertEqual(len(new_device_mails()), 1)

    def test_browser_without_cookie_counts_as_new(self):
        self.login()
        self.client.cookies.clear()
        self.login()
        self.assertEqual(len(new_device_mails()), 2)
        self.assertEqual(KnownDevice.objects.filter(user=self.user).count(), 2)

    def test_new_device_mail_capped_per_day(self):
        for _ in range(7):
            cache.clear()  # el límite de 5 logins por minuto
            self.client.cookies.clear()
            self.login()
        self.assertEqual(len(new_device_mails()), 5)

    def test_register_does_not_send_new_device_mail(self):
        response = self.client.post(
            "/api/v1/auth/register/",
            {"email": "reg@example.com", "password": "Clave12345", "first_name": "Re", "last_name": "G"},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(new_device_mails(), [])

    def test_no_mail_for_internal_users(self):
        from apps.accounts.tests.team_helpers import new_business

        data_user = new_business(self.user)
        data_user.is_active = True
        data_user.set_password(PASSWORD)
        data_user.save()
        self.login(email=data_user.email)
        self.assertEqual([m for m in new_device_mails() if m.to == [data_user.email]], [])

    def test_trusting_the_browser_still_counts_it_as_new_once(self):
        from unittest import mock

        from apps.accounts import mfa
        from apps.accounts.tests.test_mfa import NOW, RFC_SECRET, enable_totp

        enable_totp(self.user)
        challenge = self.login().data
        with mock.patch("apps.accounts.mfa.time.time", return_value=NOW):
            ok = self.client.post(
                "/api/v1/auth/2fa/verify/",
                {"mfa_token": challenge["mfa_token"], "code": mfa.totp_now(RFC_SECRET, at=NOW), "trust_browser": True},
                format="json",
            )
        self.assertEqual(ok.status_code, 200, ok.data)
        self.assertEqual(len(new_device_mails()), 1)
        self.assertTrue(KnownDevice.objects.get(user=self.user).trusted_until)


@override_settings(AUTH_COOKIE_SECURE=True)
class PasswordChangedMailTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("ana@example.com", "ana@example.com", PASSWORD)

    def test_password_change_and_reset_send_mail(self):
        login = self.client.post(LOGIN, {"email": "ana@example.com", "password": PASSWORD}, format="json")
        headers = {"HTTP_AUTHORIZATION": f"Bearer {login.data['access']}"}
        changed = self.client.post(
            "/api/v1/auth/me/change-password/",
            {"current_password": PASSWORD, "new_password": "Nueva12345", "confirm_password": "Nueva12345"},
            format="json",
            **headers,
        )
        self.assertEqual(changed.status_code, 200, changed.data)
        self.assertTrue(any(m.subject.startswith("Tu contraseña cambió") for m in mail.outbox))

        mail.outbox.clear()
        reset = self.client.post(
            "/api/v1/auth/password-reset/confirm/",
            {
                "uid": urlsafe_base64_encode(force_bytes(self.user.pk)),
                "token": make_reset_token(User.objects.get(pk=self.user.pk)),
                "new_password": "Otra123456",
            },
            format="json",
        )
        self.assertEqual(reset.status_code, 200, reset.data)
        self.assertTrue(any(m.subject.startswith("Tu contraseña cambió") for m in mail.outbox))


SECURITY_LOG = "/api/v1/auth/me/security-log/"


@override_settings(AUTH_COOKIE_SECURE=True)
class SecurityLogTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("ana@example.com", "ana@example.com", PASSWORD)
        self.other = User.objects.create_user("otro@example.com", "otro@example.com", PASSWORD)

    def login(self, email="ana@example.com", password=PASSWORD):
        return self.client.post(LOGIN, {"email": email, "password": password, "remember": True}, format="json", HTTP_USER_AGENT=CHROME)

    def test_security_log_only_own_events(self):
        self.login(email="otro@example.com")
        response = self.login()
        headers = {"HTTP_AUTHORIZATION": f"Bearer {response.data['access']}"}
        rows = self.client.get(SECURITY_LOG, **headers).data
        self.assertTrue(rows)
        self.assertTrue(all(row["action"].startswith("auth.") for row in rows))
        self.assertEqual({row["actor_email"] for row in rows}, {"ana@example.com"})
        self.assertEqual(rows[0]["browser"], "Chrome en Windows")
        self.assertNotIn("user_agent", rows[0])

    def test_security_log_includes_failed_attempts_for_own_email(self):
        self.login(password="mal-mal-1")
        response = self.login()
        headers = {"HTTP_AUTHORIZATION": f"Bearer {response.data['access']}"}
        actions = [row["action"] for row in self.client.get(SECURITY_LOG, **headers).data]
        self.assertIn("auth.login_failed", actions)

    def test_security_log_is_limited_to_30(self):
        for _ in range(35):
            AuditLog.objects.create(actor=self.user, actor_email=self.user.email, category="auth", action="auth.logout")
        response = self.login()
        headers = {"HTTP_AUTHORIZATION": f"Bearer {response.data['access']}"}
        self.assertEqual(len(self.client.get(SECURITY_LOG, **headers).data), 30)

    def test_previous_login_is_the_session_before_current(self):
        first = self.login()
        self.assertIsNone(first.data["user"]["previous_login"])
        SessionRecord.objects.update(created_at=timezone.now() - timedelta(days=1))
        second = self.login()
        previous = second.data["user"]["previous_login"]
        self.assertEqual(previous["browser"], "Chrome en Windows")
        headers = {"HTTP_AUTHORIZATION": f"Bearer {second.data['access']}"}
        me = self.client.get("/api/v1/auth/me/", **headers).data
        self.assertEqual(me["previous_login"]["browser"], "Chrome en Windows")
