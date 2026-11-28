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
# The person's role in the run's workspace was taken away while the socket was open.
ACCESS_REMOVED = 4403


class RunConsumer(AsyncWebsocketConsumer):  # type: ignore[misc]
    """``ws/runs/<run_id>/``: the changes to one run, as they happen.

    The ticket signed the person in (``TicketAuthMiddleware``). It needs
    ``workspace.view``: a run they may not see, or that does not exist, is closed
    with 4404. The server only sends:
    each event is one JSON text frame; whatever the client sends is ignored.
    """

    group: str | None = None
    user_group: str | None = None

    async def connect(self) -> None:
        run_id = self.scope["url_route"]["kwargs"]["run_id"]
        user = self.scope["user"]
        # Join the groups first, then check access: a close sent at the commit of
        # a removal then cannot fall between the check and the join and be lost.
        group = services.run_group(run_id)
        user_group = services.run_user_group(run_id, user.pk)
        await self.channel_layer.group_add(group, self.channel_name)
        await self.channel_layer.group_add(user_group, self.channel_name)
        try:
            run = await database_sync_to_async(runs.get_run)(
                user, run_id, Permission.WORKSPACE_VIEW
            )
        except ApiError:
            await self.channel_layer.group_discard(group, self.channel_name)
            await self.channel_layer.group_discard(user_group, self.channel_name)
            # Accept first, so the close code reaches the browser.
            await self.accept()
            await self.close(code=NOT_FOUND)
            return
        self.group = services.run_group(run.pk)
        self.user_group = services.run_user_group(run.pk, user.pk)
        if (self.group, self.user_group) != (group, user_group):
            # The id in the URL was spelled differently from the run's own.
            await self.channel_layer.group_discard(group, self.channel_name)
            await self.channel_layer.group_discard(user_group, self.channel_name)
            await self.channel_layer.group_add(self.group, self.channel_name)
            await self.channel_layer.group_add(self.user_group, self.channel_name)
        telemetry.connection_opened()
        await self.accept()

    async def disconnect(self, code: int) -> None:
        if self.group is not None:
            await self.channel_layer.group_discard(self.group, self.channel_name)
            if self.user_group is not None:
                await self.channel_layer.group_discard(
                    self.user_group, self.channel_name
                )
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

    async def run_access_removed(self, message: dict[str, Any]) -> None:
        await self.close(code=ACCESS_REMOVED)


class EchoConsumer(AsyncJsonWebsocketConsumer):  # type: ignore[misc]
    """Test-only: says who signed in, then repeats what it is sent."""

    async def connect(self) -> None:
        await self.accept()
        await self.send_json({"type": "hello", "user_id": str(self.scope["user"].pk)})

    async def receive_json(self, content: Any, **kwargs: Any) -> None:
        await self.send_json({"type": "echo", "data": content})
