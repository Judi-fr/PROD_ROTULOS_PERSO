"""Las claves de API, los webhooks y el alta manual "a nombre de" alguien son
de un COMERCIO, aunque el admin elija a una persona (QA en AWS, 2026-11-20).

En Integraciones el admin busca al dueño por su mail y elige una persona. Desde
los equipos los datos de un comercio cuelgan de su usuario interno, así que la
ingesta guardaba el pedido a nombre de la persona y no aparecía en Mis pedidos
de ningún comercio; los webhooks salientes, atados a la persona, no se
disparaban nunca para los pedidos del comercio.
"""

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from apps.accounts.team_models import Team, TeamMember
from apps.accounts.tests.team_helpers import new_business
from apps.orders.models import Order

from ..models import IncomingWebhook, IntegrationKey, WebhookEndpoint

User = get_user_model()


def person(email):
    return User.objects.create_user(username=email, email=email, password="Rotulos2026")


class OwnerIsBusinessTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin@example.com", email="admin@example.com", password="Rotulos2026", is_staff=True
        )
        self.merchant = person("libreria@example.com")
        self.merchant_data = new_business(self.merchant, name="Librería Sur")
        self.client.force_authenticate(user=self.admin)

    def test_la_clave_de_una_persona_queda_en_su_comercio_y_el_pedido_se_ve(self):
        response = self.client.post(
            "/api/v1/integrations/keys/", {"name": "ERP", "owner": self.merchant.pk}, format="json"
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(IntegrationKey.objects.get(pk=response.data["id"]).owner, self.merchant_data)

        self.client.force_authenticate(user=None)
        ingest = self.client.post(
            "/api/v1/ingest/orders/",
            {"destinatario": "Ana Pérez", "domicilio": "Mitre", "ciudad": "Salta", "cp": "4400", "external_id": "ERP-1"},
            format="json",
            HTTP_AUTHORIZATION=f"Api-Key {response.data['key']}",
        )
        self.assertEqual(ingest.status_code, 200)

        self.client.force_authenticate(user=self.merchant)
        listed = self.client.get("/api/v1/orders/").data["results"]
        self.assertEqual([order["external_id"] for order in listed], ["ERP-1"])

    def test_los_webhooks_de_una_persona_quedan_en_su_comercio(self):
        key = IntegrationKey.objects.create(
            owner=self.merchant_data, name="ERP", key_hash=IntegrationKey.hash_key("bp_x"), prefix="bp_x"
        )
        incoming = self.client.post(
            "/api/v1/integrations/incoming-webhooks/",
            {"name": "Tienda", "slug": "tienda-sur", "owner": self.merchant.pk, "integration_key": key.pk, "mapping": {}},
            format="json",
        )
        self.assertEqual(incoming.status_code, 201)
        self.assertEqual(IncomingWebhook.objects.get(pk=incoming.data["id"]).owner, self.merchant_data)

        outgoing = self.client.post(
            "/api/v1/integrations/webhook-endpoints/",
            {"name": "ERP", "url": "https://erp.example.com/hook", "owner": self.merchant.pk},
            format="json",
        )
        self.assertEqual(outgoing.status_code, 201)
        self.assertEqual(WebhookEndpoint.objects.get(pk=outgoing.data["id"]).owner, self.merchant_data)

    def test_en_varios_comercios_va_al_unico_del_que_es_duena(self):
        new_business(person("otra@example.com"), name="Kiosco Este")
        other_team = Team.objects.get(name="Kiosco Este")
        TeamMember.objects.create(team=other_team, user=self.merchant, role=TeamMember.Role.EMPLOYEE)

        response = self.client.post(
            "/api/v1/integrations/keys/", {"name": "ERP", "owner": self.merchant.pk}, format="json"
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(IntegrationKey.objects.get(pk=response.data["id"]).owner, self.merchant_data)

    def test_sin_un_comercio_claro_no_se_crea(self):
        employee = person("empleado@example.com")
        for name, email in (("Kiosco Este", "e@example.com"), ("Kiosco Oeste", "o@example.com")):
            new_business(person(email), name=name)
            TeamMember.objects.create(
                team=Team.objects.get(name=name), user=employee, role=TeamMember.Role.EMPLOYEE
            )

        response = self.client.post(
            "/api/v1/integrations/keys/", {"name": "ERP", "owner": employee.pk}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Kiosco Este", str(response.data["owner"]))
        self.assertFalse(IntegrationKey.objects.exists())

    def test_el_alta_manual_a_nombre_de_una_persona_queda_en_su_comercio(self):
        # La carga de pedidos es trabajo de comercio: el admin usa el suyo.
        new_business(self.admin, name="Pruebas")
        response = self.client.post(
            "/api/v1/orders/manual/",
            {"user_id": self.merchant.pk, "destinatario": "Ana Pérez", "domicilio": "Mitre", "ciudad": "Salta", "cp": "4400"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Order.objects.get(pk=response.data["id"]).user, self.merchant_data)
