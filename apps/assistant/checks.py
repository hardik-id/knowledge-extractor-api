"""The system check of the assistant: a warning at start when the LLM agent has no model.

The app still starts and the worker still runs: each reply then says, in one
sentence, that no model is configured.
"""

from typing import Any

from django.conf import settings
from django.core.checks import CheckMessage, Warning


def check_llm_settings(app_configs: Any = None, **kwargs: Any) -> list[CheckMessage]:
    if settings.ASSISTANT_AGENT != "openai":
        return []
    from apps.assistant.agents.openai_sdk.models import missing_settings

    missing = missing_settings()
    if not missing:
        return []
    return [
        Warning(
            "ASSISTANT_AGENT=openai, but no language model is configured: "
            f"set {', '.join(missing)}.",
            hint="Each reply says that the assistant is not configured until then. "
            "See docs/assistant.md.",
            id="assistant.W001",
        )
    ]
