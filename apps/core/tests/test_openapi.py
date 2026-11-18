"""The schema and Swagger UI: what they describe and when they are served."""

import importlib
from typing import Any

import pytest
from django.test import Client, override_settings
from django.urls import clear_url_caches

from config import urls as root_urls


@pytest.fixture
def schema(client: Client) -> dict[str, Any]:
    response = client.get("/api/schema", HTTP_ACCEPT="application/vnd.oai.openapi+json")
    assert response.status_code == 200
    return response.json()  # type: ignore[no-any-return]


def test_schema_has_title_version_and_prefix(schema: dict[str, Any]) -> None:
    assert schema["info"]["title"] == "Knowledge Extractor API"
    assert schema["info"]["version"] == "v1"
    assert schema["servers"] == [{"url": "/api/v1"}]


def test_bearer_scheme_is_declared(schema: dict[str, Any]) -> None:
    assert schema["components"]["securitySchemes"]["bearerAuth"] == {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
        "description": "An Entra ID access token (a dev token in local development).",
    }


def test_closed_endpoint_has_a_lock_and_open_ones_do_not(
    schema: dict[str, Any],
) -> None:
    assert schema["paths"]["/me"]["get"]["security"] == [{"bearerAuth": []}]
    assert schema["paths"]["/health"]["get"]["security"] == [{}]
    assert schema["paths"]["/ready"]["get"]["security"] == [{}]


def test_every_operation_documents_the_error_body(schema: dict[str, Any]) -> None:
    assert schema["components"]["schemas"]["Error"]["required"] == ["code", "message"]
    for path in schema["paths"].values():
        for operation in path.values():
            for status in ("401", "403", "404", "422"):
                ref = operation["responses"][status]["content"]["application/json"]
                assert ref["schema"] == {"$ref": "#/components/schemas/Error"}


def test_swagger_ui_is_served_from_this_app(client: Client) -> None:
    response = client.get("/api/docs")
    assert response.status_code == 200
    html = response.content.decode()
    assert "drf_spectacular_sidecar/swagger-ui-dist/swagger-ui-bundle.js" in html
    assert "cdn" not in html


def test_docs_are_404_when_disabled(client: Client) -> None:
    try:
        with override_settings(API_DOCS_ENABLED=False):
            importlib.reload(root_urls)
            clear_url_caches()
            for path in ("/api/schema", "/api/docs"):
                response = client.get(path)
                assert response.status_code == 404
                assert response.json()["code"] == "not_found"
    finally:
        importlib.reload(root_urls)
        clear_url_caches()
