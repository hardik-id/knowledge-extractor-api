"""Views and Django-level handlers that answer in the error contract."""

from typing import Any

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.defaults import page_not_found, server_error
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

from apps.core.errors import ApiError

API_PREFIX = "/api/"


def _json(error: ApiError) -> JsonResponse:
    return JsonResponse(error.body(), status=error.status)


@api_view(["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
def api_not_found(request: Request, rest: str = "") -> Response:
    """Catch-all for unknown URLs under /api/, so debug mode cannot show its HTML page."""
    raise ApiError("not_found")


def handler404(
    request: HttpRequest, exception: Exception, *args: Any, **kwargs: Any
) -> HttpResponse:
    if request.path.startswith(API_PREFIX):
        return _json(ApiError("not_found"))
    return page_not_found(request, exception, *args, **kwargs)


def handler500(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
    if request.path.startswith(API_PREFIX):
        return _json(ApiError("server_error"))
    return server_error(request, *args, **kwargs)
