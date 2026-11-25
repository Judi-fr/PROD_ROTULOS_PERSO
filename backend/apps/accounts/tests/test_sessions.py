"""Sesiones con nombre, "Recordarme", inactividad y cierre de sesiones
(docs/superpowers/specs/2026-11-25-recordarme-y-2fa-design.md, etapa 1)."""

import uuid

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import SessionRecord
from apps.audit.models import AuditLog

User = get_user_model()

NEW_AUTH_ACTIONS = [
    "auth.mfa_enable",
    "auth.mfa_disable",
    "auth.mfa_admin_reset",
    "auth.mfa_failed",
    "auth.recovery_code_used",
    "auth.recovery_codes_regenerated",
    "auth.session_revoke",
    "auth.new_device",
    "auth.email_change",
    "auth.password_set",
]


class SecurityModelsTests(TestCase):
    def test_user_session_defaults(self):
        user = User.objects.create_user("ana@example.com", "ana@example.com", "Clave1234")
        session = SessionRecord.objects.create(user=user, browser="Chrome en Windows", method="password")
        self.assertIsInstance(session.id, uuid.UUID)
        self.assertTrue(session.is_active)
        session.revoked_at = timezone.now()
        self.assertFalse(session.is_active)

    def test_new_audit_actions_have_category(self):
        for action in NEW_AUTH_ACTIONS:
            with self.subTest(action=action):
                self.assertIn(action, AuditLog.Action.values)
                self.assertEqual(AuditLog.ACTION_CATEGORIES[action], AuditLog.Category.AUTH)


from datetime import timedelta  # noqa: E402
from unittest import mock  # noqa: E402

from django.contrib.auth.tokens import default_token_generator  # noqa: E402
from django.core.cache import cache  # noqa: E402
from django.test import override_settings  # noqa: E402
from django.utils.encoding import force_bytes  # noqa: E402
from django.utils.http import urlsafe_base64_encode  # noqa: E402
from rest_framework.test import APITestCase  # noqa: E402
from rest_framework_simplejwt.tokens import RefreshToken  # noqa: E402

PASSWORD = "Clave1234"
CHROME_WINDOWS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/158.0.0.0 Safari/537.36"
)
COOKIE = {"HTTP_X_AUTH_MODE": "cookie"}
REFRESH_COOKIE = "rotulos_refresh"
ACCESS_COOKIE = "rotulos_access"
LOGIN = "/api/v1/auth/login/"
REFRESH = "/api/v1/auth/refresh/"
ME = "/api/v1/auth/me/"


@override_settings(AUTH_COOKIE_SECURE=True, GOOGLE_CLIENT_ID="test-client")
class SessionTokenTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("ana@example.com", "ana@example.com", PASSWORD)

    def login(self, remember=None, cookie=False, client=None):
        body = {"email": "ana@example.com", "password": PASSWORD}
        if remember is not None:
            body["remember"] = remember
        headers = {"HTTP_USER_AGENT": CHROME_WINDOWS, **(COOKIE if cookie else {})}
        return (client or self.client).post(LOGIN, body, format="json", **headers)

    def bearer(self, response):
        return {"HTTP_AUTHORIZATION": f"Bearer {response.data['access']}"}

    def test_login_creates_session_with_browser_label(self):
        response = self.login(remember=True)
        self.assertEqual(response.status_code, 200)
        session = SessionRecord.objects.get(user=self.user)
        self.assertEqual(session.browser, "Chrome en Windows")
        self.assertEqual(session.method, "password")
        self.assertTrue(session.remember)

    def test_tokens_carry_sid_and_remember(self):
        response = self.login(remember=True)
        session = SessionRecord.objects.get(user=self.user)
        refresh = RefreshToken(response.data["refresh"])
        self.assertEqual(refresh["sid"], str(session.id))
        self.assertIs(refresh["remember"], True)
        self.assertEqual(refresh.access_token["sid"], str(session.id))

    def test_remember_cookie_has_30_day_max_age(self):
        response = self.login(remember=True, cookie=True)
        self.assertEqual(response.cookies[REFRESH_COOKIE]["max-age"], 30 * 24 * 3600)

    def test_not_remembered_cookie_is_session_cookie(self):
        response = self.login(remember=False, cookie=True)
        cookie = response.cookies[REFRESH_COOKIE]
        self.assertEqual(cookie["max-age"], "")
        self.assertEqual(cookie["expires"], "")
        exp = RefreshToken(cookie.value)["exp"]
        self.assertAlmostEqual(exp - timezone.now().timestamp(), 12 * 3600, delta=60)

    def test_bearer_login_without_remember_keeps_7_days(self):
        response = self.login()
        exp = RefreshToken(response.data["refresh"])["exp"]
        self.assertAlmostEqual(exp - timezone.now().timestamp(), 7 * 24 * 3600, delta=60)

    def test_api_client_without_remember_is_not_closed_for_idleness(self):
        # Un cliente de la API no manda "remember" ni avisa actividad: sigue
        # como antes (7 días), sin cierre por inactividad.
        response = self.login()
        SessionRecord.objects.update(last_seen_at=timezone.now() - timedelta(hours=3))
        ok = self.client.post(REFRESH, {"refresh": response.data["refresh"]}, format="json")
        self.assertEqual(ok.status_code, 200)

    def test_rotation_keeps_remember_lifetime_and_sid(self):
        response = self.login(remember=True)
        sid = RefreshToken(response.data["refresh"])["sid"]
        refresh = response.data["refresh"]
        for _ in range(2):
            rotated = self.client.post(REFRESH, {"refresh": refresh}, format="json")
            self.assertEqual(rotated.status_code, 200)
            refresh = rotated.data["refresh"]
            token = RefreshToken(refresh)
            self.assertEqual(token["sid"], sid)
            self.assertAlmostEqual(token["exp"] - timezone.now().timestamp(), 30 * 24 * 3600, delta=60)
        self.assertEqual(SessionRecord.objects.filter(user=self.user).count(), 1)

    def test_revoked_session_rejects_access_immediately(self):
        response = self.login(remember=True)
        self.assertEqual(self.client.get(ME, **self.bearer(response)).status_code, 200)
        SessionRecord.objects.filter(user=self.user).update(revoked_at=timezone.now())
        denied = self.client.get(ME, **self.bearer(response))
        self.assertEqual(denied.status_code, 401)
        self.assertEqual(denied.data["code"], "session_closed")

    def test_revoked_session_rejects_refresh_and_clears_cookies(self):
        self.login(remember=True, cookie=True)
        SessionRecord.objects.filter(user=self.user).update(revoked_at=timezone.now())
        denied = self.client.post(REFRESH, {}, format="json", **COOKIE)
        self.assertEqual(denied.status_code, 401)
        self.assertEqual(denied.cookies[REFRESH_COOKIE].value, "")

    def test_closed_session_cookie_does_not_block_logging_in_again(self):
        self.login(remember=False, cookie=True)
        SessionRecord.objects.filter(user=self.user).update(revoked_at=timezone.now())
        again = self.login(remember=False, cookie=True)
        self.assertEqual(again.status_code, 200)

    @override_settings(AUTH_IDLE_MINUTES=30)
    def test_idle_non_remembered_session_is_closed_on_refresh(self):
        response = self.login(remember=False)
        # 30 minutos + el margen del servidor (sessions.IDLE_GRACE, 5).
        SessionRecord.objects.update(last_seen_at=timezone.now() - timedelta(minutes=36))
        denied = self.client.post(REFRESH, {"refresh": response.data["refresh"]}, format="json")
        self.assertEqual(denied.status_code, 401)
        self.assertEqual(SessionRecord.objects.get().revoked_reason, "idle")

        SessionRecord.objects.all().delete()
        remembered = self.login(remember=True)
        SessionRecord.objects.update(last_seen_at=timezone.now() - timedelta(minutes=36))
        ok = self.client.post(REFRESH, {"refresh": remembered.data["refresh"]}, format="json")
        self.assertEqual(ok.status_code, 200)

    def test_refresh_without_active_flag_does_not_extend_idle(self):
        response = self.login(remember=False)
        old = timezone.now() - timedelta(minutes=10)
        SessionRecord.objects.update(last_seen_at=old)
        self.client.post(REFRESH, {"refresh": response.data["refresh"]}, format="json")
        self.assertEqual(SessionRecord.objects.get().last_seen_at, old)

    def test_refresh_with_active_flag_marks_activity(self):
        response = self.login(remember=False)
        old = timezone.now() - timedelta(minutes=10)
        SessionRecord.objects.update(last_seen_at=old)
        self.client.post(REFRESH, {"refresh": response.data["refresh"], "active": True}, format="json")
        self.assertGreater(SessionRecord.objects.get().last_seen_at, old)

    def test_logout_closes_its_session(self):
        response = self.login(remember=True)
        self.client.post("/api/v1/auth/logout/", {"refresh": response.data["refresh"]}, format="json", **self.bearer(response))
        self.assertEqual(SessionRecord.objects.get().revoked_reason, "logout")

    def test_password_change_closes_other_sessions_only(self):
        other = self.login(remember=True)
        mine = self.login(remember=True)
        changed = self.client.post(
            "/api/v1/auth/me/change-password/",
            {"current_password": PASSWORD, "new_password": "Nueva12345", "confirm_password": "Nueva12345"},
            format="json",
            **self.bearer(mine),
        )
        self.assertEqual(changed.status_code, 200, changed.data)
        self.assertEqual(self.client.get(ME, **self.bearer(mine)).status_code, 200)
        self.assertEqual(self.client.get(ME, **self.bearer(other)).status_code, 401)
        # La sesión que cambió la contraseña sigue pudiendo renovarse.
        self.assertEqual(self.client.post(REFRESH, {"refresh": mine.data["refresh"]}, format="json").status_code, 200)
        self.assertEqual(self.client.post(REFRESH, {"refresh": other.data["refresh"]}, format="json").status_code, 401)

    def test_password_reset_closes_all_sessions(self):
        response = self.login(remember=True)
        uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        token = default_token_generator.make_token(self.user)
        reset = self.client.post(
            "/api/v1/auth/password-reset/confirm/",
            {"uid": uid, "token": token, "new_password": "Nueva12345"},
            format="json",
        )
        self.assertEqual(reset.status_code, 200, reset.data)
        self.assertEqual(self.client.get(ME, **self.bearer(response)).status_code, 401)

    def test_legacy_token_without_sid_still_authenticates_until_revoke_all(self):
        from apps.accounts.sessions import revoke_all

        legacy = RefreshToken.for_user(self.user)
        headers = {"HTTP_AUTHORIZATION": f"Bearer {legacy.access_token}"}
        self.assertEqual(self.client.get(ME, **headers).status_code, 200)
        revoke_all(self.user, reason="test")
        refreshed = self.client.post(REFRESH, {"refresh": str(legacy)}, format="json")
        self.assertEqual(refreshed.status_code, 401)

    def test_user_payload_carries_session(self):
        response = self.login(remember=False)
        session = SessionRecord.objects.get()
        self.assertEqual(response.data["user"]["session_id"], str(session.id))
        self.assertIs(response.data["user"]["session_remember"], False)

    def test_google_and_register_create_sessions(self):
        claims = {"email": "nuevo@gmail.com", "email_verified": True, "given_name": "Nu"}
        with mock.patch("apps.accounts.auth_views.id_token.verify_oauth2_token", return_value=claims):
            google = self.client.post("/api/v1/auth/google/", {"credential": "x", "remember": True}, format="json")
        self.assertEqual(google.status_code, 200, google.data)
        self.assertEqual(SessionRecord.objects.get(user__email="nuevo@gmail.com").method, "google")

        register = self.client.post(
            "/api/v1/auth/register/",
            {
                "email": "reg@example.com",
                "password": "Clave12345",
                "password_confirm": "Clave12345",
                "first_name": "Re",
                "last_name": "G",
            },
            format="json",
        )
        self.assertEqual(register.status_code, 201, register.data)
        self.assertEqual(SessionRecord.objects.get(user__email="reg@example.com").method, "register")


SESSIONS = "/api/v1/auth/sessions/"


@override_settings(AUTH_COOKIE_SECURE=True)
class SessionApiTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user("ana@example.com", "ana@example.com", PASSWORD)
        self.admin = User.objects.create_user("jefe@example.com", "jefe@example.com", PASSWORD, is_staff=True)

    def login(self, email="ana@example.com", ua=CHROME_WINDOWS):
        response = self.client.post(
            LOGIN, {"email": email, "password": PASSWORD, "remember": True}, format="json", HTTP_USER_AGENT=ua
        )
        self.assertEqual(response.status_code, 200, response.data)
        return {"HTTP_AUTHORIZATION": f"Bearer {response.data['access']}"}

    def test_list_marks_current_and_hides_revoked(self):
        self.login(ua="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Safari/604.1")
        gone = self.login()
        SessionRecord.objects.filter(browser="Chrome en Windows").update(revoked_at=timezone.now())
        mine = self.login()
        rows = self.client.get(SESSIONS, **mine).data
        self.assertEqual(len(rows), 2)
        current = [row for row in rows if row["current"]]
        self.assertEqual(len(current), 1)
        self.assertEqual(current[0]["browser"], "Chrome en Windows")
        self.assertIn("Safari en iPhone", [row["browser"] for row in rows])
        self.assertTrue(gone)

    def test_cannot_revoke_someone_elses_session(self):
        self.login(email="jefe@example.com")
        other = SessionRecord.objects.get(user=self.admin)
        mine = self.login()
        response = self.client.post(f"{SESSIONS}{other.id}/revoke/", **mine)
        self.assertEqual(response.status_code, 404)
        other.refresh_from_db()
        self.assertTrue(other.is_active)

    def test_revoke_one_session_audits_it(self):
        other = self.login()
        session = SessionRecord.objects.get()
        mine = self.login()
        response = self.client.post(f"{SESSIONS}{session.id}/revoke/", **mine)
        self.assertEqual(response.status_code, 204)
        self.assertEqual(self.client.get(ME, **other).status_code, 401)
        self.assertTrue(AuditLog.objects.filter(action="auth.session_revoke", actor=self.user).exists())

    def test_revoke_others_keeps_current(self):
        other = self.login()
        mine = self.login()
        response = self.client.post(f"{SESSIONS}revoke-others/", **mine)
        self.assertEqual(response.data["closed"], 1)
        self.assertEqual(self.client.get(ME, **mine).status_code, 200)
        self.assertEqual(self.client.get(ME, **other).status_code, 401)

    def test_admin_revoke_sessions_requires_users_edit(self):
        self.login()
        plain = User.objects.create_user("pepe@example.com", "pepe@example.com", PASSWORD)
        self.assertTrue(plain)
        headers = self.login(email="pepe@example.com")
        response = self.client.post(f"/api/v1/users/{self.user.pk}/revoke-sessions/", **headers)
        self.assertEqual(response.status_code, 403)

    def test_admin_revokes_someone_elses_sessions(self):
        victim = self.login()
        admin = self.login(email="jefe@example.com")
        response = self.client.post(f"/api/v1/users/{self.user.pk}/revoke-sessions/", **admin)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["closed"], 1)
        self.assertEqual(self.client.get(ME, **victim).status_code, 401)
        log = AuditLog.objects.get(action="auth.session_revoke")
        self.assertEqual(log.actor, self.admin)

    def test_admin_cannot_revoke_own_sessions(self):
        admin = self.login(email="jefe@example.com")
        response = self.client.post(f"/api/v1/users/{self.admin.pk}/revoke-sessions/", **admin)
        self.assertEqual(response.status_code, 400)

    def test_deactivating_user_closes_sessions_at_once(self):
        victim = self.login()
        admin = self.login(email="jefe@example.com")
        response = self.client.delete(f"/api/v1/users/{self.user.pk}/", **admin)
        self.assertEqual(response.status_code, 204)
        self.assertFalse(SessionRecord.objects.filter(user=self.user, revoked_at__isnull=True).exists())
        self.assertEqual(self.client.get(ME, **victim).status_code, 401)

    def test_bulk_deactivate_and_status_patch_close_sessions(self):
        self.login()
        other = User.objects.create_user("otro@example.com", "otro@example.com", PASSWORD)
        self.login(email="otro@example.com")
        admin = self.login(email="jefe@example.com")
        self.client.post(
            "/api/v1/users/bulk-actions/", {"ids": [self.user.pk], "action": "deactivate"}, format="json", **admin
        )
        self.client.patch(f"/api/v1/users/{other.pk}/", {"status": "inactive"}, format="json", **admin)
        self.assertFalse(SessionRecord.objects.filter(user__in=[self.user, other], revoked_at__isnull=True).exists())


    def test_ping_marks_activity_without_rotating(self):
        headers = self.login()
        old = timezone.now() - timedelta(minutes=10)
        SessionRecord.objects.filter(user=self.user).update(last_seen_at=old)
        response = self.client.post(f"{SESSIONS}ping/", **headers)
        self.assertEqual(response.status_code, 204)
        self.assertGreater(SessionRecord.objects.get(user=self.user).last_seen_at, old)

    def test_idle_session_inside_grace_still_works(self):
        response = self.client.post(LOGIN, {"email": "ana@example.com", "password": PASSWORD, "remember": False}, format="json")
        SessionRecord.objects.update(last_seen_at=timezone.now() - timedelta(minutes=33))
        ok = self.client.post(REFRESH, {"refresh": response.data["refresh"]}, format="json")
        self.assertEqual(ok.status_code, 200)
