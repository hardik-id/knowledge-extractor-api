"""Is each part a stub or the real thing? (docs/status.md)

``build_status`` reads the settings and stored state, pings the channel layer and
makes no other outside call: it never calls the model. The outcome of real model
calls is recorded by ``record_call`` and read back here. The answer holds modes,
provider and model names, states, times and short problem codes, never an address,
a key, a message or a body.
"""

import asyncio
import time
from datetime import datetime, timedelta
from typing import Literal

import structlog
from asgiref.sync import async_to_sync, sync_to_async
from channels.layers import get_channel_layer
from django.conf import settings
from django.db import DatabaseError
from django.db.models import Q
from django.utils import timezone
from pydantic import BaseModel

from apps.core import telemetry
from apps.core.llm import describe_failure, missing_settings
from apps.core.models import ModelCall

log = structlog.get_logger(__name__)

Mode = Literal["stub", "real"]
State = Literal["stub", "ok", "failing", "unknown"]

# A real call's outcome is written at most this often per part, unless it changes.
RECORD_INTERVAL_SECONDS = 30.0
PING_TIMEOUT_SECONDS = 2.0
WORKER_STALLED_SECONDS = 60


class Part(BaseModel):
    id: str
    mode: Mode
    label: str
    state: State
    checked_at: datetime | None = None
    problem: str | None = None


class BackendStatus(BaseModel):
    environment: str
    parts: list[Part]


# ---------------------------------------------------------------------------
# Recording the outcome of real model calls
# ---------------------------------------------------------------------------


def problem_code(error: BaseException) -> str:
    """A short code for a failed model call, from ``describe_failure``: never a message."""
    described = describe_failure(error)
    name = str(described["error"])
    status = described["status_code"]
    if "Timeout" in name or isinstance(error, TimeoutError):
        return "timeout"
    if isinstance(status, int):
        if status in (401, 403):
            return "auth_failed"
        if status == 404:
            return "not_found"
        if status == 429:
            return "rate_limited"
        if status in (400, 422):
            return "bad_request"
        if status in (502, 503, 504):
            return "unreachable"
        return "error"
    if "Authentication" in name:  # the Azure sign-in
        return "auth_failed"
    if "Connection" in name or isinstance(error, OSError):
        return "unreachable"
    return "error"


# part -> (problem, time of the last write); per process.
_written: dict[str, tuple[str, float]] = {}


def _now() -> float:
    return time.monotonic()


def record_call(part: str, error: BaseException | None = None) -> None:
    """Remember how the last real call of ``part`` went. Never raises, never fails the call.

    A repeated outcome is written at most once per ``RECORD_INTERVAL_SECONDS``.
    """
    try:
        problem = "" if error is None else problem_code(error)
        now = _now()
        last = _written.get(part)
        if last and last[0] == problem and now - last[1] < RECORD_INTERVAL_SECONDS:
            return
        ModelCall.objects.update_or_create(
            part=part, defaults={"problem": problem, "checked_at": timezone.now()}
        )
        _written[part] = (problem, now)
    except Exception as exc:
        log.warning("model_call_not_recorded", part=part, cause=type(exc).__name__)


async def arecord_call(part: str, error: BaseException | None = None) -> None:
    """``record_call`` for async code."""
    try:
        await sync_to_async(record_call)(part, error)
    except Exception as exc:
        log.warning("model_call_not_recorded", part=part, cause=type(exc).__name__)


# ---------------------------------------------------------------------------
# The parts
# ---------------------------------------------------------------------------


def _model_label() -> str:
    return f"{settings.LLM_PROVIDER} · {settings.LLM_MODEL or 'no model'}"


def _model_part(part_id: str, real: bool) -> Part:
    if not real:
        return Part(id=part_id, mode="stub", label="Scripted", state="stub")
    label = _model_label()
    missing = missing_settings()
    if missing:
        return Part(
            id=part_id,
            mode="real",
            label=label,
            state="failing",
            checked_at=timezone.now(),
            problem="not_configured",
        )
    try:
        call = ModelCall.objects.filter(part=part_id).first()
    except DatabaseError:
        call = None
    if call is None:
        return Part(id=part_id, mode="real", label=label, state="unknown")
    return Part(
        id=part_id,
        mode="real",
        label=label,
        state="failing" if call.problem else "ok",
        checked_at=call.checked_at,
        problem=call.problem or None,
    )


def _storage_part() -> Part:
    storage = settings.DOCUMENT_STORAGE == "azure"
    catalog = settings.DOCUMENT_CATALOG == "http"
    if not storage and not catalog:
        return Part(id="storage", mode="stub", label="Samples", state="stub")
    names = []
    if catalog:
        names.append("Catalog service")
    if storage:
        names.append("Azure Blob storage")
    return Part(id="storage", mode="real", label=" · ".join(names), state="unknown")


def _sign_in_part() -> Part:
    if settings.AUTH_MODE == "dev":
        return Part(id="sign_in", mode="stub", label="Dev token", state="stub")
    # The caller is signed in, which a token from the identity provider proves.
    return Part(
        id="sign_in",
        mode="real",
        label="Microsoft Entra",
        state="ok",
        checked_at=timezone.now(),
    )


async def _ping() -> None:
    layer = get_channel_layer()
    if layer is None:
        raise RuntimeError("no channel layer")
    async with asyncio.timeout(PING_TIMEOUT_SECONDS):
        channel = await layer.new_channel()
        await layer.send(channel, {"type": "status.ping"})
        await layer.receive(channel)


def _live_updates_part() -> Part:
    backend = settings.CHANNEL_LAYERS["default"]["BACKEND"]
    if "InMemory" in backend:
        return Part(id="live_updates", mode="stub", label="In memory", state="stub")
    label = "Redis" if "Redis" in backend else "Channel layer"
    problem = None
    try:
        async_to_sync(_ping)()
    except TimeoutError:
        problem = "timeout"
    except Exception as exc:
        log.warning("status_ping_failed", cause=type(exc).__name__)
        problem = "unreachable"
    return Part(
        id="live_updates",
        mode="real",
        label=label,
        state="failing" if problem else "ok",
        checked_at=timezone.now(),
        problem=problem,
    )


def _worker_part() -> Part:
    backend = settings.TASKS["default"]["BACKEND"]
    if "immediate" in backend:
        return Part(id="worker", mode="stub", label="Runs inline", state="stub")
    problem = None
    try:
        problem = "worker_stalled" if _queue_is_stalled() else None
    except DatabaseError as exc:
        log.warning("status_queue_unreadable", cause=type(exc).__name__)
        problem = "error"
    return Part(
        id="worker",
        mode="real",
        label="Background worker",
        state="failing" if problem else "ok",
        checked_at=timezone.now(),
        problem=problem,
    )


def _queue_is_stalled() -> bool:
    """A job has been ready to run for more than a minute and nobody took it."""
    from django_tasks_db.models import DBTaskResult, get_date_max

    cutoff = timezone.now() - timedelta(seconds=WORKER_STALLED_SECONDS)
    return (
        DBTaskResult.objects.ready()
        .filter(enqueued_at__lt=cutoff)
        .filter(Q(run_after=get_date_max()) | Q(run_after__lt=cutoff))
        .exists()
    )


def build_status() -> BackendStatus:
    return BackendStatus(
        environment=telemetry.environment(),
        parts=[
            _model_part("assistant", settings.ASSISTANT_AGENT == "openai"),
            _model_part("extraction", settings.EXTRACTOR == "llm"),
            _storage_part(),
            _sign_in_part(),
            _live_updates_part(),
            _worker_part(),
        ],
    )


def log_backend_status() -> None:
    """The one line at start that says which parts are real. No address, no key."""
    log.info(
        "backend status",
        assistant=settings.ASSISTANT_AGENT,
        extractor=settings.EXTRACTOR,
        provider=settings.LLM_PROVIDER,
        model=settings.LLM_MODEL,
        storage=settings.DOCUMENT_STORAGE,
        catalog=settings.DOCUMENT_CATALOG,
        auth=settings.AUTH_MODE,
    )
