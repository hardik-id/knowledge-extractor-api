"""Spans and metrics of the assistant (docs/observability.md).

Never recorded here: the message text, the reply, the prompt, the definition or
a proposal. Only ids, counts, names of things and outcomes.
"""

import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from opentelemetry import metrics
from opentelemetry.trace import Span, SpanKind

from apps.core import telemetry

SCOPE = "apps.assistant"

# How a reply job ended.
DONE = "done"  # the reply is complete
FAILED = "failed"  # the agent raised; the reply ended with the apology
CLOSED = "closed"  # someone else closed the reply while it was written
SKIPPED = "skipped"  # nothing to do: the reply was gone or done

# How a tool call ended.
OK = "ok"  # the tool answered
ERROR = "error"  # the tool raised, or answered with an `Error:` text
REFUSED = "refused"  # over the budget of tool calls: the tool did not run


@dataclass(frozen=True)
class _Instruments:
    replies: metrics.Counter
    duration: metrics.Histogram
    tool_calls: metrics.Counter


@lru_cache
def _instruments(provider: metrics.MeterProvider) -> _Instruments:
    meter = provider.get_meter(SCOPE)
    return _Instruments(
        replies=meter.create_counter(
            "assistant.replies",
            unit="{reply}",
            description="Reply jobs finished, by outcome and kind of agent.",
        ),
        duration=meter.create_histogram(
            "assistant.reply.duration",
            unit="s",
            description="How long a reply job took, by outcome and kind of agent.",
        ),
        tool_calls=meter.create_counter(
            "assistant.tool.calls",
            unit="{call}",
            description="Tool calls of the agent, by tool and outcome.",
        ),
    )


class ReplyTrace:
    """What one reply job did, collected for its span and its metrics."""

    def __init__(self, span: Span, agent: str) -> None:
        self.span = span
        self.agent = agent
        self.outcome = DONE
        self.deltas = 0
        self.proposed = False

    def started(self, run_id: Any) -> None:
        self.span.set_attribute("assistant.run_id", str(run_id))

    def failed(self, error: BaseException) -> None:
        self.outcome = FAILED
        telemetry.fail_span(self.span, error)

    def delta(self) -> None:
        self.deltas += 1

    def proposal(self) -> None:
        self.proposed = True


@contextmanager
def reply_span(message_id: Any, agent: str) -> Iterator[ReplyTrace]:
    """The `assistant.reply` span of one reply job, and its metrics when it ends."""
    started = time.perf_counter()
    tracer = telemetry.get_tracer(SCOPE)
    with tracer.start_as_current_span(
        "assistant.reply",
        attributes={"assistant.message_id": str(message_id), "assistant.agent": agent},
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        reply = ReplyTrace(span, agent)
        try:
            yield reply
        except BaseException as error:
            reply.failed(error)
            raise
        finally:
            span.set_attribute("assistant.outcome", reply.outcome)
            span.set_attribute("assistant.deltas", reply.deltas)
            span.set_attribute("assistant.proposed", reply.proposed)
            attributes = {"outcome": reply.outcome, "agent": agent}
            instruments = _instruments(telemetry.meter_provider())
            instruments.replies.add(1, attributes)
            instruments.duration.record(time.perf_counter() - started, attributes)


class ModelCall:
    """One call to a language model, for the GenAI attributes of its span."""

    def __init__(self, span: Span) -> None:
        self.span = span

    def response(
        self,
        *,
        model: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
    ) -> None:
        """What the SDK reported. Anything it did not report is left out."""
        if model is not None:
            self.span.set_attribute("gen_ai.response.model", model)
        if input_tokens is not None:
            self.span.set_attribute("gen_ai.usage.input_tokens", input_tokens)
        if output_tokens is not None:
            self.span.set_attribute("gen_ai.usage.output_tokens", output_tokens)


@contextmanager
def model_call(
    *, system: str, model: str, operation: str = "chat"
) -> Iterator[ModelCall]:
    """A client span for one model call, with OpenTelemetry's GenAI attributes.

    For an agent that talks to a language model: wrap each call, and report the
    tokens the SDK returns with `ModelCall.response`. `system` is the provider
    (`openai`), `model` the model asked for. The prompt and the completion are
    never attributes.
    """
    tracer = telemetry.get_tracer(SCOPE)
    with tracer.start_as_current_span(
        f"{operation} {model}",
        kind=SpanKind.CLIENT,
        attributes={
            "gen_ai.operation.name": operation,
            "gen_ai.system": system,
            "gen_ai.request.model": model,
        },
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        try:
            yield ModelCall(span)
        except BaseException as error:
            telemetry.fail_span(span, error)
            raise


class ToolCall:
    """One tool call, for its span: the outcome and the size of the result."""

    def __init__(self, span: Span) -> None:
        self.span = span
        self.outcome = ERROR  # until the call says how it ended
        self.size = 0

    def finished(self, outcome: str, size: int) -> None:
        self.outcome = outcome
        self.size = size


@contextmanager
def tool_call(name: str) -> Iterator[ToolCall]:
    """The `assistant.tool` span of one tool call, and its count when it ends.

    Never the arguments or the result: the name of the tool, the outcome, the
    number of characters returned. The duration is the span's own.
    """
    tracer = telemetry.get_tracer(SCOPE)
    with tracer.start_as_current_span(
        "assistant.tool",
        attributes={"assistant.tool.name": name},
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        call = ToolCall(span)
        try:
            yield call
        except BaseException as error:
            telemetry.fail_span(span, error)
            raise
        finally:
            span.set_attribute("assistant.tool.outcome", call.outcome)
            span.set_attribute("assistant.tool.result_chars", call.size)
            instruments = _instruments(telemetry.meter_provider())
            instruments.tool_calls.add(1, {"tool": name, "outcome": call.outcome})
