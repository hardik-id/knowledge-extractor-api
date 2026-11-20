"""The workspace an agent looks at: the run's documents, its extractions and a dry run."""

import dataclasses
import inspect
from typing import Any, get_type_hints

import pytest
from asgiref.sync import async_to_sync
from django.db import models as django_models

from apps.assistant.agents import base
from apps.assistant.agents.base import (
    DocumentRef,
    FileRecords,
    RecordView,
    ValueView,
    Workspace,
)
from apps.assistant.selectors import OwnerWorkspace, workspace_of_run
from apps.core.errors import ApiError
from apps.documents import selectors as documents
from apps.extraction.definition import Draft
from apps.extraction.models import (
    DefinitionVersion,
    Extraction,
    ExtractionRecord,
    FieldValue,
)
from apps.extraction.tests.default_definition import (
    DEFAULT_OUTPUT,
    DEFAULT_PROMPT,
    DEFAULT_RECORD_TYPES,
)
from apps.extraction.tests.factories import DefinitionVersionFactory
from apps.runs.models import Cell
from apps.runs.tests.factories import CellFactory, RunFactory, RunFileFactory

pytestmark = pytest.mark.django_db

ADR = "enriched/engineering/architecture/platform-adrs.md"
OTHER = "enriched/engineering/architecture/architecture-decisions-2026.md"
TITLE = "f-adr-title"


def definition() -> Draft:
    return Draft.model_validate(
        {
            "prompt": DEFAULT_PROMPT,
            "record_types": DEFAULT_RECORD_TYPES,
            "output": DEFAULT_OUTPUT,
        }
    )


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
    return CellFactory(
        file=RunFileFactory(run=run, source_ref=ADR, name="adrs.md")
    ).file


@pytest.fixture
def workspace(run: Any) -> OwnerWorkspace:
    return workspace_of_run(run)


@pytest.fixture
def capture(django_capture_on_commit_callbacks: Any) -> Any:
    return django_capture_on_commit_callbacks


@pytest.fixture(autouse=True)
def silent_sockets(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.realtime import services as realtime

    monkeypatch.setattr(realtime, "publish_run_event", lambda *_args: None)


def execute(
    client: Any, run: Any, capture: Any, files: list[Any] | None = None
) -> None:
    """Run the extractor on the files (default: all) of the run, as the worker would."""
    body = {"file_ids": [str(f.pk) for f in files]} if files else {}
    with capture(execute=True):
        response = client.post(
            f"/api/v1/runs/{run.pk}/stages/extract/executions", body, format="json"
        )
    assert response.status_code == 202, response.json()


def extraction_url(file: Any) -> str:
    return f"/api/v1/runs/{file.run_id}/files/{file.pk}/extraction"


def snapshot() -> dict[str, Any]:
    """Every row of every extraction table, and the cells."""
    return {
        model.__name__: list(model.objects.order_by("pk").values())
        for model in (
            DefinitionVersion,
            Extraction,
            ExtractionRecord,
            FieldValue,
            Cell,
        )
    }


# --- documents ----------------------------------------------------------------


def test_a_workspace_lists_and_reads_the_documents_of_its_run(
    run: Any, user: Any
) -> None:
    RunFileFactory(run=run, source_ref=OTHER, name="b.md")
    RunFileFactory(run=run, source_ref=ADR, name="a.md")
    RunFileFactory(source_ref=OTHER, name="someone else's.md")  # another run
    workspace = workspace_of_run(run)
    assert async_to_sync(workspace.documents)() == [
        DocumentRef(ADR, "a.md"),
        DocumentRef(OTHER, "b.md"),
    ]
    assert async_to_sync(workspace.read)(ADR) == documents.read_document(user, ADR).text


def test_a_document_in_the_catalog_but_not_in_the_run_is_refused(
    run: Any, user: Any
) -> None:
    RunFileFactory(run=run, source_ref=ADR)
    assert documents.read_document(user, OTHER).text  # the owner can open it
    workspace = workspace_of_run(run)
    with pytest.raises(ApiError) as error:
        async_to_sync(workspace.read)(OTHER)
    assert error.value.code == "document_not_found"
    with pytest.raises(ApiError) as error:
        async_to_sync(workspace.preview)(definition(), OTHER)
    assert error.value.code == "document_not_found"


def test_a_run_without_documents_has_an_empty_workspace(run: Any) -> None:
    workspace = workspace_of_run(run)
    assert async_to_sync(workspace.documents)() == []
    assert async_to_sync(workspace.extractions)() == []


# --- extractions ----------------------------------------------------------------


def test_extractions_show_what_a_run_of_the_extractor_stored(
    client: Any, run: Any, file: Any, workspace: OwnerWorkspace, capture: Any
) -> None:
    CellFactory(file=RunFileFactory(run=run, source_ref=OTHER, name="never.md"))
    assert async_to_sync(workspace.extractions)() == []
    execute(client, run, capture, [file])
    [found] = async_to_sync(workspace.extractions)()  # only the file with a cell
    stored = client.get(extraction_url(file)).json()
    assert isinstance(found, FileRecords)
    assert (found.document_id, found.name, found.definition_version) == (
        ADR,
        "adrs.md",
        stored["definition_version"],
    )
    assert len(found.records) == len(stored["records"]) >= 2
    for view, record in zip(found.records, stored["records"], strict=True):
        assert (view.record_type_id, view.origin, view.review) == (
            record["record_type_id"],
            "llm",
            "suggested",
        )
        assert view.values == [
            ValueView(
                f["field_id"], f["value"], f["origin"], f["review"], f["anchored"]
            )
            for f in record["fields"]
        ]


def test_extractions_show_the_reviews_after_a_correction_through_the_api(
    client: Any, run: Any, file: Any, workspace: OwnerWorkspace, capture: Any
) -> None:
    execute(client, run, capture)
    data = client.get(extraction_url(file)).json()
    first, second, *_ = data["records"]
    accepted = client.patch(
        f"{extraction_url(file)}/records/{first['id']}",
        {"revision": data["revision"], "review": "accepted"},
        format="json",
    )
    assert accepted.status_code == 200, accepted.json()
    rejected = client.patch(
        f"{extraction_url(file)}/records/{second['id']}",
        {"revision": accepted.json()["revision"], "review": "rejected"},
        format="json",
    )
    assert rejected.status_code == 200, rejected.json()
    added = client.post(
        f"{extraction_url(file)}/records",
        {
            "revision": rejected.json()["revision"],
            "record_type_id": "rt-adr",
            "span": None,
            "fields": [
                {"field_id": TITLE, "values": [{"value": "By hand", "spans": []}]}
            ],
        },
        format="json",
    )
    assert added.status_code == 200, added.json()

    [found] = async_to_sync(workspace.extractions)()
    by_title = {
        next(v.value for v in r.values if v.field_id == TITLE): r for r in found.records
    }
    assert [(r.origin, r.review) for r in found.records].count(
        ("human", "accepted")
    ) == 1
    assert by_title["By hand"].values[0] == ValueView(
        TITLE, "By hand", "human", "accepted", True
    )
    assert any(r.review == "rejected" for r in found.records)
    assert any(r.review == "accepted" and r.origin == "llm" for r in found.records)


def test_extractions_of_other_runs_do_not_show(
    client: Any, run: Any, file: Any, capture: Any
) -> None:
    other = RunFactory(owner=run.owner)
    DefinitionVersionFactory(run=other)
    CellFactory(file=RunFileFactory(run=other, source_ref=OTHER, name="o.md"))
    execute(client, run, capture)
    [found] = async_to_sync(workspace_of_run(run).extractions)()
    assert found.document_id == ADR


# --- preview ----------------------------------------------------------------------


def test_preview_returns_what_a_real_execution_stores_and_stores_nothing(
    client: Any, run: Any, file: Any, workspace: OwnerWorkspace, capture: Any
) -> None:
    before = snapshot()
    preview = async_to_sync(workspace.preview)(definition(), ADR)
    assert snapshot() == before
    assert Extraction.objects.count() == 0
    assert len(preview) >= 2
    assert all(isinstance(record, RecordView) for record in preview)

    execute(client, run, capture)
    [found] = async_to_sync(workspace.extractions)()
    assert preview == found.records


def test_preview_changes_no_cell_and_no_stored_record(
    client: Any, run: Any, file: Any, workspace: OwnerWorkspace, capture: Any
) -> None:
    execute(client, run, capture)
    before = snapshot()
    draft = definition()
    draft.record_types[0].name = "Something else"
    assert async_to_sync(workspace.preview)(draft, ADR) == []
    assert snapshot() == before


# --- what an agent can do with it ----------------------------------------------------


def _types(annotation: Any) -> list[Any]:
    """The classes inside an annotation: ``list[ValueView]`` gives ``ValueView``."""
    args = getattr(annotation, "__args__", None)
    return [t for a in args for t in _types(a)] if args else [annotation]


def _classes_reached(cls: type) -> set[type]:
    seen: set[type] = set()
    todo = [cls]
    while todo:
        current = todo.pop()
        if current in seen or not dataclasses.is_dataclass(current):
            continue
        seen.add(current)
        for hint in get_type_hints(current).values():
            todo.extend(t for t in _types(hint) if isinstance(t, type))
    return seen


def test_everything_an_agent_receives_is_plain_frozen_data() -> None:
    reached = _classes_reached(FileRecords) | _classes_reached(RecordView)
    assert reached == {FileRecords, RecordView, ValueView}
    for cls in reached:
        assert cls.__dataclass_params__.frozen  # type: ignore[attr-defined]
        for hint in get_type_hints(cls).values():
            for leaf in _types(hint):
                assert not (
                    isinstance(leaf, type) and issubclass(leaf, django_models.Model)
                )
                assert leaf in (str, int, bool, type(None), RecordView, ValueView)


def test_what_a_workspace_returns_is_not_a_model_instance(
    client: Any, run: Any, file: Any, workspace: OwnerWorkspace, capture: Any
) -> None:
    execute(client, run, capture)
    [found] = async_to_sync(workspace.extractions)()
    views: list[Any] = [
        found,
        *found.records,
        *(v for r in found.records for v in r.values),
    ]
    for view in [*views, *async_to_sync(workspace.documents)()]:
        assert dataclasses.is_dataclass(type(view))
        assert not isinstance(view, django_models.Model)
        with pytest.raises(dataclasses.FrozenInstanceError):
            view.name = "x"
        for item in vars(view).values():
            assert isinstance(item, str | int | bool | list | type(None))


def test_a_workspace_offers_four_reads_and_nothing_that_writes() -> None:
    reads = {"documents", "read", "extractions", "preview"}

    def public(cls: type) -> set[str]:
        return {
            name
            for name, member in inspect.getmembers(cls)
            if not name.startswith("_") and inspect.isfunction(member)
        }

    assert public(Workspace) == reads
    assert public(OwnerWorkspace) == reads
    for name in reads:
        assert inspect.iscoroutinefunction(getattr(OwnerWorkspace, name))
    assert not hasattr(base, "RunDocuments")
