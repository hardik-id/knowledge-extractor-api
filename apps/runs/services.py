"""Writes and business rules for the runs app.

A service takes the acting user as its first argument.
"""

from collections.abc import Sequence
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.core.errors import ApiError
from apps.documents import selectors as documents
from apps.iam.roles import Permission
from apps.identity.models import User
from apps.realtime import services as realtime
from apps.runs import selectors
from apps.runs.api.serializers import CellSerializer
from apps.runs.models import Cell, CellStatus, Run, RunFile, Stage

STORAGE = "storage"


def _resolve_documents(user: User, items: Sequence[dict[str, Any]]) -> list[Any]:
    """The catalog entries for ``items``: the checks a run's documents always pass.

    Storage documents only, none twice, each one opened as ``user`` (the first
    one the person may not open is a 404 ``document_not_found``).
    """
    sources = {item["source"] for item in items}
    if items and sources != {STORAGE}:
        raise ApiError("mixed_sources" if STORAGE in sources else "unsupported_source")
    refs = [item["source_ref"] for item in items]
    if len(set(refs)) != len(refs):
        raise ApiError(
            "validation_error",
            "A document can be in a run only once.",
            details={"source_ref": sorted({r for r in refs if refs.count(r) > 1})},
        )
    return [documents.get_document(user, ref) for ref in refs]


def _add_files(run: Run, entries: Sequence[Any]) -> None:
    """A file and a pending ``extract`` cell for each catalog entry. Facts come from the catalog."""
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


@transaction.atomic
def create_run(user: User, items: Sequence[dict[str, Any]]) -> Run:
    """A run of storage documents, one pending ``extract`` cell per file.

    Name, type, size, location and modified time come from the catalog, not from
    the request. The first ``source_ref`` the person may not open is a 404.
    """
    if not items:
        raise ApiError("no_files")
    entries = _resolve_documents(user, items)
    run = Run.objects.create(owner=user)
    _add_files(run, entries)
    return run


def create_empty_run(user: User) -> Run:
    """A run with no files, for other apps. ``POST /runs`` still refuses an empty list."""
    return Run.objects.create(owner=user)


def replace_documents(user: User, run_id: Any, items: Sequence[dict[str, Any]]) -> Run:
    """Make the run's documents exactly ``items``, which may be empty.

    A file whose ``source_ref`` is not listed goes, with its cell and records. A
    file that stays is not touched. A new document gets a file and a pending cell.
    409 ``execution_in_progress`` while a file of the run is queued or running.
    All or nothing; the run's sockets get ``{"type": "run.changed"}`` after the commit.
    """
    run = selectors.get_run(user, run_id, Permission.WORKSPACE_EDIT)
    release_stuck_cells(run)
    with transaction.atomic():
        Run.objects.select_for_update().get(pk=run.pk)
        entries = _resolve_documents(user, items)
        active = (
            Cell.objects.select_for_update(of=("self",))
            .filter(file__run=run, status__in=ACTIVE)
            .order_by("pk")
            .first()
        )
        if active is not None:
            raise ApiError(
                "execution_in_progress", details={"execution_id": active.execution_id}
            )
        wanted = {entry.id for entry in entries}
        have = set(run.files.values_list("source_ref", flat=True))
        run.files.exclude(source_ref__in=wanted).delete()
        _add_files(run, [entry for entry in entries if entry.id not in have])
        realtime.publish_run_event(run.pk, {"type": "run.changed"})
    return run


ACTIVE = (CellStatus.QUEUED, CellStatus.RUNNING)


def queue_cells(files: Sequence[RunFile], stage: str, execution_id: str) -> None:
    """Make the cells of ``files`` ``queued`` for one execution, inside the caller's transaction.

    409 ``execution_in_progress`` when one of them is already queued or running.
    The cells are locked first, so of two requests for the same file one wins.
    """
    cells = (
        Cell.objects.select_for_update()
        .filter(file__in=files, stage=stage)
        .order_by("pk")
    )
    active = next((cell for cell in cells if cell.status in ACTIVE), None)
    if active is not None:
        raise ApiError(
            "execution_in_progress", details={"execution_id": active.execution_id}
        )
    for file in files:
        set_cell(file, stage, status=CellStatus.QUEUED, execution_id=execution_id)


def delete_run(run: Run) -> None:
    """Delete the run with its files and cells. Its sockets close with 4404."""
    run_id = run.pk
    run.delete()
    realtime.close_run_sockets(run_id)


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
    """The one function through which a cell changes. It stamps ``updated_at``.

    Every change is announced on the run's socket as ``{"type": "cell", "cell"}``,
    the cell in the shape of the snapshot, once the transaction commits.
    """
    cell = Cell.objects.get(file=file, stage=stage)
    cell.status = CellStatus(status)
    cell.execution_id = execution_id
    cell.progress = progress
    cell.error = error
    cell.output = output
    cell.updated_at = timezone.now()
    cell.save()
    realtime.publish_run_event(
        file.run_id, {"type": "cell", "cell": dict(CellSerializer(cell).data)}
    )
    return cell


def release_stuck_cells(run: Run) -> None:
    """Fail the run's cells left ``queued`` or ``running`` longer than the timeout.

    A worker that died leaves its cell active; this lets the file be executed
    again. The cell keeps its ``execution_id``, so a late job sees it is no longer
    queued or running and does nothing.
    """
    deadline = timezone.now() - timedelta(seconds=settings.EXECUTION_TIMEOUT_SECONDS)
    with transaction.atomic():
        stuck = (
            Cell.objects.select_for_update(of=("self",))
            .select_related("file")
            .filter(
                file__run=run,
                status__in=ACTIVE,
                updated_at__lt=deadline,
            )
        )
        for cell in stuck:
            set_cell(
                cell.file,
                cell.stage,
                status=CellStatus.FAILED,
                execution_id=cell.execution_id,
                error={
                    "code": "execution_timeout",
                    "message": "The work did not finish in time.",
                },
            )
