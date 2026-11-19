"""The instructions name the tools and the untrusted text rule."""

from apps.assistant.agents.openai_sdk.instructions import INSTRUCTIONS


def test_the_instructions_name_both_tools_and_the_rule_about_documents() -> None:
    for word in ("propose_definition", "read_document", "untrusted"):
        assert word in INSTRUCTIONS
