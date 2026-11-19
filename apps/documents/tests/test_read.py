"""GET /api/v1/documents/{id}, through the API."""

from typing import Any
from urllib.parse import quote

import pytest

LIST = "/api/v1/documents"
ID = "enriched/engineering/architecture/platform-adrs.md"


def _etag(api_client: Any) -> str:
    items = api_client.get(LIST).json()["items"]
    return str(next(i["etag"] for i in items if i["id"] == ID))


@pytest.mark.parametrize("encoded", [False, True])
def test_reads_text_and_etag(api_client: Any, user: Any, encoded: bool) -> None:
    api_client.force_authenticate(user)
    doc_id = quote(ID, safe="") if encoded else ID
    response = api_client.get(f"{LIST}/{doc_id}")
    assert response.status_code == 200
    assert response["Content-Type"] == "text/markdown; charset=utf-8"
    assert response["ETag"] == f'"{_etag(api_client)}"'
    assert response.content.decode().startswith("---")


def test_if_none_match_is_304(api_client: Any, user: Any) -> None:
    api_client.force_authenticate(user)
    etag = _etag(api_client)
    for value in (f'"{etag}"', f'W/"{etag}"', f'"x", "{etag}"', "*"):
        response = api_client.get(f"{LIST}/{ID}", headers={"If-None-Match": value})
        assert response.status_code == 304
        assert response.content == b""
        assert response["ETag"] == f'"{etag}"'
    stale = api_client.get(f"{LIST}/{ID}", headers={"If-None-Match": '"other"'})
    assert stale.status_code == 200


def test_unknown_id_is_404(api_client: Any, user: Any) -> None:
    api_client.force_authenticate(user)
    response = api_client.get(f"{LIST}/enriched%2Fnope.md")
    assert response.status_code == 404
    assert response.json()["code"] == "document_not_found"


def test_without_a_token_is_401(api_client: Any) -> None:
    response = api_client.get(f"{LIST}/{ID}")
    assert response.status_code == 401
    assert response.json()["code"] == "unauthenticated"


def test_accept_markdown_still_works(api_client: Any, user: Any) -> None:
    api_client.force_authenticate(user)
    response = api_client.get(f"{LIST}/{ID}", headers={"Accept": "text/markdown"})
    assert response.status_code == 200


def test_cors_exposes_etag(api_client: Any, user: Any) -> None:
    api_client.force_authenticate(user)
    response = api_client.get(
        f"{LIST}/{ID}", headers={"Origin": "http://localhost:3000"}
    )
    assert response["Access-Control-Allow-Origin"] == "http://localhost:3000"
    assert "ETag" in response["Access-Control-Expose-Headers"]
