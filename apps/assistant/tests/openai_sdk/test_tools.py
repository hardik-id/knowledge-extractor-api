"""TOOLS: adding a tool is one module and one line."""

from typing import Any

import pytest
from agents import FunctionTool
from agents.testing import ScriptedModel, assistant_message, function_call

from apps.assistant.agents.openai_sdk import OpenAIAgent
from apps.assistant.agents.openai_sdk import agent as agent_module
from apps.assistant.agents.openai_sdk.agent import build_agent
from apps.assistant.agents.openai_sdk.tools import TOOLS
from apps.assistant.agents.openai_sdk.tools._shared import error
from apps.assistant.tests.openai_sdk.helpers import (
    collect,
    split,
    tool_outputs,
)


def test_every_tool_is_one_function_tool_with_a_unique_name() -> None:
    names = [t.name for t in TOOLS]
    assert all(isinstance(t, FunctionTool) for t in TOOLS)
    assert len(set(names)) == len(names)


async def _echo(ctx: Any, arguments: str) -> str:
    return error("echo is a throwaway") if not arguments else "echo"


THROWAWAY = FunctionTool(
    name="echo",
    description="A throwaway tool.",
    params_json_schema={
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    },
    on_invoke_tool=_echo,
    strict_json_schema=True,
)


@pytest.mark.asyncio
async def test_a_tool_is_added_by_one_module_and_one_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(agent_module, "TOOLS", [*TOOLS, THROWAWAY])
    assert {t.name for t in build_agent(ScriptedModel([])).tools} == {
        "read_document",
        "find_in_documents",
        "preview_extraction",
        "propose_definition",
        "outline_document",
        "summarize_records",
        "survey_documents",
        "echo",
    }
    model = ScriptedModel(
        [[function_call("echo", {}, call_id="e1")], [assistant_message("done")]]
    )
    events = await collect(OpenAIAgent(model))
    assert split(events)[0] == "done"
    assert any(t.name == "echo" for t in model.calls[0].tools)
    assert tool_outputs(model.calls[1]) == ["echo"]
