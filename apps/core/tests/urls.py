"""Test-only URLconf: the real routes plus views that raise each kind of error."""

import structlog
from django.http import HttpRequest, JsonResponse
from django.urls import path
from rest_framework import exceptions, serializers
from rest_framework.authentication import BasicAuthentication
from rest_framework.decorators import api_view, authentication_classes
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.errors import ApiError
from config.urls import handler404, handler500
from config.urls import urlpatterns as real_patterns

__all__ = ["handler404", "handler500", "urlpatterns"]

log = structlog.get_logger(__name__)


def hello(request: HttpRequest) -> JsonResponse:
    log.info("inside_view")
    return JsonResponse({"ok": True})


def boom(request: HttpRequest) -> JsonResponse:
    raise RuntimeError("boom")


class Payload(serializers.Serializer):  # type: ignore[type-arg]
    name = serializers.CharField()
    age = serializers.IntegerField()


@api_view(["GET", "POST"])
def validate(request: Request) -> Response:
    Payload(data=request.data).is_valid(raise_exception=True)
    return Response()


@api_view()
def raise_api_error(request: Request, code: str) -> Response:
    raise ApiError(code)


@api_view()
def raise_custom(request: Request) -> Response:
    raise ApiError("conflict", "Already exists.", {"name": ["taken"]})


@api_view()
@authentication_classes([BasicAuthentication])
def unauthenticated(request: Request) -> Response:
    raise exceptions.NotAuthenticated()


@api_view()
def failed(request: Request) -> Response:
    raise exceptions.AuthenticationFailed("bad token")


@api_view()
def denied(request: Request) -> Response:
    raise exceptions.PermissionDenied("secret reason")


@api_view()
def missing(request: Request) -> Response:
    raise exceptions.NotFound()


@api_view()
def crash(request: Request) -> Response:
    raise RuntimeError("internal secret detail")


urlpatterns = [
    path("hello", hello),
    path("boom", boom),
    path("api/test/validate", validate),
    path("api/test/error/<str:code>", raise_api_error),
    path("api/test/custom", raise_custom),
    path("api/test/unauthenticated", unauthenticated),
    path("api/test/failed", failed),
    path("api/test/denied", denied),
    path("api/test/missing", missing),
    path("api/test/crash", crash),
    *real_patterns,
]
