"""The reply job's span and metrics, and the model-call helper (docs/observability.md)."""

from collections.abc import Callable
from typing import Any

import pytest
from opentelemetry.trace import SpanKind, StatusCode

from apps.assistant import telemetry
from apps.assistant.models import Message
from apps.assistant.tests.test_scripted import adr, bare
from apps.core.tests.otel import Telemetry
from apps.documents import selectors as documents
from apps.realtime import services as realtime
from apps.runs.tests.factories import RunFactory, RunFileFactory

pytestmark = pytest.mark.django_db

ADR_ASK = "Extract every architecture decision record"
FAKES = "apps.assistant.tests.fakes"
SECRET_ASK = "quokka-zebra-secret-question"


@pytest.fixture
def run(user: Any) -> Any:
    return RunFactory(owner=user)


@pytest.fixture
def client(api_client: Any, user: Any) -> Any:
    api_client.force_authenticate(user)
    return api_client


def send(
    client: Any,
    run: Any,
    capture: Any,
    text: str = ADR_ASK,
    definition: Any = None,
) -> Any:
    """POST a message and commit; the reply job waits in the queue."""
    url = f"/api/v1/runs/{run.pk}/extraction/assistant/messages"
    body = {"text": text, "definition": bare() if definition is None else definition}
    with capture(execute=True):
        response = client.post(url, body, format="json")
    assert response.status_code == 201
    return response


def reply_of(run: Any) -> Message:
    return Message.objects.get(run_id=run.pk, role="assistant")


def test_a_chat_message_is_one_trace_across_the_request_and_the_reply_job(
    client: Any,
    run: Any,
    otel: Telemetry,
    queued: Callable[[], None],
    django_capture_on_commit_callbacks: Any,
) -> None:
    send(client, run, django_capture_on_commit_callbacks)
    assert otel.named("assistant.reply") == [], "the job has not run yet"

    queued()  # a worker: an empty context, only the stored trace context to go on

    (server,) = [s for s in otel.finished() if s.kind == SpanKind.SERVER]
    (job,) = otel.named("assistant.reply")
    assert job.context.trace_id == server.context.trace_id
    assert job.parent is not None and job.parent.is_remote

    assert job.attributes is not None
    deltas = job.attributes["assistant.deltas"]
    assert isinstance(deltas, int)
    assert job.attributes == {
        "assistant.message_id": str(reply_of(run).pk),
        "assistant.agent": "scripted",
        "assistant.run_id": str(run.pk),
        "assistant.outcome": "done",
        "assistant.deltas": deltas,
        "assistant.proposed": True,
    }
    assert deltas > 1
    assert job.status.status_code != StatusCode.ERROR


def test_the_number_of_deltas_is_the_number_the_socket_saw(
    client: Any,
    run: Any,
    otel: Telemetry,
    queued: Callable[[], None],
    django_capture_on_commit_callbacks: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[str] = []

    class Recorder:
        async def group_send(self, group: str, message: dict[str, Any]) -> None:
            sent.append(message["event"]["type"])

    monkeypatch.setattr(realtime, "get_channel_layer", lambda: Recorder())
    send(client, run, django_capture_on_commit_callbacks)
    queued()

    (job,) = otel.named("assistant.reply")
    assert job.attributes is not None
    assert job.attributes["assistant.deltas"] == sent.count("assistant.delta")
    assert job.attributes["assistant.proposed"] is ("assistant.proposal" in sent)
    # and events published, by type
    published = {
        p.attributes["type"]: p.value for p in otel.points("realtime.events.published")
    }
    assert published["assistant.delta"] == sent.count("assistant.delta")
    assert published["assistant.done"] == 1


def test_a_reply_without_a_proposal_says_so(
    client: Any,
    run: Any,
    otel: Telemetry,
    queued: Callable[[], None],
    django_capture_on_commit_callbacks: Any,
) -> None:
    send(client, run, django_capture_on_commit_callbacks, "what is the weather", adr())
    queued()
    (job,) = otel.named("assistant.reply")
    assert job.attributes is not None
    assert job.attributes["assistant.proposed"] is False


def test_replies_are_counted_by_outcome_and_timed(
    client: Any,
    run: Any,
    otel: Telemetry,
    queued: Callable[[], None],
    django_capture_on_commit_callbacks: Any,
) -> None:
    send(client, run, django_capture_on_commit_callbacks)
    queued()

    (count,) = otel.points("assistant.replies")
    assert count.value == 1
    assert dict(count.attributes) == {"outcome": "done", "agent": "scripted"}
    (timing,) = otel.points("assistant.reply.duration")
    assert timing.count == 1
    assert timing.sum >= 0
    assert dict(timing.attributes) == {"outcome": "done", "agent": "scripted"}


def test_a_failing_agent_ends_the_span_failed_with_the_error_type_only(
    client: Any,
    run: Any,
    otel: Telemetry,
    settings: Any,
    queued: Callable[[], None],
    django_capture_on_commit_callbacks: Any,
) -> None:
    settings.ASSISTANT_AGENT = f"{FAKES}.FailingAgent"
    send(client, run, django_capture_on_commit_callbacks)
    queued()

    (job,) = otel.named("assistant.reply")
    assert job.attributes is not None
    assert job.attributes["assistant.outcome"] == "failed"
    assert job.attributes["assistant.agent"] == "FailingAgent"
    assert job.attributes["assistant.deltas"] == 1
    assert job.attributes["error.type"] == "RuntimeError"
    assert job.status.status_code == StatusCode.ERROR
    assert not job.status.description
    assert job.events == (), "no exception event: its message could quote the text"
    (count,) = otel.points("assistant.replies")
    assert dict(count.attributes) == {"outcome": "failed", "agent": "FailingAgent"}


def test_a_job_with_nothing_to_do_is_a_skipped_span(
    client: Any,
    run: Any,
    otel: Telemetry,
    queued: Callable[[], None],
    django_capture_on_commit_callbacks: Any,
) -> None:
    send(client, run, django_capture_on_commit_callbacks)
    Message.objects.filter(run_id=run.pk, role="assistant").update(status="done")
    queued()

    (job,) = otel.named("assistant.reply")
    assert job.attributes is not None
    assert job.attributes["assistant.outcome"] == "skipped"
    assert "assistant.run_id" not in job.attributes


# --- what never goes into telemetry -----------------------------------------


@pytest.mark.parametrize("agent", ["FakeAgent", "FailingAgent", "RecordingAgent"])
def test_no_span_metric_or_log_line_holds_message_document_prompt_or_proposal_text(
    client: Any,
    run: Any,
    user: Any,
    otel: Telemetry,
    settings: Any,
    log_lines: Callable[[], str],
    queued: Callable[[], None],
    django_capture_on_commit_callbacks: Any,
    agent: str,
) -> None:
    [first, *_] = documents.list_documents(user)
    RunFileFactory(run=run, source_ref=first.id, name=first.name)
    document = documents.read_document(user, first.id).text
    settings.ASSISTANT_AGENT = f"{FAKES}.{agent}"

    send(client, run, django_capture_on_commit_callbacks, SECRET_ASK)
    queued()

    reply = reply_of(run)
    forbidden = [SECRET_ASK, reply.text, *document.splitlines()]
    if reply.proposal:
        forbidden += [reply.proposal["definition"]["prompt"]]
        forbidden += [r["reason"] for r in reply.proposal["reasons"]]
    forbidden = [f for f in forbidden if len(f) >= 12]
    assert len(forbidden) > 3
    assert otel.named("assistant.reply")

    caught = otel.everything() + "\n" + log_lines()
    for text in forbidden:
        assert text not in caught, text


# --- the GenAI span of a model call -----------------------------------------


def test_a_model_call_has_the_genai_attributes_and_the_tokens_the_sdk_reported(
    otel: Telemetry,
) -> None:
    with telemetry.model_call(system="openai", model="gpt-5") as call:
        call.response(model="gpt-5-2026-01-01", input_tokens=120, output_tokens=45)

    (span,) = otel.named("chat gpt-5")
    assert span.kind == SpanKind.CLIENT
    assert span.attributes == {
        "gen_ai.operation.name": "chat",
        "gen_ai.system": "openai",
        "gen_ai.request.model": "gpt-5",
        "gen_ai.response.model": "gpt-5-2026-01-01",
        "gen_ai.usage.input_tokens": 120,
        "gen_ai.usage.output_tokens": 45,
    }


def test_a_model_call_leaves_out_tokens_the_sdk_did_not_report(otel: Telemetry) -> None:
    with telemetry.model_call(system="openai", model="gpt-5") as call:
        call.response(model=None)

    (span,) = otel.named("chat gpt-5")
    assert span.attributes is not None
    assert not [k for k in span.attributes if k.startswith("gen_ai.usage")]


def test_a_model_call_that_fails_records_the_error_type_only(otel: Telemetry) -> None:
    with (
        pytest.raises(RuntimeError),
        telemetry.model_call(system="openai", model="gpt-5"),
    ):
        raise RuntimeError(f"rate limited while reading {SECRET_ASK}")

    (span,) = otel.named("chat gpt-5")
    assert span.attributes is not None
    assert span.attributes["error.type"] == "RuntimeError"
    assert span.status.status_code == StatusCode.ERROR
    assert span.events == ()
    assert SECRET_ASK not in otel.everything()


def test_a_model_call_span_is_a_child_of_the_reply_span(otel: Telemetry) -> None:
    with telemetry.reply_span("m1", "scripted"):
        with telemetry.model_call(system="openai", model="gpt-5"):
            pass

    (reply,) = otel.named("assistant.reply")
    (call,) = otel.named("chat gpt-5")
    assert call.parent is not None
    assert call.parent.span_id == reply.context.span_id
