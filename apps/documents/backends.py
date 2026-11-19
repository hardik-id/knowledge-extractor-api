"""Pick the catalog and the storage from the settings.

A setting is a built-in name (``samples``) or a dotted path to a class, which
is how a test swaps in a fake. ``http`` and ``azure`` are described in
docs/documents.md and not built: choosing one stops the app at start.
"""

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string

from apps.documents.interfaces import DocumentCatalog, DocumentStorage

_BUILT_IN = {
    "DOCUMENT_CATALOG": {"samples": "apps.documents.samples.SamplesCatalog"},
    "DOCUMENT_STORAGE": {"samples": "apps.documents.samples.SamplesStorage"},
}
_NOT_BUILT = {"DOCUMENT_CATALOG": "http", "DOCUMENT_STORAGE": "azure"}


def _load(setting: str) -> type:
    value = getattr(settings, setting)
    path = _BUILT_IN[setting].get(value, value if "." in value else None)
    if path is None:
        known = ", ".join(sorted(_BUILT_IN[setting]))
        hint = ""
        if value == _NOT_BUILT[setting]:
            hint = " It is described in docs/documents.md and not built yet."
        raise ImproperlyConfigured(
            f"{setting} must be one of: {known} (or a dotted path to a class), "
            f"got {value!r}.{hint}"
        )
    try:
        return import_string(path)  # type: ignore[no-any-return]
    except ImportError as error:
        raise ImproperlyConfigured(
            f"{setting}={value!r} cannot be imported: {error}"
        ) from error


def get_catalog() -> DocumentCatalog:
    return _load("DOCUMENT_CATALOG")()  # type: ignore[no-any-return]


def get_storage() -> DocumentStorage:
    return _load("DOCUMENT_STORAGE")()  # type: ignore[no-any-return]


def check_settings() -> None:
    """Raise ``ImproperlyConfigured`` when either setting names no implementation."""
    _load("DOCUMENT_CATALOG")
    _load("DOCUMENT_STORAGE")
