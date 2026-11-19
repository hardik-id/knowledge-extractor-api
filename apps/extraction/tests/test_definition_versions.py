"""The versions of the definition: list, read one, restore one, and the note."""

from typing import Any

import pytest

from apps.extraction.models import DefinitionVersion
from apps.identity.tests.factories import UserFactory
from apps.runs.tests.factories import RunFactory

pytestmark = pytest.mark.django_db


def url(run: Any, tail: str = "") -> str:
    return f"/api/v1/runs/{run.pk}/stages/extract/definition{tail}"


@pytest.fixture
def run(user: Any) -> Any:
    return RunFactory(owner=user)


@pytest.fixture
def client(api_client: Any, user: Any) -> Any:
    api_client.force_authenticate(user)
    return api_client


def save(client: Any, run: Any, **changes: Any) -> dict[str, Any]:
    current = client.get(url(run)).json()
    draft = {k: current[k] for k in ("prompt", "record_types", "output")}
    response = client.put(
        url(run),
        {"base_version": current["version"], **draft, **changes},
        format="json",
    )
    assert response.status_code == 200, response.json()
    data: dict[str, Any] = response.json()
    return data


@pytest.fixture
def three(client: Any, run: Any) -> Any:
    save(client, run, prompt="Second.")
    save(client, run, prompt="Third.", note="Tighter prompt")
    return run


def test_list_has_newest_first_with_notes_and_counts(client: Any, three: Any) -> None:
    response = client.get(url(three, "/versions"))
    assert response.status_code == 200
    items = response.json()["items"]
    assert [i["version"] for i in items] == [3, 2, 1]
    assert [i["note"] for i in items] == ["Tighter prompt", "", ""]
    for item in items:
        assert item["created_at"]
        assert item["record_type_count"] == 1
        assert item["field_count"] == 6


def test_a_save_answers_note_and_created_at(client: Any, run: Any) -> None:
    first = client.get(url(run)).json()
    assert first["note"] == ""
    assert first["created_at"]
    saved = save(client, run, note="Why")
    assert saved["note"] == "Why"
    assert client.get(url(run)).json()["note"] == "Why"


def test_read_one_version(client: Any, three: Any) -> None:
    one = client.get(url(three, "/versions/1"))
    assert one.status_code == 200
    assert one.json()["version"] == 1
    assert one.json()["record_types"][0]["name"] == "ADR"
    assert client.get(url(three, "/versions/2")).json()["prompt"] == "Second."


def test_reading_version_one_of_a_fresh_run_gives_the_default(
    client: Any, run: Any
) -> None:
    response = client.get(url(run, "/versions/1"))
    assert response.status_code == 200
    assert response.json()["version"] == 1


def test_unknown_version_is_404(client: Any, three: Any) -> None:
    response = client.get(url(three, "/versions/9"))
    assert response.status_code == 404
    assert response.json()["code"] == "definition_version_not_found"
    restore = client.post(url(three, "/versions/9/restore"))
    assert restore.status_code == 404
    assert restore.json()["code"] == "definition_version_not_found"


def test_restore_copies_a_version_as_the_newest(client: Any, three: Any) -> None:
    before = list(DefinitionVersion.objects.filter(run=three).order_by("version"))
    response = client.post(url(three, "/versions/1/restore"))
    assert response.status_code == 200
    data = response.json()
    assert data["version"] == 4
    assert data["prompt"] == before[0].prompt
    assert data["record_types"] == before[0].record_types
    assert data["note"] == "Restored from version 1"
    assert client.get(url(three)).json()["version"] == 4
    after = list(DefinitionVersion.objects.filter(run=three).order_by("version"))
    assert len(after) == 4
    for old, same in zip(before, after, strict=False):
        assert (old.pk, old.prompt, old.note, old.record_types) == (
            same.pk,
            same.prompt,
            same.note,
            same.record_types,
        )


def test_a_long_note_is_422(client: Any, run: Any) -> None:
    current = client.get(url(run)).json()
    draft = {k: current[k] for k in ("prompt", "record_types", "output")}
    ok = client.put(
        url(run), {"base_version": 1, **draft, "note": "x" * 200}, format="json"
    )
    assert ok.status_code == 200
    response = client.put(
        url(run), {"base_version": 2, **draft, "note": "x" * 201}, format="json"
    )
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_definition"


def test_someone_elses_run_is_404_everywhere(api_client: Any, three: Any) -> None:
    api_client.force_authenticate(UserFactory())
    calls = [
        api_client.get(url(three, "/versions")),
        api_client.get(url(three, "/versions/1")),
        api_client.post(url(three, "/versions/1/restore")),
    ]
    assert [c.status_code for c in calls] == [404, 404, 404]
    assert {c.json()["code"] for c in calls} == {"run_not_found"}


def test_signed_out_is_401(api_client: Any, run: Any) -> None:
    assert api_client.get(url(run, "/versions")).status_code == 401
    assert api_client.get(url(run, "/versions/1")).status_code == 401
    assert api_client.post(url(run, "/versions/1/restore")).status_code == 401
