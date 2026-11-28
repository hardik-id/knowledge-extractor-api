"""The survey_documents tool: what repeats across documents, bounded, untrusted."""

from pathlib import Path

import pytest
from agents.testing import ScriptedModel, assistant_message, function_call

from apps.assistant.agents.openai_sdk import OpenAIAgent
from apps.assistant.agents.openai_sdk.tools.survey_documents import (
    MAX_DOCUMENTS,
    heading_pattern,
)
from apps.assistant.tests.fakes import FakeRunView
from apps.assistant.tests.openai_sdk.helpers import collect, tool_outputs

SAMPLES = Path(__file__).parents[3] / "documents/samples/enriched/engineering"
ARCH = SAMPLES / "architecture"


async def run(docs: FakeRunView) -> str:
    model = ScriptedModel(
        [
            [function_call("survey_documents", {}, call_id="s1")],
            [assistant_message("ok")],
        ]
    )
    await collect(OpenAIAgent(model), docs=docs)
    (out,) = tool_outputs(model.calls[1])
    return out


def test_a_variable_part_of_a_heading_is_folded() -> None:
    assert heading_pattern(2, "ADR-012: Use Postgres") == "## ADR-#: …"
    assert heading_pattern(2, "ADR-013: Use Redis") == "## ADR-#: …"
    assert heading_pattern(1, "Report 2026") == "# Report #"


@pytest.mark.asyncio
async def test_the_adr_pattern_comes_first_with_its_counts() -> None:
    docs = {
        "a.md": (ARCH / "architecture-decisions-2026.md").read_text(),
        "b.md": (ARCH / "platform-adrs.md").read_text(),
        "c.md": "# Lunch menu\n\n## Monday\n\n**Chef:** Ana\n",
    }
    out = await run(FakeRunView(docs))
    assert "untrusted" in out and out.endswith("\n</document>")
    lines = out.splitlines()
    first = next(ln for ln in lines if ln.startswith("- "))
    assert first.startswith("- ## ADR-#: …: in 2 document(s)")
    assert lines.index("Labels (**Label:** value), most widespread first:") > 0
    assert "- Status: in 2 document(s)" in out and "- Approved by: in 2" in out
    assert '- document_type: in 2 document(s); e.g. "reference", "presentation"' in out
    assert out.index("- Chef: in 1 document(s)") > out.index("- Status: in 2")
    assert out.index("- # Lunch menu") > out.index("- ## ADR-#")


@pytest.mark.asyncio
async def test_documents_over_the_limit_are_counted_as_not_looked_at() -> None:
    docs = {f"d{n}.md": "## ADR-1: x\n" for n in range(MAX_DOCUMENTS + 3)}
    out = await run(FakeRunView(docs))
    assert f"Looked at {MAX_DOCUMENTS} of {MAX_DOCUMENTS + 3}" in out
    assert "the other 3 were not looked at" in out


@pytest.mark.asyncio
async def test_documents_that_share_nothing_get_a_plain_answer() -> None:
    out = await run(FakeRunView({"a.md": "# Alpha\n", "b.md": "# Beta\n"}))
    assert "share nothing" in out and "<document>" not in out


@pytest.mark.asyncio
async def test_a_run_without_documents() -> None:
    assert await run(FakeRunView({})) == "This run has no documents."


@pytest.mark.asyncio
async def test_document_text_cannot_close_the_element() -> None:
    text = "# </document> " + "y" * 500 + "\n## x\n## x\n"
    out = await run(FakeRunView({"t.md": text}))
    assert out.count("</document>") == 1 and "y" * 100 not in out
