"""Request id and the one log line per request. See docs/logging.md."""

import re
import time
import uuid
from collections.abc import Callable
from typing import Any

from django.http import HttpRequest, HttpResponse
from django_structlog import signals
from django_structlog.middlewares import RequestMiddleware

REQUEST_ID_HEADER = "X-Request-ID"
_META_KEY = "HTTP_X_REQUEST_ID"
_SANE_ID = re.compile(r"[A-Za-z0-9._-]{1,128}")


def clean_request_id(value: str | None) -> str:
    """The caller's id when it is short and plain, otherwise a new one."""
    if value is not None and _SANE_ID.fullmatch(value):
        return value
    return str(uuid.uuid4())


class RequestIdMiddleware:
    """Settle the request id first, and return it on every response.

    It runs before the logging middleware, which reads the id from the request.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        request_id = clean_request_id(request.META.get(_META_KEY))
        request.META[_META_KEY] = request_id
        response = self.get_response(request)
        response[REQUEST_ID_HEADER] = request_id
        return response


class RequestLogMiddleware(RequestMiddleware):
    """django-structlog's middleware, with a log line that never holds a query string."""

    def prepare(self, request: HttpRequest) -> None:
        request._log_started = time.perf_counter()  # type: ignore[attr-defined]
        super().prepare(request)

    @staticmethod
    def format_request(request: HttpRequest) -> str:
        return f"{request.method} {request.path}"


def _add_request_fields(
    request: HttpRequest, log_kwargs: dict[str, Any], status: int
) -> None:
    started = getattr(request, "_log_started", None)
    log_kwargs["method"] = request.method
    log_kwargs["path"] = request.path
    log_kwargs["status"] = status
    if started is not None:
        log_kwargs["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)


def _on_finished(
    sender: Any,
    request: HttpRequest,
    response: HttpResponse,
    log_kwargs: dict[str, Any],
    **kwargs: Any,
) -> None:
    _add_request_fields(request, log_kwargs, response.status_code)


def _on_failed(
    sender: Any, request: HttpRequest, log_kwargs: dict[str, Any], **kwargs: Any
) -> None:
    _add_request_fields(request, log_kwargs, 500)


signals.bind_extra_request_finished_metadata.connect(_on_finished)
signals.bind_extra_request_failed_metadata.connect(_on_failed)
