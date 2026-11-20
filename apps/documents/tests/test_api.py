"""GET /api/v1/documents, through the API."""

from typing import Any

import pytest

from apps.documents.tests.fakes import TEXT

URL = "/api/v1/documents"
ADR_DOCUMENTS = {
    "enriched/engineering/architecture/architecture-decisions-2026.md",
    "enriched/engineering/architecture/platform-adrs.md",
}


def test_lists_the_samples(api_client: Any, user: Any) -> None:
    api_client.force_authenticate(user)
    response = api_client.get(URL)
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 12
    assert ADR_DOCUMENTS <= {item["id"] for item in items}
    item = next(i for i in items if i["name"] == "platform-adrs.md")
    assert set(item) == {
        "id",
        "name",
        "source",
        "type",
        "size_bytes",
        "location",
        "modified_at",
        "etag",
    }
    assert item["source"] == "storage"
    assert item["type"] == "md"
    assert item["location"] == "enriched / engineering / architecture"
    assert item["size_bytes"] > 0


def test_newest_first(api_client: Any, user: Any) -> None:
    api_client.force_authenticate(user)
    stamps = [i["modified_at"] for i in api_client.get(URL).json()["items"]]
    assert stamps == sorted(stamps, reverse=True)


def test_query_narrows_on_name_and_location(api_client: Any, user: Any) -> None:
    api_client.force_authenticate(user)
    by_location = api_client.get(URL, {"q": "ARCHITECTURE"}).json()["items"]
    assert {i["id"] for i in by_location} == ADR_DOCUMENTS
    by_name = api_client.get(URL, {"q": "leave-policy"}).json()["items"]
    assert [i["name"] for i in by_name] == ["leave-policy-2026.md"]


def test_no_match_is_an_empty_list(api_client: Any, user: Any) -> None:
    api_client.force_authenticate(user)
    response = api_client.get(URL, {"q": "no such document"})
    assert response.status_code == 200
    assert response.json() == {"items": []}


def test_without_a_token_is_401(api_client: Any) -> None:
    response = api_client.get(URL)
    assert response.status_code == 401
    assert response.json()["code"] == "unauthenticated"


def test_serves_from_a_fake_catalog_and_storage(
    api_client: Any, user: Any, settings: Any
) -> None:
    from apps.documents import selectors

    settings.DOCUMENT_CATALOG = "apps.documents.tests.fakes.FakeCatalog"
    settings.DOCUMENT_STORAGE = "apps.documents.tests.fakes.FakeStorage"
    api_client.force_authenticate(user)
    items = api_client.get(URL).json()["items"]
    assert [i["id"] for i in items] == ["fake/one.md"]
    assert items[0]["etag"] == "v1"
    assert selectors.read_document(user, "fake/one.md").text == TEXT.decode()


@pytest.mark.parametrize("q", ["fake", "PLACE"])
def test_query_applies_to_a_fake_catalog(
    api_client: Any, user: Any, settings: Any, q: str
) -> None:
    settings.DOCUMENT_CATALOG = "apps.documents.tests.fakes.FakeCatalog"
    api_client.force_authenticate(user)
    assert len(api_client.get(URL, {"q": q}).json()["items"]) == 1
