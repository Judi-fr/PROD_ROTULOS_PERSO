"""Reglas de los formularios de cuenta que salieron de las pruebas manuales
(2026-11-18): la contraseña nueva no puede ser la actual, el pedido de reset
rechaza un texto que no es un email y el registro no acepta un nombre sin
apellido.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.core.cache import cache
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.auth_views import SAME_PASSWORD_MSG
from apps.accounts.tests.team_helpers import new_business

User = get_user_model()

PASSWORD = "Rotulos2026"


class AccountFormRulesBase(APITestCase):
    def setUp(self):
        cache.clear()
        super().setUp()
        self.user = User.objects.create_user(
            username="reglas@example.com", email="reglas@example.com", password=PASSWORD,
        )
        new_business(self.user)


class SamePasswordTests(AccountFormRulesBase):
    def test_change_password_refuses_the_current_one(self):
        self.client.force_authenticate(self.user)
        resp = self.client.post(
            "/api/v1/auth/me/change-password/",
            {"current_password": PASSWORD, "new_password": PASSWORD, "confirm_password": PASSWORD},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data["new_password"], SAME_PASSWORD_MSG)

    def test_reset_confirm_refuses_the_current_one(self):
        resp = self.client.post(
            "/api/v1/auth/password-reset/confirm/",
            {
                "uid": urlsafe_base64_encode(force_bytes(self.user.pk)),
                "token": default_token_generator.make_token(self.user),
                "new_password": PASSWORD,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(resp.data["detail"], SAME_PASSWORD_MSG)

    def test_reset_confirm_accepts_a_different_one(self):
        resp = self.client.post(
            "/api/v1/auth/password-reset/confirm/",
            {
                "uid": urlsafe_base64_encode(force_bytes(self.user.pk)),
                "token": default_token_generator.make_token(self.user),
                "new_password": "OtraClave2027",
            },
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)


class ResetRequestFormatTests(AccountFormRulesBase):
    def test_text_that_is_not_an_email_is_refused_and_sends_nothing(self):
        for text in ("hola que tal", "sinarroba.com", "reglas@example"):
            resp = self.client.post("/api/v1/auth/password-reset/", {"email": text}, format="json")
            self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, text)
        self.assertEqual(len(mail.outbox), 0)

    def test_a_well_formed_email_still_gets_the_generic_answer(self):
        resp = self.client.post("/api/v1/auth/password-reset/", {"email": "nadie@example.com"}, format="json")
        self.assertEqual(resp.status_code, status.HTTP_200_OK)


class RegisterNameTests(APITestCase):
    URL = "/api/v1/auth/register/"

    def setUp(self):
        cache.clear()
        super().setUp()

    def test_first_name_without_last_name_is_refused(self):
        resp = self.client.post(
            self.URL, {"email": "solo@example.com", "password": PASSWORD, "first_name": "Ana"}, format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(User.objects.filter(username="solo@example.com").exists())

    def test_full_name_is_accepted(self):
        resp = self.client.post(
            self.URL,
            {"email": "completa@example.com", "password": PASSWORD, "first_name": "Ana", "last_name": "Paz"},
            format="json",
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
