import pytest
from django.test import Client

UI = "http://localhost:3000"
pytestmark = pytest.mark.django_db


@pytest.fixture
def client() -> Client:
    return Client()


def preflight(client: Client, origin: str) -> object:
    return client.options(
        "/nothing",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization, content-type, x-request-id",
        },
    )


def test_preflight_from_the_ui_is_allowed(client: Client) -> None:
    response = preflight(client, UI)
    assert response.status_code == 200  # type: ignore[attr-defined]
    assert response["Access-Control-Allow-Origin"] == UI  # type: ignore[index]
    allowed = response["Access-Control-Allow-Headers"].lower()  # type: ignore[index]
    for name in ("authorization", "content-type", "x-request-id"):
        assert name in allowed


def test_preflight_from_another_origin_is_not_allowed(client: Client) -> None:
    response = preflight(client, "http://evil.example")
    assert "Access-Control-Allow-Origin" not in response  # type: ignore[operator]


def test_ui_response_exposes_etag_and_request_id_without_credentials(
    client: Client,
) -> None:
    response = client.get("/nothing", headers={"Origin": UI})
    assert response["Access-Control-Allow-Origin"] == UI
    exposed = response["Access-Control-Expose-Headers"].lower()
    assert "etag" in exposed
    assert "x-request-id" in exposed
    assert "Access-Control-Allow-Credentials" not in response


def test_origin_is_never_a_wildcard(client: Client) -> None:
    for origin in (UI, "http://evil.example"):
        response = client.get("/nothing", headers={"Origin": origin})
        assert response.get("Access-Control-Allow-Origin") != "*"


def test_security_headers_are_on_every_response(client: Client) -> None:
    for path in ("/nothing", "/admin/login/"):
        response = client.get(path)
        assert response["X-Content-Type-Options"] == "nosniff"
        assert response["Referrer-Policy"] == "same-origin"
        assert response["X-Frame-Options"] == "DENY"
        assert "frame-ancestors 'none'" in response["Content-Security-Policy"]


def test_admin_renders_under_its_csp(client: Client) -> None:
    response = client.get("/admin/login/")
    assert response.status_code == 200
    assert "default-src 'self'" in response["Content-Security-Policy"]
