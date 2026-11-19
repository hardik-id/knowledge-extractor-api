"""Enqueue a background job and run it in the request's trace (docs/jobs.md, docs/observability.md).

The trace context travels with the job: `enqueue_after_commit` stores the
current W3C `traceparent` (and `tracestate`) in the job's arguments, and a job
declared with `@job` restores it before its body runs, so the spans the job
makes continue the trace of the request that enqueued it. A job's own code
never touches it.
"""

import functools
from collections.abc import Callable
from typing import Any

from django.db import transaction
from django.tasks import Task, task
from opentelemetry import context
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

# The keyword argument that carries the trace context. `@job` takes it off
# before the job function sees its arguments.
TRACE_KWARG = "_trace"

# Only the trace context travels, never baggage: a request's baggage is
# whatever its caller sent.
_propagator = TraceContextTextMapPropagator()


def job(**options: Any) -> Callable[[Callable[..., Any]], Task[Any, Any]]:
    """`@task`, plus restoring the trace context stored when the job was enqueued.

    Use it in place of `@task` (`@job()`; the options are the task's). A job
    enqueued with no context (a direct `.enqueue`, no active span) starts a
    trace of its own.
    """

    def decorate(function: Callable[..., Any]) -> Task[Any, Any]:
        @functools.wraps(function)
        def run(*args: Any, **kwargs: Any) -> Any:
            carrier = kwargs.pop(TRACE_KWARG, None)
            if not carrier:
                return function(*args, **kwargs)
            token = context.attach(_propagator.extract(carrier))
            try:
                return function(*args, **kwargs)
            finally:
                context.detach(token)

        return task(**options)(run)  # type: ignore[no-any-return]

    return decorate


def enqueue_after_commit(task: Task[Any, Any], *args: Any, **kwargs: Any) -> None:
    """Enqueue `task` once the open transaction commits.

    A rollback enqueues nothing. Outside a transaction the job is enqueued
    at once. Pass ids, not objects. The current trace context goes with the
    job (see `job`).
    """
    carrier: dict[str, str] = {}
    _propagator.inject(carrier)
    if carrier:
        kwargs[TRACE_KWARG] = carrier
    transaction.on_commit(lambda: task.enqueue(*args, **kwargs))
