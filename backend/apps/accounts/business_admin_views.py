"""Comercios para el admin (2026-11-19).

El producto se organiza por comercio, pero el admin solo veía usuarios y los
comercios dados de baja: a un comercio abierto se llegaba únicamente por su
dueño (``comercio_usuario.html``). Esto es la lista de los comercios abiertos,
con su dueño, equipo, tiendas, pedidos y última actividad, y la ficha de cada
uno. Solo lectura, con ``users.view`` como el resto de lo de comercios. Todo
lo del comercio cuelga de su usuario de datos (``Team.data_user``).
"""

from datetime import timedelta

from django.db.models import Count, F, IntegerField, Max, OuterRef, Q, Subquery, Value
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.carriers.models import CarrierAccount
from apps.integrations.models import StoreConnection
from apps.orders.models import Order

from .pagination import UserAdminPagination
from .personal_profiles import public_fields
from .role_permissions import HasRolePermission
from .team_models import Team, TeamMember
from .teams import team_display_name

RECENT_DAYS = 30

# ?sort= → orden. Los vacíos van al final en los dos sentidos.
SORTS = {
    "name": ("name", "id"),
    "-name": ("-name", "-id"),
    "created_at": ("created_at", "id"),
    "-created_at": ("-created_at", "-id"),
    "orders_30d": ("orders_30d", "id"),
    "-orders_30d": ("-orders_30d", "-id"),
    "last_activity": ("last_activity", "id"),
    "-last_activity": ("-last_activity", "-id"),
}
DEFAULT_SORT = "-created_at"


class BusinessPagination(UserAdminPagination):
    page_size = 20


def _count(queryset):
    """Una cuenta por usuario de datos, como subconsulta (0 si no hay)."""
    return Coalesce(
        Subquery(queryset.values("user" if queryset.model is Order else "owner").annotate(n=Count("id")).values("n")[:1],
                 output_field=IntegerField()),
        Value(0),
    )


def businesses():
    since = timezone.now() - timedelta(days=RECENT_DAYS)
    orders = Order.objects.filter(user=OuterRef("data_user"), is_sample=False)
    stores = StoreConnection.objects.filter(owner=OuterRef("data_user"))
    return (
        Team.objects.filter(closed_at=None)
        .select_related("owner", "data_user")
        .annotate(
            member_count=Count("members", distinct=True),
            last_activity=Max("members__last_used_at"),
            orders_total=_count(orders),
            orders_30d=_count(orders.filter(created_at__gte=since)),
            last_order_at=Subquery(orders.order_by("-created_at").values("created_at")[:1]),
            stores_active=_count(stores.filter(status=StoreConnection.Status.ACTIVE)),
            stores_error=_count(stores.filter(status=StoreConnection.Status.ERROR)),
        )
    )


def _platforms(data_user_ids):
    """``{data_user_id: ["Tiendanube", ...]}`` de las tiendas conectadas (no las desconectadas)."""
    labels = dict(StoreConnection.Platform.choices)
    result = {}
    rows = (
        StoreConnection.objects.filter(owner_id__in=data_user_ids)
        .exclude(status=StoreConnection.Status.REVOKED)
        .values_list("owner_id", "platform")
        .distinct()
    )
    for owner_id, platform in rows:
        result.setdefault(owner_id, []).append(labels.get(platform, platform))
    return result


def _row(team, platforms):
    return {
        "id": team.id,
        "name": team_display_name(team),
        "owner_id": team.owner_id,
        "owner_email": team.owner.email if team.owner else "",
        "created_at": team.created_at,
        "member_count": team.member_count,
        "last_activity": team.last_activity,
        "orders_total": team.orders_total,
        "orders_30d": team.orders_30d,
        "last_order_at": team.last_order_at,
        "stores_active": team.stores_active,
        "stores_error": team.stores_error,
        "platforms": sorted(platforms.get(team.data_user_id, [])),
    }


class AdminBusinessListView(APIView):
    """GET /api/v1/teams/directory/?search=&sort=&problems=1&page= — los comercios
    abiertos. ``search`` busca en el nombre y el email del dueño; ``problems``
    deja solo los que tienen alguna tienda con errores."""

    def get_permissions(self):
        return [IsAuthenticated(), HasRolePermission("users.view")]

    def get(self, request):
        queryset = businesses()
        search = (request.query_params.get("search") or "").strip()
        if search:
            queryset = queryset.filter(Q(name__icontains=search) | Q(owner__email__icontains=search))
        if request.query_params.get("problems") in ("1", "true"):
            queryset = queryset.filter(stores_error__gt=0)
        sort = request.query_params.get("sort") or DEFAULT_SORT
        fields = SORTS.get(sort, SORTS[DEFAULT_SORT])
        first = fields[0]
        column = F(first.lstrip("-"))
        ordering = column.desc(nulls_last=True) if first.startswith("-") else column.asc(nulls_last=True)
        queryset = queryset.order_by(ordering, fields[1])

        paginator = BusinessPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        platforms = _platforms([team.data_user_id for team in page])
        return paginator.get_paginated_response([_row(team, platforms) for team in page])


class AdminBusinessDetailView(APIView):
    """GET /api/v1/teams/<id>/detail/ — la ficha de un comercio abierto: su
    equipo, sus tiendas, sus cuentas de transportista y sus números."""

    def get_permissions(self):
        return [IsAuthenticated(), HasRolePermission("users.view")]

    def get(self, request, pk):
        team = get_object_or_404(businesses(), pk=pk)
        members = (
            TeamMember.objects.filter(team=team)
            .select_related("user", "profile")
            .order_by("-role", "user__email")
        )
        platform_labels = dict(StoreConnection.Platform.choices)
        status_labels = dict(StoreConnection.Status.choices)
        carrier_labels = dict(CarrierAccount.Carrier.choices)
        data = _row(team, _platforms([team.data_user_id]))
        data.update({
            "members": [
                {
                    "user_id": member.user_id,
                    "email": member.user.email,
                    "name": public_fields(member.user, request)["display_name"],
                    "role": member.role,
                    "role_label": member.get_role_display(),
                    "profile": member.profile.name if member.profile else "Accesos a medida",
                    "last_login": member.user.last_login,
                    "is_active": member.user.is_active,
                }
                for member in members
            ],
            "stores": [
                {
                    "id": store.id,
                    "name": store.name or store.external_store_id,
                    "platform": platform_labels.get(store.platform, store.platform),
                    "status": store.status,
                    "status_label": status_labels.get(store.status, store.status),
                    "last_error": store.last_error,
                    "created_at": store.created_at,
                }
                for store in StoreConnection.objects.filter(owner_id=team.data_user_id).order_by("status", "id")
            ],
            "carriers": [
                {
                    "carrier": carrier_labels.get(account.carrier, account.carrier),
                    "is_active": account.is_active,
                    "last_error": account.last_error,
                }
                for account in CarrierAccount.objects.filter(owner_id=team.data_user_id).order_by("carrier")
            ],
        })
        return Response(data)
