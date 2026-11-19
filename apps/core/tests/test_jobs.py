from collections.abc import Callable
from typing import Any

import pytest
from django.db import transaction
from django.tasks import task, task_backends

from apps.core import telemetry
from apps.core.jobs import TRACE_KWARG, enqueue_after_commit, job
from apps.core.tests.otel import Telemetry

ran: list[int] = []


@task()
def record(number: int) -> int:
    ran.append(number)
    return number * 2


@pytest.fixture(autouse=True)
def _clear() -> None:
    ran.clear()


def test_tests_run_jobs_inline() -> None:
    result = record.enqueue(1)

    assert ran == [1]
    assert result.return_value == 2


@pytest.mark.django_db(transaction=True)
def test_job_runs_after_commit_and_not_before() -> None:
    with transaction.atomic():
        enqueue_after_commit(record, 2)
        assert ran == []

    assert ran == [2]


@pytest.mark.django_db(transaction=True)
def test_rollback_enqueues_nothing() -> None:
    with pytest.raises(RuntimeError), transaction.atomic():
        enqueue_after_commit(record, 3)
        raise RuntimeError("roll back")

    assert ran == []


# --- the trace context travels with the job -------------------------------------


@job()
def traced(number: int) -> int:
    with telemetry.get_tracer("test").start_as_current_span("work"):
        pass
    return number


@pytest.mark.django_db(transaction=True)
def test_a_job_continues_the_trace_of_the_request_that_enqueued_it(
    otel: Telemetry, queued: Callable[[], None]
) -> None:
    tracer = otel.tracer_provider.get_tracer("test")
    with tracer.start_as_current_span("request") as request:
        enqueue_after_commit(traced, 5)
    (waiting,) = task_backends["default"].results  # type: ignore[attr-defined]
    assert waiting.args == [5]
    assert set(waiting.kwargs) == {TRACE_KWARG}
    assert otel.named("work") == []

    queued()  # in an empty context, as a worker would

    (work,) = otel.named("work")
    assert work.context.trace_id == request.get_span_context().trace_id
    assert work.parent is not None
    assert work.parent.span_id == request.get_span_context().span_id
    assert work.parent.is_remote


@pytest.mark.django_db(transaction=True)
def test_a_job_enqueued_outside_a_span_carries_no_context_and_starts_a_trace(
    otel: Telemetry, queued: Callable[[], None]
) -> None:
    enqueue_after_commit(traced, 6)
    (waiting,) = task_backends["default"].results  # type: ignore[attr-defined]
    assert waiting.kwargs == {}

    queued()

    (work,) = otel.named("work")
    assert work.parent is None


seen: list[Any] = []


@job()
def look(*args: Any, **kwargs: Any) -> None:
    seen.append((args, kwargs))


@pytest.mark.django_db(transaction=True)
def test_the_job_does_not_see_the_context_in_its_arguments(
    otel: Telemetry,
) -> None:
    seen.clear()
    with otel.tracer_provider.get_tracer("test").start_as_current_span("request"):
        enqueue_after_commit(look, "a", key="b")

    assert seen == [(("a",), {"key": "b"})]


def test_a_job_called_without_context_just_runs(otel: Telemetry) -> None:
    assert traced.call(7) == 7
