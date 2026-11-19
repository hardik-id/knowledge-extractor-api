import pytest
from django.db import transaction
from django.tasks import task

from apps.core.jobs import enqueue_after_commit

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
