"""Límites propios de lotes y renders (ver labels/throttles.py).

Dibujar un rótulo ocupa un worker de gunicorn; con el límite general de
1000/min un solo usuario podía dejar la app lenta para todos. Las tasas se
bajan con ``patch.dict`` sobre el diccionario que leen los throttles.
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from rest_framework.test import APITestCase
from rest_framework.throttling import SimpleRateThrottle

from ..models import ElementLayout

User = get_user_model()

PREVIEW_URL = "/api/v1/labels/preview/"
BATCH_URL = "/api/v1/labels/batch/"
DESIGN = {"destinatario": {"left": 6, "top": 38, "text": "{{destinatario}}"}}


def tasas(**cambios):
    return patch.dict(SimpleRateThrottle.THROTTLE_RATES, cambios)


def admin(email):
    return User.objects.create_user(username=email, email=email, password="Clave123!", is_staff=True)


class LimiteDeRendersTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.usuario = admin("dibuja@example.com")
        self.client.force_authenticate(self.usuario)

    def preview(self):
        return self.client.post(PREVIEW_URL, {"design": DESIGN}, format="json")

    def test_corta_al_pasar_el_limite(self):
        with tasas(labels_render="2/min"):
            codigos = [self.preview().status_code for _ in range(3)]

        self.assertEqual(codigos, [200, 200, 429])

    def test_el_cupo_es_uno_solo_para_todos_los_renders(self):
        # Si cada endpoint tuviera su propio contador, alcanzaría con alternar.
        layout = ElementLayout.objects.create(
            name="Prueba", width_mm=100, height_mm=60, created_by=self.usuario
        )
        with tasas(labels_render="2/min"):
            self.preview()
            self.preview()
            respuesta = self.client.post(
                f"/api/v1/labels/element-layouts/{layout.pk}/render/", {"format": "png"}, format="json"
            )

        self.assertEqual(respuesta.status_code, 429)

    def test_es_por_usuario(self):
        with tasas(labels_render="1/min"):
            self.preview()
            self.client.force_authenticate(admin("otro@example.com"))
            respuesta = self.preview()

        self.assertEqual(respuesta.status_code, 200)


class LimiteDeLotesTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.client.force_authenticate(admin("lotes@example.com"))

    def test_corta_al_pasar_el_limite_aunque_el_pedido_sea_invalido(self):
        # El límite se aplica antes de validar: un loop de pedidos mal armados
        # también ocupa workers.
        with tasas(labels_batch="2/min"):
            codigos = [self.client.post(BATCH_URL, {}, format="json").status_code for _ in range(3)]

        self.assertNotIn(429, codigos[:2])
        self.assertEqual(codigos[2], 429)

    def test_los_lotes_no_gastan_el_cupo_de_renders(self):
        with tasas(labels_batch="1/min", labels_render="1/min"):
            self.client.post(BATCH_URL, {}, format="json")
            respuesta = self.client.post(PREVIEW_URL, {"design": DESIGN}, format="json")

        self.assertEqual(respuesta.status_code, 200)
