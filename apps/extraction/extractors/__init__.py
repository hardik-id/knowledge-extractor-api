"""Pick the extractor from the ``EXTRACTOR`` setting.

The setting is a built-in name (``scripted``) or a dotted path to a class, which
is how a test swaps in a fake. An unknown value stops the app at start (see
``ExtractionConfig.ready``). ``llm`` calls the configured language model.
"""

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string

from apps.extraction.extractors.base import Extractor

_BUILT_IN = {
    "scripted": "apps.extraction.extractors.scripted.ScriptedExtractor",
    "llm": "apps.extraction.extractors.llm.LlmExtractor",
}


def _load() -> type:
    value = settings.EXTRACTOR
    path = _BUILT_IN.get(value, value if "." in value else None)
    if path is None:
        known = ", ".join(sorted(_BUILT_IN))
        raise ImproperlyConfigured(
            f"EXTRACTOR must be one of: {known} (or a dotted path to a class), "
            f"got {value!r}."
        )
    try:
        return import_string(path)  # type: ignore[no-any-return]
    except ImportError as error:
        raise ImproperlyConfigured(
            f"EXTRACTOR={value!r} cannot be imported: {error}"
        ) from error


def get_extractor() -> Extractor:
    return _load()()  # type: ignore[no-any-return]


def check_settings() -> None:
    """Raise ``ImproperlyConfigured`` when ``EXTRACTOR`` names no implementation."""
    _load()


def extractor_kind() -> str:
    """What kind of extractor the setting names, for telemetry: the built-in name, or the class name."""
    value = settings.EXTRACTOR
    return str(value if value in _BUILT_IN else value.rsplit(".", 1)[-1])
