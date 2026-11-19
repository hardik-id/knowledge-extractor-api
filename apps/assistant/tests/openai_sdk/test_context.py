"""ReplyContext starts empty."""

from apps.assistant.agents.openai_sdk.context import ReplyContext
from apps.assistant.tests.fakes import FakeWorkspace


def test_a_new_context_has_no_proposal_reads_rejections_or_tool_calls() -> None:
    context = ReplyContext(workspace=FakeWorkspace(), refs=[])
    assert (context.proposal, context.reads, context.rejected, context.tool_calls) == (
        None,
        0,
        0,
        0,
    )
