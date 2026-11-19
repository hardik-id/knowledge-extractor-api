"""A small WebSocket test client over asgiref's ApplicationCommunicator.

``channels.testing`` would do this, but importing it needs daphne, a server this
project does not use.
"""

import json
from typing import Any
from urllib.parse import unquote, urlparse

from asgiref.testing import ApplicationCommunicator


class WebsocketCommunicator(ApplicationCommunicator):
    def __init__(
        self,
        application: Any,
        path: str,
        headers: list[tuple[bytes, bytes]] | None = None,
    ) -> None:
        parsed = urlparse(path)
        super().__init__(
            application,
            {
                "type": "websocket",
                "path": unquote(parsed.path),
                "query_string": parsed.query.encode("utf-8"),
                "headers": headers or [],
                "subprotocols": [],
            },
        )

    async def connect(self, timeout: float = 1) -> bool:
        """True when the socket is accepted, False when it is refused."""
        await self.send_input({"type": "websocket.connect"})
        response = await self.receive_output(timeout)
        if response["type"] == "websocket.close":
            return False
        assert response["type"] == "websocket.accept"
        return True

    async def send_json_to(self, data: Any) -> None:
        await self.send_input({"type": "websocket.receive", "text": json.dumps(data)})

    async def receive_json_from(self, timeout: float = 1) -> Any:
        response = await self.receive_output(timeout)
        assert response["type"] == "websocket.send", response
        return json.loads(response["text"])

    async def disconnect(self, code: int = 1000, timeout: float = 1) -> None:
        await self.send_input({"type": "websocket.disconnect", "code": code})
        await self.wait(timeout)
