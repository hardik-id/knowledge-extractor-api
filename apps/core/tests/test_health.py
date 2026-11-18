import pytest
from django.db.utils import OperationalError
from rest_framework.test import APIClient


@pytest.fixture
def client() -> APIClient:
    return APIClient()


def test_health_is_open_and_ok(client: APIClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.django_db
def test_ready_when_database_answers(client: APIClient) -> None:
    response = client.get("/api/v1/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_503_when_database_unreachable(
    client: APIClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*args: object, **kwargs: object) -> None:
        raise OperationalError("down")

    monkeypatch.setattr(
        "django.db.backends.base.base.BaseDatabaseWrapper.cursor", broken
    )
    response = client.get("/api/v1/ready")
    assert response.status_code == 503
    assert response.json() == {
        "code": "not_ready",
        "message": "The service is not ready.",
    }


def test_no_trailing_slash(client: APIClient) -> None:
    assert client.get("/api/v1/health/").status_code == 404
