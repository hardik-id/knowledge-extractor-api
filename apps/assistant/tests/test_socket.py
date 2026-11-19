"""A reply on the run's socket, through the real ASGI application, with the job run on commit."""

from typing import Any

import pytest
from asgiref.sync import sync_to_async
from rest_framework.test import APIClient

from apps.assistant.tests.test_scripted import bare
from apps.realtime import services as realtime
from apps.realtime.tests.communicator import WebsocketCommunicator
from apps.runs.tests.factories import RunFactory
from config.asgi import application

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]


@sync_to_async
def a_run() -> Any:
    run = RunFactory()
    return run, run.owner


@sync_to_async
def call(owner: Any, method: str, path: str, body: Any = None) -> Any:
    client = APIClient()
    client.force_authenticate(owner)
    return getattr(client, method)(path, body, format="json")


async def test_the_socket_sees_deltas_a_proposal_and_done_and_get_agrees() -> None:
    run, owner = await a_run()
    ticket = await sync_to_async(realtime.issue_ticket)(owner)
    socket = WebsocketCommunicator(
        application,
        f"/ws/runs/{run.pk}/?ticket={ticket}",
        headers=[(b"origin", b"http://localhost:3000")],
    )
    assert await socket.connect()
    path = f"/api/v1/runs/{run.pk}/extraction/assistant/messages"

    response = await call(
        owner,
        "post",
        path,
        {"text": "Extract every architecture decision record", "definition": bare()},
    )
    assert response.status_code == 201
    assert response.json()["role"] == "user"

    events = []
    while True:
        event = await socket.receive_json_from()
        events.append(event)
        if event["type"] == "assistant.done":
            break
    await socket.receive_nothing()  # type: ignore[no-untyped-call]
    await socket.disconnect()

    kinds = [event["type"] for event in events]
    assert kinds[-2:] == ["assistant.proposal", "assistant.done"]
    assert set(kinds[:-2]) == {"assistant.delta"}

    messages = (await call(owner, "get", path)).json()["messages"]
    assert [m["status"] for m in messages] == ["done", "done"]
    reply = messages[1]
    assert {event["message_id"] for event in events} == {reply["id"]}
    deltas = [e["text"] for e in events if e["type"] == "assistant.delta"]
    assert "".join(deltas) == reply["text"]
    assert events[-2]["proposal"] == reply["proposal"]
    assert reply["proposal"]["definition"]["record_types"][0]["name"] == "ADR"
