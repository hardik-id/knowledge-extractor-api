"""Print the live events of a run, one JSON line each, until Ctrl+C.

    TOKEN=$(make -s token) uv run python scripts/watch_run.py <run_id>

Asks for a fresh socket ticket (docs/realtime.md), opens /ws/runs/<run_id>/ and
prints every frame. Needs a dev or Entra access token in --token or $TOKEN.
websockets is installed with uvicorn[standard].
"""

import argparse
import asyncio
import json
import os
import sys
import urllib.request

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

CLOSE_CODES = {4401: "ticket refused", 4404: "run not found (not yours, or deleted)"}


def fetch_ticket(base_url: str, token: str) -> str:
    request = urllib.request.Request(  # noqa: S310  # a local URL given by the person running it
        f"{base_url}/api/v1/ws-ticket",
        method="POST",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
        ticket: str = json.load(response)["ticket"]
    return ticket


async def watch(base_url: str, token: str, run_id: str) -> int:
    ws_url = "ws" + base_url.removeprefix("http")
    ticket = fetch_ticket(base_url, token)
    async with connect(f"{ws_url}/ws/runs/{run_id}/?ticket={ticket}") as socket:
        print(f"watching run {run_id}, Ctrl+C to stop", file=sys.stderr, flush=True)
        try:
            async for frame in socket:
                print(frame, flush=True)
        except ConnectionClosed as closed:
            code = closed.rcvd.code if closed.rcvd else 1006
            print(f"closed {code}: {CLOSE_CODES.get(code, '')}", file=sys.stderr)
            return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("run_id")
    parser.add_argument("--token", default=os.environ.get("TOKEN"))
    parser.add_argument(
        "--base-url", default=os.environ.get("API_URL", "http://localhost:8000")
    )
    args = parser.parse_args()
    if not args.token:
        parser.error("give --token or set TOKEN (make token prints one)")
    try:
        return asyncio.run(watch(args.base_url.rstrip("/"), args.token, args.run_id))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
