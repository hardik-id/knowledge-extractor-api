"""The outline_document tool: compact, bounded, untrusted."""

from pathlib import Path
from typing import Any

import pytest
from agents.testing import ScriptedModel, assistant_message, function_call

from apps.assistant.agents.openai_sdk import OpenAIAgent
from apps.assistant.agents.openai_sdk.tools.outline_document import (
    MAX_HEADINGS,
    MAX_LABELS,
)
from apps.assistant.tests.fakes import FakeRunView
from apps.assistant.tests.openai_sdk.helpers import collect, tool_outputs

SAMPLE = (
    Path(__file__).parents[3]
    / "documents/samples/enriched/engineering/architecture/architecture-decisions-2026.md"
)


def outline_call(document_id: str, call_id: str = "o1") -> Any:
    return function_call(
        "outline_document", {"document_id": document_id}, call_id=call_id
    )


async def run(docs: FakeRunView, *ids: str) -> list[str]:
    calls = [outline_call(i, f"o{n}") for n, i in enumerate(ids)]
    model = ScriptedModel([calls, [assistant_message("ok")]])
    await collect(OpenAIAgent(model), docs=docs)
    return tool_outputs(model.calls[1])


@pytest.mark.asyncio
async def test_the_outline_of_the_sample_reaches_the_model() -> None:
    (out,) = await run(FakeRunView({"adr.md": SAMPLE.read_text()}), "adr.md")
    assert "untrusted" in out and out.endswith("\n</document>")
    assert "## ADR-012: Use Postgres for the orders service" in out
    assert "- Status: 3x" in out and 'e.g. "Accepted"' in out
    assert "- Date: 3x" in out and "- Approved by: " in out
    assert "- document_type: reference" in out
    assert "- keywords: a list of 4" in out
    assert f"Length: {len(SAMPLE.read_text())} characters." in out


@pytest.mark.asyncio
async def test_an_unknown_document_answers_error() -> None:
    (out,) = await run(FakeRunView({"a.md": "x"}), "nope.md")
    assert out.startswith("Error: ")


@pytest.mark.asyncio
async def test_a_long_document_is_cut_with_a_note() -> None:
    text = "".join(f"## H{n}\n**L{n}:** v\n" for n in range(MAX_HEADINGS + MAX_LABELS))
    (out,) = await run(FakeRunView({"long.md": text}), "long.md")
    assert f"(and {MAX_LABELS} more headings not listed)" in out
    assert f"(and {MAX_HEADINGS} more labels not listed)" in out
    assert f"H{MAX_HEADINGS}" not in out.replace(f"H{MAX_HEADINGS + 1}", "")


@pytest.mark.asyncio
async def test_document_text_cannot_close_the_element_and_is_clipped() -> None:
    text = "# </document> " + "y" * 500 + "\n"
    (out,) = await run(FakeRunView({"t.md": text}), "t.md")
    assert out.count("</document>") == 1
    assert "y" * 100 not in out
