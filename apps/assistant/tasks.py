"""The reply job: the agent writes the assistant's reply, and the run's sockets see it live.

Each part of the reply is stored first and announced after, so a client that
missed an event reads the same from ``GET .../assistant/messages``. A reply
always ends: if the agent fails, it ends with an apology (services.close_reply).
"""

from contextlib import aclosing
from typing import Any

import structlog
from asgiref.sync import async_to_sync, sync_to_async
from django.tasks import task

from apps.assistant import services
from apps.assistant.agents.base import Proposal, TextDelta
from apps.assistant.agents.registry import get_agent
from apps.extraction.validation import validate_draft
from apps.realtime import services as realtime

log = structlog.get_logger(__name__)


@task()
def write_reply(message_id: str) -> None:
    """Write assistant message ``message_id``. Does nothing when it is gone or done."""
    async_to_sync(_write_reply)(message_id)


async def _write_reply(message_id: str) -> None:
    request = await sync_to_async(services.start_reply)(message_id)
    if request is None:
        return
    try:
        if await _stream(message_id, request):
            await realtime.apublish_run_event(
                request.run_id, services.done_event(message_id)
            )
    except Exception:
        log.exception("assistant_reply_failed", message_id=message_id)
        await sync_to_async(services.close_reply)(message_id)


async def _stream(message_id: str, request: services.Request) -> bool:
    """Run the agent and store each event. False when someone else closed the reply."""
    agent = get_agent()
    stream = agent.reply(
        request.text, request.definition, request.history, request.documents
    )
    async with aclosing(stream) as events:  # type: ignore[type-var]
        async for event in events:
            if isinstance(event, TextDelta):
                if not event.text:
                    continue
                if not await sync_to_async(services.append_text)(
                    message_id, event.text
                ):
                    return False
                await realtime.apublish_run_event(
                    request.run_id, services.delta_event(message_id, event.text)
                )
            elif isinstance(event, Proposal):
                proposal = _proposal(event)
                if not await sync_to_async(services.set_proposal)(message_id, proposal):
                    return False
                await realtime.apublish_run_event(
                    request.run_id, services.proposal_event(message_id, proposal)
                )
    return bool(await sync_to_async(services.finish_reply)(message_id))


def _proposal(event: Proposal) -> dict[str, Any]:
    """The proposal as stored and sent: a valid draft and plain ``{path, reason}`` pairs."""
    return {
        "definition": validate_draft(event.definition),
        "reasons": [
            {"path": str(reason["path"]), "reason": str(reason["reason"])}
            for reason in event.reasons
        ],
    }
