"""A fake catalog and a fake storage, chosen through the settings in tests."""

from datetime import UTC, datetime

from apps.documents.interfaces import CatalogEntry, StoredContent
from apps.identity.models import User

TEXT = b"# Fake\n\nA document that no sample holds.\n"


class FakeCatalog:
    def list(self, user: User) -> list[CatalogEntry]:
        return [
            CatalogEntry(
                id="fake/one.md",
                name="one.md",
                type="md",
                size_bytes=len(TEXT),
                location="fake / place",
                modified_at=datetime(2026, 1, 1, tzinfo=UTC),
                etag="v1",
                storage_location="blob://fake-one",
            )
        ]


class FakeStorage:
    def read(self, storage_location: str) -> StoredContent:
        if storage_location != "blob://fake-one":
            raise FileNotFoundError(storage_location)
        return StoredContent(TEXT, "text/markdown", "v1")
