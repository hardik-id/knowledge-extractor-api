"""Enqueue a background job (docs/jobs.md)."""

from typing import Any

from django.db import transaction
from django.tasks import Task


def enqueue_after_commit(task: Task[Any, Any], *args: Any, **kwargs: Any) -> None:
    """Enqueue `task` once the open transaction commits.

    A rollback enqueues nothing. Outside a transaction the job is enqueued
    at once. Pass ids, not objects.
    """
    transaction.on_commit(lambda: task.enqueue(*args, **kwargs))
