"""Límites de las vistas que mandan correos (reset, registro, reenvío).

El cupo diario del SMTP es compartido: si alguien lo agota, nadie más recibe
resets ni verificaciones. Por eso, además de los límites por minuto por IP,
hay límites por email destino y por día (ver auth_views).

Las tasas de días/horas se bajan con ``patch.dict`` sobre el diccionario de
tasas que leen los throttles al instanciarse en cada pedido.
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from rest_framework import status
from rest_framework.throttling import SimpleRateThrottle

from ..models import EmailVerification
from .test_accounts import STRONG_PASSWORD, AuthTestCase

User = get_user_model()

RESET_URL = "/api/v1/auth/password-reset/"
REGISTER_URL = "/api/v1/auth/register/"
RESEND_URL = "/api/v1/auth/verify-email/resend/"


def tasas(**cambios):
    return patch.dict(SimpleRateThrottle.THROTTLE_RATES, cambios)


class PasswordResetPorEmailTests(AuthTestCase):
    def setUp(self):
        super().setUp()
        User.objects.create_user(
            username="victima@example.com", email="victima@example.com", password=STRONG_PASSWORD
        )

    def pedir_reset(self, email, ip):
        return self.client.post(RESET_URL, {"email": email}, format="json", REMOTE_ADDR=ip)

    def test_el_mismo_email_se_corta_al_cuarto_aunque_cambie_la_ip(self):
        # Desde muchas IPs (botnet) no se le puede llenar la casilla a nadie.
        codigos = [self.pedir_reset("victima@example.com", f"10.0.0.{i}").status_code for i in range(1, 5)]

        self.assertEqual(codigos, [200, 200, 200, 429])
        self.assertEqual(len(mail.outbox), 3)

    def test_cuenta_el_email_normalizado(self):
        for i, email in enumerate(["victima@example.com", "VICTIMA@example.com", " victima@Example.com "]):
            self.assertEqual(self.pedir_reset(email, f"10.0.1.{i}").status_code, 200)

        self.assertEqual(self.pedir_reset("Victima@Example.COM", "10.0.1.9").status_code, 429)

    def test_otro_email_no_se_ve_afectado(self):
        for i in range(4):
            self.pedir_reset("victima@example.com", f"10.0.2.{i}")

        self.assertEqual(self.pedir_reset("otra@example.com", "10.0.2.9").status_code, 200)

    def test_el_429_no_revela_si_la_cuenta_existe(self):
        # Mismo corte para un email sin cuenta: el límite no sirve para enumerar.
        codigos = [self.pedir_reset("nadie@example.com", f"10.0.3.{i}").status_code for i in range(1, 5)]

        self.assertEqual(codigos, [200, 200, 200, 429])
        self.assertEqual(len(mail.outbox), 0)


class PasswordResetDiarioPorIPTests(AuthTestCase):
    def test_tope_diario_por_ip_aunque_cambie_el_email(self):
        with tasas(password_reset="1000/min", password_reset_daily="3/day"):
            codigos = [
                self.client.post(RESET_URL, {"email": f"x{i}@example.com"}, format="json").status_code
                for i in range(4)
            ]

        self.assertEqual(codigos, [200, 200, 200, 429])

    def test_tener_sesion_no_saltea_el_tope_diario(self):
        # AnonRateThrottle ignora a los logueados: con él, alcanzaba con
        # crearse una cuenta para pedir resets hacia cualquier email sin tope.
        usuario = User.objects.create_user(username="u@example.com", email="u@example.com", password=STRONG_PASSWORD)
        self.client.force_authenticate(usuario)

        with tasas(password_reset="1000/min", password_reset_daily="2/day"):
            codigos = [
                self.client.post(RESET_URL, {"email": f"y{i}@example.com"}, format="json").status_code
                for i in range(3)
            ]

        self.assertEqual(codigos, [200, 200, 429])


class RegisterDiarioPorIPTests(AuthTestCase):
    def test_tope_diario_de_altas_por_ip(self):
        with tasas(anon="1000/min", register_daily="2/day"):
            codigos = [
                self.client.post(
                    REGISTER_URL, {"email": f"nuevo{i}@example.com", "password": STRONG_PASSWORD}, format="json"
                ).status_code
                for i in range(3)
            ]

        self.assertEqual(codigos, [201, 201, 429])
        self.assertFalse(User.objects.filter(username="nuevo2@example.com").exists())

    def test_otra_ip_puede_registrarse(self):
        with tasas(anon="1000/min", register_daily="1/day"):
            self.client.post(
                REGISTER_URL, {"email": "a@example.com", "password": STRONG_PASSWORD}, format="json",
                REMOTE_ADDR="10.1.0.1",
            )
            resp = self.client.post(
                REGISTER_URL, {"email": "b@example.com", "password": STRONG_PASSWORD}, format="json",
                REMOTE_ADDR="10.1.0.2",
            )

        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)


class ReenvioVerificacionPorHoraTests(AuthTestCase):
    def test_tres_reenvios_por_hora(self):
        usuario = User.objects.create_user(username="sinverificar@example.com", email="sinverificar@example.com", password=STRONG_PASSWORD)
        EmailVerification.objects.create(user=usuario, is_verified=False)
        self.client.force_authenticate(usuario)

        codigos = [self.client.post(RESEND_URL).status_code for _ in range(4)]

        self.assertEqual(codigos, [200, 200, 200, 429])
        self.assertEqual(len(mail.outbox), 3)
