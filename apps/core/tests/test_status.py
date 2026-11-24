"""GET /api/v1/status: which parts are stubs and which are real."""

import re
from datetime import timedelta
from typing import Any

import httpx2
import pytest
from asgiref.sync import async_to_sync
from django.db import connections
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
    status._ping_cache = None


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


def _run_manage(monkeypatch: pytest.MonkeyPatch, command: str) -> list[dict[str, Any]]:
    import sys

    from structlog.testing import capture_logs

    import manage

    ran: list[list[str]] = []
    monkeypatch.setattr(sys, "argv", ["manage.py", command])
    monkeypatch.setattr("django.core.management.execute_from_command_line", ran.append)
    with capture_logs() as logs:
        manage.main()
    assert ran == [["manage.py", command]]
    return [dict(e) for e in logs if e["event"] == "backend status"]


def test_a_management_command_does_not_log_the_start_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert _run_manage(monkeypatch, "check") == []


def test_the_worker_logs_the_start_line_once(monkeypatch: pytest.MonkeyPatch) -> None:
    assert len(_run_manage(monkeypatch, "db_worker")) == 1


def test_a_real_mode_with_a_missing_setting_warns_and_shows_not_configured(
    client: Any, settings: Any
) -> None:
    from apps.assistant.checks import check_llm_settings as assistant_check
    from apps.extraction.checks import check_llm_settings as extraction_check

    real_models(settings)
    settings.LLM_MODEL = ""
    assert any(m.id == "assistant.W001" for m in assistant_check())
    assert extraction_check()
    assert parts(client)["assistant"]["problem"] == "not_configured"


# --- a busy worker is not a stalled one -----------------------------------------------


def test_a_busy_worker_with_a_long_queue_is_ok(
    client: Any, database_queue: None
) -> None:
    job(20, status="RUNNING", started_at=timezone.now() - timedelta(seconds=10))
    job(90)
    assert parts(client)["worker"]["state"] == "ok"


def test_a_job_waiting_with_nothing_running_or_finished_is_stalled(
    client: Any, database_queue: None
) -> None:
    job(90)
    job(
        900,
        status="SUCCESSFUL",
        started_at=timezone.now() - timedelta(seconds=400),
        finished_at=timezone.now() - timedelta(seconds=300),
    )
    assert parts(client)["worker"]["problem"] == "worker_stalled"


def test_a_job_finished_a_moment_ago_means_the_worker_is_alive(
    client: Any, database_queue: None
) -> None:
    job(90)
    job(
        200,
        status="SUCCESSFUL",
        started_at=timezone.now() - timedelta(seconds=40),
        finished_at=timezone.now() - timedelta(seconds=20),
    )
    assert parts(client)["worker"]["state"] == "ok"


def test_a_task_running_past_the_execution_limit_does_not_prove_life(
    client: Any, database_queue: None, settings: Any
) -> None:
    settings.EXECUTION_TIMEOUT_SECONDS = 600
    job(90)
    job(2000, status="RUNNING", started_at=timezone.now() - timedelta(seconds=700))
    assert parts(client)["worker"]["problem"] == "worker_stalled"


# --- the ping is cached -----------------------------------------------------------------


def test_the_ping_is_cached_for_ten_seconds(
    client: Any, redis_layer: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = [500.0]
    pings: list[int] = []

    class Counting(_Layer):
        async def new_channel(self) -> str:
            pings.append(1)
            return "specific.x"

    monkeypatch.setattr(status, "_now", lambda: clock[0])
    monkeypatch.setattr(status, "get_channel_layer", lambda: Counting())
    first = parts(client)["live_updates"]
    parts(client)
    clock[0] += 9
    again = parts(client)["live_updates"]
    assert len(pings) == 1
    assert again["checked_at"] == first["checked_at"]
    clock[0] += 2
    parts(client)
    assert len(pings) == 2


def test_a_failed_ping_is_cached_too(
    client: Any, redis_layer: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []

    def layer() -> _Layer:
        calls.append(1)
        return _Layer(ConnectionError("down"))

    monkeypatch.setattr(status, "get_channel_layer", layer)
    parts(client)
    assert parts(client)["live_updates"]["state"] == "failing"
    assert len(calls) == 1


# --- what a failed run says about the model ------------------------------------------------


def _extract_failing_with(
    settings: Any, monkeypatch: pytest.MonkeyPatch, error: BaseException
) -> None:
    from apps.extraction.extractors.base import ExtractionError
    from apps.extraction.extractors.llm import LlmExtractor
    from apps.extraction.tests.test_llm import definition

    real_models(settings, "openai")

    def down() -> Any:
        raise error

    monkeypatch.setattr("apps.extraction.extractors.llm.connect", down)
    with pytest.raises(ExtractionError):
        LlmExtractor().extract("A document with some text.", definition())


def test_an_unusable_answer_counts_as_a_reached_model(
    settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agents import ModelBehaviorError

    _extract_failing_with(settings, monkeypatch, ModelBehaviorError("bad json"))
    assert ModelCall.objects.get(part="extraction").problem == ""


def test_the_files_own_time_budget_records_nothing(
    settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _extract_failing_with(settings, monkeypatch, TimeoutError())
    assert not ModelCall.objects.filter(part="extraction").exists()


def test_one_model_call_timing_out_records_timeout(
    settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.extraction.extractors.llm import ModelCallTimeout

    _extract_failing_with(settings, monkeypatch, ModelCallTimeout())
    assert ModelCall.objects.get(part="extraction").problem == "timeout"


# --- the assistant records -----------------------------------------------------------------


def _unauthorized() -> Exception:
    from openai import AuthenticationError

    response = httpx2.Response(401, request=_request())
    return AuthenticationError("denied", response=response, body=None)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_the_assistant_records_a_reply_and_a_refusal_by_the_provider(
    settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agents.testing import ScriptedModel, assistant_message
    from asgiref.sync import sync_to_async

    from apps.assistant.agents.openai_sdk import OpenAIAgent
    from apps.assistant.tests.openai_sdk.helpers import collect

    real_models(settings, "openai")

    class Client:
        async def close(self) -> None:
            pass

    model = ScriptedModel([[assistant_message("hello")], _unauthorized()])
    monkeypatch.setattr(
        "apps.assistant.agents.openai_sdk.runner.connect", lambda: (model, Client())
    )

    def problem() -> str:
        return ModelCall.objects.get(part="assistant").problem

    await collect(OpenAIAgent())
    assert await sync_to_async(problem)() == ""
    status._written.clear()
    await collect(OpenAIAgent())
    assert await sync_to_async(problem)() == "auth_failed"
    await sync_to_async(connections.close_all)()  # the worker thread's connection


# --- POST /status/test --------------------------------------------------------------------

TEST_URL = "/api/v1/status/test"


class FakeClient:
    closed = False

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_model(monkeypatch: pytest.MonkeyPatch) -> Any:
    """The model the test call talks to: a script of answers or errors."""
    from agents.testing import ScriptedModel

    def use(*steps: Any) -> Any:
        model = ScriptedModel(list(steps))
        client = FakeClient()
        monkeypatch.setattr("apps.core.llm.connect", lambda: (model, client))
        model.client = client  # type: ignore[attr-defined]
        return model

    return use


def test_a_test_with_only_stubs_calls_nothing(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("an outside call")

    monkeypatch.setattr("apps.core.llm.connect", forbidden)
    monkeypatch.setattr(status, "get_channel_layer", forbidden)
    response = client.post(TEST_URL)
    assert response.status_code == 200
    assert response["X-Status-Test"] == "skipped"
    assert response.json() == client.get(URL).json()
    assert not ModelCall.objects.exists()


def test_a_test_needs_sign_in(api_client: Any) -> None:
    assert api_client.post(TEST_URL).status_code == 401


def test_a_working_model_is_ok_for_both_parts_with_one_call(
    client: Any, settings: Any, fake_model: Any
) -> None:
    from agents.testing import assistant_message

    real_models(settings, "openai")
    model = fake_model([assistant_message("OK")])
    response = client.post(TEST_URL)
    assert response.status_code == 200
    assert response["X-Status-Test"] == "run"
    got = {p["id"]: p for p in response.json()["parts"]}
    for part in ("assistant", "extraction"):
        assert (got[part]["state"], got[part]["problem"]) == ("ok", None)
        assert got[part]["checked_at"] is not None
    assert len(model.calls) == 1  # one provider and model: one call
    assert model.client.closed


def test_a_few_tokens_are_asked_for(
    client: Any, settings: Any, fake_model: Any
) -> None:
    from agents.testing import assistant_message

    real_models(settings, "openai")
    model = fake_model([assistant_message("OK")])
    client.post(TEST_URL)
    assert model.calls[0].model_settings.max_tokens == status.TEST_OUTPUT_TOKENS


def test_a_401_is_failing_with_auth_failed_and_no_secret(
    client: Any, settings: Any, fake_model: Any
) -> None:
    real_models(settings, "openai")
    fake_model(_unauthorized())
    response = client.post(TEST_URL)
    assert response.status_code == 200
    got = {p["id"]: p for p in response.json()["parts"]}
    for part in ("assistant", "extraction"):
        assert (got[part]["state"], got[part]["problem"]) == ("failing", "auth_failed")
    assert "denied" not in response.content.decode()
    assert KEY not in response.content.decode()


def test_a_slow_model_is_failing_with_timeout(
    client: Any, settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    from agents.testing import ScriptedModel

    class Slow(ScriptedModel):
        async def get_response(self, *args: Any, **kwargs: Any) -> Any:
            await asyncio.sleep(5)

    real_models(settings, "openai")
    monkeypatch.setattr(status, "TEST_MODEL_TIMEOUT_SECONDS", 0.1)
    monkeypatch.setattr("apps.core.llm.connect", lambda: (Slow(), FakeClient()))
    got = {p["id"]: p for p in client.post(TEST_URL).json()["parts"]}
    assert (got["extraction"]["state"], got["extraction"]["problem"]) == (
        "failing",
        "timeout",
    )


def test_a_hung_sign_in_cannot_hold_the_request(
    client: Any, settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import time

    real_models(settings, "openai")

    async def stuck() -> None:
        time.sleep(1.5)  # blocks the loop: the call's own timeout cannot fire

    monkeypatch.setattr(status, "_call_model", stuck)
    monkeypatch.setattr(status, "TEST_MODEL_TIMEOUT_SECONDS", 0.1)
    monkeypatch.setattr(status, "TEST_SLACK_SECONDS", 0.2)
    started = time.monotonic()
    got = {p["id"]: p for p in client.post(TEST_URL).json()["parts"]}
    assert time.monotonic() - started < 1.2
    assert got["extraction"]["problem"] == "timeout"


def test_a_missing_setting_with_an_in_memory_layer_is_skipped_without_a_claim(
    client: Any, settings: Any
) -> None:
    from apps.core.models import StatusTestClaim

    real_models(settings, "openai")
    settings.LLM_MODEL = ""
    assert client.post(TEST_URL)["X-Status-Test"] == "skipped"
    assert not StatusTestClaim.objects.exists()


def test_an_unusable_answer_still_counts_as_reached(
    client: Any, settings: Any, fake_model: Any
) -> None:
    from agents import ModelBehaviorError

    real_models(settings, "openai")
    fake_model(ModelBehaviorError("garbled"))
    got = {p["id"]: p for p in client.post(TEST_URL).json()["parts"]}
    assert got["extraction"]["state"] == "ok"


def test_the_models_text_is_never_logged(
    client: Any, settings: Any, fake_model: Any
) -> None:
    from agents.testing import assistant_message
    from structlog.testing import capture_logs

    real_models(settings, "openai")
    fake_model([assistant_message("MODEL-SAID-THIS")])
    with capture_logs() as logs:
        response = client.post(TEST_URL)
    assert "MODEL-SAID-THIS" not in str(logs) + response.content.decode()


def test_a_second_test_inside_a_minute_answers_the_stored_result(
    client: Any, settings: Any, fake_model: Any
) -> None:
    from agents.testing import assistant_message

    real_models(settings, "openai")
    model = fake_model([assistant_message("OK")], _unauthorized())
    first = client.post(TEST_URL)
    second = client.post(TEST_URL)
    assert first["X-Status-Test"] == "run"
    assert second["X-Status-Test"] == "cached"
    assert second.json() == first.json()
    assert len(model.calls) == 1


def test_a_test_runs_again_after_a_minute(
    client: Any, settings: Any, fake_model: Any
) -> None:
    from agents.testing import assistant_message

    from apps.core.models import StatusTestClaim

    real_models(settings, "openai")
    model = fake_model([assistant_message("OK")], [assistant_message("OK")])
    client.post(TEST_URL)
    StatusTestClaim.objects.update(claimed_at=timezone.now() - timedelta(seconds=61))
    assert client.post(TEST_URL)["X-Status-Test"] == "run"
    assert len(model.calls) == 2


def test_a_test_writes_past_the_write_throttle(
    client: Any, settings: Any, fake_model: Any
) -> None:
    from agents.testing import assistant_message

    from apps.core.models import StatusTestClaim

    real_models(settings, "openai")
    fake_model([assistant_message("OK")], [assistant_message("OK")])
    client.post(TEST_URL)
    first = ModelCall.objects.get(part="extraction").checked_at
    StatusTestClaim.objects.update(claimed_at=None)
    client.post(TEST_URL)
    assert ModelCall.objects.get(part="extraction").checked_at > first


@pytest.mark.django_db(transaction=True)
def test_concurrent_requests_claim_the_test_once() -> None:
    from concurrent.futures import ThreadPoolExecutor

    status._claim_test()  # the row exists: the threads race on the UPDATE
    from apps.core.models import StatusTestClaim

    StatusTestClaim.objects.update(claimed_at=None)

    def claim() -> bool:
        try:
            return status._claim_test()
        finally:
            connections.close_all()

    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(lambda _: claim(), range(8)))
    assert results.count(True) == 1


def test_a_test_pings_the_channel_layer_afresh(
    client: Any, redis_layer: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    pings: list[int] = []

    class Counting(_Layer):
        async def new_channel(self) -> str:
            pings.append(1)
            return "specific.x"

    monkeypatch.setattr(status, "get_channel_layer", lambda: Counting())
    parts(client)  # fills the cache
    response = client.post(TEST_URL)
    assert len(pings) == 2
    assert response["X-Status-Test"] == "run"
    got = {p["id"]: p for p in response.json()["parts"]}["live_updates"]
    assert got["state"] == "ok"


def test_a_failing_ping_in_a_test_is_a_state_not_a_500(
    client: Any, redis_layer: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(status, "get_channel_layer", lambda: _Layer(OSError("x")))
    response = client.post(TEST_URL)
    assert response.status_code == 200
    got = {p["id"]: p for p in response.json()["parts"]}["live_updates"]
    assert (got["state"], got["problem"]) == ("failing", "unreachable")


def test_real_storage_stays_unknown_and_is_not_called(
    client: Any, settings: Any, fake_model: Any
) -> None:
    from agents.testing import assistant_message

    real_models(settings, "openai")
    settings.DOCUMENT_STORAGE = "azure"
    fake_model([assistant_message("OK")])
    got = {p["id"]: p for p in client.post(TEST_URL).json()["parts"]}
    assert got["storage"]["state"] == "unknown"


def test_a_missing_setting_is_not_called(
    client: Any, settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_models(settings, "openai")
    settings.LLM_MODEL = ""

    def forbidden() -> Any:
        raise AssertionError("an outside call")

    monkeypatch.setattr("apps.core.llm.connect", forbidden)
    got = {p["id"]: p for p in client.post(TEST_URL).json()["parts"]}
    assert got["extraction"]["problem"] == "not_configured"


def test_a_cross_origin_test_exposes_its_header(client: Any, settings: Any) -> None:
    response = client.post(TEST_URL, HTTP_ORIGIN="http://localhost:3000")
    assert response["Access-Control-Allow-Origin"] == "http://localhost:3000"
    exposed = response["Access-Control-Expose-Headers"].lower()
    assert "x-status-test" in exposed
    assert "etag" in exposed  # what was exposed before stays
