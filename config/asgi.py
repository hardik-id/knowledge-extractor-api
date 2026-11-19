"""
ASGI config for config project.

It exposes the ASGI callable as a module-level variable named ``application``.
HTTP goes to Django as before; WebSockets go through the origin check and the
ticket sign-in to ``apps/realtime/routing.py``. uvicorn serves both.

For more information on this file, see
https://docs.djangoproject.com/en/6.1/howto/deployment/asgi/
"""

import os

from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

# Django's own application first: it runs django.setup(), which the imports
# below need.
django_asgi_app = get_asgi_application()

from apps.realtime.middleware import OriginMiddleware, TicketAuthMiddleware  # noqa: E402
from apps.realtime.routing import websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": OriginMiddleware(
            TicketAuthMiddleware(URLRouter(websocket_urlpatterns))
        ),
    }
)
