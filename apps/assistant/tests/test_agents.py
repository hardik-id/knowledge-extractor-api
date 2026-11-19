"""The agent interface, the scripted agent as a stream, and the choice of agent."""

import copy
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured

from apps.assistant.agents.base import Agent, AgentEvent, Message, Proposal, TextDelta
from apps.assistant.agents.registry import check_settings, get_agent
from apps.assistant.agents.scripted import ScriptedAgent, split_into_deltas
from apps.assistant.tests.fakes import FakeAgent, FakeDocuments
from apps.assistant.tests.test_scripted import adr, assert_valid, bare
from apps.extraction.validation import validate_draft

Definition = dict[str, Any]

BARE_MESSAGES = [
    "Extract all ADRs",
    "Extract the policy requirements, suppliers must comply",
    "Find all invoices in these files",
    "hello",
]
ADR_MESSAGES = [
    "Add a field for approval date",
    "add title 2 as inferred",
    "add summary, summarise it",
    "add owner",
    "Drop the context field",
    "remove decided_on",
    "make status exact",
    "Make the title inferred",
    "rename decided on to Decision date",
    "split approver and approval date",
    "split owner and deadline",
    "split title and summary",
    "Decision can have several values",
    "approved by can have many values",
    "output as json",
    "output as csv",
    "output as markdown",
    "use status in the template",
    "what is the weather",
    "remove colour",
    "",
]


async def collect(
    agent: Agent,
    text: str,
    definition: Definition,
    history: list[Message] | None = None,
) -> list[AgentEvent]:
    stream = agent.reply(text, definition, history or [], FakeDocuments())
    return [event async for event in stream]


def split(events: list[AgentEvent]) -> tuple[list[TextDelta], list[Proposal]]:
    deltas = [e for e in events if isinstance(e, TextDelta)]
    proposals = [e for e in events if isinstance(e, Proposal)]
    return deltas, proposals


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("message", "definition"),
    [(m, bare()) for m in BARE_MESSAGES] + [(m, adr()) for m in ADR_MESSAGES],
)
async def test_a_reply_is_deltas_then_at_most_one_proposal(
    message: str, definition: Definition
) -> None:
    before = copy.deepcopy(definition)
    events = await collect(ScriptedAgent(), message, definition)
    deltas, proposals = split(events)
    assert len(deltas) >= 2
    assert len(proposals) <= 1
    assert events[: len(deltas)] == deltas, "the proposal comes after every delta"
    assert definition == before
    if proposals:
        validate_draft(proposals[0].definition)
        assert proposals[0].reasons
        if proposals[0].definition["record_types"]:
            assert_valid(proposals[0].definition)


@pytest.mark.asyncio
async def test_the_deltas_joined_are_the_whole_text() -> None:
    events = await collect(ScriptedAgent(), "Add a field for approval date", adr())
    deltas, proposals = split(events)
    assert "".join(d.text for d in deltas) == (
        'I added "Approval date" to ADR, copied exactly from the text. It is in the template too.'
    )
    assert len(proposals) == 1


@pytest.mark.asyncio
async def test_text_that_starts_and_ends_with_spaces_survives_the_split() -> None:
    for text in ["one two three four", " two  spaces\n and a newline ", "one", ""]:
        assert "".join(split_into_deltas(text)) == text


@pytest.mark.asyncio
async def test_a_message_that_changes_nothing_has_no_proposal() -> None:
    events = await collect(ScriptedAgent(), "what is the weather", adr())
    deltas, proposals = split(events)
    assert deltas
    assert proposals == []


@pytest.mark.asyncio
async def test_the_scripted_agent_ignores_history_and_makes_ids_from_the_given_function() -> (
    None
):
    counter = iter(range(1, 100))
    agent = ScriptedAgent(lambda: f"x-{next(counter)}")
    history = [Message("user", "hi"), Message("assistant", "hello")]
    events = await collect(agent, "Extract all ADRs", bare(), history)
    _, [proposal] = split(events)
    assert proposal.definition["record_types"][0]["id"] == "x-1"


@pytest.mark.asyncio
async def test_a_fake_agent_implements_the_interface() -> None:
    agent: Agent = FakeAgent()
    definition = adr()
    events = await collect(agent, "hi", definition)
    deltas, proposals = split(events)
    assert "".join(d.text for d in deltas) == "Hello, you said hi."
    assert proposals[0].definition == definition


@pytest.mark.asyncio
async def test_documents_can_be_read_through_the_interface() -> None:
    documents = FakeDocuments({"a.md": "alpha"})
    [ref] = await documents.list()
    assert ref.id == "a.md"
    assert await documents.read(ref.id) == "alpha"


# the choice of agent


def test_the_default_is_the_scripted_agent() -> None:
    assert isinstance(get_agent(), ScriptedAgent)


def test_a_dotted_path_picks_a_class(settings: Any) -> None:
    settings.ASSISTANT_AGENT = "apps.assistant.tests.fakes.FakeAgent"
    assert isinstance(get_agent(), FakeAgent)
    check_settings()


@pytest.mark.parametrize("value", ["gpt", "", "anthropic"])
def test_an_unknown_value_stops_the_app(settings: Any, value: str) -> None:
    settings.ASSISTANT_AGENT = value
    with pytest.raises(ImproperlyConfigured, match="ASSISTANT_AGENT"):
        check_settings()
    with pytest.raises(ImproperlyConfigured):
        get_agent()


def test_openai_is_known(settings: Any) -> None:
    settings.ASSISTANT_AGENT = "openai"
    check_settings()


def test_a_dotted_path_that_does_not_import_stops_the_app(settings: Any) -> None:
    settings.ASSISTANT_AGENT = "apps.assistant.nothing.Agent"
    with pytest.raises(ImproperlyConfigured, match="cannot be imported"):
        check_settings()
