from collections.abc import Callable

from django.http import HttpRequest, HttpResponse


class CrashingMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        raise RuntimeError("internal secret detail")
