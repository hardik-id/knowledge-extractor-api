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

With `OTEL_LOGS_EXPORTER=otlp` an OTLP handler sits on the root logger next to the console handler. The entry points set telemetry up before `django.setup()`, and `django.setup()` rebuilds the root logger from `LOGGING`, so `CoreConfig.ready()` attaches the handler again (`attach_log_handler()`). Only plain `extra` values (text, numbers, booleans) are exported; anything else is dropped, so Django's `request` object, whose repr holds the query string, never leaves the process.

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
- Query strings. The socket ticket travels in one. A request hook cuts the URL attributes (`http.url`, `http.target`, `url.full`, `url.path`) back to the part before `?` on server and outgoing spans, and empties `url.query`. The log line holds `request.path` only, and exported log records hold no non-plain `extra` such as Django's `request`.
- Redis command arguments and SQL parameter values.

Test: `test_no_span_and_no_log_line_holds_a_token_or_a_query_string`, `test_an_outgoing_call_records_no_query_string` and `test_an_exported_log_record_holds_no_query_string`.

## Trying it locally

Run a collector that prints what it receives, on ports of your own (the `debug` exporter, `otlp` receiver on 4318), then:

```sh
OTEL_SDK_DISABLED=false OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:14318 \
  OTEL_METRIC_EXPORT_INTERVAL=2000 uv run uvicorn config.asgi:application --port 8000 --no-access-log
```

Call `GET /api/v1/me` and look for the server span, its PostgreSQL children and `http.server.duration`.

## The collector in compose

`otel-collector` in `compose.yaml` is the Splunk distribution of the OpenTelemetry Collector (`quay.io/signalfx/splunk-otel-collector`, tag pinned), configured in `deploy/otel-collector/config.yaml`. Like `db` it is one shared service for every worktree: `docker compose up -d --wait otel-collector`. OTLP listens on 4317 (gRPC) and 4318 (HTTP); the host ports are `OTEL_GRPC_PORT` and `OTEL_HTTP_PORT`.

In compose, `api` and `worker` send to it with `OTEL_SDK_DISABLED=false`, `OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318` and `OTEL_LOGS_EXPORTER=otlp`. The worker's service name is `knowledge-extractor-worker`.

Every signal passes `memory_limiter` and `batch`, and always goes to the `debug` exporter. A Splunk exporter joins a pipeline only when its variables are set in `.env` (compose builds the exporter lists; with no credentials the pipelines hold `debug` alone). Tokens come from `.env`, which git ignores, never from the repository.

| Signal | Needs | Goes to |
| --- | --- | --- |
| traces | `SPLUNK_ACCESS_TOKEN`, `SPLUNK_REALM` | Splunk Observability Cloud, OTLP at `ingest.<realm>.observability.splunkcloud.com` |
| metrics | `SPLUNK_ACCESS_TOKEN`, `SPLUNK_REALM` | Splunk Observability Cloud (`signalfx` exporter) |
| logs | `SPLUNK_HEC_URL`, `SPLUNK_HEC_TOKEN` | Splunk Enterprise or Splunk Cloud, through HEC |

`SPLUNK_HEC_INSECURE_SKIP_VERIFY` (default `false`) skips certificate checks of the HEC endpoint. `SPLUNK_INDEX` (default `main`; the HEC token must be allowed to write to it) and `SPLUNK_SOURCETYPE` (default `knowledge-extractor-api`) set the index and sourcetype of the log events.

### Reading telemetry locally

```sh
docker compose logs -f otel-collector
```

One request to `/api/v1/me` shows as a trace (the server span and its PostgreSQL spans), as `http.server.duration` and `http.server.active_requests`, and as a log record carrying the same `trace_id` as the trace. The container has no shell or curl, so its healthcheck runs `otelcol validate` on the configuration: healthy means the configuration is valid and the process is up. To check a configuration by hand:

```sh
docker compose run --rm --no-deps --entrypoint /otelcol otel-collector validate --config=/etc/otelcol/config.yaml
```

Run the app on the host against it with `OTEL_SDK_DISABLED=false` and `OTEL_LOGS_EXPORTER=otlp` (the endpoint default is `http://localhost:4318`).

### What to search for in Splunk

Log events arrive in `SPLUNK_INDEX` with `sourcetype=SPLUNK_SOURCETYPE`. Search on the fields `trace_id`, `span_id`, `service.name` and `deployment.environment`:

```
index=main sourcetype=knowledge-extractor-api trace_id=<id>
```

In Splunk Observability Cloud, the same trace id opens the trace in APM, and `service.name` and `deployment.environment` pick the service and environment.

### Trying HEC with a local Splunk

Starting Splunk accepts its licence: that is the owner's step, not an agent's. The commands:

```sh
docker run -d --name splunk -p 8000:8000 -p 8088:8088 \
  -e SPLUNK_GENERAL_TERMS=--accept-sgt-current-at-splunk-com \
  -e SPLUNK_START_ARGS=--accept-license \
  -e SPLUNK_PASSWORD=<a password you choose> \
  -e SPLUNK_HEC_TOKEN=<a token you choose> \
  splunk/splunk:latest
```

Then in `.env`:

```
SPLUNK_HEC_URL=https://host.docker.internal:8088/services/collector
SPLUNK_HEC_TOKEN=<the same token>
SPLUNK_HEC_INSECURE_SKIP_VERIFY=true
```

`host.docker.internal` resolves inside the collector container on Docker Desktop; on Linux add `extra_hosts: ["host.docker.internal:host-gateway"]` to the service in a `compose.override.yaml`. HEC starts with a self-signed certificate, hence the skip-verify switch (local use only). Run `docker compose up -d otel-collector`, call the API, and search `index=main` in Splunk Web on port 8000.
