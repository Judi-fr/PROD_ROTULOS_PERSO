"""Contraseña para cuentas de Google, cambio de email y adopción del segundo
paso (docs/superpowers/specs/2026-11-25-recordarme-y-2fa-design.md, etapa 4)."""

import re
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts import mfa
from apps.accounts.models import EmailChangeRequest, SessionRecord
from apps.accounts.tests.test_mfa import NOW, RFC_SECRET, enable_totp
from apps.audit.models import AuditLog

User = get_user_model()
PASSWORD = "Clave1234"
LOGIN = "/api/v1/auth/login/"
SET_PASSWORD = "/api/v1/auth/me/set-password/"
CHANGE_EMAIL = "/api/v1/auth/me/change-email/"
CONFIRM_EMAIL = "/api/v1/auth/me/change-email/confirm/"


def bearer(user):
    return {"HTTP_AUTHORIZATION": f"Bearer {RefreshToken.for_user(user).access_token}"}


def link_token(message):
    return re.search(r"confirmar_cambio_email\.html\?token=([\w-]+)", message.body).group(1)


@override_settings(AUTH_COOKIE_SECURE=True)
class SetPasswordTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.google = User.objects.create_user("gogo@gmail.com", "gogo@gmail.com")
        self.google.set_unusable_password()
        self.google.save()

    def test_google_account_can_set_password(self):
        self.client.post("/api/v1/auth/2fa/reauth-email/", **bearer(self.google))
        code = next(word for word in mail.outbox[-1].body.split() if word.isdigit() and len(word) == 6)
        response = self.client.post(
            SET_PASSWORD,
            {"new_password": "Nueva12345", "new_password_confirm": "Nueva12345", "code": code},
            format="json",
            **bearer(self.google),
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.google.refresh_from_db()
        self.assertTrue(self.google.check_password("Nueva12345"))
        self.assertTrue(AuditLog.objects.filter(action="auth.password_set").exists())
        self.assertTrue(any(m.subject.startswith("Tu contraseña cambió") for m in mail.outbox))

    def test_set_password_validates_rules_and_match(self):
        weak = self.client.post(SET_PASSWORD, {"new_password": "corta", "new_password_confirm": "corta"}, format="json", **bearer(self.google))
        self.assertEqual(weak.status_code, 400)
        mismatch = self.client.post(
            SET_PASSWORD, {"new_password": "Nueva12345", "new_password_confirm": "Otra12345"}, format="json", **bearer(self.google)
        )
        self.assertEqual(mismatch.status_code, 400)

    def test_set_password_refused_when_already_has_one(self):
        user = User.objects.create_user("ana@example.com", "ana@example.com", PASSWORD)
        response = self.client.post(
            SET_PASSWORD, {"new_password": "Nueva12345", "new_password_confirm": "Nueva12345"}, format="json", **bearer(user)
        )
        self.assertEqual(response.status_code, 400)
        user.refresh_from_db()
        self.assertTrue(user.check_password(PASSWORD))

    def test_set_password_requires_mfa_code_when_enabled(self):
        enable_totp(self.google)
        body = {"new_password": "Nueva12345", "new_password_confirm": "Nueva12345"}
        missing = self.client.post(SET_PASSWORD, body, format="json", **bearer(self.google))
        self.assertEqual(missing.status_code, 400)
        with mock.patch("apps.accounts.mfa.time.time", return_value=NOW):
            ok = self.client.post(
                SET_PASSWORD, {**body, "code": mfa.totp_now(RFC_SECRET, at=NOW)}, format="json", **bearer(self.google)
            )
        self.assertEqual(ok.status_code, 200, ok.data)


@override_settings(AUTH_COOKIE_SECURE=True, FRONTEND_URL="https://app.example.com")
class ChangeEmailTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("ana@example.com", "ana@example.com", PASSWORD)

    def ask(self, new_email="nueva@example.com", **extra):
        return self.client.post(CHANGE_EMAIL, {"new_email": new_email, "password": PASSWORD, **extra}, format="json", **bearer(self.user))

    def test_change_email_requires_reauth(self):
        response = self.client.post(CHANGE_EMAIL, {"new_email": "nueva@example.com", "password": "mal"}, format="json", **bearer(self.user))
        self.assertEqual(response.status_code, 400)
        self.assertFalse(EmailChangeRequest.objects.exists())

    def test_change_email_sends_link_only_to_new_address(self):
        response = self.ask()
        self.assertEqual(response.status_code, 202, response.data)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["nueva@example.com"])
        self.assertIn("https://app.example.com/confirmar_cambio_email.html?token=", mail.outbox[0].body)

    def test_email_not_changed_until_link_opened(self):
        self.ask()
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "ana@example.com")

    def test_confirm_changes_username_and_notifies_old_email(self):
        self.ask()
        token = link_token(mail.outbox[0])
        mail.outbox.clear()
        response = self.client.post(CONFIRM_EMAIL, {"token": token}, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "nueva@example.com")
        self.assertEqual(self.user.username, "nueva@example.com")
        self.assertEqual([m.to for m in mail.outbox], [["ana@example.com"]])
        self.assertTrue(AuditLog.objects.filter(action="auth.email_change").exists())
        login = self.client.post(LOGIN, {"email": "nueva@example.com", "password": PASSWORD}, format="json")
        self.assertEqual(login.status_code, 200)
        again = self.client.post(CONFIRM_EMAIL, {"token": token}, format="json")
        self.assertEqual(again.status_code, 400)

    def test_taken_email_is_not_revealed(self):
        User.objects.create_user("ocupado@example.com", "ocupado@example.com", PASSWORD)
        free = self.ask(new_email="libre@example.com")
        mail.outbox.clear()
        taken = self.ask(new_email="Ocupado@Example.com")
        self.assertEqual(taken.status_code, free.status_code)
        self.assertEqual(taken.data, free.data)
        self.assertEqual(mail.outbox, [])
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "ana@example.com")

    def test_email_change_normalizes_case(self):
        self.ask(new_email="  Nueva@Example.COM ")
        self.assertEqual(EmailChangeRequest.objects.get().new_email, "nueva@example.com")

    def test_same_email_is_refused(self):
        self.assertEqual(self.ask(new_email="ANA@example.com").status_code, 400)

    def test_expired_change_link_rejected(self):
        self.ask()
        token = link_token(mail.outbox[0])
        EmailChangeRequest.objects.update(expires_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(self.client.post(CONFIRM_EMAIL, {"token": token}, format="json").status_code, 400)

    def test_confirm_closes_all_sessions(self):
        login = self.client.post(LOGIN, {"email": "ana@example.com", "password": PASSWORD, "remember": True}, format="json")
        headers = {"HTTP_AUTHORIZATION": f"Bearer {login.data['access']}"}
        self.client.post(CHANGE_EMAIL, {"new_email": "nueva@example.com", "password": PASSWORD}, format="json", **headers)
        token = link_token([m for m in mail.outbox if m.to == ["nueva@example.com"]][0])
        self.client.post(CONFIRM_EMAIL, {"token": token}, format="json")
        self.assertFalse(SessionRecord.objects.filter(user=self.user, revoked_at__isnull=True).exists())

    def test_google_account_without_password_reauths_with_email_code(self):
        self.user.set_unusable_password()
        self.user.save()
        self.client.post("/api/v1/auth/2fa/reauth-email/", **bearer(self.user))
        code = next(word for word in mail.outbox[-1].body.split() if word.isdigit() and len(word) == 6)
        response = self.client.post(CHANGE_EMAIL, {"new_email": "nueva@example.com", "code": code}, format="json", **bearer(self.user))
        self.assertEqual(response.status_code, 202, response.data)


@override_settings(AUTH_COOKIE_SECURE=True)
class MfaAdoptionMetricsTests(APITestCase):
    def test_metrics_mfa_adoption_excludes_internal_users(self):
        from apps.accounts.tests.team_helpers import new_business

        admin = User.objects.create_user("jefe@example.com", "jefe@example.com", PASSWORD, is_staff=True)
        ana = User.objects.create_user("ana@example.com", "ana@example.com", PASSWORD)
        new_business(ana)
        enable_totp(ana)
        response = self.client.get("/api/v1/users/metrics/", **bearer(admin))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["mfa_adoption"], {"total": 2, "enabled": 1, "totp": 1, "email": 0})


@override_settings(AUTH_COOKIE_SECURE=True)
class ReviewFixesTests(APITestCase):
    """Hallazgos de la revisión final (2026-11-26)."""

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("ana@example.com", "ana@example.com", PASSWORD)

    def reauth_code(self, user):
        self.client.post("/api/v1/auth/2fa/reauth-email/", **bearer(user))
        return next(word for word in mail.outbox[-1].body.split() if word.isdigit() and len(word) == 6)

    def test_change_email_daily_cap_counts_superseded_requests(self):
        statuses = []
        for index in range(6):
            cache.clear()
            response = self.client.post(
                CHANGE_EMAIL, {"new_email": f"nueva{index}@example.com", "password": PASSWORD}, format="json", **bearer(self.user)
            )
            statuses.append(response.status_code)
        self.assertEqual(statuses, [202] * 5 + [429])

    def test_superseded_change_link_no_longer_works(self):
        self.client.post(CHANGE_EMAIL, {"new_email": "primera@example.com", "password": PASSWORD}, format="json", **bearer(self.user))
        first = link_token(mail.outbox[-1])
        self.client.post(CHANGE_EMAIL, {"new_email": "segunda@example.com", "password": PASSWORD}, format="json", **bearer(self.user))
        self.assertEqual(self.client.post(CONFIRM_EMAIL, {"token": first}, format="json").status_code, 400)

    def test_change_email_wrong_password_counts_toward_lockout(self):
        for _ in range(3):
            wrong = self.client.post(CHANGE_EMAIL, {"new_email": "x@example.com", "password": "mal"}, format="json", **bearer(self.user))
            self.assertEqual(wrong.status_code, 400)
        locked = self.client.post(CHANGE_EMAIL, {"new_email": "x@example.com", "password": PASSWORD}, format="json", **bearer(self.user))
        self.assertEqual(locked.status_code, 423)

    def test_set_password_without_mfa_requires_email_code(self):
        google = User.objects.create_user("gogo@gmail.com", "gogo@gmail.com")
        google.set_unusable_password()
        google.save()
        body = {"new_password": "Nueva12345", "new_password_confirm": "Nueva12345"}
        self.assertEqual(self.client.post(SET_PASSWORD, body, format="json", **bearer(google)).status_code, 400)
        ok = self.client.post(SET_PASSWORD, {**body, "code": self.reauth_code(google)}, format="json", **bearer(google))
        self.assertEqual(ok.status_code, 200, ok.data)

    def test_mfa_setup_requires_reauth(self):
        setup = "/api/v1/auth/2fa/setup/"
        self.assertEqual(self.client.post(setup, {"method": "totp"}, format="json", **bearer(self.user)).status_code, 400)
        ok = self.client.post(setup, {"method": "totp", "password": PASSWORD}, format="json", **bearer(self.user))
        self.assertEqual(ok.status_code, 200, ok.data)

        google = User.objects.create_user("gogo@gmail.com", "gogo@gmail.com")
        google.set_unusable_password()
        google.save()
        with_code = self.client.post(setup, {"method": "totp", "code": self.reauth_code(google)}, format="json", **bearer(google))
        self.assertEqual(with_code.status_code, 200, with_code.data)

    def test_email_code_attempt_cap_holds_with_a_stale_copy(self):
        from apps.accounts.models import MfaEmailCode

        mfa.send_email_code(self.user, "login")
        code = next(word for word in mail.outbox[-1].body.split() if word.isdigit() and len(word) == 6)
        stale = MfaEmailCode.objects.get(user=self.user)
        MfaEmailCode.objects.update(attempts=mfa.EMAIL_CODE_MAX_ATTEMPTS)
        with mock.patch("apps.accounts.mfa._pending_email_code", return_value=stale):
            self.assertFalse(mfa.email_code_verify(self.user, code, "login"))

    def test_lockout_failures_are_counted_with_stale_copies(self):
        from apps.accounts.models import LoginLockout

        LoginLockout.objects.create(user=self.user)
        first, second = LoginLockout.objects.get(user=self.user), LoginLockout.objects.get(user=self.user)
        first.register_failure()
        second.register_failure()
        self.assertEqual(LoginLockout.objects.get(user=self.user).failed_attempts, 2)
