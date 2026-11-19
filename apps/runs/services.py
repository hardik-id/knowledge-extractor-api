"""Writes and business rules for the runs app.

A service takes the acting user as its first argument.
"""

from collections.abc import Sequence
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.core.errors import ApiError
from apps.documents import selectors as documents
from apps.identity.models import User
from apps.runs.models import Cell, CellStatus, Run, RunFile, Stage

STORAGE = "storage"


@transaction.atomic
def create_run(user: User, items: Sequence[dict[str, Any]]) -> Run:
    """A run of storage documents, one pending ``extract`` cell per file.

    Name, type, size, location and modified time come from the catalog, not from
    the request. The first ``source_ref`` the person may not open is a 404.
    """
    if not items:
        raise ApiError("no_files")
    sources = {item["source"] for item in items}
    if sources != {STORAGE}:
        raise ApiError("mixed_sources" if STORAGE in sources else "unsupported_source")
    entries = [documents.get_document(user, item["source_ref"]) for item in items]
    run = Run.objects.create(owner=user)
    files = RunFile.objects.bulk_create(
        RunFile(
            run=run,
            source=STORAGE,
            source_ref=entry.id,
            name=entry.name,
            type=entry.type,
            size_bytes=entry.size_bytes,
            location=entry.location,
            modified_at=entry.modified_at,
            etag=entry.etag,
        )
        for entry in entries
    )
    Cell.objects.bulk_create(Cell(file=file, stage=Stage.EXTRACT) for file in files)
    return run


def delete_run(run: Run) -> None:
    """Delete the run with its files and cells."""
    run.delete()


def set_cell(
    file: RunFile,
    stage: str,
    *,
    status: str,
    execution_id: str | None = None,
    progress: int | None = None,
    error: dict[str, str] | None = None,
    output: dict[str, Any] | None = None,
) -> Cell:
    """The one function through which a cell changes. It stamps ``updated_at``."""
    cell = Cell.objects.get(file=file, stage=stage)
    cell.status = CellStatus(status)
    cell.execution_id = execution_id
    cell.progress = progress
    cell.error = error
    cell.output = output
    cell.updated_at = timezone.now()
    cell.save()
    return cell
