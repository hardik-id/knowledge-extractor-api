import logging

import pytest
from django.test import Client
from rest_framework.test import APIClient

from apps.core.errors import ERRORS, ApiError

pytestmark = pytest.mark.urls("apps.core.tests.urls")


@pytest.fixture
def client() -> APIClient:
    return APIClient(raise_request_exception=False)


@pytest.mark.parametrize("code", list(ERRORS))
def test_registered_code_gives_its_status_and_message(
    client: APIClient, code: str
) -> None:
    response = client.get(f"/api/test/error/{code}")
    assert response.status_code == ERRORS[code].status
    assert response.json() == {"code": code, "message": ERRORS[code].message}


def test_message_and_details_can_be_overridden(client: APIClient) -> None:
    response = client.get("/api/test/custom")
    assert response.status_code == 409
    assert response.json() == {
        "code": "conflict",
        "message": "Already exists.",
        "details": {"name": ["taken"]},
    }


def test_unregistered_code_fails() -> None:
    with pytest.raises(ValueError, match="Unregistered"):
        ApiError("no_such_code")


def test_registry_covers_the_required_codes() -> None:
    assert {c: e.status for c, e in ERRORS.items()}.items() >= {
        "unauthenticated": 401,
        "forbidden": 403,
        "not_found": 404,
        "method_not_allowed": 405,
        "conflict": 409,
        "validation_error": 422,
        "server_error": 500,
    }.items()


def test_not_authenticated_keeps_www_authenticate(client: APIClient) -> None:
    response = client.get("/api/test/unauthenticated")
    assert response.status_code == 401
    assert response.json()["code"] == "unauthenticated"
    assert response["WWW-Authenticate"].startswith("Basic")


def test_authentication_failed(client: APIClient) -> None:
    response = client.get("/api/test/failed")
    assert response.status_code == 401
    assert response.json() == {
        "code": "unauthenticated",
        "message": ERRORS["unauthenticated"].message,
    }


def test_permission_denied(client: APIClient) -> None:
    response = client.get("/api/test/denied")
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"
    assert "secret" not in response.content.decode()


def test_not_found(client: APIClient) -> None:
    response = client.get("/api/test/missing")
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_method_not_allowed(client: APIClient) -> None:
    response = client.delete("/api/test/validate")
    assert response.status_code == 405
    assert response.json()["code"] == "method_not_allowed"


def test_validation_error_names_the_fields(client: APIClient) -> None:
    response = client.post("/api/test/validate", {"age": "x"}, format="json")
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_error"
    assert set(body["details"]) == {"name", "age"}
    assert body["details"]["name"] == ["This field is required."]


def test_unreadable_json_is_400(client: APIClient) -> None:
    response = client.post(
        "/api/test/validate", "{not json", content_type="application/json"
    )
    assert response.status_code == 400
    assert response.json()["code"] == "bad_request"


def test_unexpected_exception_is_500_logged_and_not_leaked(
    client: APIClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR):
        response = client.get("/api/test/crash")
    assert response.status_code == 500
    assert response.json() == {
        "code": "server_error",
        "message": ERRORS["server_error"].message,
    }
    assert "secret" not in response.content.decode()
    assert "Traceback" not in response.content.decode()
    record = next(r for r in caplog.records if r.exc_info)
    assert "internal secret detail" in str(record.exc_info)


@pytest.mark.parametrize("debug", [True, False])
def test_unknown_api_url_is_json_404(
    client: APIClient, settings: object, debug: bool
) -> None:
    settings.DEBUG = debug  # type: ignore[attr-defined]
    response = client.get("/api/v1/nothing/here")
    assert response.status_code == 404
    assert response["Content-Type"] == "application/json"
    assert response.json() == {"code": "not_found", "message": "Not found."}


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_unknown_api_url_is_404_for_every_method(
    client: APIClient, method: str
) -> None:
    response = getattr(client, method)("/api/v1/nothing/here")
    assert response.status_code == 404
    assert response.json() == {"code": "not_found", "message": "Not found."}


def test_unknown_url_outside_api_keeps_django_page(client: Client) -> None:
    response = client.get("/elsewhere")
    assert response.status_code == 404
    assert response["Content-Type"].startswith("text/html")


def test_middleware_crash_is_json_500(settings: object) -> None:
    settings.MIDDLEWARE = [  # type: ignore[attr-defined]
        "apps.core.tests.middleware.CrashingMiddleware",
        *settings.MIDDLEWARE,  # type: ignore[attr-defined]
    ]
    assert settings.DEBUG is False  # type: ignore[attr-defined]
    response = Client(raise_request_exception=False).get("/api/anything")
    assert response.status_code == 500
    assert response.json()["code"] == "server_error"
    assert "Traceback" not in response.content.decode()
