"""El usuario interno de un comercio (``comercio-…@datos.invalid``) no se le
muestra a nadie en la auditoría ni en la actividad (QA en AWS, 2026-11-20).

Desde los equipos los datos cuelgan de ese usuario interno, y el nombre de un
pedido o de un lote lo traía entre paréntesis: "Pedido #2
(comercio-aff292f72ccc@datos.invalid)". Los pedidos de ejemplo lo guardaban
solo, como "comercio-3e1eece27bf6@datos.invalid".
"""

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from apps.accounts.team_models import Team
from apps.accounts.tests.team_helpers import new_business

from ..models import AuditLog

User = get_user_model()

INTERNAL = "@datos.invalid"


class InternalUserHiddenTests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username="duena@example.com", email="duena@example.com", password="Rotulos2026"
        )
        self.data_user = new_business(self.owner, name="Almacén Norte")
        self.team = Team.objects.get(data_user=self.data_user)
        self.admin = User.objects.create_user(
            username="admin@example.com", email="admin@example.com", password="Rotulos2026", is_staff=True
        )

    def latest(self, action):
        return AuditLog.objects.filter(action=action).latest("id")

    def test_los_pedidos_de_ejemplo_nombran_al_comercio(self):
        self.client.force_authenticate(user=self.owner)
        self.assertEqual(self.client.post("/api/v1/orders/sample/").status_code, 201)
        self.assertEqual(self.latest("order.create").target_repr, "Almacén Norte")

    def test_un_pedido_nuevo_no_guarda_el_usuario_interno(self):
        self.client.force_authenticate(user=self.owner)
        response = self.client.post(
            "/api/v1/orders/manual/",
            {"destinatario": "Ana Pérez", "domicilio": "Mitre", "numero": "10", "ciudad": "Salta", "cp": "4400"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.latest("order.create").target_repr, f"Pedido #{response.data['id']}")

    def test_la_auditoria_del_admin_no_muestra_filas_viejas_con_el_usuario_interno(self):
        AuditLog.objects.create(
            category=AuditLog.Category.ORDERS,
            action="order.status_change",
            target_type="order",
            target_id="2",
            target_repr="Pedido #2 (comercio-aff292f72ccc@datos.invalid)",
            team_id=self.team.pk,
        )
        self.client.force_authenticate(user=self.admin)
        rows = self.client.get("/api/v1/audit/logs/").data["results"]
        self.assertIn("Pedido #2", [row["target_repr"] for row in rows])
        export = self.client.get("/api/v1/audit/logs/export/", {"file_type": "csv"})
        self.assertNotIn(INTERNAL, export.content.decode("utf-8"))

    def test_la_actividad_no_muestra_el_usuario_interno_suelto(self):
        AuditLog.objects.create(
            actor=self.owner,
            actor_email=self.owner.email,
            category=AuditLog.Category.ORDERS,
            action="order.create",
            target_type="user",
            target_id=str(self.data_user.pk),
            target_repr=self.data_user.username,
            team_id=self.team.pk,
        )
        self.client.force_authenticate(user=self.owner)
        rows = self.client.get("/api/v1/team/activity/mine/").data["results"]
        self.assertTrue(rows)
        for row in rows:
            self.assertNotIn(INTERNAL, row["target_repr"])
