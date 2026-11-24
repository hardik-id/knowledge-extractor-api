"""Which parts of the backend are stubs and which are real (docs/status.md)."""

from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.status import build_status


class PartSerializer(serializers.Serializer):  # type: ignore[type-arg]
    id = serializers.CharField()
    mode = serializers.ChoiceField(["stub", "real"])
    label = serializers.CharField()  # type: ignore[assignment]
    state = serializers.ChoiceField(["stub", "ok", "failing", "unknown"])
    checked_at = serializers.DateTimeField(allow_null=True)
    problem = serializers.CharField(allow_null=True)


class BackendStatusSerializer(serializers.Serializer):  # type: ignore[type-arg]
    environment = serializers.CharField()
    parts = PartSerializer(many=True)


@extend_schema(responses=BackendStatusSerializer)
@api_view(["GET"])
def backend_status(request: Request) -> Response:
    """Each part (assistant, extraction, storage, sign-in, live updates, worker) as a
    stub or real, with the state of what is real. Reads settings and stored state and
    pings the channel layer; it never calls the model."""
    return Response(BackendStatusSerializer(build_status().model_dump()).data)
