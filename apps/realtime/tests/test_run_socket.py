"""The run socket ``ws/runs/<run_id>/``, through the real ASGI application."""

from typing import Any

import pytest
from asgiref.sync import sync_to_async
from django.db import transaction
from rest_framework.test import APIClient

from apps.identity.tests.factories import UserFactory
from apps.realtime import services
from apps.realtime.tests.communicator import WebsocketCommunicator
from apps.runs import services as runs
from apps.runs.models import Cell, Run
from apps.runs.tests.factories import CellFactory
from config.asgi import application

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.asyncio,
]

ORIGIN = b"http://localhost:3000"


async def open_socket(user: Any, run_id: Any) -> WebsocketCommunicator:
    """A socket on the run, opened with a fresh ticket of ``user``."""
    ticket = await sync_to_async(services.issue_ticket)(user)
    communicator = WebsocketCommunicator(
        application,
        f"/ws/runs/{run_id}/?ticket={ticket}",
        headers=[(b"origin", ORIGIN)],
    )
    assert await communicator.connect()
    return communicator


async def closed_with(communicator: WebsocketCommunicator, code: int) -> None:
    assert await communicator.receive_output() == {
        "type": "websocket.close",
        "code": code,
    }


@sync_to_async
def a_cell(owner: Any = None) -> Cell:
    cell: Cell = CellFactory(**({"file__run__owner": owner} if owner else {}))
    return Cell.objects.select_related("file__run__owner").get(pk=cell.pk)


@sync_to_async
def set_running(cell: Cell, progress: int = 40) -> Cell:
    return runs.set_cell(
        cell.file, cell.stage, status="running", execution_id="x1", progress=progress
    )


@sync_to_async
def snapshot_cell(owner: Any, run_id: Any) -> Any:
    client = APIClient()
    client.force_authenticate(owner)
    return client.get(f"/api/v1/runs/{run_id}").json()["cells"][0]


async def test_the_owner_gets_every_cell_change_as_in_the_snapshot() -> None:
    cell = await a_cell()
    owner, run_id = cell.file.run.owner, cell.file.run_id
    socket = await open_socket(owner, run_id)

    await set_running(cell)

    event = await socket.receive_json_from()
    assert event == {"type": "cell", "cell": await snapshot_cell(owner, run_id)}
    assert event["cell"]["status"] == "running"
    assert event["cell"]["progress"] == 40
    await socket.receive_nothing()
    await socket.disconnect()


async def test_an_event_is_one_json_text_frame() -> None:
    cell = await a_cell()
    socket = await open_socket(cell.file.run.owner, cell.file.run_id)
    await set_running(cell)
    frame = await socket.receive_output()
    assert frame["type"] == "websocket.send"
    assert isinstance(frame["text"], str)
    assert frame.get("bytes") is None
    await socket.disconnect()


async def test_another_persons_run_is_4404() -> None:
    cell = await a_cell()
    stranger = await sync_to_async(UserFactory)()
    socket = await open_socket(stranger, cell.file.run_id)
    await closed_with(socket, 4404)


async def test_an_unknown_run_is_4404(user: Any) -> None:
    socket = await open_socket(user, "8e7f2a0c-0000-4000-8000-000000000000")
    await closed_with(socket, 4404)
    socket = await open_socket(user, "not-a-uuid")
    await closed_with(socket, 4404)


async def test_a_bad_ticket_is_4401() -> None:
    cell = await a_cell()
    communicator = WebsocketCommunicator(
        application,
        f"/ws/runs/{cell.file.run_id}/?ticket=made-up",
        headers=[(b"origin", ORIGIN)],
    )
    assert await communicator.connect()
    await closed_with(communicator, 4401)


async def test_a_refused_socket_hears_nothing_of_the_run() -> None:
    cell = await a_cell()
    stranger = await sync_to_async(UserFactory)()
    socket = await open_socket(stranger, cell.file.run_id)
    await closed_with(socket, 4404)
    owners = await open_socket(cell.file.run.owner, cell.file.run_id)
    await set_running(cell)
    assert (await owners.receive_json_from())["type"] == "cell"
    await socket.receive_nothing()
    await owners.disconnect()


async def test_two_sockets_on_one_run_both_get_it_another_run_does_not() -> None:
    cell = await a_cell()
    owner = cell.file.run.owner
    other = await a_cell(owner)
    first = await open_socket(owner, cell.file.run_id)
    second = await open_socket(owner, cell.file.run_id)
    elsewhere = await open_socket(owner, other.file.run_id)

    await set_running(cell)

    assert (await first.receive_json_from())["cell"]["file_id"] == str(cell.file_id)
    assert (await second.receive_json_from())["cell"]["file_id"] == str(cell.file_id)
    await elsewhere.receive_nothing()
    for socket in (first, second, elsewhere):
        await socket.disconnect()


async def test_messages_from_the_client_change_nothing() -> None:
    cell = await a_cell()
    socket = await open_socket(cell.file.run.owner, cell.file.run_id)

    await socket.send_json_to({"type": "cell", "cell": {"status": "failed"}})
    await socket.send_input({"type": "websocket.receive", "text": "not json"})
    await socket.send_input({"type": "websocket.receive", "bytes": b"\x00\x01"})
    await socket.send_input({"type": "websocket.receive", "text": "ping"})

    await socket.receive_nothing()
    unchanged = await Cell.objects.aget(pk=cell.pk)
    assert (unchanged.status, unchanged.updated_at) == (cell.status, cell.updated_at)
    # Still open and still following the run.
    await set_running(cell)
    assert (await socket.receive_json_from())["type"] == "cell"
    await socket.disconnect()


async def test_an_event_goes_out_after_the_commit_and_never_on_rollback() -> None:
    cell = await a_cell()
    socket = await open_socket(cell.file.run.owner, cell.file.run_id)

    @sync_to_async
    def rolled_back() -> None:
        with pytest.raises(RuntimeError), transaction.atomic():
            runs.set_cell(cell.file, cell.stage, status="running")
            raise RuntimeError("undo")

    await rolled_back()
    await socket.receive_nothing()

    @sync_to_async
    def committed() -> None:
        with transaction.atomic():
            runs.set_cell(cell.file, cell.stage, status="queued")
            runs.set_cell(cell.file, cell.stage, status="running")

    await committed()
    first = await socket.receive_json_from()
    second = await socket.receive_json_from()
    assert [first["cell"]["status"], second["cell"]["status"]] == ["queued", "running"]
    await socket.disconnect()


async def test_events_sent_while_nobody_listens_are_lost() -> None:
    cell = await a_cell()
    await set_running(cell, progress=10)
    socket = await open_socket(cell.file.run.owner, cell.file.run_id)
    await socket.receive_nothing()
    await set_running(cell, progress=20)
    assert (await socket.receive_json_from())["cell"]["progress"] == 20
    await socket.disconnect()


async def test_deleting_the_run_closes_its_sockets_with_4404() -> None:
    cell = await a_cell()
    owner, run_id = cell.file.run.owner, cell.file.run_id
    first = await open_socket(owner, run_id)
    second = await open_socket(owner, run_id)

    @sync_to_async
    def delete() -> int:
        client = APIClient()
        client.force_authenticate(owner)
        return client.delete(f"/api/v1/runs/{run_id}").status_code

    assert await delete() == 204
    await closed_with(first, 4404)
    await closed_with(second, 4404)
    assert not await Run.objects.filter(pk=run_id).aexists()
