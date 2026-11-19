"""Issuing and redeeming tickets."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Any

import pytest
from django.db import connection
from django.utils import timezone

from apps.identity.tests.factories import UserFactory
from apps.realtime import services
from apps.realtime.models import WsTicket


@pytest.mark.django_db
def test_a_ticket_signs_in_its_own_person(user: Any) -> None:
    ticket = services.issue_ticket(user)
    assert services.redeem_ticket(ticket) == user


@pytest.mark.django_db
def test_a_ticket_of_one_person_never_signs_in_another(user: Any) -> None:
    other = UserFactory()
    mine = services.issue_ticket(user)
    theirs = services.issue_ticket(other)
    assert services.redeem_ticket(theirs) == other
    assert services.redeem_ticket(mine) == user


@pytest.mark.django_db
def test_a_ticket_works_once(user: Any) -> None:
    ticket = services.issue_ticket(user)
    assert services.redeem_ticket(ticket) == user
    assert services.redeem_ticket(ticket) is None


@pytest.mark.django_db
def test_an_expired_ticket_is_refused(user: Any, settings: Any) -> None:
    ticket = services.issue_ticket(user)
    WsTicket.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    assert services.redeem_ticket(ticket) is None


@pytest.mark.django_db
def test_a_ticket_lives_ws_ticket_ttl_seconds(user: Any, settings: Any) -> None:
    settings.WS_TICKET_TTL_SECONDS = 7
    before = timezone.now()
    services.issue_ticket(user)
    lifetime = WsTicket.objects.get().expires_at - before
    assert timedelta(seconds=6) < lifetime <= timedelta(seconds=8)


@pytest.mark.django_db
def test_unknown_and_empty_tickets_are_refused(user: Any) -> None:
    services.issue_ticket(user)
    assert services.redeem_ticket("nope") is None
    assert services.redeem_ticket("") is None


@pytest.mark.django_db
def test_a_ticket_of_a_deactivated_person_is_refused(user: Any) -> None:
    ticket = services.issue_ticket(user)
    user.is_active = False
    user.save()
    assert services.redeem_ticket(ticket) is None


@pytest.mark.django_db
def test_issuing_clears_the_tickets_that_ran_out(user: Any) -> None:
    services.issue_ticket(user)
    WsTicket.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    services.issue_ticket(user)
    assert WsTicket.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_of_many_sockets_with_one_ticket_one_wins() -> None:
    ticket = services.issue_ticket(UserFactory())

    def redeem() -> Any:
        try:
            return services.redeem_ticket(ticket)
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: redeem(), range(8)))
    assert len([r for r in results if r is not None]) == 1
