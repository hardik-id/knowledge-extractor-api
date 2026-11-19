# Background jobs

Work that outlives a request (an agent's reply, an extraction) runs in a worker process. The framework is Django's own Tasks (`django.tasks`) with the database backend of `django-tasks-db`: the queue is a table in the same PostgreSQL, so there is nothing else to run.

## Running

| Where | Backend | How the worker runs |
| --- | --- | --- |
| Local and production | `django_tasks_db.DatabaseBackend` | `make worker` (`manage.py db_worker`), or the compose `worker` service |
| Tests | `ImmediateBackend` | no worker: a job runs inline, in the process that enqueues it |

`docker compose up -d worker` starts the worker from the same image as `api`; it waits for `api`, which applies the migrations. `docker compose stop worker` sends SIGTERM: the worker finishes the job it is running and exits. Read its output with `docker compose logs worker`. The queue's tables come from the package's own migrations (`manage.py migrate`).

## Rules

1. **Where.** A job lives in `apps/<app>/tasks.py`, a module-level function decorated with `@task`.
2. **Ids, not objects.** Arguments and the return value are plain JSON. The job loads what it needs by id, so it sees the current row, not a copy from enqueue time.
3. **Safe to run twice.** A job can be delivered again after a crash. Check the state first and do nothing when the work is done.
4. **After commit.** Enqueue with `enqueue_after_commit(task, *args)` from `apps.core.jobs`, never `task.enqueue` inside a transaction: the worker could pick the job up before the rows it needs are visible, and a rollback would leave a job for work that never happened.
5. **Failure.** A job logs a failure with its traceback (`logger.exception`) and the job's owner records its own failed state (for example the run is marked `failed`), so the person sees it. Do not rely on the queue's result row for that.

## Example

```python
# apps/runs/tasks.py
import logging

from django.tasks import task

logger = logging.getLogger(__name__)


@task()
def extract(
    run_id: str,
) -> None: ...  # load the run by id, return if it is already done, do the work
```

```python
# apps/runs/services.py
from apps.core.jobs import enqueue_after_commit
from apps.runs.tasks import extract


def start(run) -> None:
    ...
    enqueue_after_commit(extract, str(run.id))
```

## In tests

Jobs run inline, so a test sees the effect right away. `enqueue_after_commit` waits for the commit: use `@pytest.mark.django_db(transaction=True)` to see the job run, or `django_capture_on_commit_callbacks(execute=True)` in an ordinary test.
