from typing import cast

from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.decorators import api_view
from rest_framework.pagination import BasePagination
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.pagination import DefaultPagination
from apps.iam import selectors, services
from apps.iam.roles import Permission
from apps.iam.routes import requires
from apps.identity.models import User

from .members_serializers import (
    AddMemberSerializer,
    ChangeRoleSerializer,
    MemberListQuerySerializer,
    MemberSerializer,
)

MemberList = inline_serializer(
    "TenantMemberList",
    {
        "items": MemberSerializer(many=True),
        "next": serializers.CharField(allow_null=True),
    },
)


def _person(user_id: str) -> int:
    """A person's id from the path. One that cannot be an id names nobody (-1)."""
    if user_id.isascii() and user_id.isdecimal() and int(user_id) < 2**31:
        return int(user_id)
    return -1


@requires(GET=Permission.TENANT_MEMBERS_LIST, POST=Permission.TENANT_MEMBERS_MANAGE)
@extend_schema(
    methods=["GET"], parameters=[MemberListQuerySerializer], responses=MemberList
)
@extend_schema(
    methods=["POST"], request=AddMemberSerializer, responses=MemberSerializer
)
@api_view(["GET", "POST"])
def members(request: Request, tenant_id: str) -> Response:
    """A tenant's members (any member may list), or add a person who has signed in."""
    user = cast(User, request.user)
    if request.method == "POST":
        body = AddMemberSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        membership = services.add_tenant_member(user, tenant_id, **body.validated_data)
        return Response(MemberSerializer(membership).data, status=201)
    query = MemberListQuerySerializer(data=request.query_params)
    query.is_valid(raise_exception=True)
    tenant = selectors.get_tenant(user, tenant_id, Permission.TENANT_MEMBERS_LIST)
    paginator: BasePagination = DefaultPagination()
    page = paginator.paginate_queryset(
        selectors.list_tenant_members(tenant, query.validated_data.get("search", "")),
        request,
    )
    return paginator.get_paginated_response(MemberSerializer(page, many=True).data)


@requires(PUT=Permission.TENANT_MEMBERS_MANAGE, DELETE=Permission.TENANT_MEMBERS_MANAGE)
@extend_schema(
    methods=["PUT"], request=ChangeRoleSerializer, responses=MemberSerializer
)
@extend_schema(methods=["DELETE"], responses={204: None})
@api_view(["PUT", "DELETE"])
def member(request: Request, tenant_id: str, user_id: str) -> Response:
    """Change a member's role, or take them out of the tenant and its workspaces."""
    user = cast(User, request.user)
    if request.method == "DELETE":
        services.remove_tenant_member(user, tenant_id, _person(user_id))
        return Response(status=204)
    body = ChangeRoleSerializer(data=request.data)
    body.is_valid(raise_exception=True)
    membership = services.change_member_role(
        user, tenant_id, _person(user_id), body.validated_data["role"]
    )
    return Response(MemberSerializer(membership).data)
