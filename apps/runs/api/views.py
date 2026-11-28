from typing import cast

from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.errors import ApiError
from apps.iam.roles import Permission
from apps.iam.routes import SIGNED_IN, requires
from apps.identity.models import User
from apps.runs import selectors, services
from apps.runs.api.serializers import CreateRunSerializer, RunSerializer
from apps.workspaces import selectors as workspaces


@requires(POST=SIGNED_IN)
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


@requires(PUT=Permission.WORKSPACE_EDIT)
@extend_schema(request=CreateRunSerializer, responses=RunSerializer)
@api_view(["PUT"])
def run_documents(request: Request, run_id: str) -> Response:
    """Replace the run's documents; the definition and the conversation stay."""
    serializer = CreateRunSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    run = services.replace_documents(
        cast(User, request.user), run_id, serializer.validated_data["items"]
    )
    return Response(RunSerializer(run).data)


@requires(GET=Permission.WORKSPACE_VIEW, DELETE=Permission.WORKSPACE_MANAGE)
@extend_schema(methods=["GET"], responses=RunSerializer)
@extend_schema(methods=["DELETE"], responses={204: None})
@api_view(["GET", "DELETE"])
def run_detail(request: Request, run_id: str) -> Response:
    """The whole state of a run (GET), or throw it away (DELETE)."""
    user = cast(User, request.user)
    if request.method == "DELETE":
        run = selectors.get_run(user, run_id, Permission.WORKSPACE_MANAGE)
        if workspaces.run_has_workspace(run.pk):
            raise ApiError("run_belongs_to_workspace")
        services.delete_run(run)
        return Response(status=204)
    run = selectors.get_run(user, run_id, Permission.WORKSPACE_VIEW)
    services.release_stuck_cells(run)
    return Response(RunSerializer(run).data)
