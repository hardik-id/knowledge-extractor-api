from typing import Any

from channels.generic.websocket import AsyncJsonWebsocketConsumer


class EchoConsumer(AsyncJsonWebsocketConsumer):  # type: ignore[misc]
    """Test-only: says who signed in, then repeats what it is sent."""

    async def connect(self) -> None:
        await self.accept()
        await self.send_json({"type": "hello", "user_id": str(self.scope["user"].pk)})

    async def receive_json(self, content: Any, **kwargs: Any) -> None:
        await self.send_json({"type": "echo", "data": content})
