"""Reads for the runs app.

A selector takes the acting user and returns only what that user may see.
"""

from typing import Any
from uuid import UUID

from apps.core.errors import ApiError
from apps.core.permissions import get_visible_or_404
from apps.identity.models import User
from apps.runs.models import Run, RunFile


def get_run(user: User, run_id: Any) -> Run:
    """The run, if ``user`` owns it. Someone else's run and an unknown id are both 404."""
    return get_visible_or_404(Run, user, run_id, code="run_not_found")


def get_run_file(user: User, run_id: Any, file_id: Any) -> RunFile:
    """A file of one of ``user``'s runs, otherwise 404 ``file_not_found``."""
    run = get_run(user, run_id)
    try:
        return run.files.get(pk=UUID(str(file_id)))
    except RunFile.DoesNotExist, ValueError:
        raise ApiError("file_not_found") from None
