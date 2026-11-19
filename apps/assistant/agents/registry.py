"""Pick the agent from the ``ASSISTANT_AGENT`` setting.

A setting is a built-in name (``scripted``, ``openai``) or a dotted path to a
class, which is how a test swaps in a fake. Any other value stops the app at start.
"""

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string

from apps.assistant.agents.base import Agent

_BUILT_IN = {
    "scripted": "apps.assistant.agents.scripted.ScriptedAgent",
    "openai": "apps.assistant.agents.openai_sdk.OpenAIAgent",
}


def _load() -> type:
    value = settings.ASSISTANT_AGENT
    path = _BUILT_IN.get(value, value if "." in value else None)
    if path is None:
        known = ", ".join(sorted(_BUILT_IN))
        raise ImproperlyConfigured(
            f"ASSISTANT_AGENT must be one of: {known} (or a dotted path to a class), "
            f"got {value!r}."
        )
    try:
        return import_string(path)  # type: ignore[no-any-return]
    except ImportError as error:
        raise ImproperlyConfigured(
            f"ASSISTANT_AGENT={value!r} cannot be imported: {error}"
        ) from error


def get_agent() -> Agent:
    return _load()()  # type: ignore[no-any-return]


def check_settings() -> None:
    """Raise ``ImproperlyConfigured`` when the setting names no agent."""
    _load()


def agent_kind() -> str:
    """What kind of agent the setting names, for telemetry: the built-in name, or the class name."""
    value = settings.ASSISTANT_AGENT
    return str(value if value in _BUILT_IN else value.rsplit(".", 1)[-1])
