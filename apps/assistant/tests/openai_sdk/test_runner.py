"""The runner: replies, limits, endings, and the whole path through the reply job."""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from io import StringIO
from typing import Any

import openai
import pytest
from agents import ModelTracing
from agents.testing import (
    ModelCall,
    ModelStep,
    ScriptedModel,
    assistant_message,
)
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.assistant.agents.base import Message, TextDelta
from apps.assistant.agents.openai_sdk import OpenAIAgent
from apps.assistant.agents.openai_sdk.inputs import HISTORY_CHARS
from apps.assistant.agents.openai_sdk.runner import (
    CUT_OFF,
    MODEL_FAILED,
    NOT_CONFIGURED,
)
from apps.assistant.agents.registry import get_agent
from apps.assistant.tests.fakes import FakeWorkspace
from apps.assistant.tests.openai_sdk.helpers import *  # noqa: F403
from apps.assistant.tests.openai_sdk.helpers import (
    REQUEST,
    ScriptedOpenAIAgent,
    collect,
    configure,
    duplicate_keys,
    proposal_args,
    propose,
    read,
    record_events,
    split,
    tool_outputs,
)
from apps.assistant.tests.test_scripted import adr, bare
from apps.core.logging import build_logging_config
from apps.documents import selectors as documents
from apps.extraction.validation import validate_draft
from apps.runs.tests.factories import RunFactory, RunFileFactory


@pytest.mark.asyncio
async def test_deltas_then_one_valid_proposal_after_them() -> None:
    model = ScriptedModel(
        [
            [
                assistant_message("I set this up for decision records. "),
                propose(proposal_args()),
            ],
            [assistant_message("Apply it if it looks right.")],
        ]
    )
    events = await collect(OpenAIAgent(model))
    model.assert_complete()
    text, [proposal] = split(events)
    assert text == (
        "I set this up for decision records. \n\nApply it if it looks right."
    )
    assert events[-1] is proposal, "the proposal comes after every delta"
    assert len([e for e in events if isinstance(e, TextDelta)]) == 2
    assert validate_draft(proposal.definition) == proposal.definition
    assert proposal.definition == validate_draft(adr()), "existing ids are kept"
    assert proposal.reasons == [
        {"path": "ADR", "reason": "Looks for decision records."}
    ]
    assert tool_outputs(model.calls[1])[0].startswith("Accepted.")


@pytest.mark.asyncio
async def test_a_reply_without_a_proposal() -> None:
    model = ScriptedModel([[assistant_message("Which documents do you mean?")]])
    events = await collect(OpenAIAgent(model))
    assert events == [TextDelta("Which documents do you mean?")]


@pytest.mark.asyncio
async def test_a_model_that_never_stops_is_cut_off_at_the_turn_limit() -> None:
    docs = FakeWorkspace({"a.md": "alpha"})
    model = ScriptedModel(
        [
            [assistant_message("Let me look."), read("missing", f"r{n}")]
            for n in range(10)
        ]
    )
    events = await collect(OpenAIAgent(model, max_turns=3), docs=docs)
    assert len(model.calls) == 3
    text, proposals = split(events)
    assert text.endswith(f"\n\n{CUT_OFF}")
    assert proposals == []


@pytest.mark.asyncio
async def test_a_model_that_hangs_is_cut_off_at_the_timeout() -> None:
    async def forever(call: ModelCall) -> AsyncIterator[Any]:
        await asyncio.sleep(3600)
        yield  # pragma: no cover

    model = ScriptedModel([ModelStep.stream(forever)])
    events = await collect(OpenAIAgent(model, timeout=0.2))
    assert events == [TextDelta(CUT_OFF)]


@pytest.mark.asyncio
async def test_a_valid_proposal_made_before_the_cut_off_still_arrives() -> None:
    model = ScriptedModel(
        [[propose(proposal_args())]] + [[read("x", f"r{n}")] for n in range(5)]
    )
    events = await collect(OpenAIAgent(model, max_turns=2))
    text, [proposal] = split(events)
    assert text == CUT_OFF
    assert events[-1] is proposal


@pytest.mark.asyncio
async def test_a_failing_model_ends_the_reply_with_a_sentence_and_logs_no_details(
    caplog: pytest.LogCaptureFixture,
) -> None:
    error = openai.APIConnectionError(
        message="sk-secret-key leaked here", request=_request()
    )
    model = ScriptedModel([ModelStep.raise_error(error)])
    with caplog.at_level(logging.DEBUG):
        events = await collect(OpenAIAgent(model))
    assert events == [TextDelta(MODEL_FAILED)]
    assert "APIConnectionError" in caplog.text
    assert "sk-secret-key" not in caplog.text


def _request() -> Any:
    import httpx2

    return httpx2.Request("POST", "https://api.openai.com/v1/responses")


@pytest.mark.asyncio
async def test_the_model_gets_the_rules_the_definition_the_documents_and_the_history() -> (
    None
):
    model = ScriptedModel([[assistant_message("ok")]])
    docs = FakeWorkspace({"adrs/one.md": "alpha"})
    history = [Message("user", "earlier"), Message("assistant", "y" * 5000)]
    await collect(OpenAIAgent(model), "add owner", adr(), history, docs)
    [call] = model.calls
    assert call.tracing == ModelTracing.DISABLED
    assert call.model_settings.store is False
    instructions = call.system_instructions or ""
    assert "untrusted" in instructions
    assert "You propose, the person applies" in instructions
    assert {t.name for t in call.tools} == {
        "propose_definition",
        "read_document",
        "find_in_documents",
        "preview_extraction",
        "outline_document",
        "summarize_records",
    }
    earlier, long_turn, request = call.input
    assert earlier == {"role": "user", "content": "earlier"}
    assert len(long_turn["content"]) == HISTORY_CHARS
    content = request["content"]
    assert content.endswith("My request:\nadd owner")
    assert json.dumps(validate_draft(adr())["record_types"][0]["name"]) in content
    assert "- adrs/one.md: adrs/one.md" in content
    assert "alpha" not in content, "document text is read only through the tool"


@pytest.mark.asyncio
async def test_not_configured_answers_in_one_sentence_and_does_not_crash(
    settings: Any,
) -> None:
    configure(settings)
    events = await collect(OpenAIAgent())
    assert events == [TextDelta(NOT_CONFIGURED)]


def test_openai_is_a_built_in_agent(settings: Any) -> None:
    settings.ASSISTANT_AGENT = "openai"
    assert isinstance(get_agent(), OpenAIAgent)


def test_the_openai_client_and_the_sdk_never_log_below_info() -> None:
    config = build_logging_config("DEBUG", "console")
    for name in ("openai", "httpcore2", "httpx2"):
        assert config["loggers"][name]["level"] == "INFO"
    config = build_logging_config("WARNING", "console")
    assert config["loggers"]["openai"]["level"] == "WARNING"
    assert logging.getLogger("openai.agents").parent is logging.getLogger("openai")


@pytest.mark.django_db
def test_not_configured_through_the_api_gets_the_sentence_and_done(
    api_client: Any,
    user: Any,
    settings: Any,
    monkeypatch: pytest.MonkeyPatch,
    django_capture_on_commit_callbacks: Any,
) -> None:
    configure(settings)
    settings.ASSISTANT_AGENT = "openai"
    sent = record_events(monkeypatch)
    run = RunFactory(owner=user)
    api_client.force_authenticate(user)
    url = f"/api/v1/runs/{run.pk}/extraction/assistant/messages"
    with django_capture_on_commit_callbacks(execute=True):
        response = api_client.post(
            url, {"text": REQUEST, "definition": bare()}, format="json"
        )
        assert response.status_code == 201
    reply = api_client.get(url).json()["messages"][1]
    assert reply["text"] == NOT_CONFIGURED
    assert reply["status"] == "done"
    assert reply["proposal"] is None
    assert [e["type"] for e in sent] == ["assistant.delta", "assistant.done"]


@pytest.mark.django_db
def test_a_reply_through_the_job_logs_no_key_prompt_or_document_text(
    api_client: Any,
    user: Any,
    settings: Any,
    monkeypatch: pytest.MonkeyPatch,
    django_capture_on_commit_callbacks: Any,
    caplog: pytest.LogCaptureFixture,
) -> None:
    configure(settings, LLM_MODEL="gpt-x", OPENAI_API_KEY="sk-very-secret")
    [first, *_] = documents.list_documents(user)
    run = RunFactory(owner=user)
    RunFileFactory(run=run, source_ref=first.id, name=first.name)
    text = documents.read_document(user, first.id).text
    ScriptedOpenAIAgent.model = ScriptedModel(
        [
            [assistant_message("Let me read it."), read(first.id, "r1")],
            [propose(proposal_args(duplicate_keys()), "p1")],
            [propose(proposal_args(), "p2")],
            [assistant_message("Here is a proposal.")],
        ]
    )
    settings.ASSISTANT_AGENT = f"{ScriptedOpenAIAgent.__module__}.ScriptedOpenAIAgent"
    sent = record_events(monkeypatch)
    api_client.force_authenticate(user)
    url = f"/api/v1/runs/{run.pk}/extraction/assistant/messages"
    with (
        caplog.at_level(logging.DEBUG),
        django_capture_on_commit_callbacks(execute=True),
    ):
        response = api_client.post(
            url,
            {"text": "please find SECRET-PROMPT things", "definition": bare()},
            format="json",
        )
        assert response.status_code == 201
    reply = api_client.get(url).json()["messages"][1]
    assert reply["text"] == "Let me read it.\n\nHere is a proposal."
    assert reply["proposal"]["definition"] == validate_draft(adr())
    assert reply["status"] == "done"
    kinds = [e["type"] for e in sent]
    assert kinds[-2:] == ["assistant.proposal", "assistant.done"]
    sample = ScriptedOpenAIAgent.model.calls[1].input[-1]["output"]
    assert text[:200] in sample, "the model did get the document"
    logged = caplog.text
    assert "assistant_proposals_rejected" in logged
    for secret in ("sk-very-secret", "SECRET-PROMPT", text[:80], "Extract every"):
        assert secret not in logged


@pytest.mark.django_db
def test_ask_assistant_prints_the_deltas_and_the_proposal(settings: Any) -> None:
    ScriptedOpenAIAgent.model = ScriptedModel(
        [
            [assistant_message("Decision records it is."), propose(proposal_args())],
            [assistant_message("Done.")],
        ]
    )
    settings.ASSISTANT_AGENT = f"{ScriptedOpenAIAgent.__module__}.ScriptedOpenAIAgent"
    out = StringIO()
    call_command("ask_assistant", REQUEST, stdout=out)
    printed = out.getvalue()
    assert printed.startswith("Decision records it is.\n\nDone.\nProposal:\n")
    shown = json.loads(printed.split("Proposal:\n", 1)[1])
    assert validate_draft(shown["definition"]) == shown["definition"]
    assert shown["reasons"][0]["path"] == "ADR"


@pytest.mark.django_db
def test_ask_assistant_with_a_run_uses_its_definition_and_documents(
    settings: Any, user: Any
) -> None:
    [first, *_] = documents.list_documents(user)
    run = RunFactory(owner=user)
    RunFileFactory(run=run, source_ref=first.id, name=first.name)
    ScriptedOpenAIAgent.model = ScriptedModel(
        [[read(first.id, "r1")], [assistant_message("Nothing to change.")]]
    )
    settings.ASSISTANT_AGENT = f"{ScriptedOpenAIAgent.__module__}.ScriptedOpenAIAgent"
    out = StringIO()
    call_command("ask_assistant", "look", "--run", str(run.pk), stdout=out)
    assert out.getvalue() == "Nothing to change.\n(no proposal)\n"
    request = ScriptedOpenAIAgent.model.calls[0].input[-1]["content"]
    assert '"name": "ADR"' in request, "the run's definition"
    assert "<document>" in ScriptedOpenAIAgent.model.calls[1].input[-1]["output"]


@pytest.mark.django_db
def test_ask_assistant_with_the_scripted_agent_and_bad_input() -> None:
    out = StringIO()
    call_command("ask_assistant", "Extract all ADRs", stdout=out)
    assert "Proposal:" in out.getvalue()
    with pytest.raises(CommandError, match="Run not found"):
        call_command("ask_assistant", "hi", "--run", "not-a-uuid")
    with pytest.raises(CommandError):
        call_command("ask_assistant", "   ")
