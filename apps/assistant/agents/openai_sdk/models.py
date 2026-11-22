"""Model access: what the settings still lack, the connection, the Azure and Anthropic sign-ins."""

import asyncio
import functools
from collections.abc import Callable

import httpx2
from agents import Model, OpenAIChatCompletionsModel, OpenAIResponsesModel
from django.conf import settings
from openai import APIConnectionError, AsyncOpenAI

AZURE_SCOPE = "https://cognitiveservices.azure.com/.default"
ANTHROPIC_SIGN_IN = (
    "an Anthropic sign-in (run `ant auth login`, or set ANTHROPIC_API_KEY)"
)


def missing_settings() -> list[str]:
    """The settings the configured provider still needs; empty when it is ready."""
    provider = settings.LLM_PROVIDER
    if provider == "openai":
        needed = ["LLM_MODEL", "OPENAI_API_KEY"]
    elif provider == "azure":
        needed = ["LLM_MODEL", "AZURE_OPENAI_ENDPOINT"]
    elif provider == "anthropic":
        needed = ["LLM_MODEL"]
    else:
        return ["LLM_PROVIDER (openai, azure or anthropic)"]
    missing = [name for name in needed if not getattr(settings, name)]
    if provider == "anthropic" and not settings.ANTHROPIC_API_KEY:
        if not _anthropic_signed_in():
            missing.append(ANTHROPIC_SIGN_IN)
    return missing


def _anthropic_signed_in() -> bool:
    """Whether the Anthropic SDK finds a sign-in. It reads the environment and the disk,
    never the network, and it never raises: a broken profile counts as none."""
    try:
        import anthropic

        return anthropic.default_credentials() is not None
    except Exception:
        return False


@functools.cache
def _azure_token_provider() -> Callable[[], str]:
    """A token for Azure OpenAI from the app's own identity: managed identity in Azure,
    the developer's sign-in locally. Made once; it caches tokens until they expire."""
    from azure.identity import DefaultAzureCredential, get_bearer_token_provider

    return get_bearer_token_provider(DefaultAzureCredential(), AZURE_SCOPE)


async def _azure_token() -> str:
    return await asyncio.to_thread(_azure_token_provider())


@functools.cache
def _anthropic_sign_in() -> tuple[Callable[[], str], dict[str, str]]:
    """The token source and headers of the developer's `ant auth login` profile, through
    the `anthropic` package (a dev dependency: production refuses this provider).
    Made once; the cache refreshes the token before it expires."""
    import anthropic

    credentials = anthropic.default_credentials()
    if credentials is None:
        raise RuntimeError("no Anthropic sign-in")
    cache = anthropic.TokenCache(credentials.provider)
    return cache.get_token, dict(credentials.extra_headers or {})


async def _anthropic_token() -> str:
    try:
        get_token, _ = _anthropic_sign_in()
        return await asyncio.to_thread(get_token)
    except Exception as error:
        # One error type for the reply to handle; the cause is chained, never logged.
        request = httpx2.Request("POST", settings.ANTHROPIC_BASE_URL)
        raise APIConnectionError(request=request) from error


def connect() -> tuple[Model, AsyncOpenAI]:
    """The model named by the settings and its client, which the caller closes."""
    if settings.LLM_PROVIDER == "azure":
        endpoint = settings.AZURE_OPENAI_ENDPOINT.rstrip("/")
        client = AsyncOpenAI(base_url=f"{endpoint}/openai/v1/", api_key=_azure_token)
        # Chat Completions: every Azure OpenAI deployment serves it.
        return OpenAIChatCompletionsModel(settings.LLM_MODEL, client), client
    if settings.LLM_PROVIDER == "anthropic":
        if settings.ANTHROPIC_API_KEY:
            client = AsyncOpenAI(
                base_url=settings.ANTHROPIC_BASE_URL, api_key=settings.ANTHROPIC_API_KEY
            )
        else:
            try:
                headers = _anthropic_sign_in()[1]
            except Exception:
                headers = {}  # the first request then fails in _anthropic_token
            client = AsyncOpenAI(
                base_url=settings.ANTHROPIC_BASE_URL,
                api_key=_anthropic_token,
                default_headers=headers,
            )
        # Chat Completions: the only API Anthropic's OpenAI compatibility layer has.
        return OpenAIChatCompletionsModel(settings.LLM_MODEL, client), client
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return OpenAIResponsesModel(settings.LLM_MODEL, client), client
