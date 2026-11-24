"""Is each part a stub or the real thing? (docs/status.md)

``build_status`` reads the settings and stored state, pings the channel layer and
makes no other outside call: it never calls the model. The outcome of real model
calls is recorded by ``record_call`` and read back here. The answer holds modes,
provider and model names, states, times and short problem codes, never an address,
a key, a message or a body.
"""

import asyncio
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Literal

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
from apps.core.models import ModelCall, StatusTestClaim

log = structlog.get_logger(__name__)

Mode = Literal["stub", "real"]
State = Literal["stub", "ok", "failing", "unknown"]

# A real call's outcome is written at most this often per part, unless it changes.
RECORD_INTERVAL_SECONDS = 30.0
PING_TIMEOUT_SECONDS = 2.0
PING_CACHE_SECONDS = 10.0
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


def record_call(
    part: str, error: BaseException | None = None, *, force: bool = False
) -> None:
    """Remember how the last real call of ``part`` went. Never raises, never fails the call.

    A repeated outcome is written at most once per ``RECORD_INTERVAL_SECONDS``;
    ``force`` (a status test) always writes.
    """
    try:
        problem = "" if error is None else problem_code(error)
        now = _now()
        last = _written.get(part)
        if (
            not force
            and last
            and last[0] == problem
            and now - last[1] < RECORD_INTERVAL_SECONDS
        ):
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


# The last ping: (monotonic time, wall time, problem). Per process, shared by requests.
_ping_cache: tuple[float, datetime, str | None] | None = None
_ping_lock = threading.Lock()


def _cached_ping(fresh: bool = False) -> tuple[datetime, str | None]:
    """Ping the channel layer, at most once per ``PING_CACHE_SECONDS``, one in flight.

    Other callers wait for the one ping and reuse its answer, so repeated requests cost
    nothing and a slow Redis does not collect a ping per request.
    """
    global _ping_cache
    with _ping_lock:
        cached = _ping_cache
        if cached and not fresh and _now() - cached[0] < PING_CACHE_SECONDS:
            return cached[1], cached[2]
        problem = None
        try:
            async_to_sync(_ping)()
        except TimeoutError:
            problem = "timeout"
        except Exception as exc:
            log.warning("status_ping_failed", cause=type(exc).__name__)
            problem = "unreachable"
        _ping_cache = (_now(), timezone.now(), problem)
        return _ping_cache[1], problem


def _live_updates_part() -> Part:
    backend = settings.CHANNEL_LAYERS["default"]["BACKEND"]
    if "InMemory" in backend:
        return Part(id="live_updates", mode="stub", label="In memory", state="stub")
    label = "Redis" if "Redis" in backend else "Channel layer"
    checked_at, problem = _cached_ping()
    return Part(
        id="live_updates",
        mode="real",
        label=label,
        state="failing" if problem else "ok",
        checked_at=checked_at,
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
    """A job has been ready for more than a minute and the worker shows no sign of life.

    One worker runs one task at a time, so a job waiting behind a long task is not a
    stalled worker. Alive means a task is running that started inside the allowed
    execution time, or a task started or finished in the last minute.
    """
    from django.tasks.base import TaskResultStatus
    from django_tasks_db.models import DBTaskResult, get_date_max

    now = timezone.now()
    cutoff = now - timedelta(seconds=WORKER_STALLED_SECONDS)
    waiting = (
        DBTaskResult.objects.ready()
        .filter(enqueued_at__lt=cutoff)
        .filter(Q(run_after=get_date_max()) | Q(run_after__lt=cutoff))
        .exists()
    )
    if not waiting:
        return False
    limit = now - timedelta(seconds=settings.EXECUTION_TIMEOUT_SECONDS)
    running = DBTaskResult.objects.filter(
        status=TaskResultStatus.RUNNING, started_at__gt=limit
    ).exists()
    if running:
        return False
    recent = DBTaskResult.objects.filter(
        Q(started_at__gt=cutoff) | Q(finished_at__gt=cutoff)
    ).exists()
    return not recent


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


# ---------------------------------------------------------------------------
# POST /status/test
# ---------------------------------------------------------------------------

TEST_INTERVAL_SECONDS = 60
TEST_MODEL_TIMEOUT_SECONDS = 20.0
TEST_OUTPUT_TOKENS = 8


def _real_model_parts() -> list[str]:
    parts = []
    if settings.ASSISTANT_AGENT == "openai":
        parts.append("assistant")
    if settings.EXTRACTOR == "llm":
        parts.append("extraction")
    return parts


def _claim_test() -> bool:
    """Take the right to run a test, for the whole deployment. One conditional UPDATE."""
    StatusTestClaim.objects.get_or_create(key="status")
    now = timezone.now()
    taken = (
        StatusTestClaim.objects.filter(key="status")
        .filter(
            Q(claimed_at__isnull=True)
            | Q(claimed_at__lt=now - timedelta(seconds=TEST_INTERVAL_SECONDS))
        )
        .update(claimed_at=now)
    )
    return taken == 1


async def _call_model() -> None:
    """A model call of a few tokens. The answer is neither kept nor logged."""
    from agents import Agent, ModelSettings, RunConfig, Runner

    from apps.core.llm import connect, output_limit

    model, client = connect()
    try:
        agent: Agent[Any] = Agent(
            name="Status test",
            instructions="Answer with the single word OK.",
            model=model,
            model_settings=ModelSettings(
                store=False, **output_limit(TEST_OUTPUT_TOKENS)
            ),
        )
        await asyncio.wait_for(
            Runner.run(
                agent,
                "Ping.",
                max_turns=1,
                run_config=RunConfig(
                    tracing_disabled=True, trace_include_sensitive_data=False
                ),
            ),
            TEST_MODEL_TIMEOUT_SECONDS,
        )
    finally:
        await client.close()


def _test_model() -> BaseException | None:
    """The one test call for the model in use; the failure, or None when it worked."""
    from agents import ModelBehaviorError, ModelRefusalError

    try:
        asyncio.run(_call_model())
    except ModelBehaviorError, ModelRefusalError:
        return None  # an unusable answer still means the model was reached
    except Exception as error:
        log.warning("status_test_model_failed", **describe_failure(error))
        return error
    return None


def run_test() -> str:
    """Check every real part now. ``run`` when it did, ``cached`` when the last test is
    under a minute old (the stored result stands), ``skipped`` when nothing is real, so
    nothing is called."""
    models = _real_model_parts()
    live = "InMemory" not in settings.CHANNEL_LAYERS["default"]["BACKEND"]
    if not models and not live:
        return "skipped"
    if not _claim_test():
        return "cached"
    if models and not missing_settings():
        # Assistant and extractor use one provider and model: one call for both.
        failure = _test_model()
        for part in models:
            record_call(part, failure, force=True)
    if live:
        _cached_ping(fresh=True)
    return "run"


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
