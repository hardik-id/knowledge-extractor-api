"""The two interfaces behind the documents app.

The catalog says which documents a person may open and where their content is.
The storage reads the content at a storage location. Each is chosen by a
setting (``DOCUMENT_CATALOG``, ``DOCUMENT_STORAGE``); see docs/documents.md.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from apps.identity.models import User


@dataclass(frozen=True)
class CatalogEntry:
    """One document in the catalog."""

    id: str
    name: str
    type: str  # file type without the dot: "md"
    size_bytes: int
    location: str  # for display: "enriched / hr / policies"
    modified_at: datetime
    etag: str  # the version
    storage_location: str  # where the storage reads the content


@dataclass(frozen=True)
class StoredContent:
    """What the storage returns for a storage location."""

    content: bytes
    content_type: str
    etag: str


class DocumentCatalog(Protocol):
    def list(self, user: User) -> list[CatalogEntry]:
        """The documents ``user`` may open."""
        ...


class DocumentStorage(Protocol):
    def read(self, storage_location: str) -> StoredContent:
        """The content at ``storage_location``. Raises ``FileNotFoundError`` when absent."""
        ...
