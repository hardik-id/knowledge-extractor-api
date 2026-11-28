from typing import cast

from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.decorators import api_view
from rest_framework.pagination import BasePagination
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.pagination import DefaultPagination
from apps.iam.roles import Permission
from apps.iam.routes import SIGNED_IN, requires
from apps.identity.models import User
from apps.workspaces import selectors, services
from apps.workspaces.api.serializers import (
    CreateWorkspaceSerializer,
    ListWorkspacesSerializer,
    UpdateWorkspaceSerializer,
    WorkspaceSerializer,
)


class WorkspacePagination(DefaultPagination):
    """Last activity first. The id breaks ties."""

    ordering = ("-activity", "-id")  # type: ignore[assignment]


WorkspaceList = inline_serializer(
    "WorkspaceList",
    {
        "items": WorkspaceSerializer(many=True),
        "next": serializers.CharField(allow_null=True),
    },
)


def _workspaces(request: Request) -> Response:
    user = cast(User, request.user)
    if request.method == "POST":
        serializer = CreateWorkspaceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        workspace = services.create_workspace(user, **serializer.validated_data)
        return Response(WorkspaceSerializer(workspace).data, status=201)
    query = ListWorkspacesSerializer(data=request.query_params)
    query.is_valid(raise_exception=True)
    paginator: BasePagination = WorkspacePagination()
    page = paginator.paginate_queryset(
        selectors.list_workspaces(user, query.validated_data.get("tenant_id")), request
    )
    return paginator.get_paginated_response(WorkspaceSerializer(page, many=True).data)


def _workspace_detail(request: Request, workspace_id: str) -> Response:
    user = cast(User, request.user)
    if request.method == "DELETE":
        services.delete_workspace(user, workspace_id)
        return Response(status=204)
    if request.method == "PATCH":
        serializer = UpdateWorkspaceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        workspace = services.update_workspace(
            user, workspace_id, **serializer.validated_data
        )
        return Response(WorkspaceSerializer(workspace).data)
    return Response(
        WorkspaceSerializer(
            selectors.get_workspace(user, workspace_id, Permission.WORKSPACE_VIEW)
        ).data
    )


# The creating tenant is checked by the service (workspaces.create).
LIST = {"GET": SIGNED_IN, "POST": SIGNED_IN}
DETAIL = {
    "GET": Permission.WORKSPACE_VIEW,
    "PATCH": Permission.WORKSPACE_MANAGE,
    "DELETE": Permission.WORKSPACE_MANAGE,
}


@requires(**LIST)
@extend_schema(
    methods=["GET"],
    operation_id="workspaces_list",
    parameters=[ListWorkspacesSerializer],
    responses=WorkspaceList,
)
@extend_schema(
    methods=["POST"],
    request=CreateWorkspaceSerializer,
    responses={201: WorkspaceSerializer},
)
@api_view(["GET", "POST"])
def workspaces(request: Request) -> Response:
    """The person's workspaces, last activity first (GET), or start one (POST)."""
    return _workspaces(request)


@requires(**DETAIL)
@extend_schema(methods=["GET"], responses=WorkspaceSerializer)
@extend_schema(
    methods=["PATCH"], request=UpdateWorkspaceSerializer, responses=WorkspaceSerializer
)
@extend_schema(methods=["DELETE"], responses={204: None})
@api_view(["GET", "PATCH", "DELETE"])
def workspace_detail(request: Request, workspace_id: str) -> Response:
    """One workspace (GET), rename or describe it (PATCH), or delete it with its run (DELETE)."""
    return _workspace_detail(request, workspace_id)


# The old paths, until the UI has moved. #493 removes them.


@requires(**LIST)
@extend_schema(
    methods=["GET"],
    operation_id="projects_list",
    parameters=[ListWorkspacesSerializer],
    responses=WorkspaceList,
    deprecated=True,
)
@extend_schema(
    methods=["POST"],
    operation_id="projects_create",
    request=CreateWorkspaceSerializer,
    responses={201: WorkspaceSerializer},
    deprecated=True,
)
@api_view(["GET", "POST"])
def projects(request: Request) -> Response:
    """Deprecated: use /workspaces."""
    return _workspaces(request)


@requires(**DETAIL)
@extend_schema(
    methods=["GET"],
    operation_id="projects_retrieve",
    responses=WorkspaceSerializer,
    deprecated=True,
)
@extend_schema(
    methods=["PATCH"],
    operation_id="projects_partial_update",
    request=UpdateWorkspaceSerializer,
    responses=WorkspaceSerializer,
    deprecated=True,
)
@extend_schema(
    methods=["DELETE"],
    operation_id="projects_destroy",
    responses={204: None},
    deprecated=True,
)
@api_view(["GET", "PATCH", "DELETE"])
def project_detail(request: Request, project_id: str) -> Response:
    """Deprecated: use /workspaces/{workspace_id}."""
    return _workspace_detail(request, project_id)
