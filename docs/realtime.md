# Live updates: sockets and the ticket

The API holds WebSocket connections next to the REST API. One uvicorn process serves both: `config/asgi.py` sends HTTP to Django as before and WebSockets through two steps to `apps/realtime/routing.py`.

```
uvicorn -> ProtocolTypeRouter
             http       -> Django
             websocket  -> OriginMiddleware -> TicketAuthMiddleware -> URLRouter(websocket_urlpatterns)
```

## The ticket

A browser cannot send an `Authorization` header on a WebSocket, so it asks for a ticket over REST and puts it in the socket URL. The UI does this each time it opens or reopens a socket (`createHttpRunEvents` in the UI).

```
POST /api/v1/ws-ticket        (bearer token, no body)
200 { "ticket": "k3J..." }

ws://<host>/ws/<route>/?ticket=k3J...
```

- **Single use.** Redeeming is one `UPDATE ... WHERE used_at IS NULL AND expires_at > now`: of two sockets with the same ticket, the database lets one statement match a row, so one wins.
- **Short-lived.** It lives `WS_TICKET_TTL_SECONDS` (default 30). Expired rows are deleted whenever a new ticket is issued.
- **Tied to the person** who asked. Redeeming it puts that person in `scope["user"]`. A deactivated person gets none.
- **Never stored.** The table `realtime_wsticket` holds the SHA-256 of the ticket (`token_hash`), never the ticket.

The code is in `apps/realtime/services.py` (`issue_ticket`, `redeem_ticket`).

## Sign-in for every socket route

`TicketAuthMiddleware` (`apps/realtime/middleware.py`) wraps the whole router, so a route never signs anyone in itself. It reads `?ticket=`, redeems it and sets `scope["user"]`. The ticket is removed from the query string the routes see.

No ticket, an unknown one, a used one or an expired one: the socket is **accepted and closed with code 4401**. (A close code can only reach the browser after the handshake; refusing the handshake would show the UI a plain failure.) The UI reacts to 4401 by asking for a new ticket and trying again.

## Origin

`OriginMiddleware` checks the handshake's `Origin` against the CORS settings: `CORS_ALLOWED_ORIGINS`, and in local settings the `CORS_ALLOWED_ORIGIN_REGEXES` for any localhost port. Another origin is refused with HTTP 403 before the socket opens, and the ticket is not spent. A handshake with no `Origin` header comes from something that is not a browser and is let through: the ticket signs it in.

## Logs

A ticket is a secret in a URL. uvicorn logs `WebSocket /path?ticket=...` on the `uvicorn.error` logger, so the logging setup (`RedactTicket` in `apps/core/logging.py`) rewrites `ticket=<value>` to `ticket=[redacted]` on that logger and on the console handler. The middleware logs the path only. See [logging.md](logging.md).

## Adding a socket route

Add a `path(...)` to `websocket_urlpatterns` in `apps/realtime/routing.py` (or the routing of the app that owns the route, included there) and write the consumer. Read the person from `self.scope["user"]`. Do not read the ticket and do not log `scope["query_string"]`. Routes end with a slash, as the UI opens them (`/ws/runs/<id>/`).

## The channel layer

`CHANNEL_LAYERS["default"]` is `channels_redis` on `REDIS_URL` (the compose `redis` service). Under pytest it is the in-memory layer.

## The test route

`/ws/test/` is a test-only socket that says who signed in (`{"type": "hello", "user_id": ...}`) and echoes JSON. It exists only when `REALTIME_TEST_ROUTE=true` (on in the test settings, off otherwise), so it proves the wiring without being part of the API.

## Variables

| Variable | Meaning |
| --- | --- |
| `REDIS_URL` | Channel layer. Default `redis://localhost:<REDIS_PORT>/0` |
| `WS_TICKET_TTL_SECONDS` | Lifetime of a ticket. Default 30 |
| `REALTIME_TEST_ROUTE` | Serve `/ws/test/`. Default false |

## Tests

`apps/realtime/tests/` (ticket service and endpoint, the socket through the real ASGI application, no ticket in any log line) and `apps/core/tests/test_ticket_redaction.py`. The socket tests use a small client over `asgiref` (`tests/communicator.py`), because `channels.testing` needs daphne.
