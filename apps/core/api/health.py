"""Liveness and readiness. Both are open: no sign-in, declared on the views."""

from django.db import connection
from django.db.utils import Error as DatabaseError
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.errors import ApiError


class StatusSerializer(serializers.Serializer):  # type: ignore[type-arg]
    status = serializers.CharField()


@extend_schema(responses=StatusSerializer)
@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def health(request: Request) -> Response:
    """The process is up. Never touches the database."""
    return Response({"status": "ok"})


@extend_schema(responses=StatusSerializer)
@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def ready(request: Request) -> Response:
    """The service can reach its database."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except DatabaseError as exc:
        raise ApiError("not_ready") from exc
    return Response({"status": "ok"})
