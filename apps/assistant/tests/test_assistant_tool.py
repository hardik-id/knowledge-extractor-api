"""assistant_tool: one tool by hand, with no model; ask_assistant shows the tool calls."""

from io import StringIO
from typing import Any

import pytest
from agents import FunctionTool
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.assistant.agents.openai_sdk.tools import TOOLS
from apps.documents import selectors as documents
from apps.runs.tests.factories import RunFactory, RunFileFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def run(user: Any) -> Any:
    run = RunFactory(owner=user)
    for doc in documents.list_documents(user)[:3]:
        RunFileFactory(run=run, source_ref=doc.id, name=doc.name)
    return run


def invoke(*args: str) -> str:
    out = StringIO()
    call_command("assistant_tool", *args, stdout=out)
    return out.getvalue()


def test_list_names_the_seven_tools_with_their_descriptions(settings: Any) -> None:
    settings.ASSISTANT_AGENT = "scripted"
    printed = invoke("--list")
    assert len(TOOLS) == 7
    for tool in TOOLS:
        assert isinstance(tool, FunctionTool)
        assert f"{tool.name}\n  {tool.description}" in printed


def test_survey_documents_prints_what_the_model_would_get(run: Any) -> None:
    printed = invoke("survey_documents", "--run", str(run.pk))
    assert "Heading patterns" in printed
    assert "<document>" in printed and "untrusted" in printed


def test_find_in_documents_takes_name_value_arguments(run: Any) -> None:
    printed = invoke("find_in_documents", "--run", str(run.pk), "text=owner")
    assert "document(s) contain the phrase" in printed
    assert "match(es)" in printed


def test_a_tool_error_is_printed_as_the_model_would_read_it(run: Any) -> None:
    assert invoke("find_in_documents", "--run", str(run.pk), "text=x").startswith(
        "Error:"
    )


def test_bad_input_is_a_clear_error(run: Any) -> None:
    with pytest.raises(CommandError, match="Name a tool"):
        invoke()
    with pytest.raises(CommandError, match="No tool 'nope'"):
        invoke("nope", "--run", str(run.pk))
    with pytest.raises(CommandError, match="--run"):
        invoke("survey_documents")
    with pytest.raises(CommandError, match="Run not found"):
        invoke("survey_documents", "--run", "not-a-uuid")
    with pytest.raises(CommandError, match="name=value"):
        invoke("find_in_documents", "--run", str(run.pk), "owner")
    with pytest.raises(CommandError, match="valid JSON"):
        invoke("preview_extraction", "--run", str(run.pk), "definition={oops")
