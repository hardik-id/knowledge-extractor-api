"""POST /api/v1/runs and /api/v1/runs/{id}, through the API."""

from typing import Any

import pytest

from apps.documents import selectors as documents
from apps.identity.tests.factories import UserFactory
from apps.runs.models import Cell, Run, RunFile

pytestmark = pytest.mark.django_db

URL = "/api/v1/runs"


def item(ref: str, source: str = "storage") -> dict[str, Any]:
    return {
        "source": source,
        "source_ref": ref,
        "name": "lies.md",
        "type": "pdf",
        "size_bytes": 1,
        "location": "nowhere",
        "modified_at": "2000-01-01T00:00:00Z",
    }


@pytest.fixture
def refs(user: Any) -> list[str]:
    return [d.id for d in documents.list_documents(user)[:2]]


def create(api_client: Any, user: Any, items: list[dict[str, Any]]) -> Any:
    api_client.force_authenticate(user)
    return api_client.post(URL, {"items": items}, format="json")


def test_creates_a_run_from_two_documents(
    api_client: Any, user: Any, refs: list[str]
) -> None:
    response = create(api_client, user, [item(r) for r in refs])
    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"id", "created_at", "files", "cells"}
    assert len(body["files"]) == 2
    assert {f["source_ref"] for f in body["files"]} == set(refs)
    for f in body["files"]:
        assert f["id"] and f["etag"] and f["source"] == "storage"
        # facts come from the catalog, not from the request
        assert f["name"] != "lies.md" and f["type"] == "md"
    assert {c["file_id"] for c in body["cells"]} == {f["id"] for f in body["files"]}
    for c in body["cells"]:
        assert c["stage"] == "extract" and c["status"] == "pending"
        assert set(c) == {
            "file_id",
            "stage",
            "status",
            "execution_id",
            "progress",
            "error",
            "output",
            "updated_at",
        }
        assert c["execution_id"] is None and c["output"] is None
        assert c["updated_at"].endswith("Z") or "+" in c["updated_at"]
    assert Run.objects.get().owner == user


@pytest.mark.parametrize(
    ("sources", "code"),
    [
        ([], "no_files"),
        (["storage", "upload"], "mixed_sources"),
        (["upload", "confluence"], "unsupported_source"),
    ],
)
def test_refusals(
    api_client: Any, user: Any, refs: list[str], sources: list[str], code: str
) -> None:
    items = [item(refs[0], s) for s in sources]
    response = create(api_client, user, items)
    assert response.status_code == 422
    assert response.json()["code"] == code
    assert not Run.objects.exists()


def test_missing_items_is_422(api_client: Any, user: Any) -> None:
    api_client.force_authenticate(user)
    response = api_client.post(URL, {}, format="json")
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_unknown_document_is_404(api_client: Any, user: Any, refs: list[str]) -> None:
    response = create(api_client, user, [item(refs[0]), item("nope/x.md")])
    assert response.status_code == 404
    assert response.json()["code"] == "document_not_found"
    assert not Run.objects.exists()


def test_get_returns_the_same_run(api_client: Any, user: Any, refs: list[str]) -> None:
    created = create(api_client, user, [item(r) for r in refs]).json()
    response = api_client.get(f"{URL}/{created['id']}")
    assert response.status_code == 200
    assert response.json() == created


def test_someone_elses_and_unknown_runs_are_404(
    api_client: Any, user: Any, refs: list[str]
) -> None:
    created = create(api_client, user, [item(refs[0])]).json()
    api_client.force_authenticate(UserFactory())
    for run_id in (created["id"], "0197a000-0000-7000-8000-000000000000", "nonsense"):
        for method in (api_client.get, api_client.delete):
            response = method(f"{URL}/{run_id}")
            assert response.status_code == 404
            assert response.json()["code"] == "run_not_found"
    assert Run.objects.count() == 1


def test_delete_removes_everything(api_client: Any, user: Any, refs: list[str]) -> None:
    created = create(api_client, user, [item(r) for r in refs]).json()
    assert api_client.delete(f"{URL}/{created['id']}").status_code == 204
    response = api_client.get(f"{URL}/{created['id']}")
    assert response.status_code == 404
    assert response.json()["code"] == "run_not_found"
    assert not RunFile.objects.exists()
    assert not Cell.objects.exists()


def test_without_a_token_is_401(api_client: Any) -> None:
    for response in (
        api_client.post(URL, {}, format="json"),
        api_client.get(f"{URL}/x"),
    ):
        assert response.status_code == 401
        assert response.json()["code"] == "unauthenticated"
