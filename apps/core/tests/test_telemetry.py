"""The telemetry wiring, against in-memory exporters. See docs/observability.md."""

import http.server
import io
import json
import logging
import os
import subprocess
import sys
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import httpx2
import pytest
from django.conf import settings
from django.db import connections
from django.test import Client, override_settings
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import (
    InMemoryLogRecordExporter,
    SimpleLogRecordProcessor,
)
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from opentelemetry.trace import SpanKind
from rest_framework.test import APIClient

from apps.core import telemetry
from apps.core.logging import make_formatter

URLS = override_settings(ROOT_URLCONF="apps.core.tests.urls")
TRACE_ID = "0af7651916cd43dd8448eb211c80319c"
TRACEPARENT = f"00-{TRACE_ID}-b7ad6b7169203331-01"


@dataclass
class Telemetry:
    spans: InMemorySpanExporter
    metrics: InMemoryMetricReader
    tracer_provider: TracerProvider
    meter_provider: MeterProvider

    def finished(self) -> list[ReadableSpan]:
        return list(self.spans.get_finished_spans())

    def server_span(self) -> ReadableSpan:
        (span,) = [s for s in self.finished() if s.kind == SpanKind.SERVER]
        return span


@pytest.fixture
def otel(settings: Any) -> Iterator[Telemetry]:
    settings.OTEL_RESOURCE_ATTRIBUTES = "deployment.environment=test"
    resource = telemetry.build_resource()
    spans = InMemorySpanExporter()
    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(SimpleSpanProcessor(spans))
    reader = InMemoryMetricReader()
    meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
    telemetry.install(tracer_provider=tracer_provider, meter_provider=meter_provider)
    try:
        yield Telemetry(spans, reader, tracer_provider, meter_provider)
    finally:
        telemetry.uninstall()


@URLS
@pytest.mark.django_db
def test_logs_are_exported_with_the_trace_when_a_logger_provider_is_given(
    otel: Telemetry,
) -> None:
    telemetry.uninstall()
    exporter = InMemoryLogRecordExporter()  # type: ignore[no-untyped-call]
    logger_provider = LoggerProvider(resource=telemetry.build_resource())
    logger_provider.add_log_record_processor(SimpleLogRecordProcessor(exporter))
    telemetry.install(
        tracer_provider=otel.tracer_provider,
        meter_provider=otel.meter_provider,
        logger_provider=logger_provider,
    )
    root = logging.getLogger()
    old_level = root.level
    root.setLevel(logging.INFO)
    try:
        Client().get("/hello")
    finally:
        root.setLevel(old_level)
    server = otel.server_span()
    records = [r.log_record for r in exporter.get_finished_logs()]
    ours = [r for r in records if r.trace_id == server.context.trace_id]
    assert ours
    assert all("_logger" not in (r.attributes or {}) for r in records)


@pytest.fixture
def log_lines() -> Iterator[io.StringIO]:
    """What the root logger writes, in the production JSON format."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(make_formatter("json"))
    root = logging.getLogger()
    old_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    try:
        yield stream
    finally:
        root.removeHandler(handler)
        root.setLevel(old_level)


def lines(stream: io.StringIO) -> list[dict[str, Any]]:
    return [json.loads(line) for line in stream.getvalue().splitlines() if line]


def every_value(span: ReadableSpan) -> list[str]:
    values = [str(value) for value in (span.attributes or {}).values()]
    values += [span.name]
    for event in span.events:
        values += [str(value) for value in (event.attributes or {}).values()]
    return values


# --- what a request produces -------------------------------------------------


@URLS
@pytest.mark.django_db(transaction=True)
def test_a_request_gives_a_server_span_a_database_span_and_metrics(
    otel: Telemetry,
) -> None:
    connections.close_all()  # new connections are made through the instrumentation
    response = Client().get("/api/test/notes")
    assert response.status_code == 200

    server = otel.server_span()
    assert server.attributes is not None
    assert server.attributes["http.method"] == "GET"
    assert server.attributes["http.route"] == "api/test/notes"
    assert server.attributes["http.status_code"] == 200
    assert server.resource.attributes["service.name"] == "knowledge-extractor-api"
    assert server.resource.attributes["deployment.environment"] == "test"
    assert server.resource.attributes["service.version"]

    database = [
        s for s in otel.finished() if s.attributes and "db.system" in s.attributes
    ]
    assert database
    assert all(s.parent is not None for s in database)
    assert {s.context.trace_id for s in database} == {server.context.trace_id}

    data = otel.metrics.get_metrics_data()
    assert data is not None
    names = {
        metric.name
        for resource_metrics in data.resource_metrics
        for scope in resource_metrics.scope_metrics
        for metric in scope.metrics
    }
    assert "http.server.duration" in names
    attributes = data.resource_metrics[0].resource.attributes
    assert attributes["service.name"] == "knowledge-extractor-api"
    assert attributes["deployment.environment"] == "test"


@URLS
@pytest.mark.django_db
def test_the_request_id_is_a_span_attribute(otel: Telemetry) -> None:
    Client().get("/hello", headers={"X-Request-ID": "req-42"})
    assert otel.server_span().attributes["request_id"] == "req-42"  # type: ignore[index]


@URLS
@pytest.mark.django_db
def test_health_and_readiness_leave_no_span(otel: Telemetry) -> None:
    client = Client()
    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/api/v1/ready").status_code == 200
    assert otel.finished() == []
    assert "Server-Timing" not in client.get("/api/v1/health")


# --- logs --------------------------------------------------------------------


@URLS
@pytest.mark.django_db
def test_the_log_line_carries_the_trace_id_of_the_span(
    otel: Telemetry, log_lines: io.StringIO
) -> None:
    Client().get("/hello", headers={"X-Request-ID": "req-7"})
    server = otel.server_span()
    written = [
        line
        for line in lines(log_lines)
        if line["event"] in ("inside_view", "request_finished")
    ]
    assert {line["event"] for line in written} == {"inside_view", "request_finished"}
    for line in written:
        assert line["trace_id"] == f"{server.context.trace_id:032x}"
        assert line["trace_id"] == line["trace_id"].lower()
        assert len(line["span_id"]) == 16
        assert line["trace_flags"] == "01"
        assert line["request_id"] == "req-7"


@URLS
@pytest.mark.django_db
def test_log_lines_outside_a_span_have_no_trace_fields(
    log_lines: io.StringIO,
) -> None:
    Client().get("/hello")
    line = next(x for x in lines(log_lines) if x["event"] == "request_finished")
    assert "trace_id" not in line


# --- trace context -----------------------------------------------------------


@URLS
@pytest.mark.django_db
def test_a_traceparent_header_is_continued_and_answered(otel: Telemetry) -> None:
    response = Client().get("/hello", headers={"traceparent": TRACEPARENT})
    server = otel.server_span()
    assert f"{server.context.trace_id:032x}" == TRACE_ID
    assert server.parent is not None
    assert f"{server.parent.span_id:016x}" == "b7ad6b7169203331"
    header = response["Server-Timing"]
    assert header == (
        f'traceparent;desc="00-{TRACE_ID}-{server.context.span_id:016x}-01"'
    )


@URLS
@pytest.mark.django_db
def test_a_request_without_telemetry_gets_no_server_timing() -> None:
    assert "Server-Timing" not in Client().get("/hello")


def test_cors_lets_trace_headers_in_and_server_timing_out() -> None:
    response = Client().options(
        "/api/v1/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "traceparent, tracestate, baggage",
        },
    )
    allowed = response["Access-Control-Allow-Headers"].lower()
    for name in ("traceparent", "tracestate", "baggage"):
        assert name in allowed
    assert "Server-Timing" in settings.CORS_EXPOSE_HEADERS


# --- what is never recorded --------------------------------------------------


@URLS
@pytest.mark.django_db
def test_no_span_and_no_log_line_holds_a_token_or_a_query_string(
    otel: Telemetry, log_lines: io.StringIO
) -> None:
    secret = "Bearer s3cr3t-token-value"
    ticket = "ticket-abc-123"
    client = APIClient(raise_request_exception=False)
    client.get(
        f"/api/v1/me?ticket={ticket}&page=2",
        headers={"Authorization": secret, "Cookie": "sessionid=cookie-secret"},
    )
    spans = otel.finished()
    assert spans
    for span in spans:
        for value in every_value(span):
            assert "s3cr3t" not in value
            assert ticket not in value
            assert "cookie-secret" not in value
            assert "?" not in value
    assert "s3cr3t" not in log_lines.getvalue()
    assert ticket not in log_lines.getvalue()


@URLS
def test_an_outgoing_call_records_no_query_string(otel: Telemetry) -> None:
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *args: Any) -> None:
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.handle_request)
    thread.start()
    try:
        port = server.server_address[1]
        url = f"http://127.0.0.1:{port}/thing?ticket=abc"
        httpx2.get(url, headers={"Authorization": "Bearer s3cr3t"})
    finally:
        thread.join()
        server.server_close()
    (span,) = otel.finished()
    assert span.kind == SpanKind.CLIENT
    assert span.attributes is not None
    assert str(span.attributes["http.url"]).endswith("/thing")
    for value in every_value(span):
        assert "ticket" not in value
        assert "s3cr3t" not in value


# --- switching it off --------------------------------------------------------


def test_setup_does_nothing_when_the_sdk_is_disabled(settings: Any) -> None:
    settings.OTEL_SDK_DISABLED = True
    assert telemetry.setup_telemetry() is False
    assert not telemetry._installed


PROBE = "from apps.core import telemetry; print(telemetry._installed)"


def _manage(*args: str, **env: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - our own interpreter and manage.py
        [sys.executable, "manage.py", *args],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=settings.BASE_DIR,
        env={
            **os.environ,
            "DJANGO_SETTINGS_MODULE": "config.settings.local",
            **env,
        },
    )


def test_the_app_starts_with_telemetry_off_and_no_collector() -> None:
    result = _manage("shell", "--no-imports", "-c", PROBE, OTEL_SDK_DISABLED="true")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False"


def test_the_app_starts_with_telemetry_on_and_no_collector() -> None:
    result = _manage(
        "shell",
        "--no-imports",
        "-c",
        PROBE,
        OTEL_SDK_DISABLED="false",
        OTEL_EXPORTER_OTLP_ENDPOINT="http://127.0.0.1:1",
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "True"


def test_the_resource_has_the_three_attributes(settings: Any) -> None:
    settings.OTEL_SERVICE_NAME = "svc"
    settings.OTEL_RESOURCE_ATTRIBUTES = "deployment.environment=prod,team=x"
    attributes = telemetry.build_resource().attributes
    assert attributes["service.name"] == "svc"
    assert attributes["deployment.environment"] == "prod"
    assert attributes["team"] == "x"
    assert attributes["service.version"] != ""
