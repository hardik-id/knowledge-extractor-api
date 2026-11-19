from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured

from apps.core.errors import ApiError
from apps.documents import selectors
from apps.documents.backends import check_settings
from apps.documents.samples import SamplesStorage, etag_of

ADR = "enriched/engineering/architecture/platform-adrs.md"


def test_read_document_returns_text_and_the_listed_etag(user: Any) -> None:
    listed = next(d for d in selectors.list_documents(user) if d.id == ADR)
    document = selectors.read_document(user, ADR)
    assert "## ADR-101: Use feature flags for risky releases" in document.text
    assert document.text.startswith("---\n")  # YAML front matter
    assert document.content_type == "text/markdown"
    assert document.etag == listed.etag
    assert document.etag == etag_of(document.text.encode())


def test_get_document(user: Any) -> None:
    assert selectors.get_document(user, ADR).name == "platform-adrs.md"


def test_unknown_document_is_document_not_found(user: Any) -> None:
    for call in (selectors.get_document, selectors.read_document):
        with pytest.raises(ApiError) as caught:
            call(user, "enriched/nope.md")
        assert caught.value.code == "document_not_found"
        assert caught.value.status == 404


def test_storage_does_not_leave_the_samples_folder() -> None:
    with pytest.raises(FileNotFoundError):
        SamplesStorage().read("../../../manage.py")


@pytest.mark.parametrize("name", ["DOCUMENT_CATALOG", "DOCUMENT_STORAGE"])
@pytest.mark.parametrize("value", ["nonsense", "http", "azure"])
def test_unknown_setting_stops_the_app(settings: Any, name: str, value: str) -> None:
    setattr(settings, name, value)
    with pytest.raises(ImproperlyConfigured, match=name):
        check_settings()


def test_known_settings_pass() -> None:
    check_settings()
