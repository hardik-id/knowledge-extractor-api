"""The metrics of the run sockets (docs/observability.md)."""

from collections.abc import Callable
from typing import Any

import pytest
from asgiref.sync import sync_to_async

from apps.core.tests.otel import Telemetry
from apps.identity.tests.factories import UserFactory
from apps.realtime import services
from apps.realtime.tests.communicator import WebsocketCommunicator
from apps.realtime.tests.test_run_socket import (
    ORIGIN,
    a_cell,
    closed_with,
    open_socket,
    set_running,
)
from config.asgi import application

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.asyncio,
]


def open_connections(otel: Telemetry) -> int:
    return sum(point.value for point in otel.points("realtime.connections"))


def published(otel: Telemetry) -> dict[str, int]:
    return {
        point.attributes["type"]: point.value
        for point in otel.points("realtime.events.published")
    }


async def test_open_sockets_are_counted_up_and_down(otel: Telemetry) -> None:
    cell = await a_cell()
    owner, run_id = cell.file.run.owner, cell.file.run_id
    assert open_connections(otel) == 0

    first = await open_socket(owner, run_id)
    second = await open_socket(owner, run_id)
    assert open_connections(otel) == 2

    await first.disconnect()
    assert open_connections(otel) == 1
    await second.disconnect()
    assert open_connections(otel) == 0


async def test_a_refused_socket_is_not_counted(otel: Telemetry) -> None:
    cell = await a_cell()
    stranger = await sync_to_async(UserFactory)()
    socket = await open_socket(stranger, cell.file.run_id)
    await closed_with(socket, 4404)
    await socket.disconnect()

    bad = WebsocketCommunicator(
        application,
        f"/ws/runs/{cell.file.run_id}/?ticket=made-up",
        headers=[(b"origin", ORIGIN)],
    )
    assert await bad.connect()
    await closed_with(bad, 4401)

    assert open_connections(otel) == 0


async def test_events_are_counted_by_type(otel: Telemetry) -> None:
    cell = await a_cell()
    socket = await open_socket(cell.file.run.owner, cell.file.run_id)

    await set_running(cell)
    await set_running(cell, progress=60)
    await sync_to_async(services.close_run_sockets)(cell.file.run_id)

    assert published(otel) == {"cell": 2, "run.gone": 1}
    await socket.disconnect()


async def test_a_failed_send_is_not_counted(
    otel: Telemetry, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Broken:
        async def group_send(self, group: str, message: dict[str, Any]) -> None:
            raise ConnectionError("redis is gone")

    monkeypatch.setattr(services, "get_channel_layer", lambda: Broken())
    await services.apublish_run_event("run-1", {"type": "cell"})

    assert published(otel) == {}


async def test_no_metric_holds_a_run_a_file_or_a_ticket(
    otel: Telemetry, log_lines: Callable[[], str]
) -> None:
    cell = await a_cell()
    owner, run_id = cell.file.run.owner, cell.file.run_id
    ticket = await sync_to_async(services.issue_ticket)(owner)
    socket = WebsocketCommunicator(
        application,
        f"/ws/runs/{run_id}/?ticket={ticket}",
        headers=[(b"origin", ORIGIN)],
    )
    assert await socket.connect()
    await set_running(cell)
    await socket.receive_json_from()
    await socket.disconnect()

    caught = otel.everything() + "\n" + log_lines()
    assert otel.points("realtime.events.published")
    for secret in (ticket, str(run_id), str(cell.file_id)):
        assert secret not in caught
