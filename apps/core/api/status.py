"""Which parts of the backend are stubs and which are real (docs/status.md)."""

from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import serializers
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.status import build_status, run_test


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


@extend_schema(
    request=None,
    responses={
        200: OpenApiResponse(
            BackendStatusSerializer,
            description="The status after the test. Header `X-Status-Test` is `run` "
            "when this call tested, `cached` when the last test is under a minute old "
            "and its stored result is returned, `skipped` when nothing is real.",
        )
    },
)
@api_view(["POST"])
def backend_status_test(request: Request) -> Response:
    """Check every real part now: a model call of a few tokens (one per provider and
    model in use), a ping of the channel layer. At most one test per minute for the
    whole deployment. A failing part is a state in the body, not an error."""
    outcome = run_test()
    response = Response(BackendStatusSerializer(build_status().model_dump()).data)
    response["X-Status-Test"] = outcome
    return response
