"""The extraction job's span and metrics (docs/observability.md)."""

from collections.abc import Callable
from typing import Any

import pytest
from opentelemetry.trace import SpanKind, StatusCode

from apps.core.tests.otel import Telemetry
from apps.extraction import services
from apps.extraction.models import ExtractionRecord
from apps.extraction.tests.factories import DefinitionVersionFactory
from apps.extraction.tests.test_executions import (
    ADR,
    HERE,
    RaisingExtractor,  # noqa: F401  (named by path in a setting)
    ReleasingExtractor,  # noqa: F401  (named by path in a setting)
    text,
    url,
)
from apps.runs.tests.factories import CellFactory, RunFactory, RunFileFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def client(api_client: Any, user: Any) -> Any:
    api_client.force_authenticate(user)
    return api_client


@pytest.fixture
def file(user: Any) -> Any:
    run = RunFactory(owner=user)
    DefinitionVersionFactory(run=run)
    return CellFactory(file=RunFileFactory(run=run, source_ref=ADR)).file


def start(client: Any, file: Any, capture: Any) -> str:
    """POST the execution and commit; the extraction job waits in the queue."""
    with capture(execute=True):
        response = client.post(url(file.run_id), {}, format="json")
    assert response.status_code == 202, response.json()
    return str(response.json()["execution_id"])


def test_an_extraction_is_one_trace_across_the_request_and_the_job(
    client: Any,
    file: Any,
    otel: Telemetry,
    queued: Callable[[], None],
    django_capture_on_commit_callbacks: Any,
) -> None:
    start(client, file, django_capture_on_commit_callbacks)
    assert otel.named("extraction.file") == [], "the job has not run yet"

    queued()  # a worker: an empty context, only the stored trace context to go on

    (server,) = [s for s in otel.finished() if s.kind == SpanKind.SERVER]
    (job,) = otel.named("extraction.file")
    assert job.context.trace_id == server.context.trace_id
    assert job.parent is not None and job.parent.is_remote
    found = ExtractionRecord.objects.filter(extraction__file=file).count()
    assert found > 0
    assert job.attributes == {
        "extraction.file_id": str(file.pk),
        "extraction.run_id": str(file.run_id),
        "extraction.definition_version": 1,
        "extraction.extractor": "scripted",
        "extraction.records": found,
        "extraction.outcome": "succeeded",
    }
    assert job.status.status_code != StatusCode.ERROR


def test_extractions_are_counted_by_outcome_and_timed(
    client: Any,
    file: Any,
    otel: Telemetry,
    queued: Callable[[], None],
    django_capture_on_commit_callbacks: Any,
) -> None:
    start(client, file, django_capture_on_commit_callbacks)
    queued()

    (count,) = otel.points("extraction.files")
    assert count.value == 1
    assert dict(count.attributes) == {"outcome": "succeeded", "extractor": "scripted"}
    (timing,) = otel.points("extraction.file.duration")
    assert timing.count == 1
    assert timing.sum >= 0


def test_a_failing_extractor_ends_the_span_failed_with_the_error_type_only(
    client: Any,
    file: Any,
    otel: Telemetry,
    settings: Any,
    queued: Callable[[], None],
    django_capture_on_commit_callbacks: Any,
) -> None:
    settings.EXTRACTOR = f"{HERE}.RaisingExtractor"
    start(client, file, django_capture_on_commit_callbacks)
    queued()

    (job,) = otel.named("extraction.file")
    assert job.attributes is not None
    assert job.attributes["extraction.outcome"] == "failed"
    assert job.attributes["extraction.extractor"] == "RaisingExtractor"
    assert job.attributes["error.type"] == "RuntimeError"
    assert "extraction.records" not in job.attributes
    assert job.status.status_code == StatusCode.ERROR
    assert not job.status.description
    assert job.events == ()
    (count,) = otel.points("extraction.files")
    assert dict(count.attributes) == {
        "outcome": "failed",
        "extractor": "RaisingExtractor",
    }
    assert "the model is down" not in otel.everything()


def test_a_job_whose_cell_is_gone_is_a_skipped_span(
    client: Any,
    file: Any,
    otel: Telemetry,
    queued: Callable[[], None],
    django_capture_on_commit_callbacks: Any,
) -> None:
    start(client, file, django_capture_on_commit_callbacks)
    file.run.delete()
    queued()

    (job,) = otel.named("extraction.file")
    assert job.attributes is not None
    assert job.attributes["extraction.outcome"] == "skipped"
    assert "extraction.run_id" not in job.attributes
    (count,) = otel.points("extraction.files")
    assert dict(count.attributes)["outcome"] == "skipped"


def test_a_cell_released_while_the_extractor_works_is_a_skipped_span(
    client: Any, file: Any, otel: Telemetry, settings: Any
) -> None:
    execution_id = client.post(url(file.run_id), {}, format="json").json()[
        "execution_id"
    ]
    otel.spans.clear()
    settings.EXTRACTOR = f"{HERE}.ReleasingExtractor"

    services.run_extraction(str(file.pk), execution_id, 1)

    (job,) = otel.named("extraction.file")
    assert job.attributes is not None
    assert job.attributes["extraction.outcome"] == "skipped"
    assert "extraction.records" not in job.attributes


def test_no_span_metric_or_log_line_holds_document_text_or_a_prompt(
    client: Any,
    file: Any,
    otel: Telemetry,
    log_lines: Callable[[], str],
    settings: Any,
    queued: Callable[[], None],
    django_capture_on_commit_callbacks: Any,
) -> None:
    start(client, file, django_capture_on_commit_callbacks)
    queued()
    settings.EXTRACTOR = f"{HERE}.RaisingExtractor"
    start(client, file, django_capture_on_commit_callbacks)
    queued()

    version = file.run.definition_versions.get()
    names = [
        thing["name"]
        for record_type in version.record_types
        for thing in [record_type, *record_type["fields"]]
    ]
    forbidden = [version.prompt, *text().splitlines(), *names]
    forbidden = [f for f in forbidden if len(f) >= 12]
    assert len(forbidden) > 10
    assert len(otel.named("extraction.file")) == 2

    caught = otel.everything() + "\n" + log_lines()
    for item in forbidden:
        assert item not in caught, item
