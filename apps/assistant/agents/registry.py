"""Pick the agent from the ``ASSISTANT_AGENT`` setting.

A setting is a built-in name (``scripted``) or a dotted path to a class, which
is how a test swaps in a fake. ``openai`` is described in docs/assistant.md and
not built: choosing it stops the app at start, like any unknown value.
"""

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string

from apps.assistant.agents.base import Agent

_BUILT_IN = {"scripted": "apps.assistant.agents.scripted.ScriptedAgent"}
_NOT_BUILT = "openai"


def _load() -> type:
    value = settings.ASSISTANT_AGENT
    path = _BUILT_IN.get(value, value if "." in value else None)
    if path is None:
        known = ", ".join(sorted(_BUILT_IN))
        hint = ""
        if value == _NOT_BUILT:
            hint = " It is described in docs/assistant.md and not built yet."
        raise ImproperlyConfigured(
            f"ASSISTANT_AGENT must be one of: {known} (or a dotted path to a class), "
            f"got {value!r}.{hint}"
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
