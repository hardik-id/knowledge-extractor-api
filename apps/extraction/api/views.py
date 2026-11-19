from typing import cast

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.errors import ApiError
from apps.extraction import selectors, services
from apps.extraction.api.serializers import (
    AddRecordSerializer,
    DefinitionSerializer,
    DefinitionVersionListSerializer,
    ExecutionSerializer,
    ExtractionSerializer,
    ReplaceFieldValuesSerializer,
    ReviewValueSerializer,
    RevisionQuerySerializer,
    SaveDefinitionSerializer,
    StartExecutionSerializer,
    UpdateRecordSerializer,
    serialize_extraction,
    summarize_version,
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
        note = body["note"] if isinstance(body, dict) and "note" in body else ""
        if not isinstance(note, str):
            raise ApiError("invalid_definition", "The note must be text.")
        saved = services.save_definition(
            user, run_id, base_version=base_version, data=request.data, note=note
        )
        return Response(DefinitionSerializer(saved).data)
    return Response(DefinitionSerializer(selectors.get_definition(user, run_id)).data)


@extend_schema(
    operation_id="runs_extract_definition_versions_list",
    responses=DefinitionVersionListSerializer,
)
@api_view(["GET"])
def definition_versions(request: Request, run_id: str) -> Response:
    """Every saved version of the definition, newest first."""
    versions = selectors.list_definition_versions(cast(User, request.user), run_id)
    return Response({"items": [summarize_version(v) for v in versions]})


@extend_schema(
    operation_id="runs_extract_definition_versions_read",
    responses=DefinitionSerializer,
)
@api_view(["GET"])
def definition_version(request: Request, run_id: str, version: int) -> Response:
    """One saved version of the definition."""
    found = selectors.get_definition_version_of(
        cast(User, request.user), run_id, version
    )
    return Response(DefinitionSerializer(found).data)


@extend_schema(request=None, responses=DefinitionSerializer)
@api_view(["POST"])
def restore_definition_version(request: Request, run_id: str, version: int) -> Response:
    """Save a copy of an earlier version as the newest one."""
    restored = services.restore_definition(cast(User, request.user), run_id, version)
    return Response(DefinitionSerializer(restored).data)


@extend_schema(request=StartExecutionSerializer, responses={202: ExecutionSerializer})
@api_view(["POST"])
def executions(request: Request, run_id: str, stage: str) -> Response:
    """Run the stage on files of the run, in the background. Progress arrives as cells."""
    body = StartExecutionSerializer(data=request.data)
    body.is_valid(raise_exception=True)
    config = body.validated_data.get("config") or {}
    execution = services.start_execution(
        cast(User, request.user),
        run_id,
        stage,
        file_ids=body.validated_data.get("file_ids"),
        definition_version=config.get("definition_version"),
    )
    return Response(
        {
            "execution_id": execution.id,
            "stage": stage,
            "file_ids": execution.file_ids,
        },
        status=202,
    )


@extend_schema(responses=ExtractionSerializer)
@api_view(["GET"])
def extraction(request: Request, run_id: str, file_id: str) -> Response:
    """The records extracted from one file of the run."""
    user = cast(User, request.user)
    return Response(
        serialize_extraction(selectors.get_extraction(user, run_id, file_id))
    )


@extend_schema(request=AddRecordSerializer, responses={200: ExtractionSerializer})
@api_view(["POST"])
def records(request: Request, run_id: str, file_id: str) -> Response:
    """Add a record a person marked. Revision 0 on a fresh file makes the extraction."""
    user = cast(User, request.user)
    body = AddRecordSerializer(data=request.data)
    body.is_valid(raise_exception=True)
    extraction = services.add_record(user, run_id, file_id, **body.validated_data)
    return Response(serialize_extraction(extraction))


@extend_schema(
    methods=["PATCH"],
    request=UpdateRecordSerializer,
    responses={200: ExtractionSerializer},
)
@extend_schema(
    methods=["DELETE"],
    parameters=[OpenApiParameter("revision", int, required=True)],
    responses={200: ExtractionSerializer},
)
@api_view(["PATCH", "DELETE"])
def record(request: Request, run_id: str, file_id: str, record_id: str) -> Response:
    """Change a record (PATCH), or remove one a person added (DELETE)."""
    user = cast(User, request.user)
    if request.method == "DELETE":
        query = RevisionQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        extraction = services.delete_record(
            user, run_id, file_id, record_id, revision=query.validated_data["revision"]
        )
    else:
        body = UpdateRecordSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = dict(body.validated_data)
        extraction = services.update_record(
            user, run_id, file_id, record_id, revision=data.pop("revision"), patch=data
        )
    return Response(serialize_extraction(extraction))


@extend_schema(
    request=ReplaceFieldValuesSerializer, responses={200: ExtractionSerializer}
)
@api_view(["PUT"])
def field(
    request: Request, run_id: str, file_id: str, record_id: str, field_id: str
) -> Response:
    """Replace all values of one field of a record."""
    user = cast(User, request.user)
    body = ReplaceFieldValuesSerializer(data=request.data)
    body.is_valid(raise_exception=True)
    extraction = services.replace_field_values(
        user, run_id, file_id, record_id, field_id, **body.validated_data
    )
    return Response(serialize_extraction(extraction))


@extend_schema(request=ReviewValueSerializer, responses={200: ExtractionSerializer})
@api_view(["PATCH"])
def value(
    request: Request, run_id: str, file_id: str, record_id: str, value_id: str
) -> Response:
    """Accept or reject one value of a record."""
    user = cast(User, request.user)
    body = ReviewValueSerializer(data=request.data)
    body.is_valid(raise_exception=True)
    extraction = services.review_value(
        user, run_id, file_id, record_id, value_id, **body.validated_data
    )
    return Response(serialize_extraction(extraction))
