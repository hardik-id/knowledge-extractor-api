"""/api/v1/projects, through the API."""

from typing import Any

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.assistant.tests.factories import MessageFactory
from apps.extraction.tests.factories import DefinitionVersionFactory
from apps.identity.tests.factories import UserFactory
from apps.projects.models import Project
from apps.projects.tests.factories import ProjectFactory
from apps.runs.models import Run
from apps.runs.tests.test_api import item

pytestmark = pytest.mark.django_db

URL = "/api/v1/projects"


@pytest.fixture
def client(api_client: Any, user: Any) -> Any:
    api_client.force_authenticate(user)
    return api_client


def make(client: Any, name: str = "ADRs", **extra: Any) -> dict[str, Any]:
    response = client.post(URL, {"name": name, **extra}, format="json")
    assert response.status_code == 201, response.content
    return dict(response.json())


def test_create_makes_an_empty_run(client: Any) -> None:
    one, two = make(client, "One"), make(client, "Two", description="Why")
    assert one["run_id"] != two["run_id"]
    assert two["description"] == "Why"
    assert one["document_count"] == 0
    assert one["configuration_version"] is None
    run = client.get(f"/api/v1/runs/{one['run_id']}")
    assert run.status_code == 200
    assert run.json()["files"] == []
    assert set(one) == {
        "id",
        "name",
        "description",
        "run_id",
        "document_count",
        "configuration_version",
        "created_at",
        "updated_at",
    }


def test_list_shows_the_last_worked_on_first(client: Any, user: Any) -> None:
    one, two = make(client, "One"), make(client, "Two")
    assert [p["id"] for p in client.get(URL).json()["items"]] == [two["id"], one["id"]]
    MessageFactory(run_id=one["run_id"])
    body = client.get(URL).json()
    assert [p["id"] for p in body["items"]] == [one["id"], two["id"]]
    assert body["next"] is None


def test_activity_follows_documents_definition_and_messages(
    client: Any, user: Any
) -> None:
    from apps.documents import selectors as documents

    one, two = make(client, "One"), make(client, "Two")
    refs = [d.id for d in documents.list_documents(user)[:2]]
    put = client.put(
        f"/api/v1/runs/{one['run_id']}/documents",
        {"items": [item(ref) for ref in refs]},
        format="json",
    )
    assert put.status_code == 200
    DefinitionVersionFactory(run_id=one["run_id"], version=1)
    DefinitionVersionFactory(run_id=one["run_id"], version=2)
    MessageFactory(run_id=one["run_id"])
    body = client.get(URL).json()["items"]
    assert [p["id"] for p in body] == [one["id"], two["id"]]
    assert body[0]["document_count"] == 2
    assert body[0]["configuration_version"] == 2
    assert body[1]["document_count"] == 0
    assert body[0]["updated_at"] > body[1]["updated_at"]


def test_list_pages(client: Any) -> None:
    made = [make(client, f"P{n}")["id"] for n in range(3)]
    first = client.get(URL, {"page_size": 2}).json()
    assert [p["id"] for p in first["items"]] == [made[2], made[1]]
    second = client.get(URL, {"page_size": 2, "cursor": first["next"]}).json()
    assert [p["id"] for p in second["items"]] == [made[0]]
    assert second["next"] is None


def test_list_makes_a_fixed_number_of_queries(client: Any) -> None:
    def count() -> int:
        with CaptureQueriesContext(connection) as queries:
            assert client.get(URL).status_code == 200
        return len(queries)

    make(client)
    one = count()
    for n in range(5):
        make(client, f"P{n}")
    assert count() == one


def test_rename_and_describe(client: Any) -> None:
    project = make(client)
    response = client.patch(
        f"{URL}/{project['id']}", {"name": "Renamed", "description": "d"}, format="json"
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Renamed"
    assert client.get(f"{URL}/{project['id']}").json()["description"] == "d"
    only = client.patch(f"{URL}/{project['id']}", {"name": "Again"}, format="json")
    assert only.json()["description"] == "d"


@pytest.mark.parametrize("name", ["", "   ", "x" * 121, None])
def test_a_bad_name_is_422(client: Any, name: Any) -> None:
    assert client.post(URL, {"name": name}, format="json").status_code == 422
    project = make(client)
    response = client.patch(f"{URL}/{project['id']}", {"name": name}, format="json")
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_a_missing_name_is_422(client: Any) -> None:
    assert client.post(URL, {}, format="json").status_code == 422


def test_delete_removes_the_run(client: Any) -> None:
    project = make(client)
    assert client.delete(f"{URL}/{project['id']}").status_code == 204
    assert client.get(f"{URL}/{project['id']}").status_code == 404
    gone = client.get(f"/api/v1/runs/{project['run_id']}")
    assert gone.status_code == 404
    assert gone.json()["code"] == "run_not_found"
    assert not Project.objects.exists()


def test_the_run_of_a_project_cannot_be_deleted_alone(client: Any) -> None:
    project = make(client)
    response = client.delete(f"/api/v1/runs/{project['run_id']}")
    assert response.status_code == 409
    assert response.json()["code"] == "run_belongs_to_project"
    assert Run.objects.filter(pk=project["run_id"]).exists()
    assert client.get(f"{URL}/{project['id']}").status_code == 200


def test_a_run_without_a_project_still_deletes(client: Any, user: Any) -> None:
    from apps.runs.tests.factories import RunFactory

    run = RunFactory(owner=user)
    assert client.delete(f"/api/v1/runs/{run.pk}").status_code == 204


def test_someone_else_sees_nothing(client: Any) -> None:
    other = UserFactory()
    theirs = ProjectFactory(owner=other)
    assert client.get(URL).json() == {"items": [], "next": None}
    for call in (client.get, client.delete):
        response = call(f"{URL}/{theirs.pk}")
        assert response.status_code == 404
        assert response.json()["code"] == "project_not_found"
    patch = client.patch(f"{URL}/{theirs.pk}", {"name": "x"}, format="json")
    assert patch.status_code == 404
    assert Project.objects.filter(pk=theirs.pk).exists()


def test_an_unknown_id_is_404(client: Any) -> None:
    for pk in ("00000000-0000-0000-0000-000000000000", "nope"):
        response = client.get(f"{URL}/{pk}")
        assert response.status_code == 404
        assert response.json()["code"] == "project_not_found"


def test_without_a_token_is_401(api_client: Any) -> None:
    assert api_client.get(URL).status_code == 401


def test_a_change_to_a_record_moves_the_project_up(client: Any) -> None:
    from apps.extraction.tests.factories import (
        ExtractionFactory,
        ExtractionRecordFactory,
    )
    from apps.runs.tests.factories import RunFileFactory

    one, two = make(client, "One"), make(client, "Two")
    file = RunFileFactory(run_id=one["run_id"])
    record = ExtractionRecordFactory(extraction=ExtractionFactory(file=file))
    assert client.get(URL).json()["items"][0]["id"] == one["id"]
    other = make(client, "Three")
    assert client.get(URL).json()["items"][0]["id"] == other["id"]
    record.save()
    assert client.get(URL).json()["items"][0]["id"] == one["id"]
    assert two["id"] in [p["id"] for p in client.get(URL).json()["items"]]
