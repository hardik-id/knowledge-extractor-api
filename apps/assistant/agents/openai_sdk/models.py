"""Model access: what the settings still lack, the connection, the Azure sign-in."""

import asyncio
import functools
from collections.abc import Callable

from agents import Model, OpenAIChatCompletionsModel, OpenAIResponsesModel
from django.conf import settings
from openai import AsyncOpenAI

AZURE_SCOPE = "https://cognitiveservices.azure.com/.default"


def missing_settings() -> list[str]:
    """The settings the configured provider still needs; empty when it is ready."""
    provider = settings.LLM_PROVIDER
    if provider == "openai":
        needed = ["LLM_MODEL", "OPENAI_API_KEY"]
    elif provider == "azure":
        needed = ["LLM_MODEL", "AZURE_OPENAI_ENDPOINT"]
    else:
        return ["LLM_PROVIDER (openai or azure)"]
    return [name for name in needed if not getattr(settings, name)]


@functools.cache
def _azure_token_provider() -> Callable[[], str]:
    """A token for Azure OpenAI from the app's own identity: managed identity in Azure,
    the developer's sign-in locally. Made once; it caches tokens until they expire."""
    from azure.identity import DefaultAzureCredential, get_bearer_token_provider

    return get_bearer_token_provider(DefaultAzureCredential(), AZURE_SCOPE)


async def _azure_token() -> str:
    return await asyncio.to_thread(_azure_token_provider())


def connect() -> tuple[Model, AsyncOpenAI]:
    """The model named by the settings and its client, which the caller closes."""
    if settings.LLM_PROVIDER == "azure":
        endpoint = settings.AZURE_OPENAI_ENDPOINT.rstrip("/")
        client = AsyncOpenAI(base_url=f"{endpoint}/openai/v1/", api_key=_azure_token)
        # Chat Completions: every Azure OpenAI deployment serves it.
        return OpenAIChatCompletionsModel(settings.LLM_MODEL, client), client
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return OpenAIResponsesModel(settings.LLM_MODEL, client), client
