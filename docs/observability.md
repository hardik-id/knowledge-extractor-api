# Observability: OpenTelemetry

Every request produces a trace and metrics in OpenTelemetry's format, and every log line written inside a request carries the trace id. The shape Splunk works with.

Code: `apps/core/telemetry.py` (SDK, instrumentation, middleware), `apps/core/logging.py` (the log processor). Tests: `apps/core/tests/test_telemetry.py`.

## Setup

`setup_telemetry()` builds the SDK in code (no `opentelemetry-instrument` wrapper), once per process, from the standard `OTEL_*` variables. It is called from `config/asgi.py`, `config/wsgi.py` and `manage.py`, so uvicorn, the task worker and every management command are covered.

uvicorn workers fork or spawn: each worker imports `config.asgi` itself and sets up its own SDK. Never call `setup_telemetry()` in a parent process before the fork.

With `OTEL_SDK_DISABLED=true` it does nothing: no provider, no instrumentation, no exporter, no connection. The app starts with no collector running. The test settings turn it off; only `test_telemetry.py` builds providers, with in-memory exporters.

| Variable | Meaning | Default |
| --- | --- | --- |
| `OTEL_SDK_DISABLED` | `true` turns everything off | `true` |
| `OTEL_SERVICE_NAME` | `service.name` | `knowledge-extractor-api` |
| `OTEL_RESOURCE_ATTRIBUTES` | extra resource attributes, `key=value` comma separated | `deployment.environment=local` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | where traces, metrics and logs go (OTLP over HTTP) | `http://localhost:4318` |
| `OTEL_LOGS_EXPORTER` | `otlp` also exports log records over OTLP; `none` does not | `none` |

The SDK reads the other standard variables itself (`OTEL_EXPORTER_OTLP_HEADERS`, `OTEL_TRACES_SAMPLER`, `OTEL_METRIC_EXPORT_INTERVAL`, `OTEL_BSP_SCHEDULE_DELAY`, ...). `.env` is read before the SDK is set up, so they can go there too.

The logs signal is not stable in the Python SDK yet, so it is exported only on request. Without it, logs stay on stdout (see [logging.md](logging.md)) and carry the trace id.

## What is emitted

Resource on every signal: `service.name`, `service.version` (from `pyproject.toml`) and `deployment.environment`.

| Source | Spans and metrics |
| --- | --- |
| Django requests | one server span per request, named `<METHOD> <route>`, with `http.method`, `http.route`, `http.status_code`, and the `request_id` attribute; `http.server.duration` and `http.server.active_requests` |
| PostgreSQL (psycopg) | one client span per statement, a child of the request span; the statement has no parameter values |
| Redis | one client span per command, every argument shown as `?` |
| Outgoing HTTP (httpx2) | one client span per call; `http.client.duration` |

`/api/v1/health` and `/api/v1/ready` are left out: no span, no metric, and no database span for the readiness query.

## Logs and traces

A structlog processor adds `trace_id` (32 hex characters), `span_id` (16) and `trace_flags` (`01` sampled, `00` not), all lower-case, to every line written inside a span, next to `request_id`. Lines written outside a span (start-up, health) have none of the three. The request id is also an attribute on the server span, so a request can be found from either side.

Fields Splunk searches on:

| Where | Field |
| --- | --- |
| log line | `trace_id`, `span_id`, `trace_flags`, `request_id`, `user_id`, `status`, `path` |
| span | trace id, `request_id`, `http.route`, `http.method`, `http.status_code`, `service.name`, `deployment.environment` |

A request with a `traceparent` header continues that trace.

## Browser correlation

For Splunk RUM the response carries `Server-Timing: traceparent;desc="00-<trace id>-<span id>-01"`, built from the request's server span. CORS exposes `Server-Timing` and lets `traceparent`, `tracestate` and `baggage` request headers through (`config/settings/base.py`, see [security.md](security.md)). A browser agent that reads `Server-Timing` across origins may also need `Timing-Allow-Origin`; that is not set here.

## What is never recorded

- `Authorization` and `Cookie` values. Header capture is off by default; if an operator turns it on (`OTEL_INSTRUMENTATION_HTTP_CAPTURE_HEADERS_*`), these four are sanitized: `authorization`, `proxy-authorization`, `cookie`, `set-cookie`.
- Query strings. The socket ticket travels in one. A request hook cuts the URL attributes (`http.url`, `http.target`, `url.full`, `url.path`) back to the part before `?` on server and outgoing spans, and empties `url.query`. The log line holds `request.path` only.
- Redis command arguments and SQL parameter values.

Test: `test_no_span_and_no_log_line_holds_a_token_or_a_query_string` and `test_an_outgoing_call_records_no_query_string`.

## Trying it locally

Run a collector that prints what it receives, on ports of your own (the `debug` exporter, `otlp` receiver on 4318), then:

```sh
OTEL_SDK_DISABLED=false OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:14318 \
  OTEL_METRIC_EXPORT_INTERVAL=2000 uv run uvicorn config.asgi:application --port 8000 --no-access-log
```

Call `GET /api/v1/me` and look for the server span, its PostgreSQL children and `http.server.duration`.
