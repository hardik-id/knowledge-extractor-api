"""Every socket route, signed in by ``TicketAuthMiddleware`` (see config/asgi.py).

Add a route to ``websocket_urlpatterns``. Routes end with a slash, as the UI opens them.
"""

from django.conf import settings
from django.urls import path
from django.urls.resolvers import URLPattern, URLResolver

from apps.realtime.consumers import EchoConsumer, RunConsumer

websocket_urlpatterns: list[URLPattern | URLResolver] = [
    path("ws/runs/<str:run_id>/", RunConsumer.as_asgi()),
]

if settings.REALTIME_TEST_ROUTE:
    websocket_urlpatterns.append(path("ws/test/", EchoConsumer.as_asgi()))
