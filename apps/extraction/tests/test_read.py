"""GET /api/v1/runs/{run_id}/files/{file_id}/extraction, through the API."""

from typing import Any

import pytest
from rest_framework.test import APIClient

from apps.extraction import selectors
from apps.extraction.defaults import DEFAULT_RECORD_TYPES
from apps.extraction.tests.factories import (
    DefinitionVersionFactory,
    ExtractionFactory,
    ExtractionRecordFactory,
    FieldValueFactory,
)
from apps.identity.tests.factories import UserFactory
from apps.runs.tests.factories import RunFactory, RunFileFactory

pytestmark = pytest.mark.django_db

ADR = "enriched/engineering/architecture/platform-adrs.md"
FIELDS = [f["id"] for f in DEFAULT_RECORD_TYPES[0]["fields"]]


def url(file: Any) -> str:
    return f"/api/v1/runs/{file.run_id}/files/{file.pk}/extraction"


@pytest.fixture
def client(api_client: Any, user: Any) -> Any:
    api_client.force_authenticate(user)
    return api_client


@pytest.fixture
def file(user: Any) -> Any:
    run = RunFactory(owner=user)
    DefinitionVersionFactory(run=run)
    return RunFileFactory(run=run, source_ref=ADR)


def test_records_are_served_in_the_wire_shape(client: Any, file: Any) -> None:
    extraction = ExtractionFactory(
        file=file, revision=4, source_etag="e1", definition_version=1
    )
    quote = {"start": 361, "end": 369, "quote": "Accepted"}
    record = ExtractionRecordFactory(
        extraction=extraction,
        span={"start": 310, "end": 1422, "quote": "## ADR"},
        use_as_example=True,
    )
    value = FieldValueFactory(
        record=record, field_id="f-adr-status", value="accepted", spans=[quote]
    )
    response = client.get(url(file))
    assert response.status_code == 200
    data = response.json()
    assert set(data) == {
        "file_id",
        "revision",
        "source_etag",
        "definition_version",
        "records",
    }
    assert (data["file_id"], data["revision"], data["source_etag"]) == (
        str(file.pk),
        4,
        "e1",
    )
    assert data["definition_version"] == 1
    [rec] = data["records"]
    assert set(rec) == {
        "id",
        "file_id",
        "record_type_id",
        "span",
        "origin",
        "review",
        "use_as_example",
        "fields",
    }
    assert rec["file_id"] == str(file.pk)
    assert rec["span"] == {"start": 310, "end": 1422, "quote": "## ADR"}
    assert (rec["origin"], rec["review"], rec["use_as_example"]) == (
        "llm",
        "suggested",
        True,
    )
    [status] = [f for f in rec["fields"] if f["field_id"] == "f-adr-status"]
    assert status == {
        "id": str(value.pk),
        "field_id": "f-adr-status",
        "value": "accepted",
        "spans": [quote],
        "origin": "llm",
        "review": "suggested",
        "anchored": True,
    }


def test_fields_without_a_value_come_back_as_null(client: Any, file: Any) -> None:
    record = ExtractionRecordFactory(extraction=ExtractionFactory(file=file), span=None)
    FieldValueFactory(record=record, field_id="f-adr-title", value="Use Postgres")
    [rec] = client.get(url(file)).json()["records"]
    assert rec["span"] is None
    assert [f["field_id"] for f in rec["fields"]] == FIELDS
    empty = [f for f in rec["fields"] if f["field_id"] != "f-adr-title"]
    assert len(empty) == len(FIELDS) - 1
    for field in empty:
        assert field["value"] is None
        assert field["spans"] == []
        assert isinstance(field["id"], str)
        assert field["anchored"] is True


def test_a_multiple_field_has_one_value_per_value(client: Any, file: Any) -> None:
    record = ExtractionRecordFactory(extraction=ExtractionFactory(file=file))
    for name in ("Ana", "Ben"):
        FieldValueFactory(record=record, field_id="f-adr-approved-by", value=name)
    [rec] = client.get(url(file)).json()["records"]
    approved = [
        f["value"] for f in rec["fields"] if f["field_id"] == "f-adr-approved-by"
    ]
    assert approved == ["Ana", "Ben"]


def test_an_unanchored_value_is_served_as_stored(client: Any, file: Any) -> None:
    record = ExtractionRecordFactory(extraction=ExtractionFactory(file=file))
    made_up = {"start": 0, "end": 7, "quote": "invented"}
    FieldValueFactory(
        record=record, field_id="f-adr-title", spans=[made_up], anchored=False
    )
    [rec] = client.get(url(file)).json()["records"]
    [title] = [f for f in rec["fields"] if f["field_id"] == "f-adr-title"]
    assert title["anchored"] is False
    assert title["spans"] == [made_up]


def test_before_the_first_extraction_is_404(client: Any, file: Any) -> None:
    response = client.get(url(file))
    assert response.status_code == 404
    assert response.json()["code"] == "extraction_not_found"


def test_someone_elses_run_is_404_run_not_found(client: Any) -> None:
    other = RunFileFactory(run=RunFactory(owner=UserFactory()))
    ExtractionFactory(file=other)
    response = client.get(url(other))
    assert response.status_code == 404
    assert response.json()["code"] == "run_not_found"


def test_an_unknown_file_is_404_file_not_found(client: Any, file: Any) -> None:
    response = client.get(f"/api/v1/runs/{file.run_id}/files/not-a-file/extraction")
    assert response.status_code == 404
    assert response.json()["code"] == "file_not_found"


def test_signed_out_is_401(file: Any) -> None:
    assert APIClient().get(url(file)).status_code == 401


def test_get_extraction_and_input_text(user: Any, file: Any) -> None:
    extraction = ExtractionFactory(file=file)
    assert selectors.get_extraction(user, file.run_id, file.pk) == extraction
    document = selectors.input_text(file)
    assert "ADR-101" in document.text
    assert document.etag
