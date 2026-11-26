"""Aviso por mail de los mensajes del form de contacto (support_mail.py)."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from apps.accounts.models import SupportMessage
from apps.accounts.tests.team_helpers import new_business

User = get_user_model()

URL = "/api/v1/auth/support/"


@override_settings(
    FRONTEND_URL="https://rotulos.example.org",
    DEFAULT_FROM_EMAIL="Rotulos <support@example.org>",
)
class SupportNotificationTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            username="cliente@example.com", email="cliente@example.com", password="Rotulos2026"
        )
        new_business(self.user)
        self.client.force_authenticate(user=self.user)

    def post(self, subject="No llegan los pedidos", message="Conecté la tienda y no aparece nada."):
        return self.client.post(URL, {"subject": subject, "message": message}, format="json")

    @override_settings(SUPPORT_NOTIFY_EMAILS=["support@example.org"])
    def test_manda_aviso_a_la_casilla_de_soporte(self):
        resp = self.post()

        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(len(mail.outbox), 1)
        sent = mail.outbox[0]
        self.assertEqual(sent.to, ["support@example.org"])
        self.assertEqual(sent.from_email, "Rotulos <support@example.org>")
        self.assertEqual(sent.subject, "[Soporte] No llegan los pedidos")
        self.assertIn("cliente@example.com", sent.body)
        self.assertIn("Conecté la tienda y no aparece nada.", sent.body)
        self.assertIn("https://rotulos.example.org/soporte_admin.html", sent.body)

    @override_settings(SUPPORT_NOTIFY_EMAILS=["support@example.org"])
    def test_responder_el_aviso_le_llega_a_quien_escribio(self):
        self.post()

        self.assertEqual(mail.outbox[0].reply_to, ["cliente@example.com"])

    @override_settings(SUPPORT_NOTIFY_EMAILS=["support@example.org", "otra@example.org"])
    def test_varias_casillas(self):
        self.post()

        self.assertEqual(mail.outbox[0].to, ["support@example.org", "otra@example.org"])

    @override_settings(SUPPORT_NOTIFY_EMAILS=[])
    def test_sin_casilla_configurada_no_manda_nada_y_el_mensaje_se_guarda(self):
        resp = self.post()

        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(mail.outbox, [])
        self.assertTrue(SupportMessage.objects.filter(user=self.user).exists())

    @override_settings(SUPPORT_NOTIFY_EMAILS=["support@example.org"])
    def test_si_falla_el_mail_el_mensaje_igual_se_guarda(self):
        with patch("django.core.mail.EmailMultiAlternatives.send", side_effect=OSError("SMTP caído")):
            with self.assertLogs("apps.accounts.support_mail", level="ERROR"):
                resp = self.post()

        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertTrue(SupportMessage.objects.filter(user=self.user).exists())

    @override_settings(SUPPORT_NOTIFY_EMAILS=["support@example.org"])
    def test_el_asunto_del_usuario_no_puede_meter_cabeceras(self):
        self.post(subject="Hola\nBcc: alguien@example.net")

        sent = mail.outbox[0]
        self.assertNotIn("\n", sent.subject)
        self.assertEqual(sent.bcc, [])

    @override_settings(SUPPORT_NOTIFY_EMAILS=["support@example.org"])
    def test_el_html_escapa_lo_que_escribio_el_usuario(self):
        self.post(message="<script>alert(1)</script>")

        html = mail.outbox[0].alternatives[0][0]
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)
