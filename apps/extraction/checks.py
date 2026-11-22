"""The system check of the extractor: a warning when ``EXTRACTOR=llm`` has no model.

The app still starts: each file then fails with a sentence saying so.
"""

from typing import Any

from django.conf import settings
from django.core.checks import CheckMessage, Warning


def check_llm_settings(app_configs: Any = None, **kwargs: Any) -> list[CheckMessage]:
    if settings.EXTRACTOR != "llm":
        return []
    from apps.core.llm import missing_settings

    missing = missing_settings()
    if not missing:
        return []
    return [
        Warning(
            "EXTRACTOR=llm, but no language model is configured: "
            f"set {', '.join(missing)}.",
            hint="Each file fails to extract with that message until then. "
            "See docs/extraction.md.",
            id="extraction.W001",
        )
    ]
