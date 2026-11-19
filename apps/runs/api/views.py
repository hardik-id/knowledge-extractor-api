from typing import cast

from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

from apps.identity.models import User
from apps.runs import selectors, services
from apps.runs.api.serializers import CreateRunSerializer, RunSerializer


@extend_schema(request=CreateRunSerializer, responses={201: RunSerializer})
@api_view(["POST"])
def run_create(request: Request) -> Response:
    """Turn the picked documents into a run."""
    serializer = CreateRunSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    run = services.create_run(
        cast(User, request.user), serializer.validated_data["items"]
    )
    return Response(RunSerializer(run).data, status=201)


@extend_schema(methods=["GET"], responses=RunSerializer)
@extend_schema(methods=["DELETE"], responses={204: None})
@api_view(["GET", "DELETE"])
def run_detail(request: Request, run_id: str) -> Response:
    """The whole state of a run (GET), or throw it away (DELETE)."""
    run = selectors.get_run(cast(User, request.user), run_id)
    if request.method == "DELETE":
        services.delete_run(run)
        return Response(status=204)
    return Response(RunSerializer(run).data)
