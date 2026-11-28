import json
from typing import Any

from channels.db import database_sync_to_async
from channels.generic.websocket import (
    AsyncJsonWebsocketConsumer,
    AsyncWebsocketConsumer,
)

from apps.core.errors import ApiError
from apps.iam.roles import Permission
from apps.realtime import services, telemetry
from apps.runs import selectors as runs

# The UI stops retrying on this close code: the run is not yours, or it is gone.
NOT_FOUND = 4404


class RunConsumer(AsyncWebsocketConsumer):  # type: ignore[misc]
    """``ws/runs/<run_id>/``: the changes to one run, as they happen.

    The ticket signed the person in (``TicketAuthMiddleware``). It needs
    ``workspace.view``: a run they may not see, or that does not exist, is closed
    with 4404. The server only sends:
    each event is one JSON text frame; whatever the client sends is ignored.
    """

    group: str | None = None

    async def connect(self) -> None:
        run_id = self.scope["url_route"]["kwargs"]["run_id"]
        try:
            run = await database_sync_to_async(runs.get_run)(
                self.scope["user"], run_id, Permission.WORKSPACE_VIEW
            )
        except ApiError:
            # Accept first, so the close code reaches the browser.
            await self.accept()
            await self.close(code=NOT_FOUND)
            return
        self.group = services.run_group(run.pk)
        await self.channel_layer.group_add(self.group, self.channel_name)
        telemetry.connection_opened()
        await self.accept()

    async def disconnect(self, code: int) -> None:
        if self.group is not None:
            await self.channel_layer.group_discard(self.group, self.channel_name)
            self.group = None
            telemetry.connection_closed()

    async def receive(
        self, text_data: str | None = None, bytes_data: bytes | None = None
    ) -> None:
        """The client has nothing to say here. Messages are dropped unread."""

    async def run_event(self, message: dict[str, Any]) -> None:
        await self.send(text_data=json.dumps(message["event"]))

    async def run_gone(self, message: dict[str, Any]) -> None:
        await self.close(code=NOT_FOUND)


class EchoConsumer(AsyncJsonWebsocketConsumer):  # type: ignore[misc]
    """Test-only: says who signed in, then repeats what it is sent."""

    async def connect(self) -> None:
        await self.accept()
        await self.send_json({"type": "hello", "user_id": str(self.scope["user"].pk)})

    async def receive_json(self, content: Any, **kwargs: Any) -> None:
        await self.send_json({"type": "echo", "data": content})
