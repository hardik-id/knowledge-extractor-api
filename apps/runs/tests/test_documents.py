"""PUT /api/v1/runs/{id}/documents and create_empty_run."""

from typing import Any

import pytest

from apps.assistant.models import Message
from apps.assistant.tests.factories import MessageFactory
from apps.documents import selectors as documents
from apps.extraction.models import DefinitionVersion, ExtractionRecord
from apps.extraction.tests.factories import (
    DefinitionVersionFactory,
    ExtractionFactory,
    ExtractionRecordFactory,
)
from apps.identity.tests.factories import UserFactory
from apps.runs import services
from apps.runs.models import Cell, CellStatus, Run, RunFile
from apps.runs.tests.test_api import create, item

pytestmark = pytest.mark.django_db

URL = "/api/v1/runs"


@pytest.fixture
def refs(user: Any) -> list[str]:
    return [d.id for d in documents.list_documents(user)[:3]]


def put(api_client: Any, run_id: Any, items: list[dict[str, Any]]) -> Any:
    return api_client.put(f"{URL}/{run_id}/documents", {"items": items}, format="json")


def test_create_empty_run(user: Any) -> None:
    run = services.create_empty_run(user)
    assert run.owner == user
    assert not run.files.exists()


def test_post_still_refuses_an_empty_list(api_client: Any, user: Any) -> None:
    response = create(api_client, user, [])
    assert response.status_code == 422
    assert response.json()["code"] == "no_files"


def test_a_change_removes_keeps_and_adds(
    api_client: Any, user: Any, refs: list[str]
) -> None:
    a, b, c = refs
    run_id = create(api_client, user, [item(a), item(b)]).json()["id"]
    run = Run.objects.get(pk=run_id)
    file_a, file_b = (run.files.get(source_ref=r) for r in (a, b))
    DefinitionVersionFactory(run=run)
    MessageFactory(run=run)
    for f in (file_a, file_b):
        ExtractionRecordFactory(extraction=ExtractionFactory(file=f))
    cell_b = Cell.objects.get(file=file_b)
    cell_b.status = CellStatus.SUCCEEDED
    cell_b.save()
    versions = list(DefinitionVersion.objects.values_list("pk", "version"))
    messages = list(Message.objects.values_list("pk", "text"))
    record_b = ExtractionRecord.objects.get(extraction__file=file_b)

    response = put(api_client, run_id, [item(b), item(c)])

    assert response.status_code == 200
    body = response.json()
    assert {f["source_ref"] for f in body["files"]} == {b, c}
    assert not RunFile.objects.filter(pk=file_a.pk).exists()
    assert not Cell.objects.filter(file_id=file_a.pk).exists()
    assert ExtractionRecord.objects.count() == 1
    assert ExtractionRecord.objects.get().pk == record_b.pk
    kept = next(f for f in body["files"] if f["source_ref"] == b)
    assert kept["id"] == str(file_b.pk)
    cells = {c_["file_id"]: c_ for c_ in body["cells"]}
    assert cells[kept["id"]]["status"] == "succeeded"
    new = next(f for f in body["files"] if f["source_ref"] == c)
    assert cells[new["id"]]["status"] == "pending"
    assert list(DefinitionVersion.objects.values_list("pk", "version")) == versions
    assert list(Message.objects.values_list("pk", "text")) == messages
    assert api_client.get(f"{URL}/{run_id}").json() == body


def test_an_empty_list_leaves_no_files(
    api_client: Any, user: Any, refs: list[str]
) -> None:
    run_id = create(api_client, user, [item(refs[0])]).json()["id"]
    response = put(api_client, run_id, [])
    assert response.status_code == 200
    assert response.json()["files"] == [] and response.json()["cells"] == []
    assert Run.objects.filter(pk=run_id).exists()


def test_the_same_checks_as_create(api_client: Any, user: Any, refs: list[str]) -> None:
    run_id = create(api_client, user, [item(refs[0])]).json()["id"]
    twice = put(api_client, run_id, [item(refs[1]), item(refs[1])])
    assert twice.status_code == 422 and twice.json()["code"] == "validation_error"
    gone = put(api_client, run_id, [item(refs[1]), item("nope/x.md")])
    assert gone.status_code == 404 and gone.json()["code"] == "document_not_found"
    mixed = put(api_client, run_id, [item(refs[1]), item(refs[2], "upload")])
    assert mixed.status_code == 422 and mixed.json()["code"] == "mixed_sources"
    other = put(api_client, run_id, [item(refs[1], "upload")])
    assert other.json()["code"] == "unsupported_source"
    # nothing changed
    assert [f.source_ref for f in RunFile.objects.all()] == [refs[0]]


@pytest.mark.parametrize("status", [CellStatus.QUEUED, CellStatus.RUNNING])
def test_during_an_execution_is_409(
    api_client: Any, user: Any, refs: list[str], status: str
) -> None:
    run_id = create(api_client, user, [item(refs[0]), item(refs[1])]).json()["id"]
    cell = Cell.objects.filter(file__run_id=run_id).first()
    assert cell is not None
    cell.status = status
    cell.execution_id = "x1"
    cell.save()
    response = put(api_client, run_id, [item(refs[2])])
    assert response.status_code == 409
    assert response.json()["code"] == "execution_in_progress"
    assert RunFile.objects.filter(run_id=run_id).count() == 2


def test_someone_elses_run_is_404(api_client: Any, user: Any, refs: list[str]) -> None:
    run_id = create(api_client, user, [item(refs[0])]).json()["id"]
    api_client.force_authenticate(UserFactory())
    response = put(api_client, run_id, [])
    assert response.status_code == 404
    assert response.json()["code"] == "run_not_found"
    assert RunFile.objects.filter(run_id=run_id).count() == 1


def test_without_a_token_is_401(api_client: Any) -> None:
    assert put(api_client, "x", []).status_code == 401
