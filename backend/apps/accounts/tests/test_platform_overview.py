"""Resumen de la plataforma (GET /api/v1/admin/overview/): el Inicio del admin.
Cada bloque con el permiso de la pantalla a la que lleva."""

from datetime import timedelta

from django.contrib.auth.models import Group
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.accounts import teams
from apps.accounts.models import GroupRolePermission, RolePermission, SupportMessage
from apps.accounts.tests.team_helpers import new_business
from apps.orders.models import Address, Order

from .test_team_permissions import bearer, make_user

URL = "/api/v1/admin/overview/"


def make_admin(email="admin@example.com"):
    admin = make_user(email, group="admin")
    admin.is_staff = True
    admin.save()
    return admin


def make_order(owner, **extra):
    address = Address.objects.create(
        user=owner, street="Calle", number="1", city="Rosario", state="Santa Fe", postal_code="2000",
        recipient_name="Ana",
    )
    return Order.objects.create(user=owner, address=address, **extra)


class PlatformOverviewTests(APITestCase):
    def setUp(self):
        self.admin = make_admin()
        self.owner = make_user("dueno@example.com")
        self.data_user = new_business(self.owner)

    def test_admin_gets_every_block(self):
        response = self.client.get(URL, **bearer(self.admin))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.data["allowed"]), {"people", "businesses", "orders", "support"})
        for block in ("people", "businesses", "orders", "support"):
            self.assertIn(block, response.data)

    def test_people_counts_only_people_not_data_users(self):
        self.owner.last_login = timezone.now()
        self.owner.save(update_fields=["last_login"])
        people = self.client.get(URL, **bearer(self.admin)).data["people"]
        # El admin y el dueño; el usuario de datos del comercio no es una persona.
        self.assertEqual(people["total"], 2)
        self.assertEqual(people["new_7d"], 2)
        self.assertEqual(people["active_7d"], 1)
        self.assertEqual(people["never_logged_in"], 1)

    def test_businesses_open_new_and_closed(self):
        other = make_user("otro@example.com")
        team = teams.create_team(other, name="Cerrado")
        team.closed_at = timezone.now()
        team.save(update_fields=["closed_at"])
        businesses = self.client.get(URL, **bearer(self.admin)).data["businesses"]
        self.assertEqual(businesses["open"], 1)
        self.assertEqual(businesses["new_7d"], 1)
        self.assertEqual(businesses["closed"], 1)

    def test_orders_today_week_and_without_samples(self):
        make_order(self.data_user)
        make_order(self.data_user, is_sample=True)
        old = make_order(self.data_user)
        Order.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=20))
        orders = self.client.get(URL, **bearer(self.admin)).data["orders"]
        self.assertEqual(orders["today"], 1)
        self.assertEqual(orders["last_7d"], 1)
        self.assertEqual(len(orders["week"]), 7)
        self.assertEqual(orders["week"][-1]["entered"], 1)
        self.assertEqual(orders["stores_with_errors"], 0)

    def test_support_pending_and_in_progress(self):
        SupportMessage.objects.create(user=self.owner, subject="a", message="b")
        SupportMessage.objects.create(
            user=self.owner, subject="c", message="d", status=SupportMessage.Status.IN_PROGRESS
        )
        SupportMessage.objects.create(
            user=self.owner, subject="e", message="f", status=SupportMessage.Status.RESOLVED
        )
        support = self.client.get(URL, **bearer(self.admin)).data["support"]
        self.assertEqual(support, {"pending": 1, "in_progress": 1})

    def test_staff_sees_only_the_blocks_of_their_permissions(self):
        staff = make_user("soporte@example.com", group="soporte")
        group = Group.objects.get(name="soporte")
        GroupRolePermission.objects.create(
            group=group, permission=RolePermission.objects.get(key="support.view_all")
        )
        data = self.client.get(URL, **bearer(staff)).data
        self.assertEqual(data["allowed"], ["support"])
        self.assertNotIn("people", data)
        self.assertNotIn("orders", data)

    def test_merchant_gets_403(self):
        self.assertEqual(self.client.get(URL, **bearer(self.owner)).status_code, 403)
