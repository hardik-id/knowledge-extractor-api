"""POST .../stages/extract/executions and the job it enqueues, through the API."""

from collections.abc import Sequence
from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.documents.selectors import read_document
from apps.extraction import services
from apps.extraction.extractors.base import Definition, RawRecord, RawValue
from apps.extraction.models import Extraction, ExtractionRecord
from apps.extraction.tests.factories import DefinitionVersionFactory
from apps.identity.tests.factories import UserFactory
from apps.realtime import services as realtime
from apps.runs.models import Cell, CellStatus
from apps.runs.tests.factories import CellFactory, RunFactory, RunFileFactory

pytestmark = pytest.mark.django_db

ADR = "enriched/engineering/architecture/platform-adrs.md"
TITLE = "f-adr-title"
HERE = "apps.extraction.tests.test_executions"


def text() -> str:
    return read_document(UserFactory.build(), ADR).text


def url(run_id: Any, stage: str = "extract") -> str:
    return f"/api/v1/runs/{run_id}/stages/{stage}/executions"


def extraction_url(file: Any) -> str:
    return f"/api/v1/runs/{file.run_id}/files/{file.pk}/extraction"


@pytest.fixture
def client(api_client: Any, user: Any) -> Any:
    api_client.force_authenticate(user)
    return api_client


@pytest.fixture
def run(user: Any) -> Any:
    run = RunFactory(owner=user)
    DefinitionVersionFactory(run=run)
    return run


@pytest.fixture
def file(run: Any) -> Any:
    return CellFactory(file=RunFileFactory(run=run, source_ref=ADR)).file


@pytest.fixture
def published(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """A recording publisher: every event announced on a run socket, in order."""
    events: list[dict[str, Any]] = []
    monkeypatch.setattr(
        realtime, "publish_run_event", lambda _run_id, event: events.append(event)
    )
    return events


def execute(
    client: Any, run_id: Any, capture: Any, body: dict[str, Any] | None = None
) -> Any:
    """POST an execution and run what it queued, as the worker would."""
    with capture(execute=True):
        return client.post(url(run_id), body or {}, format="json")


def cell_of(file: Any) -> Cell:
    return Cell.objects.get(file=file, stage="extract")


# --- a run ------------------------------------------------------------------


def test_a_run_extracts_the_file_and_announces_every_step(
    client: Any,
    file: Any,
    published: list[dict[str, Any]],
    django_capture_on_commit_callbacks: Any,
) -> None:
    response = execute(
        client,
        file.run_id,
        django_capture_on_commit_callbacks,
        {"config": {"definition_version": 1}},
    )
    assert response.status_code == 202, response.json()
    execution = response.json()
    assert execution["stage"] == "extract"
    assert execution["file_ids"] == [str(file.pk)]
    execution_id = execution["execution_id"]

    statuses = [
        e["cell"]["status"] if e["type"] == "cell" else e["type"] for e in published
    ]
    assert statuses == ["queued", "running", "succeeded", "extraction.changed"]
    assert all(
        e["cell"]["execution_id"] == execution_id
        for e in published
        if e["type"] == "cell"
    )
    assert published[-1] == {
        "type": "extraction.changed",
        "file_id": str(file.pk),
        "revision": 1,
    }
    done = published[2]["cell"]
    assert done["error"] is None
    output = done["output"]
    assert output["etag"] == f"extract-{execution_id}"
    assert output["content_type"] == "application/json"
    assert output["name"] == f"{file.name.removesuffix('.md')}.extract.json"
    assert output["size"] > 0

    data = client.get(extraction_url(file)).json()
    assert data["revision"] == 1
    assert data["definition_version"] == 1
    assert data["source_etag"] == read_document(UserFactory.build(), ADR).etag
    assert len(data["records"]) >= 2
    source = text()
    for record in data["records"]:
        assert (record["origin"], record["review"]) == ("llm", "suggested")
        assert record["record_type_id"] == "rt-adr"
        span = record["span"]
        assert source[span["start"] : span["end"]] == span["quote"]
        for value in record["fields"]:
            assert (value["origin"], value["review"]) == ("llm", "suggested")
            for quoted in value["spans"]:
                assert source[quoted["start"] : quoted["end"]] == quoted["quote"]

    snapshot = client.get(f"/api/v1/runs/{file.run_id}").json()
    [cell] = snapshot["cells"]
    assert cell == done


def test_the_ui_spelling_of_the_version_is_accepted(
    client: Any, file: Any, django_capture_on_commit_callbacks: Any
) -> None:
    response = execute(
        client,
        file.run_id,
        django_capture_on_commit_callbacks,
        {"config": {"definitionVersion": 1}},
    )
    assert response.status_code == 202, response.json()
    assert cell_of(file).status == CellStatus.SUCCEEDED


def test_without_file_ids_every_file_of_the_run_runs(
    client: Any, run: Any, file: Any, django_capture_on_commit_callbacks: Any
) -> None:
    second = CellFactory(file=RunFileFactory(run=run, source_ref=ADR)).file
    response = execute(client, run.pk, django_capture_on_commit_callbacks)
    assert response.status_code == 202
    assert response.json()["file_ids"] == sorted([str(file.pk), str(second.pk)])
    assert {cell_of(f).status for f in (file, second)} == {CellStatus.SUCCEEDED}


def test_only_the_chosen_files_run(
    client: Any, run: Any, file: Any, django_capture_on_commit_callbacks: Any
) -> None:
    other = CellFactory(file=RunFileFactory(run=run, source_ref=ADR)).file
    response = execute(
        client,
        run.pk,
        django_capture_on_commit_callbacks,
        {"file_ids": [str(file.pk), str(file.pk)]},
    )
    assert response.json()["file_ids"] == [str(file.pk)]
    assert cell_of(file).status == CellStatus.SUCCEEDED
    assert cell_of(other).status == CellStatus.PENDING


def test_a_new_execution_has_a_new_output_etag(
    client: Any, file: Any, django_capture_on_commit_callbacks: Any
) -> None:
    execute(client, file.run_id, django_capture_on_commit_callbacks)
    first = cell_of(file).output
    execute(client, file.run_id, django_capture_on_commit_callbacks)
    second = cell_of(file).output
    assert first is not None and second is not None
    assert first["etag"] != second["etag"]
    assert Extraction.objects.get(file=file).revision == 2


# --- a person's work survives --------------------------------------------------


def test_a_run_again_keeps_what_a_person_did(
    client: Any, file: Any, django_capture_on_commit_callbacks: Any
) -> None:
    execute(client, file.run_id, django_capture_on_commit_callbacks)
    records = client.get(extraction_url(file)).json()["records"]
    accepted, rejected, *untouched = records
    assert untouched
    client.patch(
        f"{extraction_url(file)}/records/{accepted['id']}",
        {"revision": 1, "review": "accepted"},
        format="json",
    )
    client.patch(
        f"{extraction_url(file)}/records/{rejected['id']}",
        {"revision": 2, "review": "rejected"},
        format="json",
    )
    added = client.post(
        f"{extraction_url(file)}/records",
        {"revision": 3, "record_type_id": "rt-adr", "span": None, "fields": []},
        format="json",
    ).json()["records"]
    [human] = [r for r in added if r["origin"] == "human"]

    response = execute(client, file.run_id, django_capture_on_commit_callbacks)
    assert response.status_code == 202
    after = client.get(extraction_url(file)).json()
    assert after["revision"] == 5
    by_id = {r["id"]: r for r in after["records"]}
    assert by_id[accepted["id"]]["review"] == "accepted"
    assert by_id[rejected["id"]]["review"] == "rejected"
    assert by_id[human["id"]]["origin"] == "human"
    # the untouched suggestions are replaced: same places, new records
    old_ids = {r["id"] for r in untouched}
    fresh = [r for r in after["records"] if r["review"] == "suggested"]
    assert fresh
    assert not old_ids & {r["id"] for r in fresh}
    assert sorted(r["span"]["start"] for r in fresh) == sorted(
        r["span"]["start"] for r in untouched
    )
    # neither the accepted nor the rejected one is suggested again
    for kept in (accepted, rejected):
        same_place = [r for r in after["records"] if r["span"] == kept["span"]]
        assert [r["id"] for r in same_place] == [kept["id"]]


def test_the_runs_example_records_reach_the_extractor(
    client: Any,
    file: Any,
    settings: Any,
    django_capture_on_commit_callbacks: Any,
) -> None:
    execute(client, file.run_id, django_capture_on_commit_callbacks)
    record = ExtractionRecord.objects.filter(extraction__file=file).first()
    assert record is not None
    record.review = "accepted"
    record.use_as_example = True
    record.save()
    settings.EXTRACTOR = f"{HERE}.RecordingExtractor"
    RecordingExtractor.seen = []
    execute(client, file.run_id, django_capture_on_commit_callbacks)
    [examples] = RecordingExtractor.seen
    [example] = examples
    assert (example.record_type_id, example.span) == (
        record.record_type_id,
        record.span,
    )
    assert {v.field_id for v in example.values} == set(
        record.values.values_list("field_id", flat=True)
    )


class RecordingExtractor:
    seen: list[Sequence[RawRecord]] = []

    def extract(
        self, text: str, definition: Definition, examples: Sequence[RawRecord] = ()
    ) -> list[RawRecord]:
        RecordingExtractor.seen.append(list(examples))
        return [RawRecord("rt-adr", None, [RawValue(TITLE, "x")])]


# --- refusals -----------------------------------------------------------------


def test_a_file_already_queued_is_409(client: Any, file: Any) -> None:
    first = client.post(url(file.run_id), {}, format="json")  # the job never runs
    assert first.status_code == 202
    assert cell_of(file).status == CellStatus.QUEUED
    response = client.post(url(file.run_id), {}, format="json")
    assert response.status_code == 409
    assert response.json()["code"] == "execution_in_progress"
    assert response.json()["details"] == {"execution_id": first.json()["execution_id"]}


def test_a_running_file_is_409(client: Any, file: Any) -> None:
    Cell.objects.filter(file=file).update(status="running", execution_id="e1")
    response = client.post(url(file.run_id), {}, format="json")
    assert response.status_code == 409
    assert response.json()["code"] == "execution_in_progress"


def test_a_version_that_is_not_the_latest_is_409(
    client: Any, run: Any, file: Any
) -> None:
    DefinitionVersionFactory(run=run, version=2)
    response = client.post(
        url(run.pk), {"config": {"definition_version": 1}}, format="json"
    )
    assert response.status_code == 409
    assert response.json()["code"] == "definition_conflict"
    assert response.json()["details"] == {"version": 2}
    assert cell_of(file).status == CellStatus.PENDING  # nothing was queued


@pytest.mark.parametrize(
    "file_ids", [["not-a-uuid"], ["01900000-0000-7000-8000-000000000000"], []]
)
def test_a_file_that_is_not_in_the_run_is_422(
    client: Any, file: Any, file_ids: list[str]
) -> None:
    response = client.post(url(file.run_id), {"file_ids": file_ids}, format="json")
    assert response.status_code == 422
    assert response.json()["code"] == "unknown_file"


def test_a_file_of_another_run_is_422(client: Any, user: Any, file: Any) -> None:
    other = CellFactory(file=RunFileFactory(run=RunFactory(owner=user))).file
    response = client.post(
        url(file.run_id), {"file_ids": [str(other.pk)]}, format="json"
    )
    assert response.status_code == 422
    assert response.json()["code"] == "unknown_file"


def test_another_stage_is_404(client: Any, file: Any) -> None:
    response = client.post(url(file.run_id, "index"), {}, format="json")
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_someone_elses_run_is_404(client: Any) -> None:
    other = RunFactory()
    CellFactory(file=RunFileFactory(run=other, source_ref=ADR))
    response = client.post(url(other.pk), {}, format="json")
    assert response.status_code == 404
    assert response.json()["code"] == "run_not_found"


def test_a_bad_body_is_422(client: Any, file: Any) -> None:
    response = client.post(
        url(file.run_id), {"config": {"definition_version": "x"}}, format="json"
    )
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_without_a_token_is_401(file: Any) -> None:
    assert APIClient().post(url(file.run_id), {}, format="json").status_code == 401


# --- failures -----------------------------------------------------------------


class RaisingExtractor:
    def extract(self, *_args: Any, **_kwargs: Any) -> list[RawRecord]:
        raise RuntimeError("the model is down")


def test_an_extractor_that_raises_fails_the_cell_and_can_run_again(
    client: Any,
    file: Any,
    settings: Any,
    published: list[dict[str, Any]],
    django_capture_on_commit_callbacks: Any,
) -> None:
    settings.EXTRACTOR = f"{HERE}.RaisingExtractor"
    response = execute(client, file.run_id, django_capture_on_commit_callbacks)
    assert response.status_code == 202
    cell = cell_of(file)
    assert cell.status == CellStatus.FAILED
    assert cell.error == {
        "code": "extraction_failed",
        "message": "The extraction failed.",
    }
    assert "model is down" not in str(published)
    assert not Extraction.objects.filter(file=file).exists()
    assert not any(e["type"] == "extraction.changed" for e in published)

    settings.EXTRACTOR = "scripted"
    again = execute(client, file.run_id, django_capture_on_commit_callbacks)
    assert again.status_code == 202
    assert cell_of(file).status == CellStatus.SUCCEEDED
    assert cell_of(file).error is None


def test_a_failure_leaves_the_earlier_records_as_they_were(
    client: Any,
    file: Any,
    settings: Any,
    django_capture_on_commit_callbacks: Any,
) -> None:
    execute(client, file.run_id, django_capture_on_commit_callbacks)
    before = client.get(extraction_url(file)).json()
    settings.EXTRACTOR = f"{HERE}.RaisingExtractor"
    execute(client, file.run_id, django_capture_on_commit_callbacks)
    assert cell_of(file).status == CellStatus.FAILED
    assert client.get(extraction_url(file)).json() == before


def test_a_storage_failure_stores_nothing(
    client: Any,
    file: Any,
    monkeypatch: pytest.MonkeyPatch,
    django_capture_on_commit_callbacks: Any,
) -> None:
    def broken(*_args: Any) -> None:
        raise RuntimeError("disk full")

    monkeypatch.setattr(services, "_store", broken)
    execute(client, file.run_id, django_capture_on_commit_callbacks)
    assert cell_of(file).status == CellStatus.FAILED
    assert not Extraction.objects.filter(file=file).exists()


def test_a_missing_document_fails_with_upstream_not_ready(
    client: Any, run: Any, django_capture_on_commit_callbacks: Any
) -> None:
    file = CellFactory(file=RunFileFactory(run=run, source_ref="gone.md")).file
    execute(client, run.pk, django_capture_on_commit_callbacks)
    cell = cell_of(file)
    assert cell.status == CellStatus.FAILED
    assert cell.error is not None
    assert cell.error["code"] == "upstream_not_ready"


# --- a job whose cell moved on ------------------------------------------------


def test_a_job_whose_cell_belongs_to_another_execution_does_nothing(
    client: Any, file: Any, published: list[dict[str, Any]]
) -> None:
    client.post(url(file.run_id), {}, format="json")  # queued, job not run
    queued = cell_of(file)
    published.clear()
    services.run_extraction(str(file.pk), "another-execution", 1)
    assert cell_of(file).status == CellStatus.QUEUED
    assert cell_of(file).updated_at == queued.updated_at
    assert not Extraction.objects.filter(file=file).exists()
    assert published == []


def test_a_job_for_a_released_cell_does_nothing(client: Any, file: Any) -> None:
    execution_id = client.post(url(file.run_id), {}, format="json").json()[
        "execution_id"
    ]
    Cell.objects.filter(file=file).update(status="failed")
    services.run_extraction(str(file.pk), execution_id, 1)
    assert cell_of(file).status == CellStatus.FAILED
    assert not Extraction.objects.filter(file=file).exists()


def test_a_job_for_a_deleted_run_does_nothing(client: Any, file: Any) -> None:
    execution_id = client.post(url(file.run_id), {}, format="json").json()[
        "execution_id"
    ]
    file_id = str(file.pk)
    file.run.delete()
    services.run_extraction(file_id, execution_id, 1)
    assert not Extraction.objects.exists()


def test_a_cell_that_stopped_belonging_while_running_stores_nothing(
    client: Any, file: Any, settings: Any
) -> None:
    execution_id = client.post(url(file.run_id), {}, format="json").json()[
        "execution_id"
    ]
    settings.EXTRACTOR = f"{HERE}.ReleasingExtractor"
    services.run_extraction(str(file.pk), execution_id, 1)
    assert cell_of(file).status == CellStatus.FAILED
    assert cell_of(file).error == {"code": "execution_timeout", "message": "late"}
    assert not Extraction.objects.filter(file=file).exists()


class ReleasingExtractor:
    """Takes so long that the cell is released while it works."""

    def extract(self, *_args: Any, **_kwargs: Any) -> list[RawRecord]:
        Cell.objects.update(
            status="failed", error={"code": "execution_timeout", "message": "late"}
        )
        return []


# --- the timeout --------------------------------------------------------------


def stick(file: Any, status: str, seconds_ago: int) -> None:
    Cell.objects.filter(file=file).update(
        status=status,
        execution_id="dead-worker",
        updated_at=timezone.now() - timedelta(seconds=seconds_ago),
    )


def test_a_stuck_running_cell_is_released_at_the_snapshot(
    client: Any, file: Any, settings: Any, published: list[dict[str, Any]]
) -> None:
    settings.EXECUTION_TIMEOUT_SECONDS = 60
    stick(file, "running", 61)
    [cell] = client.get(f"/api/v1/runs/{file.run_id}").json()["cells"]
    assert cell["status"] == "failed"
    assert cell["execution_id"] == "dead-worker"
    assert cell["error"]["code"] == "execution_timeout"
    assert [e["cell"]["status"] for e in published] == ["failed"]


def test_a_stuck_queued_cell_is_released_at_the_next_execution(
    client: Any, file: Any, settings: Any, django_capture_on_commit_callbacks: Any
) -> None:
    settings.EXECUTION_TIMEOUT_SECONDS = 60
    stick(file, "queued", 61)
    response = execute(client, file.run_id, django_capture_on_commit_callbacks)
    assert response.status_code == 202, response.json()
    assert cell_of(file).status == CellStatus.SUCCEEDED


def test_a_cell_within_the_timeout_is_left_alone(
    client: Any, file: Any, settings: Any
) -> None:
    settings.EXECUTION_TIMEOUT_SECONDS = 60
    stick(file, "running", 30)
    [cell] = client.get(f"/api/v1/runs/{file.run_id}").json()["cells"]
    assert cell["status"] == "running"
    assert client.post(url(file.run_id), {}, format="json").status_code == 409
