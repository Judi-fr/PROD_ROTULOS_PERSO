"""La barra lateral del comerciante (2026-11-18): la arma el backend, filtrada
por permiso, y el frontend (app_sidebar.js) solo la dibuja."""

from rest_framework.test import APITestCase

from apps.accounts.tests.team_helpers import new_business

from .test_team_permissions import add_employee, bearer, make_user

URL = "/api/v1/auth/users/me/dashboard/"


def sidebar(client, user):
    return {item["key"]: item for item in client.get(URL, **bearer(user)).data["sidebar"]}


class SidebarTests(APITestCase):
    def setUp(self):
        self.owner = make_user("owner@example.com")
        new_business(self.owner)

    def test_owner_gets_every_section_in_order(self):
        items = sidebar(self.client, self.owner)
        self.assertEqual(
            list(items), ["home", "orders", "print", "design", "stores", "carriers", "business", "help"]
        )
        self.assertEqual(items["home"]["url"], "dashboard.html")
        self.assertEqual(items["orders"]["badge"], "orders")
        self.assertEqual(items["print"]["badge"], "print")
        self.assertEqual(items["help"]["place"], "bottom")
        self.assertEqual(items["stores"]["url"], "tiendas.html")
        self.assertIn("editor_rotulos.html", items["design"]["match"])

    def test_carriers_section_lists_each_carrier_and_the_rates(self):
        links = [link["url"] for link in sidebar(self.client, self.owner)["carriers"]["links"]]
        self.assertIn("transportista.html?carrier=andreani", links)
        self.assertIn("tarifas_envio.html", links)
        self.assertIn("checkout_transportistas.html", links)

    def test_employee_sees_only_what_their_accesses_allow(self):
        deposito, _ = add_employee(self.owner, "dep@example.com", profile="Depósito")
        items = sidebar(self.client, deposito)
        self.assertNotIn("stores", items)
        self.assertNotIn("carriers", items)
        self.assertNotIn("design", items)
        self.assertIn("orders", items)
        business = [link["url"] for link in items["business"]["links"]]
        self.assertEqual(business, ["equipo.html#datos"])

    def test_admin_also_gets_administration_at_the_bottom(self):
        admin = make_user("admin@example.com", group="admin")
        admin.is_staff = True
        admin.save()
        items = sidebar(self.client, admin)
        self.assertEqual(items["admin"]["url"], "gestionuser.html")
        self.assertEqual(items["admin"]["place"], "bottom")
