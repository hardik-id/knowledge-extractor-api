"""The only door to the documents app for other apps.

Each function takes the acting user first. Callers never learn which catalog or
storage runs behind them.
"""

from dataclasses import dataclass

from apps.core.errors import ApiError
from apps.documents.backends import get_catalog, get_storage
from apps.documents.interfaces import CatalogEntry
from apps.identity.models import User


@dataclass(frozen=True)
class DocumentText:
    text: str
    content_type: str
    etag: str


def list_documents(user: User, query: str = "") -> list[CatalogEntry]:
    """The documents ``user`` may open, newest first. ``query`` matches name and location."""
    needle = query.strip().casefold()
    entries = [
        entry
        for entry in get_catalog().list(user)
        if not needle
        or needle in entry.name.casefold()
        or needle in entry.location.casefold()
    ]
    return sorted(
        entries, key=lambda entry: (entry.modified_at, entry.id), reverse=True
    )


def get_document(user: User, document_id: str) -> CatalogEntry:
    """One listed document. A document the person may not open is a 404 too."""
    for entry in get_catalog().list(user):
        if entry.id == document_id:
            return entry
    raise ApiError("document_not_found")


def read_document(user: User, document_id: str) -> DocumentText:
    """The text, content type and ETag of a document."""
    entry = get_document(user, document_id)
    try:
        stored = get_storage().read(entry.storage_location)
    except FileNotFoundError:
        raise ApiError("document_not_found") from None
    return DocumentText(
        stored.content.decode("utf-8"), stored.content_type, stored.etag
    )
