"""build_input: what the model is told besides the instructions."""

from apps.assistant.agents.base import DocumentRef, Message
from apps.assistant.agents.openai_sdk.inputs import HISTORY_MESSAGES, build_input
from apps.assistant.tests.test_scripted import bare
from apps.extraction.definition import Draft


def test_the_history_and_the_document_list_are_capped() -> None:
    history = [Message("user", f"m{n}") for n in range(50)]
    refs = [DocumentRef(id=f"d{n}", name=f"d{n}") for n in range(60)]
    items = build_input("hi", Draft.model_validate(bare()), history, refs)
    assert len(items) == HISTORY_MESSAGES + 1
    assert items[0]["content"] == "m30"  # type: ignore[typeddict-item]
    assert "- and 10 more" in items[-1]["content"]  # type: ignore[typeddict-item]
