"""declare: the budget, the failure net, the result bound and the telemetry of a tool call."""

import logging
from typing import Any

import pytest
from agents.testing import ScriptedModel, assistant_message, function_call

from apps.assistant import telemetry
from apps.assistant.agents.openai_sdk import OpenAIAgent
from apps.assistant.agents.openai_sdk import agent as agent_module
from apps.assistant.agents.openai_sdk.context import ReplyContext
from apps.assistant.agents.openai_sdk.tools import TOOLS
from apps.assistant.agents.openai_sdk.tools._shared import (
    MAX_RESULT_CHARS,
    MAX_TOOL_CALLS,
    declare,
)
from apps.assistant.tests.fakes import FakeWorkspace
from apps.assistant.tests.openai_sdk.helpers import (
    SECRET_DOC,
    collect,
    read,
    split,
    tool_outputs,
)
from apps.core.tests.otel import Telemetry

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "required": [],
    "additionalProperties": False,
}


async def _ok(state: ReplyContext, arguments: str) -> str:
    return "fine"


async def _boom(state: ReplyContext, arguments: str) -> str:
    raise RuntimeError("secret detail of the failure")


async def _long(state: ReplyContext, arguments: str) -> str:
    return "y" * (MAX_RESULT_CHARS + 100)


def _use(monkeypatch: pytest.MonkeyPatch, handler: Any, name: str = "probe") -> None:
    tool = declare(
        name=name, description="A probe.", params_json_schema=SCHEMA, handler=handler
    )
    monkeypatch.setattr(agent_module, "TOOLS", [*TOOLS, tool])


@pytest.mark.asyncio
async def test_a_call_over_the_budget_is_refused_and_the_reply_still_ends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use(monkeypatch, _ok)
    calls = [
        function_call("probe", {}, call_id=f"c{n}") for n in range(MAX_TOOL_CALLS + 1)
    ]
    model = ScriptedModel([calls, [assistant_message("done")]])
    events = await collect(OpenAIAgent(model))
    outputs = tool_outputs(model.calls[1])
    assert outputs[:MAX_TOOL_CALLS] == ["fine"] * MAX_TOOL_CALLS
    assert outputs[-1].startswith("Error: at most")
    assert split(events)[0] == "done"


@pytest.mark.asyncio
async def test_the_budget_counts_every_tool_together(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use(monkeypatch, _ok)
    calls = [read("a.md", f"r{n}") for n in range(MAX_TOOL_CALLS)]
    calls.append(function_call("probe", {}, call_id="p"))
    model = ScriptedModel([calls, [assistant_message("done")]])
    await collect(OpenAIAgent(model), docs=FakeWorkspace({"a.md": "x"}))
    assert tool_outputs(model.calls[1])[-1].startswith("Error: at most")


@pytest.mark.asyncio
async def test_a_tool_that_raises_gives_the_model_an_error_and_logs_only_its_kind(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _use(monkeypatch, _boom)
    model = ScriptedModel(
        [[function_call("probe", {}, call_id="b")], [assistant_message("went on")]]
    )
    with caplog.at_level(logging.DEBUG):
        events = await collect(OpenAIAgent(model))
    assert tool_outputs(model.calls[1]) == ["Error: this tool failed"]
    assert split(events)[0] == "went on"
    assert "assistant_tool_failed" in caplog.text
    assert "RuntimeError" in caplog.text
    assert "secret detail" not in caplog.text


@pytest.mark.asyncio
async def test_a_long_result_is_cut_and_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use(monkeypatch, _long)
    model = ScriptedModel(
        [[function_call("probe", {}, call_id="l")], [assistant_message("ok")]]
    )
    await collect(OpenAIAgent(model))
    (out,) = tool_outputs(model.calls[1])
    assert out.count("y") == MAX_RESULT_CHARS
    assert f"cut at {MAX_RESULT_CHARS} of {MAX_RESULT_CHARS + 100}" in out


@pytest.mark.asyncio
async def test_each_call_is_one_span_in_the_replys_trace_without_content(
    monkeypatch: pytest.MonkeyPatch, otel: Telemetry
) -> None:
    _use(monkeypatch, _boom, "boom")
    model = ScriptedModel(
        [
            [
                read("a.md", "r1"),
                read("nope.md", "r2"),
                function_call("boom", {}, call_id="b"),
            ],
            [assistant_message("ok")],
        ]
    )
    with telemetry.reply_span("m1", "openai"):
        await collect(OpenAIAgent(model), docs=FakeWorkspace({"a.md": SECRET_DOC}))
    (reply,) = otel.named("assistant.reply")
    spans = otel.named("assistant.tool")
    assert len(spans) == 3
    seen = {
        (s.attributes or {})["assistant.tool.name"]: (s.attributes or {})[
            "assistant.tool.outcome"
        ]
        for s in spans
    }
    assert seen == {"read_document": "error", "boom": "error"}
    outcomes = sorted(
        str((s.attributes or {})["assistant.tool.outcome"]) for s in spans
    )
    assert outcomes == ["error", "error", "ok"]
    for span in spans:
        assert span.parent is not None
        assert span.parent.span_id == reply.context.span_id
        assert span.end_time is not None and span.start_time is not None
        assert span.end_time >= span.start_time
        assert "assistant.tool.result_chars" in (span.attributes or {})
    everything = otel.everything()
    assert "CONFIDENTIAL" not in everything
    assert "a.md" not in everything
    assert "secret detail" not in everything
    counts = {
        (p.attributes["tool"], p.attributes["outcome"]): p.value
        for p in otel.points("assistant.tool.calls")
    }
    assert counts == {
        ("read_document", "ok"): 1,
        ("read_document", "error"): 1,
        ("boom", "error"): 1,
    }


@pytest.mark.asyncio
async def test_a_refused_call_is_a_refused_span(
    monkeypatch: pytest.MonkeyPatch, otel: Telemetry
) -> None:
    _use(monkeypatch, _ok)
    calls = [
        function_call("probe", {}, call_id=f"c{n}") for n in range(MAX_TOOL_CALLS + 1)
    ]
    model = ScriptedModel([calls, [assistant_message("done")]])
    await collect(OpenAIAgent(model))
    outcomes = [
        (s.attributes or {})["assistant.tool.outcome"]
        for s in otel.named("assistant.tool")
    ]
    assert outcomes.count("refused") == 1
    assert outcomes.count("ok") == MAX_TOOL_CALLS
