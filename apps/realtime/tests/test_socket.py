"""The socket sign-in, through the real ASGI application."""

from datetime import timedelta
from typing import Any

import pytest
from asgiref.sync import sync_to_async
from django.utils import timezone

from apps.identity.tests.factories import UserFactory
from apps.realtime import services
from apps.realtime.models import WsTicket
from apps.realtime.tests.communicator import WebsocketCommunicator
from config.asgi import application

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.asyncio,
]

ORIGIN = b"http://localhost:3000"


def connect(
    query: str = "", origin: bytes | None = ORIGIN, path: str = "/ws/test/"
) -> WebsocketCommunicator:
    headers = [(b"origin", origin)] if origin else []
    return WebsocketCommunicator(application, f"{path}{query}", headers=headers)


@pytest.fixture
def ticket(user: Any) -> str:
    return services.issue_ticket(user)


async def refused_with_4401(communicator: WebsocketCommunicator) -> None:
    connected = await communicator.connect()
    assert connected  # accepted, so the close code reaches the browser
    message = await communicator.receive_output()
    assert message == {"type": "websocket.close", "code": 4401}


async def test_a_ticket_opens_the_socket_for_its_person(user: Any, ticket: str) -> None:
    communicator = connect(f"?ticket={ticket}")
    connected = await communicator.connect()
    assert connected
    assert await communicator.receive_json_from() == {
        "type": "hello",
        "user_id": str(user.pk),
    }
    await communicator.send_json_to({"n": 1})
    assert await communicator.receive_json_from() == {"type": "echo", "data": {"n": 1}}
    await communicator.disconnect()


async def test_the_same_ticket_a_second_time_is_4401(ticket: str) -> None:
    first = connect(f"?ticket={ticket}")
    assert await first.connect()
    await first.disconnect()
    await refused_with_4401(connect(f"?ticket={ticket}"))


async def test_an_expired_ticket_is_4401(ticket: str) -> None:
    await WsTicket.objects.aupdate(expires_at=timezone.now() - timedelta(seconds=1))
    await refused_with_4401(connect(f"?ticket={ticket}"))


async def test_no_ticket_is_4401() -> None:
    await refused_with_4401(connect())
    await refused_with_4401(connect("?ticket="))
    await refused_with_4401(connect("?other=1"))


async def test_an_unknown_ticket_is_4401() -> None:
    await refused_with_4401(connect("?ticket=made-up"))


async def test_a_ticket_of_person_a_never_signs_in_person_b(
    user: Any, ticket: str
) -> None:
    other = await sync_to_async(UserFactory)()
    communicator = connect(f"?ticket={ticket}")
    assert await communicator.connect()
    hello = await communicator.receive_json_from()
    assert hello["user_id"] == str(user.pk) != str(other.pk)
    await communicator.disconnect()


async def test_an_origin_that_is_not_allowed_is_refused(ticket: str) -> None:
    communicator = connect(f"?ticket={ticket}", origin=b"http://evil.example")
    connected = await communicator.connect()
    assert not connected
    # The ticket was not spent on the refused handshake.
    assert await WsTicket.objects.filter(used_at__isnull=True).acount() == 1


async def test_an_origin_with_the_right_host_and_another_port_is_refused(
    ticket: str,
) -> None:
    communicator = connect(f"?ticket={ticket}", origin=b"http://localhost:3001")
    assert not await communicator.connect()


async def test_a_socket_without_an_origin_is_signed_in_by_its_ticket(
    ticket: str,
) -> None:
    communicator = connect(f"?ticket={ticket}", origin=None)
    assert await communicator.connect()
    await communicator.disconnect()


async def test_local_patterns_are_allowed_like_in_cors(
    ticket: str, settings: Any
) -> None:
    settings.CORS_ALLOWED_ORIGIN_REGEXES = [r"^http://localhost:\d+$"]
    communicator = connect(f"?ticket={ticket}", origin=b"http://localhost:5173")
    assert await communicator.connect()
    await communicator.disconnect()


async def test_the_routes_do_not_see_the_ticket(ticket: str) -> None:
    from apps.realtime.middleware import TicketAuthMiddleware

    seen: dict[str, Any] = {}

    async def inner(scope: Any, receive: Any, send: Any) -> None:
        seen.update(scope)
        await receive()
        await send({"type": "websocket.close"})

    communicator = WebsocketCommunicator(
        TicketAuthMiddleware(inner), f"/ws/x/?ticket={ticket}&run=1"
    )
    await communicator.connect()
    assert seen["query_string"] == b"run=1"
    assert seen["user"].pk


async def test_no_log_line_holds_the_ticket(
    ticket: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("DEBUG")
    good = connect(f"?ticket={ticket}")
    await good.connect()
    await good.disconnect()
    await refused_with_4401(connect(f"?ticket={ticket}"))
    await refused_with_4401(connect("?ticket=made-up-secret"))
    text = caplog.text + "".join(str(vars(r)) for r in caplog.records)
    assert ticket not in text
    assert "made-up-secret" not in text
    assert "ws_ticket_refused" in text
