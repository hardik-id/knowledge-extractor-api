"""Test-only URLconf: the real routes plus views that raise each kind of error."""

from collections.abc import Callable
from typing import Any

import structlog
from django.http import HttpRequest, JsonResponse
from django.urls import path
from rest_framework import exceptions, serializers
from rest_framework.authentication import BasicAuthentication
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.generics import ListAPIView
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.errors import ApiError
from apps.core.permissions import get_visible_or_404, require_can_change
from apps.core.tests.models import Note, SharedNote
from config.urls import handler404, handler500
from config.urls import urlpatterns as real_patterns

__all__ = ["handler404", "handler500", "urlpatterns"]

log = structlog.get_logger(__name__)


def open_api_view(
    methods: list[str] | None = None,
) -> Callable[[Callable[..., Response]], Callable[..., Response]]:
    """``api_view`` that needs no sign-in: these views test the error contract
    and pagination, not authentication. ``whoami`` below declares nothing."""

    def decorator(func: Callable[..., Response]) -> Callable[..., Response]:
        return api_view(methods)(permission_classes([AllowAny])(func))

    return decorator


def hello(request: HttpRequest) -> JsonResponse:
    log.info("inside_view")
    return JsonResponse({"ok": True})


def boom(request: HttpRequest) -> JsonResponse:
    raise RuntimeError("boom")


class Payload(serializers.Serializer):  # type: ignore[type-arg]
    name = serializers.CharField()
    age = serializers.IntegerField()


@open_api_view(["GET", "POST"])
def validate(request: Request) -> Response:
    Payload(data=request.data).is_valid(raise_exception=True)
    return Response()


@open_api_view()
def raise_api_error(request: Request, code: str) -> Response:
    raise ApiError(code)


@open_api_view()
def raise_custom(request: Request) -> Response:
    raise ApiError("conflict", "Already exists.", {"name": ["taken"]})


@open_api_view()
@authentication_classes([BasicAuthentication])
def unauthenticated(request: Request) -> Response:
    raise exceptions.NotAuthenticated()


@open_api_view()
def failed(request: Request) -> Response:
    raise exceptions.AuthenticationFailed("bad token")


@open_api_view()
def denied(request: Request) -> Response:
    raise exceptions.PermissionDenied("secret reason")


@open_api_view()
def missing(request: Request) -> Response:
    raise exceptions.NotFound()


@open_api_view()
def crash(request: Request) -> Response:
    raise RuntimeError("internal secret detail")


@api_view()
def whoami(request: Request) -> Response:
    """Declares nothing, so it takes the project defaults: closed."""
    log.info("inside_whoami")
    return Response({"id": request.user.pk})


class NoteSerializer(serializers.ModelSerializer):  # type: ignore[type-arg]
    class Meta:
        model = Note
        fields = ["id", "text", "created_at", "updated_at"]


class NoteList(ListAPIView):  # type: ignore[type-arg]
    """A list endpoint on the default pagination."""

    permission_classes = [AllowAny]
    queryset = Note.objects.all()
    serializer_class = NoteSerializer


class SharedNoteSerializer(serializers.ModelSerializer):  # type: ignore[type-arg]
    class Meta:
        model = SharedNote
        fields = ["id", "text", "shared"]


@api_view(["GET"])
def shared_note_list(request: Request) -> Response:
    """Built only from the helpers: no ownership check of its own."""
    rows = SharedNote.objects.visible_to(request.user)
    return Response({"items": SharedNoteSerializer(rows, many=True).data})


@api_view(["GET", "PATCH"])
def shared_note_detail(request: Request, pk: str) -> Response:
    """Built only from the helpers: no ownership check of its own."""
    note = get_visible_or_404(SharedNote, request.user, pk)
    if request.method == "PATCH":
        require_can_change(note, request.user)
        data: Any = request.data
        note.text = data["text"]
        note.save()
    return Response(SharedNoteSerializer(note).data)


urlpatterns = [
    path("api/test/shared-notes", shared_note_list),
    path("api/test/shared-notes/<str:pk>", shared_note_detail),
    path("api/test/notes", NoteList.as_view()),
    path("api/test/whoami", whoami),
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
