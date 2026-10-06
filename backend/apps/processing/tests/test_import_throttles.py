"""Límites de las lecturas con el modelo: cada una se paga por token.

Ninguno llama a Claude: ``_request_reading`` se simula como en
test_processing. Las tasas se bajan con ``patch.dict`` sobre el diccionario
que leen los throttles al instanciarse en cada pedido.
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework.throttling import SimpleRateThrottle

from apps.documents.models import UploadedLabelFile

from .test_processing import respuesta_del_modelo

User = get_user_model()


def tasas(**cambios):
    return patch.dict(SimpleRateThrottle.THROTTLE_RATES, cambios)


@patch("apps.processing.agent._request_reading")
class TopeDiarioDeLecturasTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.url = reverse("label-import-list")
        self.usuario = User.objects.create_user(username="ana", email="ana@test.com", password="x")
        self.documento = UploadedLabelFile.objects.create(
            file="rotulos/r.png", original_filename="r.png", mime_type="image/png",
            size_bytes=100, uploaded_by=self.usuario,
        )
        self.client.force_authenticate(self.usuario)

    def leer(self):
        return self.client.post(self.url, {"uploaded_file": self.documento.pk})

    def test_corta_al_llegar_al_tope_diario_sin_llamar_al_modelo(self, pedir):
        pedir.return_value = (respuesta_del_modelo(), {"input": 1, "output": 1}, "req")

        with tasas(importacion_rotulo="1000/min", label_import_daily="2/day"):
            codigos = [self.leer().status_code for _ in range(3)]

        self.assertEqual(codigos, [201, 201, 429])
        self.assertEqual(pedir.call_count, 2)  # la tercera no gastó tokens

    def test_reintentar_tambien_cuenta(self, pedir):
        pedir.return_value = (respuesta_del_modelo(), {"input": 1, "output": 1}, "req")

        with tasas(importacion_rotulo="1000/min", label_import_daily="2/day"):
            primera = self.leer()
            self.client.post(reverse("label-import-retry", args=[primera.data["id"]]))
            tercera = self.client.post(reverse("label-import-retry", args=[primera.data["id"]]))

        self.assertEqual(tercera.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(pedir.call_count, 2)

    def test_listar_y_ver_no_gastan_el_cupo(self, pedir):
        pedir.return_value = (respuesta_del_modelo(), {"input": 1, "output": 1}, "req")

        with tasas(importacion_rotulo="1000/min", label_import_daily="1/day"):
            for _ in range(5):
                self.assertEqual(self.client.get(self.url).status_code, 200)
            respuesta = self.leer()

        self.assertEqual(respuesta.status_code, status.HTTP_201_CREATED)

    def test_el_tope_es_por_usuario(self, pedir):
        pedir.return_value = (respuesta_del_modelo(), {"input": 1, "output": 1}, "req")
        otro = User.objects.create_user(username="beto", email="beto@test.com", password="x")
        suyo = UploadedLabelFile.objects.create(
            file="rotulos/b.png", original_filename="b.png", mime_type="image/png",
            size_bytes=100, uploaded_by=otro,
        )

        with tasas(importacion_rotulo="1000/min", label_import_daily="1/day"):
            self.leer()
            self.client.force_authenticate(otro)
            respuesta = self.client.post(self.url, {"uploaded_file": suyo.pk})

        self.assertEqual(respuesta.status_code, status.HTTP_201_CREATED)
