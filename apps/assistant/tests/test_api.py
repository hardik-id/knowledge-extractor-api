"""GET and POST /api/v1/runs/{id}/extraction/assistant/messages, and the reply job."""

import copy
from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone

from apps.assistant import services, tasks
from apps.assistant.agents.scripted import assistant_reply
from apps.assistant.models import Message, Role, Status
from apps.assistant.proposal import Proposal
from apps.assistant.tests.factories import MessageFactory
from apps.assistant.tests.fakes import RecordingAgent
from apps.assistant.tests.test_scripted import adr, bare
from apps.documents import selectors as documents
from apps.extraction.definition import Draft
from apps.realtime import services as realtime
from apps.runs.tests.factories import RunFactory, RunFileFactory

pytestmark = pytest.mark.django_db

ADR_ASK = "Extract every architecture decision record"
FAKES = "apps.assistant.tests.fakes"


def url(run: Any) -> str:
    return f"/api/v1/runs/{run.pk}/extraction/assistant/messages"


@pytest.fixture
def run(user: Any) -> Any:
    return RunFactory(owner=user)


@pytest.fixture
def client(api_client: Any, user: Any) -> Any:
    api_client.force_authenticate(user)
    return api_client


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """The run events, in the order they went out."""
    out: list[dict[str, Any]] = []

    class Recorder:
        async def group_send(self, group: str, message: dict[str, Any]) -> None:
            assert message["type"] == "run.event"
            out.append({"group": group, **message["event"]})

    monkeypatch.setattr(realtime, "get_channel_layer", lambda: Recorder())
    return out


@pytest.fixture
def jobs(django_capture_on_commit_callbacks: Any) -> Any:
    """Run what is enqueued after commit (the reply job) at the end of the block."""
    return lambda: django_capture_on_commit_callbacks(execute=True)


def post(client: Any, run: Any, text: Any = ADR_ASK, definition: Any = None) -> Any:
    body = {"text": text, "definition": bare() if definition is None else definition}
    return client.post(url(run), body, format="json")


def streaming_reply(run: Any, **kwargs: Any) -> Message:
    asked = MessageFactory(run=run, definition=bare())
    reply: Message = MessageFactory(
        run=run,
        role=Role.ASSISTANT,
        status=Status.STREAMING,
        reply_to=asked,
        **{"text": "", **kwargs},
    )
    return reply


def no_ids(definition: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(definition)
    for record_type in out["record_types"]:
        record_type.pop("id")
        for field in record_type["fields"]:
            field.pop("id")
    return out


# the conversation


def test_a_run_starts_with_no_messages(client: Any, run: Any) -> None:
    response = client.get(url(run))
    assert response.status_code == 200
    assert response.json() == {"messages": []}


def test_post_answers_the_users_message_and_the_reply_arrives(
    client: Any, run: Any, sent: list[Any], jobs: Any
) -> None:
    with jobs():
        response = post(client, run, f"  {ADR_ASK}  ")
        assert response.status_code == 201
        mine = response.json()
        assert set(mine) == {
            "id",
            "role",
            "text",
            "proposal",
            "status",
            "author",
            "created_at",
        }
        assert mine["author"] == {
            "id": str(run.owner.pk),
            "name": run.owner.name,
        }
        assert mine["role"] == "user"
        assert mine["text"] == ADR_ASK
        assert mine["proposal"] is None
        assert mine["status"] == "done"
        assert sent == [], "nothing goes out before the commit"

    messages = client.get(url(run)).json()["messages"]
    assert [(m["role"], m["status"]) for m in messages] == [
        ("user", "done"),
        ("assistant", "done"),
    ]
    assert messages[0] == mine
    reply = messages[1]
    expected = assistant_reply(ADR_ASK, Draft.model_validate(bare()))
    assert expected.proposal
    assert reply["text"] == expected.text
    assert reply["proposal"]["definition"]["record_types"][0]["name"] == "ADR"
    assert no_ids(reply["proposal"]["definition"]) == no_ids(
        expected.proposal.definition.model_dump()
    )
    assert reply["proposal"]["reasons"] == expected.proposal.model_dump()["reasons"]

    # the socket saw the same: deltas, then the proposal, then done
    assert {event.pop("group") for event in sent} == {f"run.{run.pk}"}
    kinds = [event["type"] for event in sent]
    assert kinds[-2:] == ["assistant.proposal", "assistant.done"]
    assert set(kinds[:-2]) == {"assistant.delta"}
    assert len(kinds) > 3
    assert all(event["message_id"] == reply["id"] for event in sent)
    deltas = [event["text"] for event in sent if event["type"] == "assistant.delta"]
    assert "".join(deltas) == reply["text"]
    assert sent[-2]["proposal"] == reply["proposal"]
    assert sent[-1] == {"type": "assistant.done", "message_id": reply["id"]}


def test_a_reply_without_a_proposal(
    client: Any, run: Any, sent: list[Any], jobs: Any
) -> None:
    with jobs():
        assert post(client, run, "what is the weather", adr()).status_code == 201
    reply = client.get(url(run)).json()["messages"][1]
    assert reply["proposal"] is None
    assert reply["status"] == "done"
    assert "assistant.proposal" not in [event["type"] for event in sent]


def test_the_next_message_gets_the_history_and_the_draft(
    client: Any, run: Any, settings: Any, jobs: Any, sent: list[Any]
) -> None:
    with jobs():
        post(client, run)
    settings.ASSISTANT_AGENT = f"{FAKES}.RecordingAgent"
    RecordingAgent.calls = []
    with jobs():
        assert post(client, run, "add owner", adr()).status_code == 201
    [call] = RecordingAgent.calls
    assert call["text"] == "add owner"
    assert call["definition"] == Draft.model_validate(adr())
    history = call["history"]
    assert [(m.role, m.text) for m in history] == [  # type: ignore[attr-defined]
        ("user", ADR_ASK),
        ("assistant", assistant_reply(ADR_ASK, Draft.model_validate(bare())).text),
    ]


def test_the_agent_reads_the_runs_documents_as_the_runs_owner(
    client: Any, run: Any, user: Any, settings: Any, jobs: Any, sent: list[Any]
) -> None:
    [first, *_] = documents.list_documents(user)
    RunFileFactory(run=run, source_ref=first.id, name=first.name)
    settings.ASSISTANT_AGENT = f"{FAKES}.RecordingAgent"
    RecordingAgent.calls = []
    with jobs():
        post(client, run)
    [call] = RecordingAgent.calls
    assert call["texts"] == [documents.read_document(user, first.id).text]
    reply = client.get(url(run)).json()["messages"][1]
    assert reply["text"] == "I read 1 documents."


# refusals


def test_a_second_message_while_the_reply_streams_is_409(client: Any, run: Any) -> None:
    # Without running the job, the first reply stays streaming.
    assert post(client, run).status_code == 201
    response = post(client, run, "add owner", adr())
    assert response.status_code == 409
    assert response.json()["code"] == "assistant_busy"
    assert Message.objects.filter(run=run).count() == 2


@pytest.mark.parametrize("text", ["", "   ", "\n\t", None])
def test_blank_text_is_422(client: Any, run: Any, text: Any) -> None:
    response = post(client, run, text)
    assert response.status_code == 422
    assert response.json()["code"] == "empty_message"
    assert not Message.objects.exists()


def test_text_that_is_not_text_is_422(client: Any, run: Any) -> None:
    response = post(client, run, ["hello"])
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


@pytest.mark.parametrize(
    "definition",
    [
        {"prompt": "x"},
        {
            "prompt": "x",
            "record_types": [],
            "output": {"format": "pdf", "template": ""},
        },
        "not a definition",
    ],
)
def test_a_bad_definition_is_422(client: Any, run: Any, definition: Any) -> None:
    response = post(client, run, ADR_ASK, definition)
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_definition"
    assert not Message.objects.exists()


def test_no_definition_is_422(client: Any, run: Any) -> None:
    response = client.post(url(run), {"text": ADR_ASK}, format="json")
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_definition"


def test_someone_elses_run_is_404(client: Any) -> None:
    theirs = RunFactory()
    MessageFactory(run=theirs)
    for response in [client.get(url(theirs)), post(client, theirs)]:
        assert response.status_code == 404
        assert response.json()["code"] == "run_not_found"
    assert Message.objects.filter(run=theirs).count() == 1


def test_an_unknown_run_is_404(client: Any) -> None:
    response = client.get("/api/v1/runs/not-a-uuid/extraction/assistant/messages")
    assert response.status_code == 404


def test_without_a_token_is_401(api_client: Any, run: Any) -> None:
    assert api_client.get(url(run)).status_code == 401
    assert post(api_client, run).status_code == 401


# a reply always ends


def test_an_agent_that_raises_ends_with_the_apology(
    client: Any, run: Any, settings: Any, sent: list[Any], jobs: Any
) -> None:
    settings.ASSISTANT_AGENT = f"{FAKES}.FailingAgent"
    with jobs():
        assert post(client, run).status_code == 201
    reply = client.get(url(run)).json()["messages"][1]
    assert reply["status"] == "done"
    assert reply["text"] == f"Let me see\n\n{services.APOLOGY}"
    assert [(event["type"], event.get("text")) for event in sent] == [
        ("assistant.delta", "Let me see"),
        ("assistant.delta", f"\n\n{services.APOLOGY}"),
        ("assistant.done", None),
    ]
    settings.ASSISTANT_AGENT = "scripted"
    assert post(client, run).status_code == 201, "the next message is accepted"


def test_an_agent_that_raises_at_once_says_only_the_apology(
    client: Any, run: Any, settings: Any, sent: list[Any], jobs: Any
) -> None:
    settings.ASSISTANT_AGENT = f"{FAKES}.SilentFailingAgent"
    with jobs():
        post(client, run)
    reply = client.get(url(run)).json()["messages"][1]
    assert reply["text"] == services.APOLOGY
    assert reply["status"] == "done"
    assert [event["type"] for event in sent] == ["assistant.delta", "assistant.done"]


def test_a_proposal_that_is_not_valid_ends_with_the_apology(
    client: Any, run: Any, settings: Any, sent: list[Any], jobs: Any
) -> None:
    settings.ASSISTANT_AGENT = f"{FAKES}.BadProposalAgent"
    with jobs():
        post(client, run)
    reply = client.get(url(run)).json()["messages"][1]
    assert reply["proposal"] is None
    assert reply["text"] == f"Here you go.\n\n{services.APOLOGY}"
    assert "assistant.proposal" not in [event["type"] for event in sent]


@pytest.fixture
def later(monkeypatch: pytest.MonkeyPatch, settings: Any) -> Any:
    """Freeze the clock ``seconds`` from now."""
    settings.ASSISTANT_REPLY_TIMEOUT_SECONDS = 60
    start = timezone.now()

    def freeze(seconds: float) -> None:
        monkeypatch.setattr(timezone, "now", lambda: start + timedelta(seconds=seconds))

    return freeze


def test_a_reply_streaming_past_the_timeout_is_closed_on_the_next_get(
    client: Any, run: Any, later: Any, sent: list[Any], jobs: Any
) -> None:
    reply = streaming_reply(run)
    later(59)
    assert client.get(url(run)).json()["messages"][1]["status"] == "streaming"
    assert post(client, run).status_code == 409
    later(61)
    with jobs():
        messages = client.get(url(run)).json()["messages"]
    assert messages[1]["status"] == "done"
    assert messages[1]["text"] == services.APOLOGY
    assert sent == [
        {
            "group": f"run.{run.pk}",
            "type": "assistant.delta",
            "message_id": str(reply.pk),
            "text": services.APOLOGY,
        },
        {
            "group": f"run.{run.pk}",
            "type": "assistant.done",
            "message_id": str(reply.pk),
        },
    ]


def test_a_reply_streaming_past_the_timeout_is_closed_on_the_next_post(
    client: Any, run: Any, later: Any, sent: list[Any], jobs: Any
) -> None:
    reply = streaming_reply(run, text="Half a")
    later(61)
    with jobs():
        assert post(client, run).status_code == 201
    reply.refresh_from_db()
    assert reply.status == Status.DONE
    assert reply.text == f"Half a\n\n{services.APOLOGY}"
    assert Message.objects.filter(run=run).count() == 4
    assert not Message.objects.filter(status=Status.STREAMING).exists()


def test_a_blank_post_still_closes_a_stale_reply(
    client: Any, run: Any, later: Any, sent: list[Any]
) -> None:
    reply = streaming_reply(run)
    later(61)
    assert post(client, run, " ").status_code == 422
    reply.refresh_from_db()
    assert reply.status == Status.DONE


# the job on its own


def test_the_job_leaves_a_reply_that_is_done_alone(run: Any, sent: list[Any]) -> None:
    reply = MessageFactory(run=run, role=Role.ASSISTANT, text="Done.")
    tasks.write_reply.call(str(reply.pk))
    reply.refresh_from_db()
    assert reply.text == "Done."
    assert sent == []


def test_the_job_on_a_reply_that_is_gone_does_nothing(sent: list[Any]) -> None:
    tasks.write_reply.call("8e7f2a0c-0000-4000-8000-000000000000")
    assert sent == []


def test_a_second_run_of_the_job_closes_a_half_written_reply(
    run: Any, sent: list[Any], jobs: Any
) -> None:
    reply = streaming_reply(run, text="Half a")
    with jobs():
        tasks.write_reply.call(str(reply.pk))
    reply.refresh_from_db()
    assert reply.status == Status.DONE
    assert reply.text == f"Half a\n\n{services.APOLOGY}"


def test_writes_stop_once_the_reply_is_done(run: Any) -> None:
    reply = MessageFactory(run=run, role=Role.ASSISTANT, text="Done.")
    assert services.append_text(reply.pk, "more") is False
    assert (
        services.set_proposal(
            reply.pk, Proposal(definition=Draft.model_validate(bare()), reasons=[])
        )
        is False
    )
    assert services.finish_reply(reply.pk) is False
    reply.refresh_from_db()
    assert reply.text == "Done."
    assert reply.proposal is None


def test_one_reply_at_a_time_is_kept_by_the_database(run: Any) -> None:
    from django.db import IntegrityError, transaction

    streaming_reply(run)
    with pytest.raises(IntegrityError), transaction.atomic():
        streaming_reply(run)


# clearing the conversation


def test_delete_clears_the_conversation_and_the_next_post_works(
    client: Any, run: Any, sent: list[Any], jobs: Any
) -> None:
    with jobs():
        assert post(client, run).status_code == 201
    assert Message.objects.filter(run=run).count() == 2
    sent.clear()
    with jobs():
        response = client.delete(url(run))
    assert response.status_code == 204
    assert client.get(url(run)).json() == {"messages": []}
    assert sent == [{"group": f"run.{run.pk}", "type": "assistant.cleared"}]
    assert post(client, run).status_code == 201


def test_delete_while_a_reply_streams_is_409(
    client: Any, run: Any, sent: list[Any]
) -> None:
    streaming_reply(run)
    response = client.delete(url(run))
    assert response.status_code == 409
    assert response.json()["code"] == "assistant_busy"
    assert Message.objects.filter(run=run).count() == 2
    assert sent == []


def test_delete_after_the_timeout_of_a_dead_reply_works(
    client: Any, run: Any, later: Any, jobs: Any
) -> None:
    streaming_reply(run)
    later(61)
    with jobs():
        assert client.delete(url(run)).status_code == 204
    assert Message.objects.filter(run=run).count() == 0


def test_delete_on_someone_elses_run_is_404(client: Any) -> None:
    other = RunFactory()
    MessageFactory(run=other, definition=bare())
    response = client.delete(url(other))
    assert response.status_code == 404
    assert Message.objects.filter(run=other).count() == 1


def test_an_old_stored_proposal_without_chunking_is_still_served(
    client: Any, run: Any
) -> None:
    """A proposal saved before configurations had a chunking has no such key."""
    old = {
        "definition": {k: v for k, v in adr().items() if k != "chunking"},
        "reasons": [{"path": "ADR", "reason": "Looks for decision records."}],
    }
    MessageFactory(run=run, role=Role.ASSISTANT, text="Here.", proposal=old)
    [message] = client.get(url(run)).json()["messages"]
    assert message["proposal"]["definition"]["record_types"][0]["name"] == "ADR"
    assert message["proposal"]["definition"]["chunking"] == {
        "strategy": "auto",
        "size": None,
        "custom": None,
    }


def test_messages_carry_their_author_and_an_old_one_without_still_serializes() -> None:
    from apps.assistant.models import Message, Role, Status
    from apps.identity.tests.factories import UserFactory
    from apps.runs.tests.factories import RunFactory

    run = RunFactory()
    person = UserFactory(name="Ada Lovelace")
    Message.objects.create(
        run=run, role=Role.USER, text="hi", status=Status.DONE, author=person
    )
    Message.objects.create(run=run, role=Role.USER, text="old", status=Status.DONE)
    Message.objects.create(run=run, role=Role.ASSISTANT, status=Status.DONE)
    from apps.assistant.api.serializers import MessageSerializer

    data = [MessageSerializer(m).data for m in Message.objects.filter(run=run)]
    assert data[0]["author"] == {"id": str(person.pk), "name": "Ada Lovelace"}
    assert data[1]["author"] is None
    assert data[2]["author"] is None
