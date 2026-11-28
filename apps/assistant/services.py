"""Writes and business rules for the assistant app.

A service takes the acting user as its first argument. The functions below the
line are the reply job's writes: each changes the stored reply only while it is
still ``streaming``, and announces the change once it is stored.
"""

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F, TextField, Value
from django.db.models.functions import Concat
from django.utils import timezone

from apps.assistant import selectors, tasks
from apps.assistant.agents.base import Message as Turn
from apps.assistant.models import Message, Role, Status
from apps.assistant.proposal import Proposal
from apps.core.errors import ApiError
from apps.core.jobs import enqueue_after_commit
from apps.extraction.definition import Draft
from apps.extraction.validation import parse_draft
from apps.iam.roles import Permission
from apps.identity.models import User
from apps.realtime import services as realtime
from apps.runs import selectors as runs

# What a reply that cannot finish ends with.
APOLOGY = "Sorry, something went wrong and I could not finish this reply."


def send_message(user: User, run_id: Any, *, text: str, definition: Any) -> Message:
    """Store what the person wrote and an empty reply, and start the reply job.

    404 for a run they do not see, 403 without ``workspace.edit``, 422
    ``empty_message`` for blank text,
    422 ``invalid_definition`` for a bad draft, 409 ``assistant_busy`` while a
    reply is still being written. Returns the person's message.
    """
    run = runs.get_run(user, run_id, Permission.WORKSPACE_EDIT)
    _close_stale_replies(run)
    text = text.strip()
    if not text:
        raise ApiError("empty_message")
    draft = parse_draft(definition)
    try:
        with transaction.atomic():
            if Message.objects.filter(run_id=run.pk, status=Status.STREAMING).exists():
                raise _busy()
            asked = Message.objects.create(
                run_id=run.pk,
                role=Role.USER,
                text=text,
                status=Status.DONE,
                definition=draft.model_dump(),
            )
            reply = Message.objects.create(
                run_id=run.pk,
                role=Role.ASSISTANT,
                status=Status.STREAMING,
                reply_to=asked,
            )
            enqueue_after_commit(tasks.write_reply, str(reply.pk))
    except IntegrityError:  # a concurrent message started a reply first
        raise _busy() from None
    return asked


def clear_messages(user: User, run_id: Any) -> None:
    """Remove every message of the run and announce ``assistant.cleared`` after the commit.

    404 for a run they do not see, 403 without ``workspace.edit``, 409
    ``assistant_busy`` while a reply is still being written (a stale one is closed first).
    """
    run = runs.get_run(user, run_id, Permission.WORKSPACE_EDIT)
    _close_stale_replies(run)
    with transaction.atomic():
        if Message.objects.filter(run_id=run.pk, status=Status.STREAMING).exists():
            raise _busy()
        Message.objects.filter(run_id=run.pk).delete()
        realtime.publish_run_event(run.pk, {"type": "assistant.cleared"})


def _busy() -> ApiError:
    return ApiError("assistant_busy")


def close_stale_replies(user: User, run_id: Any) -> None:
    """Close the run's replies still streaming after ``ASSISTANT_REPLY_TIMEOUT_SECONDS``.

    Their worker died: they end as an agent failure does, and no longer count as busy.
    Reading the conversation does this, so it needs ``workspace.view`` only.
    """
    _close_stale_replies(runs.get_run(user, run_id, Permission.WORKSPACE_VIEW))


def _close_stale_replies(run: Any) -> None:
    cutoff = timezone.now() - timedelta(
        seconds=settings.ASSISTANT_REPLY_TIMEOUT_SECONDS
    )
    stale = Message.objects.filter(
        run_id=run.pk, status=Status.STREAMING, created_at__lt=cutoff
    ).values_list("pk", flat=True)
    for message_id in list(stale):
        close_reply(message_id)


# ---------------------------------------------------------------------------
# The reply job's writes (apps/assistant/tasks.py).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Request:
    """What the agent is given for one reply."""

    run_id: Any
    text: str
    definition: Draft
    history: list[Turn]
    run_view: selectors.StoredRunView


def start_reply(message_id: Any) -> Request | None:
    """What the agent needs to write reply ``message_id``, or None when there is nothing to do.

    A reply that is gone or done needs nothing. A reply that already has some of
    its text was started by an earlier run of the job that died: it is closed,
    because the deltas it sent cannot be taken back.
    """
    message = (
        Message.objects.select_related("reply_to", "run__owner")
        .filter(pk=message_id, role=Role.ASSISTANT, status=Status.STREAMING)
        .first()
    )
    if message is None:
        return None
    asked = message.reply_to
    if (
        asked is None
        or not asked.definition
        or message.text
        or message.proposal is not None
    ):
        close_reply(message.pk)
        return None
    history = [
        Turn(role=m.role, text=m.text)  # type: ignore[arg-type]
        for m in Message.objects.filter(
            run_id=message.run_id,
            status=Status.DONE,
            created_at__lt=asked.created_at,
        )
    ]
    return Request(
        run_id=message.run_id,
        text=asked.text,
        definition=Draft.model_validate(asked.definition),
        history=history,
        run_view=selectors.run_run_view(message),
    )


def _streaming(message_id: Any) -> Any:
    return Message.objects.filter(pk=message_id, status=Status.STREAMING)


def append_text(message_id: Any, text: str) -> bool:
    """Add ``text`` to the reply. False when the reply is no longer streaming."""
    return bool(
        _streaming(message_id).update(
            text=Concat(F("text"), Value(text), output_field=TextField()),
            updated_at=timezone.now(),
        )
    )


def set_proposal(message_id: Any, proposal: Proposal) -> bool:
    """Store the reply's proposal. False when the reply is no longer streaming."""
    return bool(
        _streaming(message_id).update(
            proposal=proposal.model_dump(), updated_at=timezone.now()
        )
    )


def finish_reply(message_id: Any) -> bool:
    """Mark the reply done. False when it already was."""
    return bool(
        _streaming(message_id).update(status=Status.DONE, updated_at=timezone.now())
    )


def close_reply(message_id: Any) -> None:
    """End a reply that will not be finished: the apology is added and it is done.

    The apology goes out as a delta, then ``assistant.done``, once this commits.
    A reply that is already done is left alone.
    """
    with transaction.atomic():
        message = _streaming(message_id).select_for_update().first()
        if message is None:
            return
        delta = f"\n\n{APOLOGY}" if message.text else APOLOGY
        message.text += delta
        message.status = Status.DONE
        message.save(update_fields=["text", "status", "updated_at"])
        realtime.publish_run_event(message.run_id, delta_event(message.pk, delta))
        realtime.publish_run_event(message.run_id, done_event(message.pk))


def delta_event(message_id: Any, text: str) -> dict[str, Any]:
    return {"type": "assistant.delta", "message_id": str(message_id), "text": text}


def proposal_event(message_id: Any, proposal: Proposal) -> dict[str, Any]:
    return {
        "type": "assistant.proposal",
        "message_id": str(message_id),
        "proposal": proposal.model_dump(),
    }


def done_event(message_id: Any) -> dict[str, Any]:
    return {"type": "assistant.done", "message_id": str(message_id)}
