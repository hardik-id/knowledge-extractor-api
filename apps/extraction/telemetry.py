"""The span and metrics of an extraction job (docs/observability.md).

Never recorded here: the document's text, the prompt, the definition, the
records or their values. Only ids, counts, the kind of extractor and outcomes.
"""

import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from opentelemetry import metrics
from opentelemetry.trace import Span

from apps.core import telemetry

SCOPE = "apps.extraction"

# How an extraction job ended.
SUCCEEDED = "succeeded"  # the records are stored
FAILED = "failed"  # the cell is failed, the records are as they were
SKIPPED = "skipped"  # nothing to do: the cell no longer belongs to this execution


@dataclass(frozen=True)
class _Instruments:
    files: metrics.Counter
    duration: metrics.Histogram


@lru_cache
def _instruments(provider: metrics.MeterProvider) -> _Instruments:
    meter = provider.get_meter(SCOPE)
    return _Instruments(
        files=meter.create_counter(
            "extraction.files",
            unit="{file}",
            description="Extraction jobs finished, by outcome and kind of extractor.",
        ),
        duration=meter.create_histogram(
            "extraction.file.duration",
            unit="s",
            description="How long an extraction job took, by outcome and kind of extractor.",
        ),
    )


class FileTrace:
    """What one extraction job did, collected for its span and its metrics."""

    def __init__(self, span: Span, extractor: str) -> None:
        self.span = span
        self.extractor = extractor
        self.outcome = SUCCEEDED
        self.records: int | None = None

    def started(self, run_id: Any) -> None:
        self.span.set_attribute("extraction.run_id", str(run_id))

    def failed(self, error: BaseException) -> None:
        self.outcome = FAILED
        telemetry.fail_span(self.span, error)


@contextmanager
def file_span(
    file_id: Any, definition_version: int, extractor: str
) -> Iterator[FileTrace]:
    """The `extraction.file` span of one extraction job, and its metrics when it ends."""
    started = time.perf_counter()
    tracer = telemetry.get_tracer(SCOPE)
    with tracer.start_as_current_span(
        "extraction.file",
        attributes={
            "extraction.file_id": str(file_id),
            "extraction.definition_version": definition_version,
            "extraction.extractor": extractor,
        },
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        file = FileTrace(span, extractor)
        try:
            yield file
        except BaseException as error:
            file.failed(error)
            raise
        finally:
            span.set_attribute("extraction.outcome", file.outcome)
            if file.records is not None:
                span.set_attribute("extraction.records", file.records)
            attributes = {"outcome": file.outcome, "extractor": extractor}
            instruments = _instruments(telemetry.meter_provider())
            instruments.files.add(1, attributes)
            instruments.duration.record(time.perf_counter() - started, attributes)
