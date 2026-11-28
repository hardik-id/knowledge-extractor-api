"""One person walks the whole Studio flow, in the order the UI makes the calls.

Through the API and a run socket, as the app does it: start a workspace, set its
documents, shape the extraction configuration with the assistant, extract,
review the records, extract again, read and restore versions, change the
documents, clear the conversation, rename and delete the workspace. Every response and every socket message goes
through the checker of its shape (``tests/shapes.py``), so a change that would
break the UI's parser fails here. A second person sees none of it.

Jobs run inline (the test settings) and events go through the in-memory layer.
"""

import copy
from collections.abc import Callable
from typing import Any

import pytest
from asgiref.sync import sync_to_async
from rest_framework.test import APIClient

from apps.identity.tests.factories import UserFactory
from apps.realtime.tests.communicator import WebsocketCommunicator
from config.asgi import application
from tests import shapes

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

ADR = "enriched/engineering/architecture/platform-adrs.md"
ORIGIN = b"http://localhost:3000"
ASK = "add owner"
API = "/api/v1"


@sync_to_async
def call(
    user: Any,
    method: str,
    path: str,
    body: Any = None,
    check: Callable[[Any], None] | None = None,
    expect: int = 200,
) -> Any:
    """One request as ``user``. Checks the status, and the shape of a JSON body."""
    client = APIClient()
    client.force_authenticate(user)
    response = getattr(client, method)(path, body, format="json")
    detail = response.content.decode()[:300]
    assert response.status_code == expect, f"{method} {path}: {detail}"
    if check is not None:
        check(response.json())
    return response


async def open_socket(user: Any, run_id: str) -> WebsocketCommunicator:
    ticket = (await call(user, "post", f"{API}/ws-ticket")).json()["ticket"]
    socket = WebsocketCommunicator(
        application,
        f"/ws/runs/{run_id}/?ticket={ticket}",
        headers=[(b"origin", ORIGIN)],
    )
    assert await socket.connect()
    return socket


async def events_until(
    socket: WebsocketCommunicator, last: Callable[[dict[str, Any]], bool]
) -> list[dict[str, Any]]:
    """Every message up to and including the one ``last`` accepts, each checked."""
    events = []
    while True:
        event = await socket.receive_json_from(timeout=5)
        shapes.check_socket_message(event)
        events.append(event)
        if last(event):
            return events


def changed(revision: int) -> Callable[[dict[str, Any]], bool]:
    return lambda e: e["type"] == "extraction.changed" and e["revision"] == revision


def is_run_changed(event: dict[str, Any]) -> bool:
    return bool(event["type"] == "run.changed")


def draft(definition: dict[str, Any]) -> dict[str, Any]:
    """A definition as the API takes it: without its version."""
    return {k: v for k, v in definition.items() if k != "version"}


async def test_a_person_walks_the_whole_studio_flow() -> None:
    me = await sync_to_async(UserFactory)()

    # Documents: the list, then one with its ETag.
    listed = (
        await call(me, "get", f"{API}/documents", check=shapes.check_files)
    ).json()
    etag = next(d["etag"] for d in listed["items"] if d["id"] == ADR)
    read = await call(me, "get", f"{API}/documents/{ADR}")
    assert read["ETag"] == f'"{etag}"'

    # A workspace, on the list, with its empty run.
    workspace = (
        await call(
            me,
            "post",
            f"{API}/workspaces",
            {"name": "ADRs"},
            shapes.check_workspace,
            201,
        )
    ).json()
    assert (workspace["document_count"], workspace["configuration_version"]) == (0, 1)
    workspace_url = f"{API}/workspaces/{workspace['id']}"
    workspaces = (
        await call(me, "get", f"{API}/workspaces", check=shapes.check_workspaces)
    ).json()
    assert [p["id"] for p in workspaces["items"]] == [workspace["id"]]
    # A workspace from a template: version 1 is the template, and says so.
    skill = (
        await call(
            me,
            "post",
            f"{API}/workspaces",
            {"name": "Skills", "template_id": "skill"},
            shapes.check_workspace,
            201,
        )
    ).json()
    skill_versions = (
        await call(
            me,
            "get",
            f"{API}/runs/{skill['run_id']}/stages/extract/definition/versions",
            check=shapes.check_versions,
        )
    ).json()
    assert [(v["version"], v["note"]) for v in skill_versions["items"]] == [
        (1, "From template: Agent skills")
    ]
    skill_one = (
        await call(
            me,
            "get",
            f"{API}/runs/{skill['run_id']}/stages/extract/definition/versions/1",
            check=shapes.check_saved_definition,
        )
    ).json()
    assert [t["name"] for t in skill_one["record_types"]] == ["Skill"]
    await call(me, "delete", f"{API}/workspaces/{skill['id']}", expect=204)

    run_id = workspace["run_id"]
    run = f"{API}/runs/{run_id}"
    empty = (await call(me, "get", run, check=shapes.check_run)).json()
    assert (empty["files"], empty["cells"]) == ([], [])
    socket = await open_socket(me, run_id)

    # Its documents: the page is told to fetch the snapshot again.
    created = (
        await call(
            me,
            "put",
            f"{run}/documents",
            {"items": [{"source": "storage", "source_ref": ADR}]},
            shapes.check_run,
        )
    ).json()
    assert [e["type"] for e in await events_until(socket, is_run_changed)] == [
        "run.changed"
    ]
    file = created["files"][0]["id"]
    extraction = f"{run}/files/{file}/extraction"
    snapshot = (await call(me, "get", run, check=shapes.check_run)).json()
    assert [(c["stage"], c["status"]) for c in snapshot["cells"]] == [
        ("extract", "pending")
    ]

    # The definition: the default, then a saved version.
    definition_url = f"{run}/stages/extract/definition"
    first = (
        await call(me, "get", definition_url, check=shapes.check_definition)
    ).json()
    assert first["version"] == 1
    mine = draft(first) | {"prompt": "Find the decisions."}
    saved = (
        await call(
            me,
            "put",
            definition_url,
            {**mine, "base_version": 1, "note": "Decisions only"},
            shapes.check_saved_definition,
        )
    ).json()
    assert (saved["version"], saved["prompt"]) == (2, "Find the decisions.")
    assert saved["note"] == "Decisions only"

    # The assistant: a prompt, then its reply on the socket.
    messages_url = f"{run}/extraction/assistant/messages"
    sent = (
        await call(
            me,
            "post",
            messages_url,
            {"text": ASK, "definition": draft(saved)},
            shapes.check_assistant_message,
            201,
        )
    ).json()
    assert sent["role"] == "user"
    heard = await events_until(socket, lambda e: e["type"] == "assistant.done")
    kinds = [e["type"] for e in heard]
    assert kinds[-2:] == ["assistant.proposal", "assistant.done"]
    assert set(kinds[:-2]) == {"assistant.delta"}
    proposal = heard[-2]["proposal"]
    thread = (
        await call(me, "get", messages_url, check=shapes.check_assistant_messages)
    ).json()["messages"]
    assert [m["status"] for m in thread] == ["done", "done"]
    assert thread[1]["proposal"] == proposal

    # Apply the proposal with a save.
    applied = (
        await call(
            me,
            "put",
            definition_url,
            {**copy.deepcopy(proposal["definition"]), "base_version": 2},
            shapes.check_definition,
        )
    ).json()
    assert applied["version"] == 3
    record_type = applied["record_types"][0]["id"]

    # Extract: the cell goes queued, running, succeeded; then the records change.
    execution = (
        await call(
            me,
            "post",
            f"{run}/stages/extract/executions",
            {"file_ids": [file], "config": {"definition_version": 3}},
            shapes.check_execution,
            202,
        )
    ).json()
    assert execution["file_ids"] == [file]
    heard = await events_until(socket, changed(1))
    assert [e["cell"]["status"] for e in heard if e["type"] == "cell"] == [
        "queued",
        "running",
        "succeeded",
    ]
    assert all(
        e["cell"]["execution_id"] == execution["execution_id"]
        for e in heard
        if e["type"] == "cell"
    )

    # The records, then the person's review.
    records = (await call(me, "get", extraction, check=shapes.check_extraction)).json()
    assert (records["revision"], records["definition_version"]) == (1, 3)
    accepted, rejected, *_ = records["records"]
    assert accepted["review"] == rejected["review"] == "suggested"

    def edit(method: str, path: str, body: dict[str, Any]) -> Any:
        return call(me, method, f"{extraction}{path}", body, shapes.check_extraction)

    after = (
        await edit(
            "patch", f"/records/{accepted['id']}", {"revision": 1, "review": "accepted"}
        )
    ).json()
    assert after["revision"] == 2
    await events_until(socket, changed(2))
    after = (
        await edit(
            "patch", f"/records/{rejected['id']}", {"revision": 2, "review": "rejected"}
        )
    ).json()
    await events_until(socket, changed(3))
    after = (
        await edit(
            "post",
            "/records",
            {"revision": 3, "record_type_id": record_type, "span": None, "fields": []},
        )
    ).json()
    assert after["revision"] == 4
    await events_until(socket, changed(4))
    [by_hand] = [r for r in after["records"] if r["origin"] == "human"]
    assert by_hand["review"] == "accepted"

    field = accepted["fields"][0]["field_id"]
    after = (
        await edit(
            "put",
            f"/records/{accepted['id']}/fields/{field}",
            {"revision": 4, "values": [{"value": "Mine", "spans": []}]},
        )
    ).json()
    assert after["revision"] == 5
    await events_until(socket, changed(5))

    def mine_of(data: dict[str, Any]) -> list[dict[str, Any]]:
        """The values of the field the person set."""
        return [
            v
            for r in data["records"]
            if r["id"] == accepted["id"]
            for v in r["fields"]
            if v["field_id"] == field
        ]

    assert [(v["value"], v["origin"], v["review"]) for v in mine_of(after)] == [
        ("Mine", "human", "accepted")
    ]

    # A stale revision is refused.
    stale = await call(
        me,
        "patch",
        f"{extraction}/records/{rejected['id']}",
        {"revision": 1, "review": "accepted"},
        expect=409,
    )
    assert stale.json()["code"] == "revision_conflict"

    # Extract again: the person's work is kept.
    await call(
        me,
        "post",
        f"{run}/stages/extract/executions",
        {"file_ids": [file]},
        shapes.check_execution,
        202,
    )
    await events_until(socket, changed(6))
    again = (await call(me, "get", extraction, check=shapes.check_extraction)).json()
    by_id = {r["id"]: r for r in again["records"]}
    assert by_id[accepted["id"]]["review"] == "accepted"
    assert by_id[rejected["id"]]["review"] == "rejected"
    assert by_id[by_hand["id"]]["origin"] == "human"
    assert [(v["value"], v["origin"]) for v in mine_of(again)] == [("Mine", "human")]

    # The versions: the list, one read, one restored as the newest.
    versions_url = f"{definition_url}/versions"
    listing = (await call(me, "get", versions_url, check=shapes.check_versions)).json()
    assert [v["version"] for v in listing["items"]] == [3, 2, 1]
    assert [v["note"] for v in listing["items"]][1] == "Decisions only"
    old = (
        await call(me, "get", f"{versions_url}/2", check=shapes.check_saved_definition)
    ).json()
    assert (old["version"], old["prompt"]) == (2, "Find the decisions.")
    restored = (
        await call(
            me,
            "post",
            f"{versions_url}/2/restore",
            check=shapes.check_saved_definition,
        )
    ).json()
    assert (restored["version"], restored["note"]) == (4, "Restored from version 2")
    assert restored["prompt"] == old["prompt"]
    newest = (await call(me, "get", versions_url, check=shapes.check_versions)).json()
    assert [v["version"] for v in newest["items"]] == [4, 3, 2, 1]

    # Change the documents: the definition, the conversation and what stays stay.
    other_doc = next(d["id"] for d in listed["items"] if d["id"] != ADR)
    both = (
        await call(
            me,
            "put",
            f"{run}/documents",
            {
                "items": [
                    {"source": "storage", "source_ref": d} for d in (ADR, other_doc)
                ]
            },
            shapes.check_run,
        )
    ).json()
    await events_until(socket, is_run_changed)
    assert len(both["files"]) == 2
    assert file in [f["id"] for f in both["files"]]
    kept = (await call(me, "get", extraction, check=shapes.check_extraction)).json()
    assert [r["id"] for r in kept["records"]] == [r["id"] for r in again["records"]]
    assert (
        await call(me, "get", definition_url, check=shapes.check_saved_definition)
    ).json()["version"] == 4
    thread = (
        await call(me, "get", messages_url, check=shapes.check_assistant_messages)
    ).json()["messages"]
    assert len(thread) == 2
    listed_workspace = (
        await call(me, "get", workspace_url, check=shapes.check_workspace)
    ).json()
    assert (
        listed_workspace["document_count"],
        listed_workspace["configuration_version"],
    ) == (2, 4)

    # Clear the conversation: nothing else changes.
    await call(me, "delete", messages_url, expect=204)
    cleared = await events_until(socket, lambda e: e["type"] == "assistant.cleared")
    assert [e["type"] for e in cleared] == ["assistant.cleared"]
    empty_thread = (
        await call(me, "get", messages_url, check=shapes.check_assistant_messages)
    ).json()
    assert empty_thread["messages"] == []
    assert (
        await call(me, "get", definition_url, check=shapes.check_saved_definition)
    ).json()["version"] == 4

    # Rename the workspace; its run cannot be deleted on its own.
    renamed = (
        await call(
            me,
            "patch",
            workspace_url,
            {"name": "Architecture decisions", "description": "Why we chose"},
            shapes.check_workspace,
        )
    ).json()
    assert renamed["name"] == "Architecture decisions"
    refused = await call(me, "delete", run, expect=409)
    assert refused.json()["code"] == "run_belongs_to_workspace"

    # A second person sees none of it.
    other = await sync_to_async(UserFactory)()
    base = f"{extraction}/records/{accepted['id']}"
    attempts: list[tuple[str, str, Any]] = [
        ("get", run, None),
        ("get", definition_url, None),
        ("put", definition_url, {**mine, "base_version": 3}),
        ("get", messages_url, None),
        ("post", messages_url, {"text": ASK, "definition": mine}),
        ("post", f"{run}/stages/extract/executions", {}),
        ("get", extraction, None),
        (
            "post",
            f"{extraction}/records",
            {"revision": 6, "record_type_id": record_type, "span": None, "fields": []},
        ),
        ("patch", base, {"revision": 6, "review": "accepted"}),
        ("put", f"{base}/fields/{field}", {"revision": 6, "values": []}),
        (
            "patch",
            f"{base}/values/{mine_of(again)[0]['id']}",
            {"revision": 6, "review": "rejected"},
        ),
        ("put", f"{run}/documents", {"items": []}),
        ("get", versions_url, None),
        ("get", f"{versions_url}/2", None),
        ("post", f"{versions_url}/2/restore", None),
        ("delete", messages_url, None),
        ("get", workspace_url, None),
        ("patch", workspace_url, {"name": "Mine now"}),
        ("delete", workspace_url, None),
        ("delete", run, None),
    ]
    for method, path, body in attempts:
        denied = await call(other, method, path, body, expect=404)
        assert "code" in denied.json(), f"{method} {path}"
    nothing = await call(
        other, "get", f"{API}/workspaces", check=shapes.check_workspaces
    )
    assert nothing.json()["items"] == []
    stranger = await open_socket_refused(other, created["id"])
    assert stranger == 4404

    # Delete the workspace: it, its run and its socket are gone.
    await call(me, "delete", workspace_url, expect=204)
    await call(me, "get", workspace_url, expect=404)
    await call(me, "get", run, expect=404)
    gone = (
        await call(me, "get", f"{API}/workspaces", check=shapes.check_workspaces)
    ).json()
    assert gone["items"] == []
    closed = await socket.receive_output(timeout=5)  # type: ignore[no-untyped-call]
    assert closed == {"type": "websocket.close", "code": 4404}


async def open_socket_refused(user: Any, run_id: str) -> int:
    """The code a socket on someone else's run is closed with."""
    ticket = (await call(user, "post", f"{API}/ws-ticket")).json()["ticket"]
    socket = WebsocketCommunicator(
        application,
        f"/ws/runs/{run_id}/?ticket={ticket}",
        headers=[(b"origin", ORIGIN)],
    )
    assert await socket.connect()
    closed = await socket.receive_output(timeout=5)  # type: ignore[no-untyped-call]
    assert closed["type"] == "websocket.close"
    return int(closed["code"])
