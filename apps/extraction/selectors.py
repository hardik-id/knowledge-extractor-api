"""Reads for the extraction app.

A selector takes the acting user and returns only what that user may see.
"""

from typing import Any

from django.db import IntegrityError, transaction

from apps.core.errors import ApiError
from apps.extraction.defaults import (
    DEFAULT_OUTPUT,
    DEFAULT_PROMPT,
    DEFAULT_RECORD_TYPES,
)
from apps.extraction.models import DefinitionVersion
from apps.identity.models import User
from apps.runs import selectors as runs


def latest_version(run_id: Any) -> DefinitionVersion | None:
    return DefinitionVersion.objects.filter(run_id=run_id).order_by("-version").first()


def get_definition(user: User, run_id: Any) -> DefinitionVersion:
    """The latest definition of ``user``'s run; the first read makes version 1.

    Someone else's run and an unknown id are both 404 ``run_not_found``.
    """
    run = runs.get_run(user, run_id)
    current = latest_version(run.pk)
    if current is not None:
        return current
    try:
        with transaction.atomic():
            return DefinitionVersion.objects.create(
                run=run,
                version=1,
                prompt=DEFAULT_PROMPT,
                record_types=DEFAULT_RECORD_TYPES,
                output=DEFAULT_OUTPUT,
            )
    except IntegrityError:  # a concurrent first read made it
        current = latest_version(run.pk)
        if current is None:
            raise
        return current


def get_definition_version(run_id: Any, version: int) -> DefinitionVersion:
    """One saved version of a run's definition, for the code that ran with it."""
    try:
        return DefinitionVersion.objects.get(run_id=run_id, version=version)
    except DefinitionVersion.DoesNotExist:
        raise ApiError("not_found", "Definition version not found.") from None
