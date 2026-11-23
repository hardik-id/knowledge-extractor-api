"""Model access: missing settings, the providers and their sign-ins."""

from typing import Any

import anthropic
import httpx2
import pytest
import structlog
from agents import OpenAIChatCompletionsModel, OpenAIResponsesModel

from apps.core import llm as models
from apps.core.llm import connect, missing_settings


def configure(settings: Any, **values: str) -> None:
    settings.LLM_PROVIDER = "openai"
    settings.LLM_MODEL = ""
    settings.OPENAI_API_KEY = ""
    settings.AZURE_OPENAI_ENDPOINT = ""
    for name, value in values.items():
        setattr(settings, name, value)


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
    configure(settings, LLM_PROVIDER="bogus", LLM_MODEL="m")
    assert missing_settings() == ["LLM_PROVIDER (openai, azure or anthropic)"]


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


# --- anthropic (local testing) ----------------------------------------------


class FakeCredentials:
    """What `anthropic.default_credentials()` returns, with no profile on disk."""

    def __init__(self) -> None:
        self.calls = 0
        self.extra_headers = {"anthropic-workspace-id": "wrkspc_test"}

    def provider(self) -> anthropic.AccessToken:
        self.calls += 1
        return anthropic.AccessToken(token="login-token", expires_at=None)


@pytest.fixture
def signed_in(monkeypatch: pytest.MonkeyPatch) -> Any:
    credentials = FakeCredentials()
    monkeypatch.setattr(anthropic, "default_credentials", lambda: credentials)
    models._anthropic_sign_in.cache_clear()
    yield credentials
    models._anthropic_sign_in.cache_clear()


def anthropic_settings(settings: Any, **values: str) -> None:
    settings.ANTHROPIC_API_KEY = ""
    settings.ANTHROPIC_BASE_URL = "https://api.anthropic.com/v1/"
    configure(settings, LLM_PROVIDER="anthropic", LLM_MODEL="claude-haiku-5-5")
    for name, value in values.items():
        setattr(settings, name, value)


@pytest.mark.asyncio
async def test_anthropic_with_a_key_uses_chat_completions_and_never_imports_the_sdk(
    settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    anthropic_settings(settings, ANTHROPIC_API_KEY="sk-ant-test")

    def fail() -> None:
        raise AssertionError("the key makes the sign-in unnecessary")

    monkeypatch.setattr(anthropic, "default_credentials", fail)
    model, client = connect()
    assert isinstance(model, OpenAIChatCompletionsModel)
    assert model.model == "claude-haiku-5-5"
    assert str(client.base_url) == "https://api.anthropic.com/v1/"
    assert client.api_key == "sk-ant-test"
    assert missing_settings() == []
    await client.close()


@pytest.mark.asyncio
async def test_anthropic_without_a_key_signs_in_through_the_cached_provider(
    settings: Any, signed_in: FakeCredentials
) -> None:
    anthropic_settings(settings, ANTHROPIC_BASE_URL="https://gateway.test/v1/")
    model, client = connect()
    assert isinstance(model, OpenAIChatCompletionsModel)
    assert str(client.base_url) == "https://gateway.test/v1/"
    assert client.default_headers["anthropic-workspace-id"] == "wrkspc_test"
    assert await models._anthropic_token() == "login-token"
    assert await models._anthropic_token() == "login-token"
    assert signed_in.calls == 1, "the token cache serves the second call"
    await client.close()


@pytest.mark.asyncio
async def test_a_failed_anthropic_sign_in_is_an_api_error_the_reply_handles(
    settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from openai import APIError

    anthropic_settings(settings)

    def broken() -> None:
        raise OSError("no profile")

    monkeypatch.setattr(anthropic, "default_credentials", broken)
    models._anthropic_sign_in.cache_clear()
    _, client = connect()
    with structlog.testing.capture_logs() as logs, pytest.raises(APIError):
        await models._anthropic_token()
    assert logs == [
        {
            "event": "assistant_sign_in_failed",
            "cause": "OSError",
            "log_level": "warning",
        }
    ], "the log names the cause, never its message"
    await client.close()


def test_missing_settings_for_anthropic(
    settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    anthropic_settings(settings, LLM_MODEL="")
    monkeypatch.setattr(anthropic, "default_credentials", lambda: FakeCredentials())
    assert missing_settings() == ["LLM_MODEL"]
    anthropic_settings(settings)
    assert missing_settings() == []
    monkeypatch.setattr(anthropic, "default_credentials", lambda: None)
    [entry] = missing_settings()
    assert "ant auth login" in entry
    assert "ANTHROPIC_API_KEY" in entry
    anthropic_settings(settings, ANTHROPIC_API_KEY="sk-ant-test")
    assert missing_settings() == []


def test_a_broken_profile_or_a_missing_package_is_no_sign_in(
    settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    anthropic_settings(settings)

    def broken() -> None:
        raise RuntimeError("profile not found")

    monkeypatch.setattr(anthropic, "default_credentials", broken)
    assert len(missing_settings()) == 1
    monkeypatch.undo()
    monkeypatch.setitem(__import__("sys").modules, "anthropic", None)  # not installed
    assert len(missing_settings()) == 1


def test_production_refuses_the_anthropic_provider() -> None:
    from apps.identity.tests.test_dev_sign_in import import_production

    result = import_production(LLM_PROVIDER="anthropic")
    assert result.returncode != 0
    assert "LLM_PROVIDER=anthropic is for local testing" in result.stderr
    assert "LLM_PROVIDER=azure" in result.stderr
    assert import_production(LLM_PROVIDER="azure").returncode == 0


# --- the output limit and the failure log ---------------------------------------


async def sent_request(settings: Any, provider: str) -> dict[str, Any]:
    """The arguments of the call the model makes, with the client's call replaced."""
    from agents import ModelSettings, ModelTracing
    from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel

    from apps.core.llm import output_limit

    configure(
        settings,
        LLM_PROVIDER=provider,
        LLM_MODEL="m",
        OPENAI_API_KEY="k",
        AZURE_OPENAI_ENDPOINT="https://x.openai.azure.com/",
        ANTHROPIC_API_KEY="k",
    )
    model, client = connect()
    sent: dict[str, Any] = {}

    async def create(**kwargs: Any) -> Any:
        sent.update(kwargs)
        raise RuntimeError("stop")

    client.chat.completions.create = create  # type: ignore[method-assign]
    client.responses.create = create  # type: ignore[method-assign]
    assert provider == "openai" or isinstance(model, OpenAIChatCompletionsModel)
    with pytest.raises(RuntimeError, match="stop"):
        await model.get_response(
            "x",
            [{"role": "user", "content": "hi"}],
            ModelSettings(store=False, **output_limit(77)),
            [],
            None,
            [],
            ModelTracing.DISABLED,
            previous_response_id=None,
            conversation_id=None,
            prompt=None,
        )
    await client.close()
    return sent


@pytest.mark.asyncio
async def test_azure_sends_max_completion_tokens_and_no_max_tokens(
    settings: Any,
) -> None:
    sent = await sent_request(settings, "azure")
    assert sent["max_completion_tokens"] == 77
    assert "max_tokens" not in sent or not isinstance(sent["max_tokens"], int)


@pytest.mark.asyncio
async def test_anthropic_still_sends_max_tokens(settings: Any) -> None:
    sent = await sent_request(settings, "anthropic")
    assert sent["max_tokens"] == 77
    assert "max_completion_tokens" not in sent


@pytest.mark.asyncio
async def test_openai_still_maps_the_limit_to_max_output_tokens(
    settings: Any,
) -> None:
    sent = await sent_request(settings, "openai")
    assert sent["max_output_tokens"] == 77


def test_the_output_limit_per_provider(settings: Any) -> None:
    from apps.core.llm import output_limit

    for provider in ("openai", "anthropic"):
        settings.LLM_PROVIDER = provider
        assert output_limit(5) == {"max_tokens": 5}
    settings.LLM_PROVIDER = "azure"
    assert output_limit(5) == {"extra_args": {"max_completion_tokens": 5}}


def test_a_failure_is_described_by_identifiers_never_by_message() -> None:
    from openai import BadRequestError

    from apps.core.llm import describe_failure

    request = httpx2.Request("POST", "https://x.invalid/")
    response = httpx2.Response(400, request=request)
    error = BadRequestError(
        "Unsupported parameter: 'max_tokens' SECRET-DOCUMENT-TEXT",
        response=response,
        body={"message": "SECRET-BODY", "code": "x"},
    )
    error.code = "unsupported_parameter"
    error.param = "max_tokens"
    described = describe_failure(error)
    assert described == {
        "error": "BadRequestError",
        "status_code": 400,
        "error_code": "unsupported_parameter",
        "error_param": "max_tokens",
    }
    assert "SECRET" not in str(described)


def test_the_identifiers_are_cut_and_a_plain_error_has_only_its_class() -> None:
    from apps.core.llm import describe_failure

    assert describe_failure(TimeoutError()) == {
        "error": "TimeoutError",
        "status_code": None,
    }
    error = RuntimeError("m")
    error.code = "c" * 500  # type: ignore[attr-defined]
    assert len(describe_failure(error)["error_code"]) == 80
