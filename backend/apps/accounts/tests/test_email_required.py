"""Confirmar el email es obligatorio para usar la app (2026-11-18, pedido del
usuario: cuentas con emails inventados como asdfg@asdfg.com se creaban y
usaban igual). Lo hace cumplir la autenticación (authentication.py) en toda
la API; las vistas públicas y lo mínimo para confirmar quedan abiertos."""

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import EmailVerification
from apps.accounts.tests.team_helpers import new_business

User = get_user_model()

PASSWORD = "Rotulos2026"


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class EmailRequiredTests(APITestCase):
    def setUp(self):
        cache.clear()
        super().setUp()

    def register(self, email="nueva@example.com"):
        resp = self.client.post(
            "/api/v1/auth/register/",
            {"email": email, "password": PASSWORD, "first_name": "Ana", "last_name": "Paz"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {resp.data['access']}")
        return resp

    def test_new_account_is_blocked_until_it_confirms(self):
        resp = self.register()
        self.assertFalse(resp.data["user"]["email_verified"])
        blocked = self.client.post("/api/v1/team/create/", {"name": "Mi comercio"}, format="json")
        self.assertEqual(blocked.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(blocked.data["code"], "email_not_verified")

        token = EmailVerification.objects.get(user__email="nueva@example.com").token
        self.assertEqual(self.client.post("/api/v1/auth/verify-email/confirm/", {"token": token}, format="json").status_code, 200)
        created = self.client.post("/api/v1/team/create/", {"name": "Mi comercio"}, format="json")
        self.assertEqual(created.status_code, status.HTTP_200_OK)

    def test_unconfirmed_account_can_see_itself_resend_and_log_out(self):
        registered = self.register()
        me = self.client.get("/api/v1/auth/me/")
        self.assertEqual(me.status_code, status.HTTP_200_OK)
        self.assertFalse(me.data["email_verified"])
        sent_before = len(mail.outbox)
        resend = self.client.post("/api/v1/auth/verify-email/resend/")
        self.assertEqual(resend.status_code, status.HTTP_200_OK)
        self.assertEqual(len(mail.outbox), sent_before + 1)
        logout = self.client.post("/api/v1/auth/logout/", {"refresh": registered.data["refresh"]}, format="json")
        self.assertEqual(logout.status_code, status.HTTP_205_RESET_CONTENT)

    def test_unconfirmed_account_can_still_log_in(self):
        self.register()
        self.client.credentials()
        login = self.client.post("/api/v1/auth/login/", {"email": "nueva@example.com", "password": PASSWORD}, format="json")
        self.assertEqual(login.status_code, status.HTTP_200_OK)
        self.assertFalse(login.data["user"]["email_verified"])

    def test_public_views_stay_open_with_an_unconfirmed_session(self):
        self.register()
        self.assertEqual(self.client.get("/api/v1/health/").status_code, status.HTTP_200_OK)

    def test_accounts_without_a_pending_verification_are_not_affected(self):
        # Las cuentas viejas, las de Google y las que crea el admin no tienen
        # verificación pendiente: cuentan como confirmadas.
        user = User.objects.create_user(username="vieja@example.com", email="vieja@example.com", password=PASSWORD)
        new_business(user)
        self.client.force_authenticate(user)
        self.assertEqual(self.client.get("/api/v1/orders/").status_code, status.HTTP_200_OK)
