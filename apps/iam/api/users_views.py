from typing import cast

from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.decorators import api_view
from rest_framework.pagination import BasePagination
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.errors import ApiError
from apps.core.pagination import DefaultPagination
from apps.iam import selectors
from apps.iam.routes import SIGNED_IN, requires
from apps.identity.models import User

from .users_serializers import UserListQuerySerializer, UserSerializer

UserList = inline_serializer(
    "UserList",
    {
        "items": UserSerializer(many=True),
        "next": serializers.CharField(allow_null=True),
    },
)


# Signed in, because two kinds of person may call it; the view decides which answer.
@requires(GET=SIGNED_IN)
@extend_schema(parameters=[UserListQuerySerializer], responses=UserList)
@api_view(["GET"])
def users(request: Request) -> Response:
    """Find people. A platform admin lists everyone who has signed in (``?search=``).

    A tenant admin may only ask for one exact sign-in name (``?preferred_username=``):
    the answer is that person or nothing, never a part of a name or a list.
    Anyone else is refused.
    """
    user = cast(User, request.user)
    query = UserListQuerySerializer(data=request.query_params)
    query.is_valid(raise_exception=True)
    if selectors.is_platform_admin(user):
        paginator: BasePagination = DefaultPagination()
        page = paginator.paginate_queryset(
            selectors.list_users(query.validated_data.get("search", "")), request
        )
        return paginator.get_paginated_response(UserSerializer(page, many=True).data)
    name = query.validated_data.get("preferred_username")
    if name is None or not selectors.is_admin_of_a_tenant(user):
        raise ApiError("forbidden")
    found = selectors.find_user_by_username(name)
    items = [] if found is None else [UserSerializer(found).data]
    return Response({"items": items, "next": None})
