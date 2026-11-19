"""The built-in catalog and storage: Markdown files shipped in ``samples/``.

``samples/manifest.json`` lists the documents; each id is the path of its file
under ``samples/``, like a container path. Everyone sees every sample.
"""

import hashlib
import json
from datetime import datetime
from pathlib import Path

from apps.documents.interfaces import CatalogEntry, StoredContent
from apps.identity.models import User

SAMPLES_DIR = Path(__file__).resolve().parent / "samples"
CONTENT_TYPE = "text/markdown"


def etag_of(content: bytes) -> str:
    """The version of a content: a hash, so it changes exactly when the content does."""
    return hashlib.sha256(content).hexdigest()[:16]


def _path_of(storage_location: str) -> Path:
    path = (SAMPLES_DIR / storage_location).resolve()
    if SAMPLES_DIR not in path.parents or not path.is_file():
        raise FileNotFoundError(storage_location)
    return path


class SamplesCatalog:
    def list(self, user: User) -> list[CatalogEntry]:
        manifest = json.loads((SAMPLES_DIR / "manifest.json").read_text("utf-8"))
        entries = []
        for item in manifest:
            content = _path_of(item["id"]).read_bytes()
            entries.append(
                CatalogEntry(
                    id=item["id"],
                    name=item["name"],
                    type=item["name"].rsplit(".", 1)[-1],
                    size_bytes=len(content),
                    location=item["location"],
                    modified_at=datetime.fromisoformat(item["modified_at"]),
                    etag=etag_of(content),
                    storage_location=item["id"],
                )
            )
        return entries


class SamplesStorage:
    def read(self, storage_location: str) -> StoredContent:
        content = _path_of(storage_location).read_bytes()
        return StoredContent(content, CONTENT_TYPE, etag_of(content))
