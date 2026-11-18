from typing import cast

from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

from apps.identity import selectors
from apps.identity.api.serializers import MeSerializer
from apps.identity.models import User


@extend_schema(responses=MeSerializer)
@api_view(["GET"])
def me(request: Request) -> Response:
    """The signed-in person."""
    return Response(MeSerializer(selectors.get_me(cast(User, request.user))).data)
