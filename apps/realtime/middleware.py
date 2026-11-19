"""The two steps every socket route goes through, in this order (config/asgi.py):

1. ``OriginMiddleware`` refuses a handshake from an origin the UI is not served from.
2. ``TicketAuthMiddleware`` signs the person in with the ``?ticket=`` of the URL.

See docs/realtime.md.
"""

import re
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any
from urllib.parse import parse_qsl, urlencode

import structlog
from channels.db import database_sync_to_async
from django.conf import settings

from apps.realtime import services

log = structlog.get_logger(__name__)

Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

# The close code the UI reacts to: it asks for a new ticket and tries again.
UNAUTHORIZED = 4401


def _origin(scope: Scope) -> str | None:
    for name, value in scope.get("headers", []):
        if name == b"origin":
            return str(value.decode("latin1"))
    return None


def origin_allowed(origin: str) -> bool:
    """The same rule as CORS: the listed origins, plus the local-dev patterns."""
    if origin in (o.rstrip("/") for o in settings.CORS_ALLOWED_ORIGINS):
        return True
    return any(
        re.match(pattern, origin)
        for pattern in getattr(settings, "CORS_ALLOWED_ORIGIN_REGEXES", [])
    )


class OriginMiddleware:
    """Refuses (HTTP 403, before the socket opens) a browser from another origin.

    A handshake without an ``Origin`` header comes from something that is not a
    browser. It is let through: the ticket is what signs it in.
    """

    def __init__(self, inner: ASGIApp) -> None:
        self.inner = inner

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        origin = _origin(scope)
        if origin is None or origin_allowed(origin):
            await self.inner(scope, receive, send)
            return
        log.warning("ws_origin_refused", path=scope["path"], origin=origin[:200])
        await receive()  # websocket.connect
        await send({"type": "websocket.close", "code": 403})


class TicketAuthMiddleware:
    """Reads ``?ticket=``, redeems it and puts the person in ``scope["user"]``.

    No ticket, a used one, an expired one or an unknown one: the socket is
    accepted and closed with 4401. The close code can only reach the browser
    after the handshake, so the socket is not refused with a 403 here.
    The ticket is removed from the query string the routes see.
    """

    def __init__(self, inner: ASGIApp) -> None:
        self.inner = inner

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        query = parse_qsl(scope.get("query_string", b"").decode("latin1"))
        ticket = next((value for key, value in query if key == "ticket"), "")
        user = None
        if ticket:
            user = await database_sync_to_async(services.redeem_ticket)(ticket)
        if user is None:
            log.info(
                "ws_ticket_refused",
                path=scope["path"],
                reason="refused" if ticket else "missing",
            )
            await receive()  # websocket.connect
            await send({"type": "websocket.accept"})
            await send({"type": "websocket.close", "code": UNAUTHORIZED})
            return
        rest = urlencode([(key, value) for key, value in query if key != "ticket"])
        await self.inner(
            {**scope, "user": user, "query_string": rest.encode("latin1")},
            receive,
            send,
        )
