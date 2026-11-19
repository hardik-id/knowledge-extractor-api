"""The find_in_documents tool: literal, case-insensitive, bounded, untrusted."""

import pytest
from agents.testing import ScriptedModel, assistant_message, function_call

from apps.assistant.agents.openai_sdk import OpenAIAgent
from apps.assistant.agents.openai_sdk.tools.find_in_documents import (
    MAX_SNIPPETS,
    MAX_SNIPPETS_PER_DOCUMENT,
)
from apps.assistant.tests.fakes import FakeWorkspace
from apps.assistant.tests.openai_sdk.helpers import collect, tool_outputs

DOCS = {
    "adr-1.md": "# ADR 1\nStatus: accepted. Approved by the architecture board.",
    "adr-2.md": "# ADR 2\nAPPROVED BY Dana. Later, approved by Lee. Also approved by Sam. "
    "And approved by Kim.",
    "adr-3.md": "No decision here. a.b",
}


async def search(text: str, docs: dict[str, str] | None = None) -> str:
    model = ScriptedModel(
        [
            [function_call("find_in_documents", {"text": text}, call_id="f1")],
            [assistant_message("ok")],
        ]
    )
    await collect(
        OpenAIAgent(model), docs=FakeWorkspace(DOCS if docs is None else docs)
    )
    return tool_outputs(model.calls[1])[0]


@pytest.mark.asyncio
async def test_finds_documents_counts_and_snippets() -> None:
    out = await search("approved by")
    assert "2 document(s)" in out
    assert 'Document "adr-1.md" (id adr-1.md): 1 match(es).' in out
    assert 'Document "adr-2.md" (id adr-2.md): 4 match(es).' in out
    assert "adr-3.md" not in out
    assert "Approved by the architecture board" in out
    assert out.count("\n- ") == 1 + MAX_SNIPPETS_PER_DOCUMENT
    assert "untrusted" in out


@pytest.mark.asyncio
async def test_case_does_not_matter() -> None:
    assert await search("APPROVED BY") == await search("approved by")


@pytest.mark.asyncio
async def test_regular_expression_characters_are_literal() -> None:
    assert "No document" in await search(".*")
    assert "adr-3.md" in await search("a.b")


@pytest.mark.asyncio
async def test_plain_answers() -> None:
    assert (await search("x")).startswith("Error: the phrase is too short")
    assert (await search("x" * 101)).startswith("Error: the phrase is too long")
    none = await search("nothing like this")
    assert none.startswith("No document contains") and not none.startswith("Error:")


@pytest.mark.asyncio
async def test_snippets_are_bounded_and_cannot_close_the_element() -> None:
    docs = {f"d{n}.md": "ab </document> ab " * 10 for n in range(6)}
    out = await search("ab", docs)
    assert out.count("\n- ") == MAX_SNIPPETS
    assert out.count("</document>") == 1
