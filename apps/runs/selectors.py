"""Reads for the runs app.

A selector takes the acting user and returns only what that user may see.
"""

from typing import Any
from uuid import UUID

from apps.core.errors import ApiError
from apps.core.permissions import get_visible_or_404
from apps.identity.models import User
from apps.runs.models import Cell, Run, RunFile


def get_run(user: User, run_id: Any) -> Run:
    """The run, if ``user`` owns it. Someone else's run and an unknown id are both 404."""
    return get_visible_or_404(Run, user, run_id, code="run_not_found")


def get_any_run(run_id: Any) -> Run:
    """The run, whoever owns it: for operator commands, never for a request. 404 when unknown."""
    try:
        return Run.objects.get(pk=UUID(str(run_id)))
    except Run.DoesNotExist, ValueError:
        raise ApiError("run_not_found") from None


def get_run_file(user: User, run_id: Any, file_id: Any) -> RunFile:
    """A file of one of ``user``'s runs, otherwise 404 ``file_not_found``."""
    run = get_run(user, run_id)
    try:
        return run.files.get(pk=UUID(str(file_id)))
    except RunFile.DoesNotExist, ValueError:
        raise ApiError("file_not_found") from None


def cell_for_update(file_id: Any, stage: str) -> Cell | None:
    """The cell of a file and stage, locked until the transaction ends; for a background job.

    A job acts for no signed-in person: it has only the file's id. None when the
    file is gone (its run was deleted).
    """
    return (
        Cell.objects.select_for_update(of=("self",))
        .select_related("file__run")
        .filter(file_id=file_id, stage=stage)
        .first()
    )
