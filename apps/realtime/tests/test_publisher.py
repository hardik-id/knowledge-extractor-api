"""publish_run_event and its async twin: after the commit, and never raising."""

from typing import Any

import pytest
from channels.layers import get_channel_layer
from django.db import transaction
from rest_framework.test import APIClient
from structlog.testing import capture_logs

from apps.realtime import services
from apps.runs import services as runs
from apps.runs.models import Cell, CellStatus, Run
from apps.runs.tests.factories import CellFactory


class FailingLayer:
    """A channel layer whose server is down."""

    async def group_send(self, group: str, message: dict[str, Any]) -> None:
        raise ConnectionError("redis is down")


@pytest.fixture
def layer_down(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(services, "get_channel_layer", lambda: FailingLayer())


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = []

    class Recorder:
        async def group_send(self, group: str, message: dict[str, Any]) -> None:
            out.append((group, message))

    monkeypatch.setattr(services, "get_channel_layer", lambda: Recorder())
    return out


def test_the_group_of_a_run_is_one_name_whatever_the_id_looks_like() -> None:
    run_id = "8E7F2A0C-0000-4000-8000-000000000000"
    assert services.run_group(run_id) == services.run_group(run_id.lower())
    assert services.run_group(run_id).startswith("run.")


@pytest.mark.django_db
def test_it_waits_for_the_commit(
    sent: list[Any], django_capture_on_commit_callbacks: Any
) -> None:
    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        services.publish_run_event("r1", {"type": "cell", "cell": {}})
        assert sent == []
    assert len(callbacks) == 1
    assert sent == [
        ("run.r1", {"type": "run.event", "event": {"type": "cell", "cell": {}}})
    ]


@pytest.mark.django_db(transaction=True)
def test_outside_a_transaction_it_goes_at_once(sent: list[Any]) -> None:
    services.publish_run_event("r1", {"type": "x"})
    assert sent == [("run.r1", {"type": "run.event", "event": {"type": "x"}})]


@pytest.mark.django_db(transaction=True)
def test_a_layer_that_is_down_does_not_break_set_cell(layer_down: None) -> None:
    cell = CellFactory()
    with capture_logs() as logs:
        with transaction.atomic():
            changed = runs.set_cell(cell.file, cell.stage, status="running")
    assert changed.status == CellStatus.RUNNING
    assert Cell.objects.get(pk=cell.pk).status == CellStatus.RUNNING
    failures = [line for line in logs if line["event"] == "run_event_not_sent"]
    assert failures == [
        {
            "event": "run_event_not_sent",
            "run_id": str(cell.file.run_id),
            "kind": "cell",
            "log_level": "error",
            "exc_info": True,
        }
    ]


@pytest.mark.django_db(transaction=True)
def test_a_layer_that_is_down_does_not_break_the_request(
    layer_down: None, api_client: APIClient
) -> None:
    cell = CellFactory()
    run = cell.file.run
    api_client.force_authenticate(run.owner)
    with capture_logs() as logs:
        response = api_client.delete(f"/api/v1/runs/{run.pk}")
    assert response.status_code == 204
    assert not Run.objects.filter(pk=run.pk).exists()
    assert [line["kind"] for line in logs if line["event"] == "run_event_not_sent"] == [
        "run.gone"
    ]


@pytest.mark.django_db(transaction=True)
def test_no_channel_layer_at_all_is_logged_not_raised(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(services, "get_channel_layer", lambda: None)
    with capture_logs() as logs:
        services.publish_run_event("r1", {"type": "cell"})
    assert [line["event"] for line in logs] == ["run_event_not_sent"]


@pytest.mark.asyncio
async def test_called_from_an_event_loop_the_sync_one_logs_instead_of_raising(
    sent: list[Any],
) -> None:
    # The sync one belongs in sync code: from an event loop Django refuses to
    # touch the transaction. That must not reach the caller.
    with capture_logs() as logs:
        services.publish_run_event("r1", {"type": "cell"})
    assert sent == []
    assert [line["event"] for line in logs] == ["run_event_not_sent"]


@pytest.mark.asyncio
async def test_the_async_twin_sends_at_once(sent: list[Any]) -> None:
    await services.apublish_run_event("r1", {"type": "assistant.done"})
    assert sent == [
        ("run.r1", {"type": "run.event", "event": {"type": "assistant.done"}})
    ]


@pytest.mark.asyncio
async def test_the_async_twin_never_raises(layer_down: None) -> None:
    with capture_logs() as logs:
        await services.apublish_run_event("r1", {"type": "assistant.delta"})
    assert [(line["event"], line["kind"]) for line in logs] == [
        ("run_event_not_sent", "assistant.delta")
    ]


def test_the_tests_use_the_in_memory_layer() -> None:
    assert type(get_channel_layer()).__name__ == "InMemoryChannelLayer"


@pytest.mark.django_db(transaction=True)
def test_a_send_that_fails_at_the_commit_does_not_fail_the_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(func: Any) -> Any:
        raise RuntimeError("no event loop for you")

    monkeypatch.setattr(services, "async_to_sync", broken)
    cell = CellFactory()
    with capture_logs() as logs, transaction.atomic():
        runs.set_cell(cell.file, cell.stage, status="failed")
    assert Cell.objects.get(pk=cell.pk).status == CellStatus.FAILED
    assert [line["event"] for line in logs] == ["run_event_not_sent"]
