# Logging

Every request has an id, and every log line written while it is served carries it.

## Request id

`RequestIdMiddleware` (`apps/core/middleware.py`) runs first. It takes `X-Request-ID` from the request when the value is 1 to 128 characters of `A-Z a-z 0-9 . _ -`; anything else (too long, other characters, empty) is replaced by a new UUID. The id is returned in the `X-Request-ID` response header on every response, 404 and 500 included. The UI shows it as the reference on unknown errors.

## Log lines

[django-structlog](https://django-structlog.readthedocs.io/) is wired in `config/settings/base.py`; the structlog setup is in `apps/core/logging.py`. `RequestLogMiddleware` writes one line per request, `request_finished` (or `request_failed` for an unhandled exception), with `request_id`, `method`, `path`, `status`, `duration_ms` and `user_id` (the person, set once the token is accepted; see [auth.md](auth.md)). The `request_started` line is dropped.

Settings:

| Variable | Values | Default |
| --- | --- | --- |
| `LOG_LEVEL` | any Python level name | `INFO` |
| `LOG_FORMAT` | `json` or `console` | `console` |

With `json` each line is one JSON object. Plain `logging` records (Django, libraries) go through the same formatter and carry the request id too.

## In app code

```python
import structlog

log = structlog.get_logger(__name__)

log.info("run_started", run_id=run.id)
```

Nothing else is needed: the request id is added from the context of the current request. Pass values as keyword arguments, not formatted into the message.

## What is never logged

- Tokens and the `Authorization` header. The middleware does not read it. Do not log it, and do not log request headers or bodies wholesale.
- The query string. A WebSocket ticket will travel in one. The log line holds `request.path` only, and the `django.server` logger (runserver prints the full path) and the `uvicorn.access` logger (`GET /path?query`) are switched off in favour of the request line. The Dockerfile and `compose.yaml` also start uvicorn with `--no-access-log`; keep that flag on any other command that starts it. Django applies `LOGGING` after uvicorn has set up its own config, so the `uvicorn.access` entry in `LOGGING` wins whichever way uvicorn is launched.

Tests: `apps/core/tests/test_request_logging.py`.
