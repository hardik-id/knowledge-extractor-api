"""The reply job: the agent writes the assistant's reply, and the run's sockets see it live.

Each part of the reply is stored first and announced after, so a client that
missed an event reads the same from ``GET .../assistant/messages``. A reply
always ends: if the agent fails, it ends with an apology (services.close_reply).
"""

from contextlib import aclosing

import structlog
from asgiref.sync import async_to_sync, sync_to_async

from apps.assistant import services, telemetry
from apps.assistant.agents.base import TextDelta
from apps.assistant.agents.registry import agent_kind, get_agent
from apps.assistant.proposal import Proposal
from apps.core.jobs import job
from apps.realtime import services as realtime

log = structlog.get_logger(__name__)


@job()
def write_reply(message_id: str) -> None:
    """Write assistant message ``message_id``. Does nothing when it is gone or done.

    The job's span is ``assistant.reply`` (docs/observability.md).
    """
    with telemetry.reply_span(message_id, agent_kind()) as reply:
        async_to_sync(_write_reply)(message_id, reply)


async def _write_reply(message_id: str, reply: telemetry.ReplyTrace) -> None:
    request = await sync_to_async(services.start_reply)(message_id)
    if request is None:
        reply.outcome = telemetry.SKIPPED
        return
    reply.started(request.run_id)
    try:
        if await _stream(message_id, request, reply):
            await realtime.apublish_run_event(
                request.run_id, services.done_event(message_id)
            )
        else:
            reply.outcome = telemetry.CLOSED
    except Exception as error:
        log.exception("assistant_reply_failed", message_id=message_id)
        reply.failed(error)
        await sync_to_async(services.close_reply)(message_id)


async def _stream(
    message_id: str, request: services.Request, reply: telemetry.ReplyTrace
) -> bool:
    """Run the agent and store each event. False when someone else closed the reply."""
    agent = get_agent()
    stream = agent.reply(
        request.text, request.definition, request.history, request.workspace
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
                reply.delta()
                await realtime.apublish_run_event(
                    request.run_id, services.delta_event(message_id, event.text)
                )
            elif isinstance(event, Proposal):
                if not await sync_to_async(services.set_proposal)(message_id, event):
                    return False
                reply.proposal()
                await realtime.apublish_run_event(
                    request.run_id, services.proposal_event(message_id, event)
                )
    return bool(await sync_to_async(services.finish_reply)(message_id))
