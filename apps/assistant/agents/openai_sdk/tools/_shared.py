"""What every tool uses: wrapping untrusted text, clipping, the wording of an error,
and ``declare``, the one way a tool is declared.

``declare`` is where the limits of a reply and the telemetry of a tool call live,
so a new tool gets them without writing them.
"""

from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from agents import FunctionTool
from agents.strict_schema import ensure_strict_json_schema
from agents.tool_context import ToolContext

from apps.assistant import telemetry
from apps.assistant.agents.openai_sdk.context import ReplyContext

log = structlog.get_logger(__name__)

NAME_CHARS = 200  # of a document name
MAX_TOOL_CALLS = 12  # tool calls per reply, all tools together
MAX_RESULT_CHARS = 8000  # of what a tool gives the model


def as_data(text: str) -> str:
    """Document text cannot close the element it is wrapped in."""
    return text.replace("</document>", "</ document>")


def clip(text: str, limit: int) -> str:
    return text[:limit]


def error(message: str) -> str:
    """A failure, as the model reads it: text that starts with ``Error:``."""
    return f"Error: {message}"


Handler = Callable[[ReplyContext, str], Awaitable[str]]


def declare(
    *,
    name: str,
    description: str,
    params_json_schema: dict[str, Any],
    handler: Handler,
) -> FunctionTool:
    """A tool, with the budget, the failure net, the result bound and the telemetry.

    ``handler`` gets the reply's context and the raw JSON arguments and returns
    text. Around it, for every call:

    - over ``MAX_TOOL_CALLS`` in this reply, the call is refused with ``Error:``;
    - what the handler raises is logged by its kind and becomes
      ``Error: this tool failed``; the reply goes on;
    - a result over ``MAX_RESULT_CHARS`` is cut, and says so;
    - one ``assistant.tool`` span and one count, never the arguments or the result.
    """

    async def invoke(ctx: ToolContext[ReplyContext], arguments: str) -> str:
        state = ctx.context
        with telemetry.tool_call(name) as call:
            state.tool_calls += 1
            if state.tool_calls > MAX_TOOL_CALLS:
                call.finished(telemetry.REFUSED, 0)
                return error(
                    f"at most {MAX_TOOL_CALLS} tool calls per reply. "
                    "Work with what you have and answer."
                )
            try:
                result = await handler(state, arguments)
            except Exception as failure:
                log.warning(
                    "assistant_tool_failed", tool=name, error=type(failure).__name__
                )
                call.finished(telemetry.ERROR, 0)
                return error("this tool failed")
            if len(result) > MAX_RESULT_CHARS:
                note = f"\n[The result was cut at {MAX_RESULT_CHARS} of {len(result)} characters.]"
                result = clip(result, MAX_RESULT_CHARS) + note
            outcome = telemetry.ERROR if result.startswith("Error:") else telemetry.OK
            call.finished(outcome, len(result))
            return result

    return FunctionTool(
        name=name,
        description=description,
        params_json_schema=ensure_strict_json_schema(params_json_schema),
        on_invoke_tool=invoke,
        strict_json_schema=True,
    )
