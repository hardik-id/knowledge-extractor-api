"""Model access: missing settings, the two providers, the system check."""

from typing import Any

import pytest
from agents import OpenAIChatCompletionsModel, OpenAIResponsesModel

from apps.assistant.agents.openai_sdk import models
from apps.assistant.agents.openai_sdk.models import connect, missing_settings
from apps.assistant.checks import check_llm_settings
from apps.assistant.tests.openai_sdk.helpers import configure


def test_missing_settings_per_provider(settings: Any) -> None:
    configure(settings)
    assert missing_settings() == ["LLM_MODEL", "OPENAI_API_KEY"]
    configure(settings, LLM_MODEL="gpt-x", OPENAI_API_KEY="k")
    assert missing_settings() == []
    configure(settings, LLM_PROVIDER="azure", LLM_MODEL="deployment")
    assert missing_settings() == ["AZURE_OPENAI_ENDPOINT"]
    configure(
        settings,
        LLM_PROVIDER="azure",
        LLM_MODEL="deployment",
        AZURE_OPENAI_ENDPOINT="https://x.openai.azure.com/",
    )
    assert missing_settings() == []
    configure(settings, LLM_PROVIDER="anthropic", LLM_MODEL="m")
    assert missing_settings() == ["LLM_PROVIDER (openai or azure)"]


@pytest.mark.asyncio
async def test_openai_connects_with_the_key_and_the_responses_api(
    settings: Any,
) -> None:
    configure(settings, LLM_MODEL="gpt-x", OPENAI_API_KEY="sk-test")
    model, client = connect()
    assert isinstance(model, OpenAIResponsesModel)
    assert model.model == "gpt-x"
    assert client.api_key == "sk-test"
    await client.close()


@pytest.mark.asyncio
async def test_azure_signs_in_with_the_apps_identity_and_no_key(
    settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure(
        settings,
        LLM_PROVIDER="azure",
        LLM_MODEL="my-deployment",
        AZURE_OPENAI_ENDPOINT="https://example.openai.azure.com/",
    )
    scopes: list[str] = []

    def provider() -> str:
        return "entra-token"

    def fake_provider(credential: Any, scope: str) -> Any:
        scopes.append(scope)
        return provider

    import azure.identity

    monkeypatch.setattr(azure.identity, "get_bearer_token_provider", fake_provider)
    models._azure_token_provider.cache_clear()
    try:
        model, client = connect()
        assert isinstance(model, OpenAIChatCompletionsModel)
        assert model.model == "my-deployment"
        assert str(client.base_url) == "https://example.openai.azure.com/openai/v1/"
        assert await models._azure_token() == "entra-token"
        assert scopes == [models.AZURE_SCOPE]
        await client.close()
    finally:
        models._azure_token_provider.cache_clear()


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
