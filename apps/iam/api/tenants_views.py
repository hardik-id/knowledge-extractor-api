from typing import Any, cast

from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view
from rest_framework.pagination import BasePagination
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.pagination import DefaultPagination
from apps.iam import tenants
from apps.iam.models import Tenant
from apps.iam.roles import Permission
from apps.iam.routes import SIGNED_IN, requires
from apps.iam.selectors import get_tenant
from apps.identity.models import User
from apps.workspaces import selectors as workspace_selectors

from .tenants_serializers import (
    TenantList,
    TenantNameSerializer,
    TenantSerializer,
    TenantWorkspaceList,
    TenantWorkspaceSerializer,
)


class TenantWorkspacePagination(DefaultPagination):
    """Last activity first. The id breaks ties."""

    ordering = ("-activity", "-id")  # type: ignore[assignment]


def _wire(tenant: Tenant, role: Any = None, counts: bool = False) -> dict[str, Any]:
    return {
        "id": tenant.pk,
        "name": tenant.name,
        "is_default": tenant.is_default,
        "role": role.value if role else None,
        "member_count": getattr(tenant, "member_count", None) if counts else None,
        "workspace_count": getattr(tenant, "workspace_count", None) if counts else None,
        "created_at": tenant.created_at,
    }


@requires(GET=SIGNED_IN, POST=Permission.TENANTS_MANAGE)
@extend_schema(methods=["GET"], responses=TenantList)
@extend_schema(
    methods=["POST"], request=TenantNameSerializer, responses={201: TenantSerializer}
)
@api_view(["GET", "POST"])
def tenants_list(request: Request) -> Response:
    """The tenants the person belongs to; a platform admin gets all, with counts (GET). Make one (POST)."""
    user = cast(User, request.user)
    if request.method == "POST":
        serializer = TenantNameSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        tenant = tenants.create_tenant(user, serializer.validated_data["name"])
        return Response(TenantSerializer(_wire(tenant, counts=False)).data, status=201)
    items = [_wire(t, role, counts) for t, role, counts in tenants.list_tenants(user)]
    return Response({"items": TenantSerializer(items, many=True).data, "next": None})


@requires(PATCH=Permission.TENANTS_MANAGE, DELETE=Permission.TENANTS_MANAGE)
@extend_schema(
    methods=["PATCH"], request=TenantNameSerializer, responses=TenantSerializer
)
@extend_schema(methods=["DELETE"], responses={204: None})
@api_view(["PATCH", "DELETE"])
def tenant_detail(request: Request, tenant_id: str) -> Response:
    """Rename a tenant (PATCH), or delete one with no workspaces (DELETE)."""
    user = cast(User, request.user)
    if request.method == "DELETE":
        tenants.delete_tenant(user, tenant_id)
        return Response(status=204)
    serializer = TenantNameSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    tenant = tenants.rename_tenant(user, tenant_id, serializer.validated_data["name"])
    return Response(TenantSerializer(_wire(tenant)).data)


@requires(GET=Permission.TENANT_WORKSPACES_LIST)
@extend_schema(responses=TenantWorkspaceList)
@api_view(["GET"])
def tenant_workspaces(request: Request, tenant_id: str) -> Response:
    """Every workspace of the tenant: name, owners, member count, last activity. No content."""
    user = cast(User, request.user)
    tenant = get_tenant(user, tenant_id, Permission.TENANT_WORKSPACES_LIST)
    paginator: BasePagination = TenantWorkspacePagination()
    page = paginator.paginate_queryset(
        workspace_selectors.list_tenant_workspaces(user, tenant.pk), request
    )
    return paginator.get_paginated_response(
        TenantWorkspaceSerializer(page, many=True).data
    )
