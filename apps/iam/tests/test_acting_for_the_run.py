"""Jobs and the assistant act for the run, not for a person (task 5 of #488).

The person who made the workspace is no member any more; another person owns it,
and an editor works in it. The extraction job and the assistant's run view read
the run they were given, through nobody's workspace role.
"""

from typing import Any

import pytest
from asgiref.sync import async_to_sync
from rest_framework.test import APIClient

from apps.assistant.selectors import run_view_of
from apps.assistant.services import APOLOGY
from apps.assistant.tests.test_scripted import adr
from apps.documents import selectors as documents
from apps.extraction.definition import Draft
from apps.extraction.tests.factories import DefinitionVersionFactory
from apps.iam.models import WorkspaceMembership
from apps.iam.roles import WorkspaceRole
from apps.identity.tests.factories import UserFactory
from apps.runs.models import Cell, CellStatus
from apps.runs.tests.factories import CellFactory, RunFileFactory
from apps.workspaces.tests.factories import WorkspaceFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def setting() -> dict[str, Any]:
    workspace = WorkspaceFactory()
    maker = workspace.owner
    document = documents.list_documents(maker)[0]
    file = RunFileFactory(run=workspace.run, source_ref=document.id)
    CellFactory(file=file)
    DefinitionVersionFactory(run=workspace.run)
    WorkspaceMembership.objects.filter(workspace=workspace, user=maker).delete()
    for role in (WorkspaceRole.OWNER, WorkspaceRole.EDITOR):
        WorkspaceMembership.objects.create(
            workspace=workspace, user=UserFactory(), role=role
        )
    editor = WorkspaceMembership.objects.get(
        workspace=workspace, role=WorkspaceRole.EDITOR
    ).user
    client = APIClient()
    client.force_authenticate(editor)
    return {"workspace": workspace, "file": file, "client": client, "maker": maker}


def test_the_maker_without_a_role_no_longer_sees_it(setting: dict[str, Any]) -> None:
    client = APIClient()
    client.force_authenticate(setting["maker"])
    run_id = setting["workspace"].run_id
    assert client.get(f"/api/v1/runs/{run_id}").status_code == 404


def test_an_editor_starts_an_execution_and_it_extracts(
    setting: dict[str, Any], django_capture_on_commit_callbacks: Any
) -> None:
    run_id = setting["workspace"].run_id
    with django_capture_on_commit_callbacks(execute=True):
        response = setting["client"].post(
            f"/api/v1/runs/{run_id}/stages/extract/executions", {}, format="json"
        )
    assert response.status_code == 202, response.json()
    cell = Cell.objects.get(file=setting["file"])
    assert cell.status == CellStatus.SUCCEEDED, cell.error


def test_an_editor_asks_the_assistant_and_it_replies(
    setting: dict[str, Any], django_capture_on_commit_callbacks: Any
) -> None:
    url = f"/api/v1/runs/{setting['workspace'].run_id}/extraction/assistant/messages"
    client = setting["client"]
    with django_capture_on_commit_callbacks(execute=True):
        sent = client.post(
            url,
            {"text": "Extract every architecture decision record", "definition": adr()},
            format="json",
        )
    assert sent.status_code == 201, sent.json()
    reply = client.get(url).json()["messages"][1]
    assert reply["status"] == "done"
    assert reply["text"]
    assert APOLOGY not in reply["text"]


def test_the_run_view_reads_the_runs_documents(setting: dict[str, Any]) -> None:
    run = setting["workspace"].run
    view = run_view_of(run)
    file = setting["file"]
    assert [d.id for d in async_to_sync(view.documents)()] == [file.source_ref]
    assert async_to_sync(view.read)(file.source_ref)
    assert async_to_sync(view.extractions)() == []
    draft = Draft.model_validate(adr())
    assert isinstance(async_to_sync(view.preview)(draft, file.source_ref), list)
