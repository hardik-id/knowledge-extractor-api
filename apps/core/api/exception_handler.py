"""REST framework exception handler: every error becomes ``{ code, message }``."""

import logging
from typing import Any

from django.core.exceptions import PermissionDenied
from django.http import Http404
from rest_framework import exceptions
from rest_framework.response import Response
from rest_framework.views import set_rollback

from apps.core.errors import ApiError

logger = logging.getLogger(__name__)


def to_api_error(exc: Exception) -> ApiError:
    """Map any exception to the ApiError that describes it."""
    if isinstance(exc, ApiError):
        return exc
    if isinstance(exc, exceptions.ValidationError):
        detail: Any = exc.detail
        if not isinstance(detail, dict):
            detail = {"non_field_errors": detail}
        return ApiError("validation_error", details=_plain(detail))
    if isinstance(exc, exceptions.NotAuthenticated | exceptions.AuthenticationFailed):
        return ApiError("unauthenticated")
    if isinstance(exc, exceptions.PermissionDenied | PermissionDenied):
        return ApiError("forbidden")
    if isinstance(exc, exceptions.NotFound | Http404):
        return ApiError("not_found")
    if isinstance(exc, exceptions.MethodNotAllowed):
        return ApiError("method_not_allowed")
    if isinstance(exc, exceptions.ParseError):
        return ApiError("bad_request")
    return ApiError("server_error")


def _plain(value: Any) -> Any:
    """Turn DRF's ErrorDetail structures into plain strings, lists and dicts."""
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(item) for item in value]
    return str(value)


def exception_handler(exc: Exception, context: dict[str, Any]) -> Response:
    error = to_api_error(exc)
    if error.code == "server_error" and not isinstance(exc, ApiError):
        logger.error("Unhandled exception", exc_info=exc)
    set_rollback()
    headers: dict[str, str] = {}
    auth_header = getattr(exc, "auth_header", None)
    if error.code == "unauthenticated" and auth_header:
        headers["WWW-Authenticate"] = auth_header
    return Response(error.body(), status=error.status, headers=headers)
