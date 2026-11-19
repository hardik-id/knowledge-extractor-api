"""Fixtures and helpers for tests that look at spans, metrics and log lines.

Registered for every test by the root ``conftest.py``. ``otel`` installs
in-memory exporters; the helpers read what they caught.
"""

import io
import logging
from collections.abc import Callable, Iterator
from contextvars import Context
from dataclasses import dataclass
from typing import Any

import pytest
from django.tasks import task_backends
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from apps.core import telemetry
from apps.core.logging import make_formatter


@dataclass
class Telemetry:
    spans: InMemorySpanExporter
    reader: InMemoryMetricReader
    tracer_provider: TracerProvider
    meter_provider: MeterProvider

    def finished(self) -> list[ReadableSpan]:
        return list(self.spans.get_finished_spans())

    def named(self, name: str) -> list[ReadableSpan]:
        return [span for span in self.finished() if span.name == name]

    def points(self, name: str) -> list[Any]:
        """The data points of metric ``name``: ``value`` for sums, ``count`` for histograms."""
        data = self.reader.get_metrics_data()
        return [
            point
            for resource in (data.resource_metrics if data else [])
            for scope in resource.scope_metrics
            for metric in scope.metrics
            if metric.name == name
            for point in metric.data.data_points
        ]

    def everything(self) -> str:
        """Every name, attribute and value that spans and metrics hold, as one string."""
        parts: list[str] = []

        def add(attributes: Any) -> None:
            parts.extend(
                f"{key}={value!s}" for key, value in (attributes or {}).items()
            )

        for span in self.finished():
            parts += [span.name, str(span.status.description or "")]
            add(span.attributes)
            for event in span.events:
                parts += [event.name]
                add(event.attributes)
            for link in span.links:
                add(link.attributes)
        data = self.reader.get_metrics_data()
        for resource in data.resource_metrics if data else []:
            for scope in resource.scope_metrics:
                for metric in scope.metrics:
                    parts += [metric.name, metric.description or "", metric.unit or ""]
                    for point in metric.data.data_points:
                        add(point.attributes)
        return "\n".join(parts)


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


@pytest.fixture
def log_lines() -> Iterator[Callable[[], str]]:
    """What the root logger writes, in the production JSON format; call it to read."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(make_formatter("json"))
    root = logging.getLogger()
    old_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    try:
        yield stream.getvalue
    finally:
        root.removeHandler(handler)
        root.setLevel(old_level)


@pytest.fixture
def queued(settings: Any) -> Iterator[Callable[[], None]]:
    """Jobs wait in a queue instead of running inline. Call the result to run them.

    Each job runs in an empty context, as a worker process would run it: only
    what the job restored from its arguments can tie it to the request.
    """
    settings.TASKS = {
        "default": {"BACKEND": "django.tasks.backends.dummy.DummyBackend"}
    }
    backend = task_backends["default"]

    def run_all() -> None:
        results = list(backend.results)  # type: ignore[attr-defined]
        backend.results.clear()  # type: ignore[attr-defined]
        for result in results:
            Context().run(result.task.call, *result.args, **result.kwargs)

    yield run_all
