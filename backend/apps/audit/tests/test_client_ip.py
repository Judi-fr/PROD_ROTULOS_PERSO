"""La IP del cliente detrás de un proxy (balanceador de AWS, Caddy).

``X-Forwarded-For`` lo puede mandar cualquiera: solo valen las entradas que
agregaron NUESTROS proxies, contando desde la derecha (``TRUSTED_PROXIES``).
Antes la auditoría tomaba la primera (la que inventa el cliente) y los
límites por IP usaban el encabezado entero, así que cambiándolo en cada
intento se esquivaban."""

from copy import deepcopy

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import RequestFactory, SimpleTestCase, override_settings
from rest_framework.test import APITestCase

from apps.audit.models import AuditLog
from apps.common.net import client_ip

User = get_user_model()


def rest_framework_with(num_proxies):
    config = deepcopy(settings.REST_FRAMEWORK)
    config["NUM_PROXIES"] = num_proxies
    return config


class ClientIpTests(SimpleTestCase):
    def request(self, xff=None, remote="10.0.0.5"):
        extra = {"REMOTE_ADDR": remote}
        if xff is not None:
            extra["HTTP_X_FORWARDED_FOR"] = xff
        return RequestFactory().get("/", **extra)

    @override_settings(TRUSTED_PROXIES=0)
    def test_without_proxies_the_header_is_ignored(self):
        self.assertEqual(client_ip(self.request("6.6.6.6")), "10.0.0.5")

    @override_settings(TRUSTED_PROXIES=1)
    def test_one_proxy_takes_the_entry_it_added(self):
        # El cliente mandó "6.6.6.6"; el balanceador agregó la IP real al final.
        self.assertEqual(client_ip(self.request("6.6.6.6, 181.105.40.154")), "181.105.40.154")

    @override_settings(TRUSTED_PROXIES=2)
    def test_two_proxies_skip_the_inner_one(self):
        self.assertEqual(client_ip(self.request("6.6.6.6, 181.105.40.154, 10.1.1.1")), "181.105.40.154")

    @override_settings(TRUSTED_PROXIES=1)
    def test_missing_or_garbage_header_falls_back_to_remote_addr(self):
        self.assertEqual(client_ip(self.request()), "10.0.0.5")
        self.assertEqual(client_ip(self.request("no-es-una-ip")), "10.0.0.5")

    @override_settings(TRUSTED_PROXIES=3)
    def test_shorter_header_than_proxies_falls_back_to_remote_addr(self):
        self.assertEqual(client_ip(self.request("181.105.40.154")), "10.0.0.5")


class SpoofedForwardedForTests(APITestCase):
    def setUp(self):
        cache.clear()
        User.objects.create_user("ana@example.com", "ana@example.com", "Clave1234")

    def test_audit_ignores_a_forged_header_without_proxies(self):
        self.client.post(
            "/api/v1/auth/login/",
            {"email": "ana@example.com", "password": "mal"},
            format="json",
            HTTP_X_FORWARDED_FOR="6.6.6.6",
            REMOTE_ADDR="10.0.0.5",
        )
        self.assertEqual(AuditLog.objects.get(action="auth.login_failed").ip_address, "10.0.0.5")

    def test_login_limit_cannot_be_dodged_by_changing_the_header(self):
        statuses = []
        for attempt in range(6):
            response = self.client.post(
                "/api/v1/auth/login/",
                {"email": f"nadie{attempt}@example.com", "password": "mal"},
                format="json",
                HTTP_X_FORWARDED_FOR=f"6.6.6.{attempt}",
                REMOTE_ADDR="10.0.0.5",
            )
            statuses.append(response.status_code)
        self.assertEqual(statuses[-1], 429)

    def test_behind_one_proxy_the_limit_follows_the_real_ip(self):
        with override_settings(TRUSTED_PROXIES=1, REST_FRAMEWORK=rest_framework_with(1)):
            statuses = []
            for attempt in range(6):
                response = self.client.post(
                    "/api/v1/auth/login/",
                    {"email": f"nadie{attempt}@example.com", "password": "mal"},
                    format="json",
                    HTTP_X_FORWARDED_FOR=f"6.6.6.{attempt}, 181.105.40.154",
                    REMOTE_ADDR="10.0.0.5",
                )
                statuses.append(response.status_code)
            self.assertEqual(statuses[-1], 429)
            self.assertEqual(AuditLog.objects.filter(action="auth.login_failed").first().ip_address, "181.105.40.154")
