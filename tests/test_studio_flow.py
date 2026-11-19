"""One person walks the whole Studio flow, in the order the UI makes the calls.

Through the API and a run socket, as the app does it: pick a document, make a
run, shape the definition with the assistant, extract, review the records,
extract again, delete the run. Every response and every socket message goes
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

    # A run of that document, and its snapshot.
    created = (
        await call(
            me,
            "post",
            f"{API}/runs",
            {"items": [{"source": "storage", "source_ref": ADR}]},
            shapes.check_run,
            201,
        )
    ).json()
    run = f"{API}/runs/{created['id']}"
    file = created["files"][0]["id"]
    extraction = f"{run}/files/{file}/extraction"
    socket = await open_socket(me, created["id"])
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
            {**mine, "base_version": 1},
            shapes.check_definition,
        )
    ).json()
    assert (saved["version"], saved["prompt"]) == (2, "Find the decisions.")

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

    # A second person sees none of it.
    other = await sync_to_async(UserFactory)()
    base = f"{extraction}/records/{accepted['id']}"
    for method, path, body in [
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
        ("delete", run, None),
    ]:
        denied = await call(other, method, path, body, expect=404)
        assert "code" in denied.json(), f"{method} {path}"
    stranger = await open_socket_refused(other, created["id"])
    assert stranger == 4404

    # Delete the run: its snapshot is gone, and so is its socket.
    await call(me, "delete", run, expect=204)
    await call(me, "get", run, expect=404)
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
