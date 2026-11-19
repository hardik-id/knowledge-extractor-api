"""Every socket route, signed in by ``TicketAuthMiddleware`` (see config/asgi.py).

Add a route to ``websocket_urlpatterns``. The run socket is added by the runs app.
"""

from django.conf import settings
from django.urls import path
from django.urls.resolvers import URLPattern, URLResolver

from apps.realtime.consumers import EchoConsumer

websocket_urlpatterns: list[URLPattern | URLResolver] = []

if settings.REALTIME_TEST_ROUTE:
    websocket_urlpatterns.append(path("ws/test/", EchoConsumer.as_asgi()))
