"""POST, PATCH and DELETE under .../extraction/records, through the API."""

import threading
from typing import Any

import pytest
from django.db import connection
from rest_framework.test import APIClient

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
TITLE, STATUS, APPROVED = "f-adr-title", "f-adr-status", "f-adr-approved-by"


def base(file: Any) -> str:
    return f"/api/v1/runs/{file.run_id}/files/{file.pk}/extraction"


def text() -> str:
    return read_document(UserFactory.build(), ADR).text


def span(quote: str) -> dict[str, Any]:
    start = text().index(quote)
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
def published(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Any, dict[str, Any]]]:
    """A recording publisher: what was announced, and for which run."""
    events: list[tuple[Any, dict[str, Any]]] = []
    monkeypatch.setattr(
        realtime,
        "publish_run_event",
        lambda run_id, event: events.append((run_id, event)),
    )
    return events


def new_record(revision: int = 0, **extra: Any) -> dict[str, Any]:
    return {
        "revision": revision,
        "record_type_id": "rt-adr",
        "span": None,
        "fields": [],
        **extra,
    }


def stored(file: Any, **extra: Any) -> Any:
    extraction = ExtractionFactory(file=file, revision=3)
    return extraction, ExtractionRecordFactory(extraction=extraction, **extra)


# --- add -------------------------------------------------------------------


def test_a_first_add_makes_the_extraction_at_revision_1(
    client: Any, file: Any, published: list[Any]
) -> None:
    title = span("## ADR")
    body = new_record(
        span=title,
        fields=[
            {"field_id": TITLE, "values": [{"value": title["quote"], "spans": [title]}]}
        ],
    )
    response = client.post(f"{base(file)}/records", body, format="json")
    assert response.status_code == 200, response.json()
    data = response.json()
    assert data["revision"] == 1
    assert data["file_id"] == str(file.pk)
    assert data["definition_version"] == 1
    assert data["source_etag"]
    [rec] = data["records"]
    assert (rec["origin"], rec["review"]) == ("human", "accepted")
    assert rec["span"] == title
    [field] = [f for f in rec["fields"] if f["field_id"] == TITLE]
    assert (field["origin"], field["review"], field["anchored"]) == (
        "human",
        "accepted",
        True,
    )
    assert field["spans"] == [title]
    other = [f for f in rec["fields"] if f["field_id"] != TITLE]
    assert all(f["value"] is None for f in other)
    assert published == [
        (
            file.run_id,
            {"type": "extraction.changed", "file_id": str(file.pk), "revision": 1},
        )
    ]


def test_fields_left_out_store_nothing_and_an_empty_list_is_not_found(
    client: Any, file: Any
) -> None:
    body = new_record(fields=[{"field_id": STATUS, "values": []}])
    assert client.post(f"{base(file)}/records", body, format="json").status_code == 200
    [value] = FieldValue.objects.all()
    assert (value.field_id, value.value, value.origin, value.review) == (
        STATUS,
        None,
        Origin.HUMAN,
        Review.ACCEPTED,
    )


def test_a_second_add_raises_the_revision(client: Any, file: Any) -> None:
    client.post(f"{base(file)}/records", new_record(0), format="json")
    response = client.post(f"{base(file)}/records", new_record(1), format="json")
    assert response.status_code == 200
    assert response.json()["revision"] == 2
    assert len(response.json()["records"]) == 2


def test_a_multiple_field_takes_several_values(client: Any, file: Any) -> None:
    values = [{"value": "Ana", "spans": []}, {"value": "Ben", "spans": []}]
    body = new_record(fields=[{"field_id": APPROVED, "values": values}])
    response = client.post(f"{base(file)}/records", body, format="json")
    [rec] = response.json()["records"]
    assert [f["value"] for f in rec["fields"] if f["field_id"] == APPROVED] == [
        "Ana",
        "Ben",
    ]


def test_a_first_add_needs_revision_0(
    client: Any, file: Any, published: list[Any]
) -> None:
    response = client.post(f"{base(file)}/records", new_record(2), format="json")
    assert response.status_code == 409
    assert response.json()["code"] == "revision_conflict"
    assert response.json()["details"] == {"revision": 0}
    assert not Extraction.objects.exists()
    assert published == []


def test_a_first_add_without_text_is_not_ready(
    client: Any, user: Any, published: list[Any]
) -> None:
    run = RunFactory(owner=user)
    DefinitionVersionFactory(run=run)
    nothing = RunFileFactory(run=run, source_ref="enriched/no-such-file.md")
    response = client.post(f"{base(nothing)}/records", new_record(0), format="json")
    assert response.status_code == 422
    assert response.json()["code"] == "upstream_not_ready"
    assert not Extraction.objects.exists()
    assert published == []


def test_an_unknown_record_type_or_field_is_422(
    client: Any, file: Any, published: list[Any]
) -> None:
    for body in (
        new_record(record_type_id="rt-nope"),
        new_record(fields=[{"field_id": "f-nope", "values": []}]),
    ):
        response = client.post(f"{base(file)}/records", body, format="json")
        assert response.status_code == 422
        assert response.json()["code"] == "unknown_field"
    assert not Extraction.objects.exists()
    assert published == []


def test_a_span_that_does_not_match_is_422_and_nothing_is_kept(
    client: Any, file: Any, published: list[Any]
) -> None:
    wrong = {"start": 0, "end": 4, "quote": "nope"}
    body = new_record(
        fields=[{"field_id": TITLE, "values": [{"value": "x", "spans": [wrong]}]}]
    )
    response = client.post(f"{base(file)}/records", body, format="json")
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_span"
    response = client.post(
        f"{base(file)}/records", new_record(span=wrong), format="json"
    )
    assert response.json()["code"] == "invalid_span"
    assert not Extraction.objects.exists()
    assert published == []


def test_two_values_for_a_single_field_is_422(client: Any, file: Any) -> None:
    values = [{"value": "a", "spans": []}, {"value": "b", "spans": []}]
    body = new_record(fields=[{"field_id": TITLE, "values": values}])
    response = client.post(f"{base(file)}/records", body, format="json")
    assert response.status_code == 422
    assert response.json()["code"] == "too_many_values"


def test_a_bad_body_is_422(client: Any, file: Any) -> None:
    response = client.post(
        f"{base(file)}/records", {"record_type_id": "rt-adr"}, format="json"
    )
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_an_add_to_an_old_revision_is_409(
    client: Any, file: Any, published: list[Any]
) -> None:
    stored(file)
    response = client.post(f"{base(file)}/records", new_record(2), format="json")
    assert response.status_code == 409
    assert response.json()["code"] == "revision_conflict"
    assert response.json()["details"] == {"revision": 3}
    assert published == []


# --- change ----------------------------------------------------------------


def test_only_the_keys_sent_change(
    client: Any, file: Any, published: list[Any]
) -> None:
    quote = span("ADR")
    _, record = stored(file, span=quote)
    url = f"{base(file)}/records/{record.pk}"
    response = client.patch(url, {"revision": 3, "use_as_example": True}, format="json")
    assert response.status_code == 200
    data = response.json()
    assert data["revision"] == 4
    [rec] = data["records"]
    assert rec["use_as_example"] is True
    assert rec["span"] == quote
    assert rec["review"] == "suggested"
    response = client.patch(url, {"revision": 4, "span": None}, format="json")
    [rec] = response.json()["records"]
    assert rec["span"] is None
    assert rec["use_as_example"] is True
    response = client.patch(url, {"revision": 5, "span": quote}, format="json")
    assert response.json()["records"][0]["span"] == quote
    assert [event["revision"] for _, event in published] == [4, 5, 6]


def test_accepting_a_record_accepts_its_suggested_values(
    client: Any, file: Any
) -> None:
    _, record = stored(file)
    FieldValueFactory(record=record, field_id=TITLE, review="suggested")
    FieldValueFactory(record=record, field_id=STATUS, review="rejected")
    FieldValueFactory(
        record=record, field_id=APPROVED, review="suggested", origin="human"
    )
    response = client.patch(
        f"{base(file)}/records/{record.pk}",
        {"revision": 3, "review": "accepted"},
        format="json",
    )
    assert response.status_code == 200
    [rec] = response.json()["records"]
    assert rec["review"] == "accepted"
    reviews = {f["field_id"]: f["review"] for f in rec["fields"] if f["value"]}
    assert reviews == {TITLE: "accepted", STATUS: "rejected", APPROVED: "accepted"}


def test_rejecting_does_not_touch_the_values(client: Any, file: Any) -> None:
    _, record = stored(file)
    FieldValueFactory(record=record, field_id=TITLE, review="suggested")
    response = client.patch(
        f"{base(file)}/records/{record.pk}",
        {"revision": 3, "review": "rejected"},
        format="json",
    )
    [rec] = response.json()["records"]
    assert rec["review"] == "rejected"
    [title] = [f for f in rec["fields"] if f["field_id"] == TITLE]
    assert title["review"] == "suggested"


def test_a_patch_with_a_bad_span_is_422(
    client: Any, file: Any, published: list[Any]
) -> None:
    _, record = stored(file)
    response = client.patch(
        f"{base(file)}/records/{record.pk}",
        {"revision": 3, "span": {"start": 0, "end": 3, "quote": "zzz"}},
        format="json",
    )
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_span"
    assert published == []


def test_a_patch_with_an_unknown_review_is_422(client: Any, file: Any) -> None:
    _, record = stored(file)
    response = client.patch(
        f"{base(file)}/records/{record.pk}",
        {"revision": 3, "review": "maybe"},
        format="json",
    )
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


# --- delete ----------------------------------------------------------------


def test_a_person_can_delete_a_record_they_added(
    client: Any, file: Any, published: list[Any]
) -> None:
    added = client.post(f"{base(file)}/records", new_record(0), format="json").json()
    record_id = added["records"][0]["id"]
    response = client.delete(f"{base(file)}/records/{record_id}?revision=1")
    assert response.status_code == 200
    assert response.json()["records"] == []
    assert response.json()["revision"] == 2
    assert [event["revision"] for _, event in published] == [1, 2]


def test_a_suggestion_is_not_deletable(
    client: Any, file: Any, published: list[Any]
) -> None:
    _, record = stored(file)
    response = client.delete(f"{base(file)}/records/{record.pk}?revision=3")
    assert response.status_code == 422
    assert response.json()["code"] == "not_deletable"
    assert Extraction.objects.get().revision == 3
    assert published == []


def test_delete_needs_a_revision(client: Any, file: Any) -> None:
    _, record = stored(file, origin="human")
    response = client.delete(f"{base(file)}/records/{record.pk}")
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


# --- the shared rules ------------------------------------------------------


@pytest.mark.parametrize("method", ["patch", "delete"])
def test_an_unknown_record_is_404(client: Any, file: Any, method: str) -> None:
    stored(file)
    other = "01900000-0000-7000-8000-000000000000"
    for record_id in (other, "not-a-uuid"):
        url = f"{base(file)}/records/{record_id}"
        if method == "patch":
            response = client.patch(url, {"revision": 3}, format="json")
        else:
            response = client.delete(f"{url}?revision=3")
        assert response.status_code == 404
        assert response.json()["code"] == "record_not_found"


def test_a_record_of_another_file_is_404(client: Any, file: Any, user: Any) -> None:
    _, record = stored(file)
    other = RunFileFactory(run=file.run, source_ref=ADR)
    ExtractionFactory(file=other, revision=1)
    response = client.patch(
        f"{base(other)}/records/{record.pk}", {"revision": 1}, format="json"
    )
    assert response.status_code == 404
    assert response.json()["code"] == "record_not_found"


@pytest.mark.parametrize("method", ["patch", "delete"])
def test_without_an_extraction_it_is_404(
    client: Any, file: Any, published: list[Any], method: str
) -> None:
    url = f"{base(file)}/records/01900000-0000-7000-8000-000000000000"
    if method == "patch":
        response = client.patch(url, {"revision": 1}, format="json")
    else:
        response = client.delete(f"{url}?revision=1")
    assert response.status_code == 404
    assert response.json()["code"] == "extraction_not_found"
    assert published == []


def test_an_old_revision_is_409_with_the_current_one(
    client: Any, file: Any, published: list[Any]
) -> None:
    _, record = stored(file)
    response = client.patch(
        f"{base(file)}/records/{record.pk}",
        {"revision": 2, "review": "accepted"},
        format="json",
    )
    assert response.status_code == 409
    assert response.json()["code"] == "revision_conflict"
    assert response.json()["details"] == {"revision": 3}
    assert published == []


def test_a_file_that_is_not_in_the_run_is_404(client: Any, file: Any) -> None:
    url = f"/api/v1/runs/{file.run_id}/files/{RunFileFactory().pk}/extraction/records"
    assert client.post(url, new_record(), format="json").status_code == 404
    assert (
        client.post(url, new_record(), format="json").json()["code"] == "file_not_found"
    )


def test_another_persons_run_is_404(file: Any) -> None:
    client = APIClient()
    client.force_authenticate(UserFactory())
    response = client.post(f"{base(file)}/records", new_record(), format="json")
    assert response.status_code == 404
    assert response.json()["code"] == "run_not_found"


def test_signing_in_is_required(file: Any) -> None:
    assert (
        APIClient()
        .post(f"{base(file)}/records", new_record(), format="json")
        .status_code
        == 401
    )


def test_the_event_goes_out_after_the_commit(
    client: Any,
    file: Any,
    monkeypatch: pytest.MonkeyPatch,
    django_capture_on_commit_callbacks: Any,
) -> None:
    sent: list[tuple[str, dict[str, Any]]] = []

    class Recorder:
        async def group_send(self, group: str, message: dict[str, Any]) -> None:
            sent.append((group, message))

    monkeypatch.setattr(realtime, "get_channel_layer", lambda: Recorder())
    with django_capture_on_commit_callbacks(execute=True):
        client.post(f"{base(file)}/records", new_record(0), format="json")
    assert sent == [
        (
            realtime.run_group(file.run_id),
            {
                "type": "run.event",
                "event": {
                    "type": "extraction.changed",
                    "file_id": str(file.pk),
                    "revision": 1,
                },
            },
        )
    ]


# --- two writes at once ----------------------------------------------------


def race(file: Any, user: Any, calls: list[Any]) -> list[int]:
    """Send every call at the same moment, each on its own connection."""
    start = threading.Barrier(len(calls))
    statuses: list[int] = [0] * len(calls)

    def run(index: int) -> None:
        try:
            client = APIClient()
            client.force_authenticate(user)
            start.wait()
            statuses[index] = calls[index](client).status_code
        finally:
            connection.close()

    threads = [threading.Thread(target=run, args=(i,)) for i in range(len(calls))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return statuses


@pytest.mark.django_db(transaction=True)
def test_two_first_adds_at_once_give_one_200_and_one_409(
    file: Any, user: Any, published: list[Any]
) -> None:
    add = lambda client: client.post(  # noqa: E731
        f"{base(file)}/records", new_record(0), format="json"
    )
    assert sorted(race(file, user, [add, add])) == [200, 409]
    extraction = Extraction.objects.get()
    assert extraction.revision == 1
    assert extraction.records.count() == 1
    assert len(published) == 1


@pytest.mark.django_db(transaction=True)
def test_two_writes_with_one_revision_at_once_give_one_200_and_one_409(
    file: Any, user: Any, published: list[Any]
) -> None:
    _, record = stored(file)
    patch = lambda client: client.patch(  # noqa: E731
        f"{base(file)}/records/{record.pk}",
        {"revision": 3, "use_as_example": True},
        format="json",
    )
    assert sorted(race(file, user, [patch, patch, patch])) == [200, 409, 409]
    assert Extraction.objects.get().revision == 4
    assert len(published) == 1
