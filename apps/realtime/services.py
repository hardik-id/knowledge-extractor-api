"""Socket tickets, and the events the run socket sends.

A browser cannot send an ``Authorization`` header on a WebSocket, so the person
asks for a ticket over REST and puts it in the socket URL (docs/realtime.md).
Any part of the backend announces a change to a run with ``publish_run_event``.
"""

import hashlib
import secrets
from datetime import timedelta
from typing import Any

import structlog
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.identity.models import User
from apps.realtime import telemetry
from apps.realtime.models import WsTicket

log = structlog.get_logger(__name__)


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


# ---------------------------------------------------------------------------
# Run events: what the run socket sends (docs/realtime.md).
# ---------------------------------------------------------------------------


def run_group(run_id: Any) -> str:
    """The channel-layer group of a run: every socket that follows it."""
    return f"run.{str(run_id).lower()}"


def run_user_group(run_id: Any, user_id: Any) -> str:
    """The channel-layer group of one person's sockets on a run."""
    return f"{run_group(run_id)}.user.{user_id}"


def publish_run_event(run_id: Any, event: dict[str, Any]) -> None:
    """Send ``event`` to everyone who follows the run, once the transaction commits.

    For request code and jobs. Outside a transaction it goes at once. Rolled back,
    it never goes. It never raises: a failure is logged and the caller carries on.
    Nobody listening is fine; the event is lost on purpose.
    """
    _on_commit(run_id, {"type": "run.event", "event": event})


async def apublish_run_event(run_id: Any, event: dict[str, Any]) -> None:
    """``publish_run_event`` for async code. Async code holds no transaction: it goes at once."""
    await _asend(run_id, {"type": "run.event", "event": event})


def close_run_sockets(run_id: Any) -> None:
    """Close every socket on the run with 4404, once the transaction commits. Never raises."""
    _on_commit(run_id, {"type": "run.gone"})


def close_user_run_sockets(run_id: Any, user_id: Any) -> None:
    """Close one person's sockets on the run with 4403, once the transaction commits.

    For when their access is taken away. Never raises.
    """
    _on_commit(run_id, {"type": "run.access_removed"}, user_id)


def _on_commit(run_id: Any, message: dict[str, Any], user_id: Any = None) -> None:
    try:
        transaction.on_commit(lambda: _send(run_id, message, user_id))
    except Exception:
        log.exception("run_event_not_sent", run_id=str(run_id), kind=_kind(message))


def _send(run_id: Any, message: dict[str, Any], user_id: Any = None) -> None:
    try:
        async_to_sync(_asend)(run_id, message, user_id)
    except Exception:
        # _asend logs its own failures; this is async_to_sync itself failing.
        # Run at commit time, an exception here would fail the caller's commit.
        log.exception("run_event_not_sent", run_id=str(run_id), kind=_kind(message))


async def _asend(run_id: Any, message: dict[str, Any], user_id: Any = None) -> None:
    try:
        layer = get_channel_layer()
        if layer is None:
            raise RuntimeError("no channel layer is configured")
        group = (
            run_group(run_id) if user_id is None else run_user_group(run_id, user_id)
        )
        await layer.group_send(group, message)
        telemetry.event_published(_kind(message))
    except Exception:
        log.exception("run_event_not_sent", run_id=str(run_id), kind=_kind(message))


def _kind(message: dict[str, Any]) -> str:
    """What a message is, for the log: the event type, or ``run.gone``."""
    event = message.get("event")
    return str(event.get("type")) if isinstance(event, dict) else str(message["type"])
