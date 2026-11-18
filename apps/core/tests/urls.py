import structlog
from django.http import HttpRequest, JsonResponse
from django.urls import path

log = structlog.get_logger(__name__)


def hello(request: HttpRequest) -> JsonResponse:
    log.info("inside_view")
    return JsonResponse({"ok": True})


def boom(request: HttpRequest) -> JsonResponse:
    raise RuntimeError("boom")


urlpatterns = [path("hello", hello), path("boom", boom)]
