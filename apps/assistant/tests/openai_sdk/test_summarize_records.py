"""The summarize_records tool: counts that add up, rejected examples as untrusted data."""

import pytest
from agents.testing import ScriptedModel, assistant_message, function_call

from apps.assistant.agents.base import FileRecords, RecordView, ValueView
from apps.assistant.agents.openai_sdk import OpenAIAgent
from apps.assistant.agents.openai_sdk.tools.summarize_records import (
    EXAMPLE_CHARS,
    EXAMPLES,
)
from apps.assistant.tests.fakes import FakeWorkspace
from apps.assistant.tests.openai_sdk.helpers import *  # noqa: F403
from apps.assistant.tests.openai_sdk.helpers import collect, tool_outputs


def value(
    field_id: str,
    text: str | None,
    review: str = "suggested",
    origin: str = "llm",
    anchored: bool = True,
) -> ValueView:
    return ValueView(field_id, text, origin, review, anchored)


def record(
    values: list[ValueView], review: str = "suggested", origin: str = "llm"
) -> RecordView:
    return RecordView("adr", origin, review, values)


async def summary(files: list[FileRecords]) -> str:
    model = ScriptedModel(
        [
            [function_call("summarize_records", {}, call_id="s1")],
            [assistant_message("ok")],
        ]
    )
    await collect(OpenAIAgent(model), docs=FakeWorkspace(extracted=files))
    return tool_outputs(model.calls[1])[0]


@pytest.mark.asyncio
async def test_nothing_extracted_is_a_plain_answer() -> None:
    for files in ([], [FileRecords("d1", "a.md", 1, [])]):
        out = await summary(files)
        assert not out.startswith("Error:")
        assert "Nothing has been extracted" in out


@pytest.mark.asyncio
async def test_counts_per_type_and_field_with_the_corrections() -> None:
    files = [
        FileRecords(
            "d1",
            "a.md",
            2,
            [
                record(
                    [value("title", "Use X", "accepted"), value("status", None)],
                    review="accepted",
                ),
                record(
                    [
                        value("title", "Bad </document> title", "rejected"),
                        value("status", "ok", anchored=False),
                    ]
                ),
                record(
                    [value("title", "By hand", "accepted", "human")],
                    "accepted",
                    "human",
                ),
            ],
        )
    ]
    out = await summary(files)
    assert (
        'Record type "adr": 3 records (2 accepted, 0 rejected, 1 suggested; 1 added by hand)'
        in out
    )
    assert (
        'Field "title": found in 3, not found in 0; 0 found but not anchored; values 2 accepted, 1 rejected, 0 suggested; 1 values added or changed by hand'
        in out
    )
    assert 'Field "status": found in 1, not found in 2; 1 found but not anchored' in out
    assert "rejected, for example: <document>Bad </ document> title</document>" in out
    assert out.count("</document>") == 2, "once for the run, once for the document"


@pytest.mark.asyncio
async def test_a_field_never_found_is_reported_as_such() -> None:
    out = await summary([FileRecords("d1", "a.md", 1, [record([value("date", None)])])])
    assert 'Field "date": never found in 1 records' in out


@pytest.mark.asyncio
async def test_rejected_examples_are_few_and_clipped() -> None:
    rejected = [value("title", "z" * 1000, "rejected") for _ in range(5)]
    out = await summary([FileRecords("d1", "a.md", 1, [record([v]) for v in rejected])])
    whole_run = out.split("Document ")[0]
    assert whole_run.count("rejected, for example") == EXAMPLES
    assert "z" * EXAMPLE_CHARS in out and "z" * (EXAMPLE_CHARS + 1) not in out


@pytest.mark.asyncio
async def test_found_plus_not_found_is_the_records_of_the_type() -> None:
    records = [
        record([value("a", "x")]),
        record([value("a", None), value("b", "y")]),
        record([value("b", None)]),
        record([]),
    ]
    out = await summary([FileRecords("d1", "a.md", 1, records)])
    assert "4 records" in out
    assert 'Field "a": found in 1, not found in 3' in out
    assert 'Field "b": found in 1, not found in 3' in out
