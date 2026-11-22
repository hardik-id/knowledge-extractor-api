"""OpenAIAgent: runs one reply, turns SDK events into TextDelta and Proposal,
keeps the limits and the endings.

The model streams its explanation, which becomes ``TextDelta``s; the first valid
proposal is the only one that reaches the person, after the text. The SDK's own
trace export to OpenAI is switched off.
"""

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from typing import Any, cast

import structlog
from agents import (
    AgentsException,
    MaxTurnsExceeded,
    Model,
    RunConfig,
    Runner,
    set_tracing_disabled,
)
from agents.stream_events import RawResponsesStreamEvent
from azure.core.exceptions import AzureError
from openai import APIError, AsyncOpenAI

from apps.assistant.agents.base import (
    AgentEvent,
    Message,
    TextDelta,
    ToolUsed,
    Workspace,
)
from apps.assistant.agents.openai_sdk.agent import build_agent
from apps.assistant.agents.openai_sdk.context import ReplyContext
from apps.assistant.agents.openai_sdk.inputs import build_input
from apps.core.llm import connect, missing_settings
from apps.extraction.definition import Draft

log = structlog.get_logger(__name__)

# Our own spans come from OpenTelemetry; the SDK never exports traces to OpenAI.
set_tracing_disabled(True)

# Limits of one reply.
MAX_TURNS = 8  # model calls, tool round trips included
REPLY_TIMEOUT_SECONDS = 120.0  # below ASSISTANT_REPLY_TIMEOUT_SECONDS

NOT_CONFIGURED = (
    "No language model is configured for the assistant yet, so I cannot answer."
)
CUT_OFF = "I had to stop here because this reply took too long; please ask again, perhaps for less at once."
MODEL_FAILED = "I could not reach the language model, so I could not finish this reply."


def _failure(error: BaseException) -> dict[str, Any]:
    """What is logged about a failure: its kind, never its message (it can quote the request)."""
    return {
        "error": type(error).__name__,
        "status_code": getattr(error, "status_code", None),
    }


def _unannounced(state: ReplyContext) -> list[ToolUsed]:
    """The tool calls that ended since the last look, each once."""
    new = state.used[state.announced :]
    state.announced = len(state.used)
    return new


class OpenAIAgent:
    """The assistant as an LLM agent. ``model`` replaces the configured one (tests pass a fake)."""

    def __init__(
        self,
        model: Model | None = None,
        *,
        max_turns: int = MAX_TURNS,
        timeout: float = REPLY_TIMEOUT_SECONDS,
    ) -> None:
        self._model = model
        self._max_turns = max_turns
        self._timeout = timeout

    async def reply(
        self,
        text: str,
        definition: Draft,
        history: list[Message],
        workspace: Workspace,
    ) -> AsyncIterator[AgentEvent]:
        client: AsyncOpenAI | None = None
        model = self._model
        if model is None:
            missing = missing_settings()
            if missing:
                log.warning("assistant_not_configured", missing=missing)
                yield TextDelta(NOT_CONFIGURED)
                return
            model, client = connect()
        try:
            refs = await workspace.documents()
            state = ReplyContext(workspace=workspace, refs=refs)
            async for event in self._run(model, state, text, definition, history):
                yield event
        finally:
            if client is not None:
                await client.close()

    async def _run(
        self,
        model: Model,
        state: ReplyContext,
        text: str,
        definition: Draft,
        history: list[Message],
    ) -> AsyncIterator[AgentEvent]:
        result = Runner.run_streamed(
            build_agent(model),
            build_input(text, definition, history, state.refs),
            context=state,
            max_turns=self._max_turns,
            run_config=RunConfig(
                tracing_disabled=True, trace_include_sensitive_data=False
            ),
        )
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._timeout
        events = cast(AsyncGenerator[Any], result.stream_events())
        wrote = False  # some text has gone out
        new_turn = False  # the model started another response since the last text
        ending: str | None = None
        try:
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise TimeoutError
                try:
                    event = await asyncio.wait_for(anext(events), remaining)
                except StopAsyncIteration:
                    break
                for used in _unannounced(state):
                    yield used
                if not isinstance(event, RawResponsesStreamEvent):
                    continue
                if event.data.type == "response.created":
                    new_turn = True
                elif event.data.type == "response.output_text.delta":
                    delta: str = event.data.delta
                    if not delta:
                        continue
                    if wrote and new_turn:
                        delta = f"\n\n{delta}"
                    new_turn = False
                    wrote = True
                    yield TextDelta(delta)
        except TimeoutError as error:
            log.warning("assistant_reply_cut_off", reason="timeout", **_failure(error))
            ending = CUT_OFF
        except MaxTurnsExceeded as error:
            log.warning(
                "assistant_reply_cut_off", reason="max_turns", **_failure(error)
            )
            ending = CUT_OFF
        except (APIError, AgentsException, AzureError) as error:
            # The model, the SDK or the Azure sign-in failed.
            log.warning("assistant_model_failed", **_failure(error))
            ending = MODEL_FAILED
        finally:
            result.cancel()
            await events.aclose()
        for used in _unannounced(state):
            yield used
        if state.rejected:
            log.info("assistant_proposals_rejected", count=state.rejected)
        if ending:
            yield TextDelta(f"\n\n{ending}" if wrote else ending)
        if state.proposal is not None:
            yield state.proposal
