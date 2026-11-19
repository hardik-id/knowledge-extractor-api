"""PUT .../records/{id}/fields/{id} and PATCH .../records/{id}/values/{id}, through the API."""

from typing import Any

import pytest

from apps.documents.selectors import read_document
from apps.extraction.models import Extraction, FieldValue, Origin, Review
from apps.extraction.tests.factories import (
    DefinitionVersionFactory,
    ExtractionFactory,
    ExtractionRecordFactory,
    FieldValueFactory,
)
from apps.identity.tests.factories import UserFactory
from apps.realtime import services as realtime
from apps.runs.tests.factories import RunFactory, RunFileFactory

pytestmark = pytest.mark.django_db

ADR = "enriched/engineering/architecture/platform-adrs.md"
TITLE, APPROVED = "f-adr-title", "f-adr-approved-by"  # APPROVED takes several values
GHOST = "01900000-0000-7000-8000-000000000000"


def base(file: Any) -> str:
    return f"/api/v1/runs/{file.run_id}/files/{file.pk}/extraction"


def span(quote: str) -> dict[str, Any]:
    start = read_document(UserFactory.build(), ADR).text.index(quote)
    return {"start": start, "end": start + len(quote), "quote": quote}


@pytest.fixture
def client(api_client: Any, user: Any) -> Any:
    api_client.force_authenticate(user)
    return api_client


@pytest.fixture
def file(user: Any) -> Any:
    run = RunFactory(owner=user)
    DefinitionVersionFactory(run=run)
    return RunFileFactory(run=run, source_ref=ADR)


@pytest.fixture
def published(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    events: list[Any] = []
    monkeypatch.setattr(
        realtime, "publish_run_event", lambda run_id, event: events.append(event)
    )
    return events


@pytest.fixture
def record(file: Any) -> Any:
    extraction = ExtractionFactory(file=file, revision=3)
    return ExtractionRecordFactory(extraction=extraction)


def put(client: Any, file: Any, record: Any, field: str, **body: Any) -> Any:
    return client.put(
        f"{base(file)}/records/{record.pk}/fields/{field}",
        {"revision": 3, **body},
        format="json",
    )


def patch(client: Any, file: Any, record: Any, value_id: Any, **body: Any) -> Any:
    return client.patch(
        f"{base(file)}/records/{record.pk}/values/{value_id}",
        {"revision": 3, **body},
        format="json",
    )


def values_of(data: dict[str, Any], field: str) -> list[dict[str, Any]]:
    return [f for f in data["records"][0]["fields"] if f["field_id"] == field]


# --- PUT -------------------------------------------------------------------


def test_new_values_are_human_and_accepted_and_the_old_are_gone(
    client: Any, file: Any, record: Any, published: list[Any]
) -> None:
    FieldValueFactory(record=record, field_id=TITLE, value="Old")
    title = span("## ADR")
    response = put(
        client, file, record, TITLE, values=[{"value": "New", "spans": [title]}]
    )
    assert response.status_code == 200, response.json()
    data = response.json()
    assert data["revision"] == 4
    [value] = values_of(data, TITLE)
    assert (value["value"], value["spans"]) == ("New", [title])
    assert (value["origin"], value["review"], value["anchored"]) == (
        "human",
        "accepted",
        True,
    )
    assert FieldValue.objects.filter(field_id=TITLE).count() == 1
    assert published == [
        {"type": "extraction.changed", "file_id": str(file.pk), "revision": 4}
    ]


def test_values_sent_back_unchanged_keep_id_origin_and_review(
    client: Any, file: Any, record: Any
) -> None:
    quote = span("## ADR")
    kept = [
        FieldValueFactory(
            record=record,
            field_id=APPROVED,
            value=name,
            spans=[quote] if i == 0 else [],
        )
        for i, name in enumerate(["Ann", "Bob"])
    ]
    response = put(
        client,
        file,
        record,
        APPROVED,
        values=[
            {"value": "Ann", "spans": [quote]},
            {"value": "Bob", "spans": []},
        ],
    )
    assert response.status_code == 200
    data = response.json()
    assert data["revision"] == 4
    got = values_of(data, APPROVED)
    assert [v["id"] for v in got] == [str(v.pk) for v in kept]
    assert all((v["origin"], v["review"]) == ("llm", "suggested") for v in got)


def test_one_value_of_a_list_can_be_added_or_removed(
    client: Any, file: Any, record: Any
) -> None:
    ann = FieldValueFactory(record=record, field_id=APPROVED, value="Ann")
    bob = FieldValueFactory(record=record, field_id=APPROVED, value="Bob")
    added = put(
        client,
        file,
        record,
        APPROVED,
        values=[{"value": v, "spans": []} for v in ("Ann", "Bob", "Cy")],
    ).json()
    got = values_of(added, APPROVED)
    assert [v["value"] for v in got] == ["Ann", "Bob", "Cy"]
    assert [v["review"] for v in got] == ["suggested", "suggested", "accepted"]
    assert {got[0]["id"], got[1]["id"]} == {str(ann.pk), str(bob.pk)}
    removed = client.put(
        f"{base(file)}/records/{record.pk}/fields/{APPROVED}",
        {"revision": 4, "values": [{"value": "Bob", "spans": []}]},
        format="json",
    ).json()
    [only] = values_of(removed, APPROVED)
    assert only["id"] == str(bob.pk)
    assert removed["revision"] == 5


def test_an_empty_list_resets_the_field_to_not_found(
    client: Any, file: Any, record: Any
) -> None:
    FieldValueFactory(record=record, field_id=APPROVED, value="Ann")
    FieldValueFactory(record=record, field_id=APPROVED, value="Bob")
    data = put(client, file, record, APPROVED, values=[]).json()
    [value] = values_of(data, APPROVED)
    assert value["value"] is None
    assert value["spans"] == []
    assert (value["origin"], value["review"]) == ("human", "accepted")
    assert not value["id"].startswith(f"{record.pk}:")  # stored, not made up
    assert FieldValue.objects.filter(field_id=APPROVED).count() == 1


def test_a_single_field_with_two_values_is_422_and_nothing_changes(
    client: Any, file: Any, record: Any, published: list[Any]
) -> None:
    FieldValueFactory(record=record, field_id=TITLE, value="Old")
    response = put(
        client,
        file,
        record,
        TITLE,
        values=[{"value": "a", "spans": []}, {"value": "b", "spans": []}],
    )
    assert response.status_code == 422
    assert response.json()["code"] == "too_many_values"
    assert Extraction.objects.get().revision == 3
    assert FieldValue.objects.get().value == "Old"
    assert published == []


def test_a_bad_span_is_422_and_nothing_changes(
    client: Any, file: Any, record: Any
) -> None:
    FieldValueFactory(record=record, field_id=TITLE, value="Old")
    bad = {"start": 0, "end": 3, "quote": "nope"}
    response = put(client, file, record, TITLE, values=[{"value": "x", "spans": [bad]}])
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_span"
    assert FieldValue.objects.get().value == "Old"
    assert Extraction.objects.get().revision == 3


def test_an_unknown_field_is_422(client: Any, file: Any, record: Any) -> None:
    response = put(client, file, record, "f-nope", values=[])
    assert response.status_code == 422
    assert response.json()["code"] == "unknown_field"


def test_a_bad_body_is_422(client: Any, file: Any, record: Any) -> None:
    response = put(client, file, record, TITLE, values="x")
    assert response.status_code == 422


def test_put_on_an_unknown_record_is_404(client: Any, file: Any, record: Any) -> None:
    response = client.put(
        f"{base(file)}/records/{GHOST}/fields/{TITLE}",
        {"revision": 3, "values": []},
        format="json",
    )
    assert (response.status_code, response.json()["code"]) == (404, "record_not_found")


def test_put_with_an_old_revision_is_409(client: Any, file: Any, record: Any) -> None:
    response = put(client, file, record, TITLE, values=[], revision=2)
    assert response.status_code == 409
    assert response.json()["code"] == "revision_conflict"
    assert response.json()["details"] == {"revision": 3}


# --- PATCH -----------------------------------------------------------------


@pytest.mark.parametrize("review", ["accepted", "rejected"])
def test_a_value_is_accepted_or_rejected(
    client: Any, file: Any, record: Any, review: str, published: list[Any]
) -> None:
    value = FieldValueFactory(record=record, field_id=TITLE)
    other = FieldValueFactory(record=record, field_id=APPROVED)
    response = patch(client, file, record, value.pk, review=review)
    assert response.status_code == 200, response.json()
    assert response.json()["revision"] == 4
    value.refresh_from_db()
    other.refresh_from_db()
    assert value.review == review
    assert value.origin == Origin.LLM
    assert other.review == Review.SUGGESTED
    assert len(published) == 1


def test_an_unknown_value_is_404(client: Any, file: Any, record: Any) -> None:
    for value_id in (GHOST, "not-a-uuid", f"{record.pk}:{TITLE}"):
        response = patch(client, file, record, value_id, review="accepted")
        assert (response.status_code, response.json()["code"]) == (
            404,
            "value_not_found",
        )


def test_a_value_of_another_record_is_404(client: Any, file: Any, record: Any) -> None:
    other = ExtractionRecordFactory(extraction=record.extraction)
    value = FieldValueFactory(record=other, field_id=TITLE)
    response = patch(client, file, record, value.pk, review="accepted")
    assert response.json()["code"] == "value_not_found"


def test_a_bad_review_is_422(client: Any, file: Any, record: Any) -> None:
    value = FieldValueFactory(record=record, field_id=TITLE)
    assert patch(client, file, record, value.pk, review="maybe").status_code == 422


def test_patch_with_an_old_revision_is_409(client: Any, file: Any, record: Any) -> None:
    value = FieldValueFactory(record=record, field_id=TITLE)
    response = patch(client, file, record, value.pk, review="accepted", revision=1)
    assert response.status_code == 409
    assert response.json()["code"] == "revision_conflict"
    value.refresh_from_db()
    assert value.review == Review.SUGGESTED
