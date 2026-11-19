from typing import cast

from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.decorators import api_view
from rest_framework.pagination import BasePagination
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.pagination import DefaultPagination
from apps.identity.models import User
from apps.projects import selectors, services
from apps.projects.api.serializers import (
    CreateProjectSerializer,
    ProjectSerializer,
    UpdateProjectSerializer,
)


class ProjectPagination(DefaultPagination):
    """Last activity first. The id breaks ties."""

    ordering = ("-activity", "-id")  # type: ignore[assignment]


ProjectList = inline_serializer(
    "ProjectList",
    {
        "items": ProjectSerializer(many=True),
        "next": serializers.CharField(allow_null=True),
    },
)


@extend_schema(methods=["GET"], operation_id="projects_list", responses=ProjectList)
@extend_schema(
    methods=["POST"],
    request=CreateProjectSerializer,
    responses={201: ProjectSerializer},
)
@api_view(["GET", "POST"])
def projects(request: Request) -> Response:
    """The person's projects, last activity first (GET), or start one (POST)."""
    user = cast(User, request.user)
    if request.method == "POST":
        serializer = CreateProjectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        project = services.create_project(user, **serializer.validated_data)
        return Response(ProjectSerializer(project).data, status=201)
    paginator: BasePagination = ProjectPagination()
    page = paginator.paginate_queryset(selectors.list_projects(user), request)
    return paginator.get_paginated_response(ProjectSerializer(page, many=True).data)


@extend_schema(methods=["GET"], responses=ProjectSerializer)
@extend_schema(
    methods=["PATCH"], request=UpdateProjectSerializer, responses=ProjectSerializer
)
@extend_schema(methods=["DELETE"], responses={204: None})
@api_view(["GET", "PATCH", "DELETE"])
def project_detail(request: Request, project_id: str) -> Response:
    """One project (GET), rename or describe it (PATCH), or delete it with its run (DELETE)."""
    user = cast(User, request.user)
    if request.method == "DELETE":
        services.delete_project(user, project_id)
        return Response(status=204)
    if request.method == "PATCH":
        serializer = UpdateProjectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        project = services.update_project(user, project_id, **serializer.validated_data)
        return Response(ProjectSerializer(project).data)
    return Response(ProjectSerializer(selectors.get_project(user, project_id)).data)
