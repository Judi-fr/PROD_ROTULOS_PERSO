"""Comercios para el admin (GET /api/v1/teams/directory/ y /teams/<id>/detail/):
la lista de los comercios abiertos y la ficha de cada uno (2026-11-19)."""

from datetime import timedelta

from django.utils import timezone
from rest_framework.test import APITestCase

from apps.accounts import teams
from apps.accounts.models import TeamMember
from apps.accounts.team_models import Team
from apps.carriers.models import CarrierAccount
from apps.integrations.models import StoreConnection
from apps.orders.models import Address, Order

from .test_team_permissions import add_employee, bearer, make_user

LIST = "/api/v1/teams/directory/"


def make_admin():
    admin = make_user("admin@example.com", group="admin")
    admin.is_staff = True
    admin.save()
    return admin


class AdminBusinessesTests(APITestCase):
    def setUp(self):
        self.admin = make_admin()
        self.owner = make_user("dueno@example.com")
        self.team = teams.create_team(self.owner, name="Kiosco Norte")
        self.data = self.team.data_user
        add_employee(self.owner, "empleado@example.com")
        address = Address.objects.create(user=self.data, recipient_name="Ana", street="Calle", number="1", city="CABA")
        Order.objects.create(user=self.data, address=address)
        Order.objects.create(user=self.data, address=address, is_sample=True)
        viejo = Order.objects.create(user=self.data, address=address)
        Order.objects.filter(pk=viejo.pk).update(created_at=timezone.now() - timedelta(days=60))
        StoreConnection.objects.create(owner=self.data, platform="tiendanube", external_store_id="1", name="Norte", status="active")
        StoreConnection.objects.create(owner=self.data, platform="shopify", external_store_id="x.myshopify.com", status="error")

        other = make_user("otro@example.com")
        self.other = teams.create_team(other, name="Almacén Sur")
        closed_owner = make_user("cerrado@example.com")
        closed = teams.create_team(closed_owner, name="Cerrado")
        closed.closed_at = timezone.now()
        closed.save(update_fields=["closed_at"])

    def rows(self, query=""):
        response = self.client.get(f"{LIST}{query}", **bearer(self.admin))
        self.assertEqual(response.status_code, 200)
        return response.data

    def test_lists_only_open_businesses_with_their_numbers(self):
        data = self.rows("?sort=name")
        self.assertEqual(data["pagination"]["count"], 2)
        names = [row["name"] for row in data["results"]]
        self.assertEqual(names, ["Almacén Sur", "Kiosco Norte"])
        kiosco = data["results"][1]
        self.assertEqual(kiosco["owner_email"], "dueno@example.com")
        self.assertEqual(kiosco["member_count"], 2)
        # Los de ejemplo no cuentan.
        self.assertEqual(kiosco["orders_total"], 2)
        self.assertEqual(kiosco["orders_30d"], 1)
        self.assertIsNotNone(kiosco["last_order_at"])
        self.assertEqual(kiosco["stores_active"], 1)
        self.assertEqual(kiosco["stores_error"], 1)
        self.assertEqual(sorted(kiosco["platforms"]), ["Shopify", "Tiendanube"])

    def test_search_by_name_or_owner_email(self):
        self.assertEqual([r["name"] for r in self.rows("?search=norte")["results"]], ["Kiosco Norte"])
        self.assertEqual([r["name"] for r in self.rows("?search=otro@")["results"]], ["Almacén Sur"])

    def test_filter_with_problems_and_sort_by_orders(self):
        self.assertEqual([r["name"] for r in self.rows("?problems=1")["results"]], ["Kiosco Norte"])
        self.assertEqual(self.rows("?sort=-orders_30d")["results"][0]["name"], "Kiosco Norte")

    def test_detail_has_members_stores_and_carriers(self):
        CarrierAccount.objects.create(owner=self.data, carrier="andreani", is_active=False, last_error="Clave rechazada")
        response = self.client.get(f"/api/v1/teams/{self.team.id}/detail/", **bearer(self.admin))
        self.assertEqual(response.status_code, 200)
        detail = response.data
        self.assertEqual(detail["name"], "Kiosco Norte")
        roles = {m["email"]: m["role"] for m in detail["members"]}
        self.assertEqual(roles, {"dueno@example.com": TeamMember.Role.OWNER, "empleado@example.com": TeamMember.Role.EMPLOYEE})
        self.assertEqual(len(detail["stores"]), 2)
        self.assertEqual(detail["carriers"][0]["last_error"], "Clave rechazada")
        self.assertEqual(detail["orders_total"], 2)

    def test_needs_users_view(self):
        self.assertEqual(self.client.get(LIST, **bearer(self.owner)).status_code, 403)
        self.assertEqual(self.client.get(f"/api/v1/teams/{self.team.id}/detail/", **bearer(self.owner)).status_code, 403)

    def test_detail_of_a_closed_business_is_404(self):
        closed = Team.objects.get(name="Cerrado")
        self.assertEqual(self.client.get(f"/api/v1/teams/{closed.id}/detail/", **bearer(self.admin)).status_code, 404)
