from typing import cast

from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.errors import ApiError
from apps.extraction import selectors, services
from apps.extraction.api.serializers import (
    DefinitionSerializer,
    SaveDefinitionSerializer,
)
from apps.identity.models import User


@extend_schema(methods=["GET"], responses=DefinitionSerializer)
@extend_schema(
    methods=["PUT"], request=SaveDefinitionSerializer, responses=DefinitionSerializer
)
@api_view(["GET", "PUT"])
def definition(request: Request, run_id: str) -> Response:
    """The run's extraction definition (GET), or save a new version of it (PUT)."""
    user = cast(User, request.user)
    if request.method == "PUT":
        body = request.data
        base_version = body.get("base_version") if isinstance(body, dict) else None
        if not isinstance(base_version, int) or isinstance(base_version, bool):
            raise ApiError("validation_error", "base_version must be a number.")
        saved = services.save_definition(
            user, run_id, base_version=base_version, data=request.data
        )
        return Response(DefinitionSerializer(saved).data)
    return Response(DefinitionSerializer(selectors.get_definition(user, run_id)).data)
