"""The system check of the extractor: a warning when ``EXTRACTOR=llm`` has no model.

The app still starts: each file then fails with a sentence saying so.
"""

from typing import Any

from django.conf import settings
from django.core.checks import CheckMessage, Warning


def check_extraction_limits(
    app_configs: Any = None, **kwargs: Any
) -> list[CheckMessage]:
    """Warn when one file's calls may outlast the cell or cannot finish in time."""
    if settings.EXTRACTOR != "llm":
        return []
    file_timeout = settings.EXTRACTION_FILE_TIMEOUT_SECONDS
    rounds = -(
        -settings.EXTRACTION_MAX_CHUNKS // max(settings.EXTRACTION_CONCURRENCY, 1)
    )
    problems = []
    if file_timeout >= settings.EXECUTION_TIMEOUT_SECONDS:
        problems.append(
            "EXTRACTION_FILE_TIMEOUT_SECONDS is not below EXECUTION_TIMEOUT_SECONDS: "
            "the cell is released while the worker still pays for calls"
        )
    if rounds * settings.EXTRACTION_MODEL_TIMEOUT_SECONDS > file_timeout:
        problems.append(
            "EXTRACTION_MAX_CHUNKS parts, EXTRACTION_CONCURRENCY at a time, may not "
            "finish within EXTRACTION_FILE_TIMEOUT_SECONDS at "
            "EXTRACTION_MODEL_TIMEOUT_SECONDS per call"
        )
    return [
        Warning(
            problem + ".",
            hint="See docs/extraction.md.",
            id="extraction.W002",
        )
        for problem in problems
    ]


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
