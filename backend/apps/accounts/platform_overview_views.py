"""El Inicio del admin: un resumen de toda la plataforma (2026-11-19).

Antes, un admin sin comercio entraba al panel y solo veía "No estás trabajando
en ningún comercio". Esto es lo primero que tiene que ver quien administra:
personas, comercios, pedidos y soporte. Cada bloque se manda solo con el
permiso de la pantalla a la que lleva (como ``orders/stats/``), así el
personal de la plataforma ve lo suyo. El estado del sistema lo lee la página
de ``/health/system/``, que ya existe.
"""

from datetime import datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.carriers.models import CarrierAccount
from apps.integrations.models import StoreConnection
from apps.orders.models import Order
from apps.orders.summary_views import week

from .models import SupportMessage
from .permissions_map import user_has_permission
from .team_models import Team
from .user_admin_views import people

User = get_user_model()

# Bloque → permiso (el de la pantalla a la que lleva cada uno).
BLOCKS = {
    "people": "users.view",
    "businesses": "users.view",
    "orders": "orders.view_all",
    "support": "support.view_all",
}


class PlatformOverviewView(APIView):
    """GET /api/v1/admin/overview/ → ``{allowed, people?, businesses?, orders?, support?}``.
    Sin ningún bloque permitido, 403."""

    def get(self, request):
        allowed = [block for block, key in BLOCKS.items() if user_has_permission(request.user, key)]
        if not allowed:
            raise PermissionDenied("No tenés acceso al resumen de la plataforma.")
        now = timezone.now()
        week_ago = now - timedelta(days=7)
        data = {"allowed": allowed}
        if "people" in allowed:
            persons = people()
            data["people"] = {
                "total": persons.count(),
                "new_7d": persons.filter(date_joined__gte=week_ago).count(),
                "active_7d": persons.filter(last_login__gte=week_ago).count(),
                "never_logged_in": persons.filter(last_login__isnull=True).count(),
            }
        if "businesses" in allowed:
            open_teams = Team.objects.filter(closed_at__isnull=True)
            data["businesses"] = {
                "open": open_teams.count(),
                "new_7d": open_teams.filter(created_at__gte=week_ago).count(),
                "closed": Team.objects.filter(closed_at__isnull=False).count(),
            }
        if "orders" in allowed:
            orders = Order.objects.filter(is_sample=False)
            today_start = timezone.make_aware(datetime.combine(timezone.localdate(), time.min))
            data["orders"] = {
                "today": orders.filter(created_at__gte=today_start).count(),
                "last_7d": orders.filter(created_at__gte=week_ago).count(),
                "week": week(orders),
                "stores_active": StoreConnection.objects.filter(status=StoreConnection.Status.ACTIVE).count(),
                "stores_with_errors": StoreConnection.objects.filter(status=StoreConnection.Status.ERROR).count(),
                "carrier_accounts_failing": CarrierAccount.objects.filter(is_active=False)
                .exclude(last_error="")
                .count(),
            }
        if "support" in allowed:
            messages = SupportMessage.objects
            data["support"] = {
                "pending": messages.filter(status=SupportMessage.Status.PENDING).count(),
                "in_progress": messages.filter(status=SupportMessage.Status.IN_PROGRESS).count(),
            }
        return Response(data)
