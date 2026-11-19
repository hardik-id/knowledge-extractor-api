# Live updates: sockets, the ticket and run events

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

## The run socket

```
ws://<host>/ws/runs/{run_id}/?ticket=k3J...
```

The route the UI opens for a run (`createHttpRunEvents` in the UI), with the trailing slash. `RunConsumer` in `apps/realtime/consumers.py`, routed in `apps/realtime/routing.py`.

1. The ticket signs the person in (above).
2. The run must be visible to that person (`runs.selectors.get_run`). Otherwise the socket is accepted and closed with **4404**: someone else's run, an unknown id and a malformed id look the same.
3. The socket joins the run's group (`run.<run_id>` on the channel layer) and from then on receives every event published for the run.

The server only sends. Each event is one JSON text frame. Whatever the client sends is dropped unread: it changes nothing and gets no answer.

Events published while nobody listens, or while a socket is reconnecting, are lost on purpose. The UI fetches the run's snapshot (`GET /api/v1/runs/{run_id}`) every time its socket opens, so it never needs them.

Deleting a run (`DELETE /api/v1/runs/{run_id}`) closes its sockets with 4404, once the delete has committed.

### Close codes

| Code | Meaning | The UI |
| --- | --- | --- |
| 4401 | No ticket, or an unknown, used or expired one | asks for a new ticket and tries again |
| 4404 | The run is not yours, does not exist, or was deleted | stops |

The UI also stops on 4403 (not used by this API so far) and retries on any other code.

### Events

| `type` | Shape | Sent by |
| --- | --- | --- |
| `cell` | `{ "type": "cell", "cell": { file_id, stage, status, execution_id, progress, error, output, updated_at } }`, the cell as in the snapshot | `runs.services.set_cell`, on every change |
| `run.changed` | `{ "type": "run.changed" }` | `runs.services.replace_documents`, once the change of the run's documents is committed; the page fetches the snapshot again |
| `extraction.changed` | `{ "type": "extraction.changed", "file_id", "revision" }` | the extraction app, when a file's revision changes (#149, #152) |
| `assistant.delta` | `{ "type": "assistant.delta", "message_id", "text" }` | the assistant (#146) |
| `assistant.proposal` | `{ "type": "assistant.proposal", "message_id", "proposal" }` | the assistant (#146) |
| `assistant.done` | `{ "type": "assistant.done", "message_id" }` | the assistant (#146) |
| `assistant.cleared` | `{ "type": "assistant.cleared" }` | the assistant, when the conversation is deleted (#325) |

## Publishing an event

Any part of the backend announces a change to a run with one call (`apps/realtime/services.py`):

```python
from apps.realtime import services as realtime

realtime.publish_run_event(run_id, {"type": "cell", "cell": {...}})        # request code, jobs
await realtime.apublish_run_event(run_id, {"type": "assistant.done", ...})  # async code
```

- **After the commit.** `publish_run_event` hands the send to `transaction.on_commit`: inside a transaction the event goes out once it commits, and never if it rolls back. Outside a transaction it goes at once. It works the same in a request and in a job in the worker process (`async_to_sync` over the channel layer).
- **The async twin** sends at once: async code holds no transaction of its own.
- **Never raises.** If the channel layer is down or missing, the failure is logged (`run_event_not_sent`, with `run_id` and `kind`, the event type) and the caller carries on. The request or the job does not fail because nobody could be told.
- The event must be plain JSON data (dicts, lists, strings, numbers, booleans, null): it goes through Redis and then into one text frame.
- `close_run_sockets(run_id)` closes the run's sockets with 4404 the same way; `runs.services.delete_run` calls it.

## Adding a socket route

Add a `path(...)` to `websocket_urlpatterns` in `apps/realtime/routing.py` and write the consumer. Read the person from `self.scope["user"]`. Do not read the ticket and do not log `scope["query_string"]`. Routes end with a slash, as the UI opens them (`/ws/runs/<id>/`).

## The channel layer

`CHANNEL_LAYERS["default"]` is `channels_redis` on `REDIS_URL` (the compose `redis` service). Under pytest it is the in-memory layer.

A listening socket waits on Redis for up to 5 s at a time (`brpop_timeout` in `channels_redis`), and redis-py 8 gives up on a read after 5 s by default. So the layer's host sets `socket_timeout` to 10 s: without it an idle socket is dropped after 5 s with `redis.exceptions.TimeoutError`. A connect gives up after 5 s (`socket_connect_timeout`). `apps/realtime/tests/test_redis_layer.py` holds a socket idle past that wait on the real Redis; it is skipped when Redis is not running.

## The test route

`/ws/test/` is a test-only socket that says who signed in (`{"type": "hello", "user_id": ...}`) and echoes JSON. It exists only when `REALTIME_TEST_ROUTE=true` (on in the test settings, off otherwise), so it proves the wiring without being part of the API.

## Variables

| Variable | Meaning |
| --- | --- |
| `REDIS_URL` | Channel layer. Default `redis://localhost:<REDIS_PORT>/0` |
| `WS_TICKET_TTL_SECONDS` | Lifetime of a ticket. Default 30 |
| `REALTIME_TEST_ROUTE` | Serve `/ws/test/`. Default false |

## Tests

`apps/realtime/tests/` (ticket service and endpoint, the socket through the real ASGI application, no ticket in any log line, the run socket in `test_run_socket.py`, the publisher with a failing layer in `test_publisher.py`) and `apps/core/tests/test_ticket_redaction.py`. The socket tests use a small client over `asgiref` (`tests/communicator.py`), because `channels.testing` needs daphne.
