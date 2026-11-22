"""The system check of the assistant: a warning when the LLM agent has no model."""

from typing import Any

import anthropic
import pytest

from apps.assistant.checks import check_llm_settings
from apps.assistant.tests.openai_sdk.helpers import configure


class FakeCredentials:
    """What `anthropic.default_credentials()` returns, with no profile on disk."""


def anthropic_settings(settings: Any) -> None:
    settings.ANTHROPIC_API_KEY = ""
    settings.ANTHROPIC_BASE_URL = "https://api.anthropic.com/v1/"
    configure(settings, LLM_PROVIDER="anthropic", LLM_MODEL="claude-haiku-5-5")


def test_the_system_check_warns_only_for_openai_without_a_model(settings: Any) -> None:
    configure(settings)
    settings.ASSISTANT_AGENT = "scripted"
    assert check_llm_settings() == []
    settings.ASSISTANT_AGENT = "openai"
    [warning] = check_llm_settings()
    assert warning.id == "assistant.W001"
    assert "LLM_MODEL, OPENAI_API_KEY" in warning.msg
    assert not warning.is_serious()
    configure(settings, LLM_MODEL="gpt-x", OPENAI_API_KEY="sk-test")
    assert check_llm_settings() == []


def test_the_system_check_warns_for_anthropic_without_a_sign_in(
    settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    anthropic_settings(settings)
    settings.ASSISTANT_AGENT = "openai"
    monkeypatch.setattr(anthropic, "default_credentials", lambda: None)
    [warning] = check_llm_settings()
    assert warning.id == "assistant.W001"
    assert "ant auth login" in warning.msg
    monkeypatch.setattr(anthropic, "default_credentials", lambda: FakeCredentials())
    assert check_llm_settings() == []
