"""GET /api/v1/status: which parts are stubs and which are real."""

import re
from datetime import timedelta
from typing import Any

import httpx2
import pytest
from asgiref.sync import async_to_sync
from django.utils import timezone
from openai import APIConnectionError, APITimeoutError

from apps.core import status
from apps.core.models import ModelCall

pytestmark = pytest.mark.django_db

URL = "/api/v1/status"
ENDPOINT = "https://secret-endpoint.example.com"
KEY = "fake-key-for-tests"


@pytest.fixture(autouse=True)
def _fresh_throttle() -> None:
    status._written.clear()


@pytest.fixture
def client(api_client: Any, user: Any) -> Any:
    api_client.force_authenticate(user)
    return api_client


def parts(client: Any) -> dict[str, dict[str, Any]]:
    response = client.get(URL)
    assert response.status_code == 200
    return {part["id"]: part for part in response.json()["parts"]}


def real_models(settings: Any, provider: str = "azure") -> None:
    settings.ASSISTANT_AGENT = "openai"
    settings.EXTRACTOR = "llm"
    settings.LLM_PROVIDER = provider
    settings.LLM_MODEL = "gpt-test"
    settings.AZURE_OPENAI_ENDPOINT = ENDPOINT
    settings.OPENAI_API_KEY = KEY


def error_of(status_code: int) -> Exception:
    error = Exception("boom")
    error.status_code = status_code  # type: ignore[attr-defined]
    return error


# --- the default, all scripted ---------------------------------------------------


def test_the_default_setup_is_all_stubs(client: Any, settings: Any) -> None:
    settings.ASSISTANT_AGENT = "scripted"
    settings.EXTRACTOR = "scripted"
    settings.DOCUMENT_STORAGE = "samples"
    settings.DOCUMENT_CATALOG = "samples"
    response = client.get(URL)
    assert response.status_code == 200
    stub = {"mode": "stub", "state": "stub", "checked_at": None, "problem": None}
    assert response.json() == {
        "environment": "local",
        "parts": [
            {"id": "assistant", "label": "Scripted", **stub},
            {"id": "extraction", "label": "Scripted", **stub},
            {"id": "storage", "label": "Samples", **stub},
            {"id": "sign_in", "label": "Dev token", **stub},
            {"id": "live_updates", "label": "In memory", **stub},
            {"id": "worker", "label": "Runs inline", **stub},
        ],
    }


def test_sign_in_is_required(api_client: Any) -> None:
    assert api_client.get(URL).status_code == 401


# --- the model parts -----------------------------------------------------------------


def test_a_real_model_not_called_yet_is_unknown(client: Any, settings: Any) -> None:
    real_models(settings)
    for part in ("assistant", "extraction"):
        got = parts(client)[part]
        assert got["mode"] == "real"
        assert got["label"] == "azure · gpt-test"
        assert got["state"] == "unknown"
        assert got["checked_at"] is None


def test_a_real_model_with_a_missing_setting_is_failing(
    client: Any, settings: Any
) -> None:
    real_models(settings)
    settings.AZURE_OPENAI_ENDPOINT = ""
    got = parts(client)["extraction"]
    assert got["state"] == "failing"
    assert got["problem"] == "not_configured"


def test_the_recorded_outcome_is_ok_or_failing(client: Any, settings: Any) -> None:
    real_models(settings)
    status.record_call("extraction")
    got = parts(client)["extraction"]
    assert (got["state"], got["problem"]) == ("ok", None)
    assert got["checked_at"] is not None
    status.record_call("assistant", error_of(429))
    got = parts(client)["assistant"]
    assert (got["state"], got["problem"]) == ("failing", "rate_limited")


def test_the_body_holds_no_endpoint_and_no_key(client: Any, settings: Any) -> None:
    real_models(settings)
    settings.ANTHROPIC_API_KEY = KEY
    settings.ANTHROPIC_BASE_URL = ENDPOINT
    settings.DOCUMENT_CATALOG_URL = ENDPOINT
    status.record_call(
        "extraction",
        APIConnectionError(message=f"{ENDPOINT} {KEY}", request=_request()),
    )
    body = client.get(URL).content.decode()
    assert "secret" not in body
    assert KEY not in body
    assert "example.com" not in body
    assert "boom" not in body


# --- the problem codes ----------------------------------------------------------------


def _request() -> httpx2.Request:
    return httpx2.Request("POST", ENDPOINT)


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (error_of(401), "auth_failed"),
        (error_of(403), "auth_failed"),
        (error_of(404), "not_found"),
        (error_of(429), "rate_limited"),
        (error_of(400), "bad_request"),
        (error_of(422), "bad_request"),
        (error_of(503), "unreachable"),
        (error_of(500), "error"),
        (APITimeoutError(request=_request()), "timeout"),
        (TimeoutError(), "timeout"),
        (APIConnectionError(message="x", request=_request()), "unreachable"),
        (ConnectionResetError(), "unreachable"),
        (RuntimeError("x"), "error"),
    ],
)
def test_a_failure_becomes_a_short_code(error: BaseException, code: str) -> None:
    assert status.problem_code(error) == code


# --- recording and throttling ---------------------------------------------------------


def test_a_repeated_outcome_is_written_once_per_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = [1000.0]
    monkeypatch.setattr(status, "_now", lambda: clock[0])
    status.record_call("extraction")
    first = ModelCall.objects.get(part="extraction").checked_at
    clock[0] += 10
    status.record_call("extraction")
    assert ModelCall.objects.get(part="extraction").checked_at == first
    clock[0] += 25  # past 30 s since the write
    status.record_call("extraction")
    assert ModelCall.objects.get(part="extraction").checked_at > first
    assert ModelCall.objects.count() == 1


def test_a_changed_outcome_is_written_at_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(status, "_now", lambda: 1000.0)
    status.record_call("extraction")
    status.record_call("extraction", error_of(401))
    assert ModelCall.objects.get(part="extraction").problem == "auth_failed"
    status.record_call("extraction")
    assert ModelCall.objects.get(part="extraction").problem == ""


def test_recording_works_from_async_code() -> None:
    async_to_sync(status.arecord_call)("assistant", error_of(404))
    assert ModelCall.objects.get(part="assistant").problem == "not_found"


def test_a_recording_error_does_not_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("database down")

    monkeypatch.setattr(ModelCall.objects, "update_or_create", broken)
    status.record_call("extraction")
    async_to_sync(status.arecord_call)("extraction")


def test_the_new_columns_have_a_database_default() -> None:
    assert str(ModelCall._meta.get_field("problem").db_default) == ""
    assert ModelCall._meta.get_field("checked_at").db_default is not None


def test_the_extractor_records_a_failed_call(
    settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.extraction.extractors.base import Definition, ExtractionError
    from apps.extraction.extractors.llm import LlmExtractor
    from apps.extraction.tests.test_llm import definition

    real_models(settings, "openai")

    def down() -> Any:
        raise APIConnectionError(message=ENDPOINT, request=_request())

    monkeypatch.setattr("apps.extraction.extractors.llm.connect", down)
    d: Definition = definition()
    with pytest.raises(ExtractionError):
        LlmExtractor().extract("A document with some text.", d)
    assert ModelCall.objects.get(part="extraction").problem == "unreachable"


# --- the other parts -------------------------------------------------------------------


def test_real_storage_and_entra_sign_in(client: Any, settings: Any) -> None:
    settings.DOCUMENT_STORAGE = "azure"
    settings.DOCUMENT_CATALOG = "http"
    settings.DOCUMENT_CATALOG_URL = ENDPOINT
    settings.AUTH_MODE = "entra"
    got = parts(client)
    assert got["storage"]["mode"] == "real"
    assert got["storage"]["state"] == "unknown"
    assert got["storage"]["label"] == "Catalog service · Azure Blob storage"
    assert got["sign_in"]["mode"] == "real"
    assert got["sign_in"]["state"] == "ok"
    assert ENDPOINT not in client.get(URL).content.decode()


def test_the_order_of_the_parts(client: Any) -> None:
    ids = [part["id"] for part in client.get(URL).json()["parts"]]
    assert ids == [
        "assistant",
        "extraction",
        "storage",
        "sign_in",
        "live_updates",
        "worker",
    ]


class _Layer:
    def __init__(self, error: BaseException | None = None) -> None:
        self.error = error

    async def new_channel(self) -> str:
        if self.error:
            raise self.error
        return "specific.x"

    async def send(self, channel: str, message: dict[str, Any]) -> None:
        self.message = message

    async def receive(self, channel: str) -> dict[str, Any]:
        return self.message


@pytest.fixture
def redis_layer(settings: Any) -> None:
    settings.CHANNEL_LAYERS = {
        "default": {"BACKEND": "channels_redis.core.RedisChannelLayer"}
    }


def test_the_channel_layer_answers(
    client: Any, redis_layer: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(status, "get_channel_layer", lambda: _Layer())
    got = parts(client)["live_updates"]
    assert (got["mode"], got["label"], got["state"]) == ("real", "Redis", "ok")
    assert got["checked_at"] is not None


@pytest.mark.parametrize(
    ("error", "code"),
    [(ConnectionError(f"{ENDPOINT} down"), "unreachable"), (TimeoutError(), "timeout")],
)
def test_a_failing_channel_layer_is_failing_not_a_500(
    client: Any,
    redis_layer: None,
    monkeypatch: pytest.MonkeyPatch,
    error: BaseException,
    code: str,
) -> None:
    monkeypatch.setattr(status, "get_channel_layer", lambda: _Layer(error))
    response = client.get(URL)
    assert response.status_code == 200
    got = {p["id"]: p for p in response.json()["parts"]}["live_updates"]
    assert (got["state"], got["problem"]) == ("failing", code)
    assert ENDPOINT not in response.content.decode()


def test_a_hanging_channel_layer_times_out(
    client: Any, redis_layer: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    class Hang(_Layer):
        async def receive(self, channel: str) -> dict[str, Any]:
            await asyncio.sleep(10)
            return {}

    monkeypatch.setattr(status, "PING_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(status, "get_channel_layer", lambda: Hang())
    assert parts(client)["live_updates"]["problem"] == "timeout"


# --- the worker -------------------------------------------------------------------------


@pytest.fixture
def database_queue(settings: Any) -> None:
    settings.TASKS = {"default": {"BACKEND": "django_tasks_db.DatabaseBackend"}}


def job(waiting_seconds: int, **fields: Any) -> Any:
    from django_tasks_db.models import DBTaskResult, get_date_max

    row = DBTaskResult.objects.create(
        args_kwargs={"args": [], "kwargs": {}},
        task_path="apps.core.tests.x",
        backend_name="default",
        run_after=fields.pop("run_after", get_date_max()),
        **fields,
    )
    DBTaskResult.objects.filter(pk=row.pk).update(
        enqueued_at=timezone.now() - timedelta(seconds=waiting_seconds)
    )
    return row


def test_an_empty_queue_is_ok(client: Any, database_queue: None) -> None:
    got = parts(client)["worker"]
    assert (got["mode"], got["label"], got["state"]) == (
        "real",
        "Background worker",
        "ok",
    )
    assert got["problem"] is None


def test_a_job_waiting_a_while_is_ok(client: Any, database_queue: None) -> None:
    job(30)
    assert parts(client)["worker"]["state"] == "ok"


def test_a_job_waiting_over_a_minute_is_a_stalled_worker(
    client: Any, database_queue: None
) -> None:
    job(61)
    got = parts(client)["worker"]
    assert (got["state"], got["problem"]) == ("failing", "worker_stalled")


def test_a_job_that_runs_or_is_finished_does_not_stall(
    client: Any, database_queue: None
) -> None:
    job(600, status="RUNNING")
    job(600, status="SUCCESSFUL")
    assert parts(client)["worker"]["state"] == "ok"


def test_a_job_scheduled_for_later_does_not_stall(
    client: Any, database_queue: None
) -> None:
    job(600, run_after=timezone.now() + timedelta(hours=1))
    assert parts(client)["worker"]["state"] == "ok"


# --- start ---------------------------------------------------------------------------------


def test_the_start_line_names_modes_and_no_secret(
    settings: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    from structlog.testing import capture_logs

    real_models(settings)
    settings.ANTHROPIC_API_KEY = KEY
    with capture_logs() as logs:
        status.log_backend_status()
    assert len(logs) == 1
    assert dict(logs[0]) == {
        "event": "backend status",
        "log_level": "info",
        "assistant": "openai",
        "extractor": "llm",
        "provider": "azure",
        "model": "gpt-test",
        "storage": "samples",
        "catalog": "samples",
        "auth": "dev",
    }
    assert not re.search(r"secret|fake-key", str(logs))


def test_the_start_line_is_not_logged_by_tests_or_management_commands() -> None:
    from django.core.management import call_command
    from structlog.testing import capture_logs

    with capture_logs() as logs:
        call_command("check")
    assert all(entry["event"] != "backend status" for entry in logs)


def test_a_real_mode_with_a_missing_setting_is_still_reported_at_start(
    settings: Any,
) -> None:
    from apps.assistant.checks import check_llm_settings as assistant_check
    from apps.extraction.checks import check_llm_settings as extraction_check

    real_models(settings)
    settings.LLM_MODEL = ""
    assert any(m.id == "assistant.W001" for m in assistant_check())
    assert extraction_check()
