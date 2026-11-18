"""GET /api/v1/me through the API with a signed token."""

import uuid
from typing import Any

import pytest
from rest_framework.test import APIClient

from apps.identity.tests.conftest import TENANT, MakeToken

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("token_config")]

URL = "/api/v1/me"


def get(token: str | None = None, url: str = URL) -> Any:
    client = APIClient(raise_request_exception=False)
    if token is not None:
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client.get(url)


def test_returns_the_signed_in_person(make_token: MakeToken) -> None:
    response = get(
        make_token(name="Ada Lovelace", preferred_username="ada@example.com")
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"id", "name", "preferred_username"}
    assert body["name"] == "Ada Lovelace"
    assert body["preferred_username"] == "ada@example.com"


def test_returns_only_the_callers_own_data(make_token: MakeToken) -> None:
    get(make_token(oid=str(uuid.uuid4()), name="Other", tid=TENANT))
    body = get(make_token(oid=str(uuid.uuid4()), name="Me")).json()
    assert body["name"] == "Me"


def test_without_a_token_is_401() -> None:
    response = get()
    assert response.status_code == 401
    assert response.json()["code"] == "unauthenticated"


def test_trailing_slash_is_not_a_route(make_token: MakeToken) -> None:
    assert get(make_token(), URL + "/").status_code == 404
