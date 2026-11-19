"""Socket tickets: issue one to a signed-in person, redeem it once.

A browser cannot send an ``Authorization`` header on a WebSocket, so the person
asks for a ticket over REST and puts it in the socket URL (docs/realtime.md).
"""

import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from apps.identity.models import User
from apps.realtime.models import WsTicket


def _hash(ticket: str) -> str:
    return hashlib.sha256(ticket.encode()).hexdigest()


def issue_ticket(user: User) -> str:
    """A new ticket for ``user``. The clear text is returned here and nowhere else."""
    now = timezone.now()
    # Tickets live seconds: whatever has run out is of no use to anybody.
    WsTicket.objects.filter(expires_at__lt=now).delete()
    ticket = secrets.token_urlsafe(32)
    WsTicket.objects.create(
        token_hash=_hash(ticket),
        user=user,
        expires_at=now + timedelta(seconds=settings.WS_TICKET_TTL_SECONDS),
    )
    return ticket


def redeem_ticket(ticket: str) -> User | None:
    """The person a ticket belongs to, or None. Burns the ticket.

    One UPDATE decides: of two sockets with the same ticket, the database lets
    the statement that runs second match no row, so only one of them wins.
    """
    now = timezone.now()
    token_hash = _hash(ticket)
    burned = WsTicket.objects.filter(
        token_hash=token_hash, used_at__isnull=True, expires_at__gt=now
    ).update(used_at=now)
    if not burned:
        return None
    user = WsTicket.objects.select_related("user").get(token_hash=token_hash).user
    return user if user.is_active else None
