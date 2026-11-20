"""Scenarios: a fake model follows a script and the real tools answer it.

They test that results reach the model, the order of the calls, the budget and the
single proposal. They say nothing about how good a real model's answers are.
"""

from typing import Any

import pytest
from agents.testing import ScriptedModel, assistant_message, function_call

from apps.assistant.agents.base import (
    AgentEvent,
    FileRecords,
    RecordView,
    ToolUsed,
    ValueView,
)
from apps.assistant.agents.openai_sdk import OpenAIAgent
from apps.assistant.agents.openai_sdk.tools._shared import MAX_TOOL_CALLS
from apps.assistant.proposal import Proposal
from apps.assistant.tests.fakes import FakeWorkspace
from apps.assistant.tests.openai_sdk.helpers import (
    collect,
    proposal_args,
    propose,
    split,
    tool_outputs,
)
from apps.assistant.tests.test_scripted import adr, bare, validated

DOCS = {
    "adr-1.md": "# Decisions\n\n## ADR-1: Use Postgres\n\n**Status:** accepted\n"
    "**Owner:** Dana\n",
    "adr-2.md": "# Decisions\n\n## ADR-2: Use Redis\n\n**Status:** proposed\n"
    "**Owner:** Lee\n",
}


def called(events: list[AgentEvent]) -> list[tuple[str, str]]:
    return [(e.name, e.outcome) for e in events if isinstance(e, ToolUsed)]


@pytest.mark.asyncio
async def test_what_can_i_extract_on_an_empty_definition() -> None:
    previewed = [
        RecordView(
            validated(adr())["record_types"][0]["id"],
            "llm",
            "suggested",
            [ValueView("title", "Use Postgres", "llm", "suggested", True)],
        )
    ]
    model = ScriptedModel(
        [
            [function_call("survey_documents", {}, call_id="c1")],
            [
                function_call(
                    "outline_document", {"document_id": "adr-1.md"}, call_id="c2"
                )
            ],
            [
                function_call(
                    "preview_extraction",
                    {"definition": validated(adr()), "document_id": "adr-1.md"},
                    call_id="c3",
                )
            ],
            [
                assistant_message("Each document holds decisions. I suggest this. "),
                propose(proposal_args()),
            ],
            [assistant_message("Apply it if it looks right.")],
        ]
    )
    events = await collect(
        OpenAIAgent(model),
        "What can I extract from these documents?",
        docs=FakeWorkspace(DOCS, previewed=previewed),
    )
    model.assert_complete()
    assert called(events) == [
        ("survey_documents", "ok"),
        ("outline_document", "ok"),
        ("preview_extraction", "ok"),
        ("propose_definition", "ok"),
    ]
    assert "ADR-#: …" in tool_outputs(model.calls[1])[-1], (
        "the survey reached the model"
    )
    assert "Owner" in tool_outputs(model.calls[2])[-1], "the outline reached the model"
    assert "1 records found" in tool_outputs(model.calls[3])[-1], (
        "the preview reached the model"
    )
    text, proposals = split(events)
    assert len(proposals) == 1 and events[-1] is proposals[0]
    assert text.startswith("Each document holds decisions.")


@pytest.mark.asyncio
async def test_is_there_an_owner_anywhere_answers_without_a_proposal() -> None:
    model = ScriptedModel(
        [
            [function_call("find_in_documents", {"text": "owner"}, call_id="c1")],
            [assistant_message("Yes: both documents name an owner, Dana and Lee.")],
        ]
    )
    events = await collect(
        OpenAIAgent(model), "Is there an owner anywhere?", docs=FakeWorkspace(DOCS)
    )
    model.assert_complete()
    assert called(events) == [("find_in_documents", "ok")]
    out = tool_outputs(model.calls[1])[-1]
    assert "2 document(s) contain the phrase" in out and "Dana" in out
    text, proposals = split(events)
    assert proposals == [] and "Dana and Lee" in text


@pytest.mark.asyncio
async def test_what_should_i_improve_after_a_run_summarizes_then_proposes() -> None:
    extracted = [
        FileRecords(
            "adr-1.md",
            "adr-1.md",
            1,
            [
                RecordView(
                    "adr",
                    "llm",
                    "suggested",
                    [ValueView("owner", None, "llm", "suggested", True)],
                )
            ],
        )
    ]
    model = ScriptedModel(
        [
            [function_call("summarize_records", {}, call_id="c1")],
            [
                assistant_message("The owner was never found. "),
                propose(proposal_args()),
            ],
            [assistant_message("Apply it if you agree.")],
        ]
    )
    events = await collect(
        OpenAIAgent(model),
        "What should I improve?",
        definition=adr(),
        docs=FakeWorkspace(DOCS, extracted=extracted),
    )
    model.assert_complete()
    assert called(events) == [
        ("summarize_records", "ok"),
        ("propose_definition", "ok"),
    ]
    assert "adr-1.md" in tool_outputs(model.calls[1])[-1]
    _, proposals = split(events)
    assert len(proposals) == 1


@pytest.mark.asyncio
async def test_only_the_first_proposal_is_kept_and_the_budget_is_enforced() -> None:
    steps: list[Any] = [
        [propose(proposal_args(), call_id="p0")],
        [propose(proposal_args(bare()), call_id="p1")],
    ]
    steps += [
        [function_call("survey_documents", {}, call_id=f"s{i}")]
        for i in range(MAX_TOOL_CALLS)
    ]
    steps.append([assistant_message("Stopping.")])
    model = ScriptedModel(steps)
    events = await collect(
        OpenAIAgent(model, max_turns=MAX_TOOL_CALLS + 4),
        docs=FakeWorkspace(DOCS),
    )
    proposals = [e for e in events if isinstance(e, Proposal)]
    assert len(proposals) == 1
    assert proposals[0].definition.model_dump() == validated(adr()), "the first one"
    outcomes = [o for n, o in called(events)]
    assert outcomes[:2] == ["ok", "error"], "a second proposal is refused"
    assert outcomes[-1] == "refused", "past the budget a call is refused"
