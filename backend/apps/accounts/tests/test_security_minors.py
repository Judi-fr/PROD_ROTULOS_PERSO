"""Detalles menores de la revisión final de la seguridad de la cuenta
(.superpowers ledger, "minor (deferred)"), 2026-11-26."""

import re
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core import mail
from django.core.cache import cache
from django.db import IntegrityError
from django.test import override_settings
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts import mfa
from apps.accounts.models import EmailVerification, SessionRecord
from apps.accounts.tests.test_mfa import NOW, RFC_SECRET, enable_totp

User = get_user_model()
PASSWORD = "Clave1234"
LOGIN = "/api/v1/auth/login/"
REFRESH = "/api/v1/auth/refresh/"
COOKIE = {"HTTP_X_AUTH_MODE": "cookie"}


def bearer(user):
    return {"HTTP_AUTHORIZATION": f"Bearer {RefreshToken.for_user(user).access_token}"}


@override_settings(AUTH_COOKIE_SECURE=True)
class SecurityMinorsTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("ana@example.com", "ana@example.com", PASSWORD)

    # 1. Un mismo código de la app no sirve dos veces aunque lleguen juntos.
    def test_totp_step_is_claimed_in_the_database(self):
        config = enable_totp(self.user)
        stale = type(config).objects.get(pk=config.pk)
        code = mfa.totp_now(RFC_SECRET, at=NOW)
        with mock.patch("apps.accounts.mfa.time.time", return_value=NOW):
            self.assertTrue(mfa.totp_verify(config, code))
            self.assertFalse(mfa.totp_verify(stale, code))

    # 2. Un refresh viejo (sin sid) pasa a ser una sesión con nombre al rotar.
    def test_legacy_refresh_becomes_a_named_session_on_rotation(self):
        legacy = RefreshToken.for_user(self.user)
        rotated = self.client.post(REFRESH, {"refresh": str(legacy)}, format="json")
        self.assertEqual(rotated.status_code, 200)
        token = RefreshToken(rotated.data["refresh"])
        session = SessionRecord.objects.get(user=self.user)
        self.assertEqual(token["sid"], str(session.id))
        self.assertTrue(session.remember)

    # 3. Salir con el access vencido igual cierra la sesión en el servidor.
    def test_logout_with_only_the_refresh_cookie_closes_the_session(self):
        self.client.post(LOGIN, {"email": "ana@example.com", "password": PASSWORD, "remember": False}, format="json", **COOKIE)
        self.client.cookies.pop("rotulos_access")
        response = self.client.post("/api/v1/auth/logout/", format="json", **COOKIE)
        self.assertEqual(response.status_code, 205)
        self.assertEqual(SessionRecord.objects.get().revoked_reason, "logout")

    def test_logout_with_an_already_rotated_refresh_still_closes_its_session(self):
        login = self.client.post(LOGIN, {"email": "ana@example.com", "password": PASSWORD, "remember": True}, format="json")
        old = login.data["refresh"]
        self.client.post(REFRESH, {"refresh": old}, format="json")
        response = self.client.post(
            "/api/v1/auth/logout/", {"refresh": old}, format="json", HTTP_AUTHORIZATION=f"Bearer {login.data['access']}"
        )
        self.assertEqual(response.status_code, 205)
        self.assertEqual(SessionRecord.objects.get().revoked_reason, "logout")

    def test_logout_without_header_in_cookie_mode_does_nothing(self):
        self.client.post(LOGIN, {"email": "ana@example.com", "password": PASSWORD, "remember": True}, format="json", **COOKIE)
        self.client.cookies.pop("rotulos_access")
        response = self.client.post("/api/v1/auth/logout/", format="json")
        self.assertEqual(response.status_code, 400)
        self.assertTrue(SessionRecord.objects.get().is_active)

    # 4. Con el email sin confirmar se puede corregir un email mal escrito.
    def test_unverified_account_can_change_its_email(self):
        EmailVerification.objects.create(user=self.user, token="t" * 30, is_verified=False)
        response = self.client.post(
            "/api/v1/auth/me/change-email/", {"new_email": "bien@example.com", "password": PASSWORD}, format="json", **bearer(self.user)
        )
        self.assertEqual(response.status_code, 202, response.data)

    # 5. Confirmar el cambio no echa al navegador que lo pidió, y una carrera
    #    con un registro del mismo email no da 500.
    def test_confirm_keeps_the_session_of_the_browser_that_confirms(self):
        login = self.client.post(LOGIN, {"email": "ana@example.com", "password": PASSWORD, "remember": True}, format="json", **COOKIE)
        self.assertEqual(login.status_code, 200)
        other = self.client_class()
        other.post(LOGIN, {"email": "ana@example.com", "password": PASSWORD, "remember": True}, format="json", **COOKIE)
        self.client.post("/api/v1/auth/me/change-email/", {"new_email": "nueva@example.com", "password": PASSWORD}, format="json", **COOKIE)
        token = re.search(r"token=([\w-]+)", mail.outbox[-1].body).group(1)
        ok = self.client.post("/api/v1/auth/me/change-email/confirm/", {"token": token}, format="json", **COOKIE)
        self.assertEqual(ok.status_code, 200, ok.data)
        open_sessions = SessionRecord.objects.filter(user=self.user, revoked_at__isnull=True)
        self.assertEqual(open_sessions.count(), 1)

    def test_confirm_race_with_registration_answers_400(self):
        self.client.post(
            "/api/v1/auth/me/change-email/", {"new_email": "nueva@example.com", "password": PASSWORD}, format="json", **bearer(self.user)
        )
        token = re.search(r"token=([\w-]+)", mail.outbox[-1].body).group(1)
        with mock.patch.object(User, "save", side_effect=IntegrityError("duplicado")):
            response = self.client.post("/api/v1/auth/me/change-email/confirm/", {"token": token}, format="json")
        self.assertEqual(response.status_code, 400)

    # 6. Personal de la plataforma no le saca la protección al admin.
    def test_staff_cannot_reset_admin_2fa_or_close_admin_sessions(self):
        admin = User.objects.create_user("jefe@example.com", "jefe@example.com", PASSWORD, is_staff=True)
        admin.groups.add(Group.objects.get_or_create(name="admin")[0])
        enable_totp(admin)
        staff = User.objects.create_user("soporte@example.com", "soporte@example.com", PASSWORD)
        staff.groups.add(Group.objects.get_or_create(name="soporte")[0])
        with mock.patch("apps.accounts.user_admin_views.user_has_permission", return_value=True):
            reset = self.client.post(f"/api/v1/users/{admin.pk}/reset-2fa/", **bearer(staff))
            revoke = self.client.post(f"/api/v1/users/{admin.pk}/revoke-sessions/", **bearer(staff))
        self.assertEqual(reset.status_code, 403)
        self.assertEqual(revoke.status_code, 403)
        self.assertTrue(mfa.mfa_enabled(admin))
