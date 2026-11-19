"""POST /api/v1/ws-ticket through the API."""

from typing import Any

import pytest

from apps.realtime.models import WsTicket

pytestmark = pytest.mark.django_db

URL = "/api/v1/ws-ticket"


def test_gives_a_ticket_to_the_signed_in_person(api_client: Any, user: Any) -> None:
    api_client.force_authenticate(user)
    response = api_client.post(URL)
    assert response.status_code == 200
    body = response.json()
    assert list(body) == ["ticket"]
    assert len(body["ticket"]) >= 32
    assert WsTicket.objects.get().user == user


def test_every_call_gives_another_ticket(api_client: Any, user: Any) -> None:
    api_client.force_authenticate(user)
    first = api_client.post(URL).json()["ticket"]
    second = api_client.post(URL).json()["ticket"]
    assert first != second


def test_the_database_holds_no_clear_ticket(api_client: Any, user: Any) -> None:
    api_client.force_authenticate(user)
    ticket = api_client.post(URL).json()["ticket"]
    row = WsTicket.objects.get()
    assert ticket not in {str(value) for value in vars(row).values()}
    assert len(row.token_hash) == 64


def test_without_a_token_is_401(api_client: Any) -> None:
    response = api_client.post(URL)
    assert response.status_code == 401
    assert response.json()["code"] == "unauthenticated"
    assert not WsTicket.objects.exists()
