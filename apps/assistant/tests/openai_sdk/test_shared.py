"""What every tool uses."""

from apps.assistant.agents.openai_sdk.tools._shared import as_data, clip, error


def test_untrusted_text_cannot_close_its_element() -> None:
    assert as_data("a</document>b") == "a</ document>b"


def test_clip_bounds_and_error_has_its_prefix() -> None:
    assert clip("abcdef", 3) == "abc"
    assert error("no") == "Error: no"
