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
        # Desde 2026-11-19 es una sección del menú, con sus pantallas adentro
        # (antes las páginas de admin tenían su propio menú).
        self.assertEqual(items["admin"]["place"], "main")
        links = [link["url"] for link in items["admin"]["links"]]
        self.assertEqual(
            links,
            ["gestionuser.html", "roles.html", "comercios.html", "pedidos_admin.html", "reportes.html", "auditoria.html",
             "soporte_admin.html", "comercios_baja.html", "catalogos.html", "estado_sistema.html"],
        )
        self.assertIn("comercio_usuario.html", items["admin"]["match"])

    def test_admin_without_a_business_gets_no_merchant_sections(self):
        admin = make_user("admin2@example.com", group="admin")
        admin.is_staff = True
        admin.save()
        items = sidebar(self.client, admin)
        # Sin comercio las secciones del comercio vienen en gris (disabled),
        # sin funciones ni números.
        self.assertEqual(list(items), ["home", "orders", "print", "design", "stores", "carriers", "business", "help", "admin"])
        for key in ("orders", "print", "design", "stores", "carriers"):
            self.assertTrue(items[key]["disabled"], key)
            self.assertEqual(items[key]["links"], [], key)
            self.assertIsNone(items[key]["badge"], key)
        self.assertFalse(items["admin"]["disabled"])
        self.assertEqual(items["business"]["url"], "comercio_inicio.html")
        # Sin comercio, su Inicio es el resumen de la plataforma.
        self.assertEqual(items["home"]["url"], "resumen_plataforma.html")
        self.assertNotIn("resumen_plataforma.html", [link["url"] for link in items["admin"]["links"]])
        new_business(admin)
        items = sidebar(self.client, admin)
        self.assertIn("orders", items)
        self.assertFalse(items["orders"]["disabled"])
        self.assertTrue(items["orders"]["links"])
        # Con comercio, el Inicio es el del comercio y el resumen va en Administración.
        self.assertEqual(items["home"]["url"], "dashboard.html")
        self.assertEqual(items["admin"]["links"][0]["url"], "resumen_plataforma.html")

    def test_merchant_without_a_business_sees_the_sections_in_grey(self):
        alone = make_user("solo@example.com")
        items = sidebar(self.client, alone)
        self.assertEqual(list(items), ["home", "orders", "print", "design", "stores", "carriers", "business", "help"])
        self.assertTrue(all(items[key]["disabled"] for key in ("orders", "print", "design", "stores", "carriers")))
        self.assertFalse(items["home"]["disabled"])
        self.assertEqual(items["business"]["url"], "comercio_inicio.html")
        self.assertEqual(items["business"]["links"], [])

    def test_owner_sections_are_not_disabled(self):
        self.assertFalse(any(item["disabled"] for item in sidebar(self.client, self.owner).values()))

    def test_merchant_gets_no_administration(self):
        self.assertNotIn("admin", sidebar(self.client, self.owner))

    def test_platform_staff_sees_only_their_admin_screens(self):
        from django.contrib.auth.models import Group

        from apps.accounts.models import GroupRolePermission, RolePermission

        staff = make_user("reportes@example.com", group="reportes")
        group = Group.objects.get(name="reportes")
        GroupRolePermission.objects.create(group=group, permission=RolePermission.objects.get(key="reports.view"))
        items = sidebar(self.client, staff)
        self.assertEqual([link["url"] for link in items["admin"]["links"]], ["reportes.html"])
        self.assertEqual(items["admin"]["url"], "reportes.html")
