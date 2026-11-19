"""OpenTelemetry for the API: traces, metrics and, on request, logs. See docs/observability.md.

`setup_telemetry()` builds the SDK in code, once per process, from the standard
`OTEL_*` variables and instruments Django, PostgreSQL, Redis and httpx. The three
entry points (`config/asgi.py`, `config/wsgi.py`, `manage.py`) call it, so every
uvicorn worker, the task worker and every management command is covered.
`OTEL_SDK_DISABLED=true` makes it do nothing.

The middleware here answers with the trace id (`Server-Timing`) and keeps the
request id on the span. The log side (trace id on every line) is in
`apps/core/logging.py`.
"""

import logging
import os
import tomllib
from collections.abc import Callable
from typing import Any

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from opentelemetry import context, metrics, trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.django import DjangoInstrumentor
from opentelemetry.instrumentation.httpx import HTTPX2ClientInstrumentor
from opentelemetry.instrumentation.logging.handler import LoggingHandler
from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Span

# Health and readiness are probed every few seconds and say nothing: no span, no
# metric, and no database span for the readiness query either (see QuietProbes).
EXCLUDED_URLS = r"/api/v1/(health|ready)(\?|$)"

# Span attributes that carry the request or call URL, and so possibly a query
# string (the socket ticket travels in one). Cut back to the part before the "?".
_URL_ATTRIBUTES = ("http.url", "http.target", "url.full", "url.path")
# Request headers that are never recorded, even when an operator turns on header
# capture (OTEL_INSTRUMENTATION_HTTP_CAPTURE_HEADERS_SERVER_REQUEST).
_SANITIZED_HEADERS = "authorization,proxy-authorization,cookie,set-cookie"

_REQUEST_ID_ATTRIBUTE = "request_id"

_installed = False
_log_handler: logging.Handler | None = None
# The providers `install` was given. Code that makes its own spans and metrics
# (jobs, the assistant, extraction, sockets) asks for them here, so a test can
# install in-memory ones; with none installed the global providers answer.
_tracer_provider: TracerProvider | None = None
_meter_provider: MeterProvider | None = None


def _service_version() -> str:
    try:
        with (settings.BASE_DIR / "pyproject.toml").open("rb") as handle:
            return str(tomllib.load(handle)["project"]["version"])
    except OSError, KeyError, tomllib.TOMLDecodeError:
        return "unknown"


def _resource_attributes() -> dict[str, str]:
    """OTEL_RESOURCE_ATTRIBUTES (key=value pairs), with the three we always send."""
    attributes: dict[str, str] = {}
    for pair in settings.OTEL_RESOURCE_ATTRIBUTES.split(","):
        key, separator, value = pair.partition("=")
        if separator and key.strip():
            attributes[key.strip()] = value.strip()
    attributes["service.name"] = settings.OTEL_SERVICE_NAME
    attributes.setdefault("service.version", _service_version())
    attributes.setdefault("deployment.environment", "local")
    return attributes


def build_resource() -> Resource:
    return Resource.create(_resource_attributes())


def strip_query(span: Span, *args: Any) -> None:
    """Request or call hook: the URL attributes lose their query string."""
    attributes = getattr(span, "attributes", None) or {}
    for key in _URL_ATTRIBUTES:
        value = attributes.get(key)
        if isinstance(value, str) and "?" in value:
            span.set_attribute(key, value.split("?", 1)[0])
    if attributes.get("url.query"):
        span.set_attribute("url.query", "")


async def strip_query_async(span: Span, *args: Any) -> None:
    strip_query(span)


_STANDARD_RECORD_ATTRIBUTES = frozenset(logging.makeLogRecord({}).__dict__) | {
    "message",
    "asctime",
    "taskName",
}
_PLAIN_TYPES = (str, bool, int, float)


def _is_plain(value: object) -> bool:
    if isinstance(value, _PLAIN_TYPES):
        return True
    return isinstance(value, list | tuple) and all(
        isinstance(item, _PLAIN_TYPES) for item in value
    )


class _PlainRecords(logging.Filter):
    """Only plain `extra` values reach the OTLP exporter.

    The handler turns any other value into its `str()`. structlog hangs its logger
    on the record, and Django's `django.request` logger adds the request, whose
    repr holds the full path with the query string (the socket ticket). Both go.
    """

    def filter(self, record: logging.LogRecord) -> logging.LogRecord:
        plain = logging.makeLogRecord(record.__dict__)
        for name, value in record.__dict__.items():
            if name not in _STANDARD_RECORD_ATTRIBUTES and not _is_plain(value):
                del plain.__dict__[name]
        return plain


def install(
    *,
    tracer_provider: TracerProvider,
    meter_provider: MeterProvider,
    logger_provider: LoggerProvider | None = None,
) -> None:
    """Instrument everything against these providers. `setup_telemetry` calls it."""
    global _installed, _log_handler, _tracer_provider, _meter_provider
    _tracer_provider = tracer_provider
    _meter_provider = meter_provider
    DjangoInstrumentor().instrument(
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        excluded_urls=EXCLUDED_URLS,
        request_hook=strip_query,
    )
    PsycopgInstrumentor().instrument(tracer_provider=tracer_provider)
    # The Redis instrumentation records commands with every argument as "?".
    RedisInstrumentor().instrument(tracer_provider=tracer_provider)
    HTTPX2ClientInstrumentor().instrument(
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        request_hook=strip_query,
        async_request_hook=strip_query_async,
    )
    if logger_provider is not None:
        # An OTLP handler for the root logger. It stamps the current span's ids on
        # each record itself.
        _log_handler = LoggingHandler(logger_provider=logger_provider)
        _log_handler.addFilter(_PlainRecords())
        attach_log_handler()
    _installed = True


def get_tracer(name: str) -> trace.Tracer:
    """A tracer from the installed provider, else the global one (a no-op when telemetry is off)."""
    return (_tracer_provider or trace.get_tracer_provider()).get_tracer(name)


def meter_provider() -> metrics.MeterProvider:
    """The installed meter provider, else the global one. Key a cache of instruments on it."""
    return _meter_provider or metrics.get_meter_provider()


def get_meter(name: str) -> metrics.Meter:
    return meter_provider().get_meter(name)


def fail_span(span: Span, error: BaseException) -> None:
    """Mark a span failed with the exception's type and nothing else.

    A message can quote what the person wrote, so it is never recorded: no
    description, no `exception` event, only `error.type`.
    """
    span.set_attribute("error.type", type(error).__qualname__)
    span.set_status(trace.Status(trace.StatusCode.ERROR))


def attach_log_handler() -> None:
    """Put the OTLP log handler on the root logger, if there is one and it is not there.

    The entry points set telemetry up before `django.setup()`, and `django.setup()`
    runs `dictConfig(LOGGING)`, which removes every handler the root logger has.
    `CoreConfig.ready()` calls this again once logging is configured.
    """
    root = logging.getLogger()
    if _log_handler is not None and _log_handler not in root.handlers:
        root.addHandler(_log_handler)


def uninstall() -> None:
    """Undo `install`. For tests; a process never needs it."""
    global _installed, _log_handler, _tracer_provider, _meter_provider
    _tracer_provider = None
    _meter_provider = None
    instrumentors: list[Any] = [
        DjangoInstrumentor(),
        PsycopgInstrumentor(),
        RedisInstrumentor(),
        HTTPX2ClientInstrumentor(),
    ]
    for instrumentor in instrumentors:
        instrumentor.uninstrument()
    if _log_handler is not None:
        logging.getLogger().removeHandler(_log_handler)
        _log_handler = None
    _installed = False


def setup_telemetry() -> bool:
    """Set the SDK up in this process. Returns whether telemetry is on.

    Call it from code that every worker runs (the entry points), never before a
    fork: each uvicorn worker imports `config.asgi` itself and so sets up its own.
    A second call in the same process does nothing.
    """
    if settings.OTEL_SDK_DISABLED:
        return False
    if _installed:
        return True
    os.environ.setdefault("OTEL_PYTHON_DJANGO_EXCLUDED_URLS", EXCLUDED_URLS)
    os.environ.setdefault(
        "OTEL_INSTRUMENTATION_HTTP_CAPTURE_HEADERS_SANITIZE_FIELDS", _SANITIZED_HEADERS
    )

    resource = build_resource()
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(tracer_provider)

    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[PeriodicExportingMetricReader(OTLPMetricExporter())],
    )
    metrics.set_meter_provider(meter_provider)

    logger_provider: LoggerProvider | None = None
    if settings.OTEL_LOGS_EXPORTER == "otlp":
        logger_provider = LoggerProvider(resource=resource)
        logger_provider.add_log_record_processor(
            BatchLogRecordProcessor(OTLPLogExporter())
        )
        set_logger_provider(logger_provider)

    install(
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        logger_provider=logger_provider,
    )
    return True


def _sampled_flag(span_context: trace.SpanContext) -> str:
    """ "01" when the trace is sampled, else "00" (the W3C random-id bit is left out)."""
    return f"{int(span_context.trace_flags) & 1:02x}"


def traceparent(span: Span) -> str | None:
    """The W3C traceparent of a span, or None when there is no real span."""
    span_context = span.get_span_context()
    if not span_context.is_valid:
        return None
    return (
        f"00-{span_context.trace_id:032x}-{span_context.span_id:016x}"
        f"-{_sampled_flag(span_context)}"
    )


class TelemetryMiddleware:
    """Per request: the request id on the span, and the trace id on the response.

    It sits right after the request id middleware, inside the server span that
    the Django instrumentation opens, so the current span is the request's.

    The response carries `Server-Timing: traceparent;desc="00-<trace>-<span>-01"`,
    which the browser agent (Splunk RUM) reads to join a page view to this trace.

    For the paths in `EXCLUDED_URLS` it switches instrumentation off for the
    request. They get no server span, and without it the readiness query would
    otherwise become a trace of its own.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if _is_excluded(request.path):
            token = context.attach(
                context.set_value(context._SUPPRESS_INSTRUMENTATION_KEY, True)
            )
            try:
                return self.get_response(request)
            finally:
                context.detach(token)

        span = trace.get_current_span()
        request_id = request.META.get("HTTP_X_REQUEST_ID")
        if request_id and span.is_recording():
            span.set_attribute(_REQUEST_ID_ATTRIBUTE, request_id)
        response = self.get_response(request)
        value = traceparent(span)
        if value is not None:
            response["Server-Timing"] = f'traceparent;desc="{value}"'
        return response


def _is_excluded(path: str) -> bool:
    return path in ("/api/v1/health", "/api/v1/ready")
