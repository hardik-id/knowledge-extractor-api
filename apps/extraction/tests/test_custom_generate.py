"""POST .../stages/extract/chunking/generate, with an author that needs no model."""

import asyncio
from typing import Any

import httpx2
import pytest
from openai import APIConnectionError

from apps.core.errors import ERRORS
from apps.extraction import services
from apps.extraction.custom_chunking import author
from apps.extraction.custom_chunking.author import AgentAnswer, AuthorRequest
from apps.extraction.custom_chunking.errors import SplitterFailed
from apps.extraction.custom_chunking.fetch import ReferenceRefused
from apps.extraction.tests import custom_code as code
from apps.extraction.tests.test_executions import ADR, text
from apps.identity.tests.factories import UserFactory
from apps.runs.tests.factories import RunFactory, RunFileFactory

pytestmark = pytest.mark.django_db

BODY = {"instruction": "Split at every level-2 heading"}


def url(run: Any) -> str:
    return f"/api/v1/runs/{run.pk}/stages/extract/chunking/generate"


@pytest.fixture
def client(api_client: Any, user: Any) -> Any:
    api_client.force_authenticate(user)
    return api_client


@pytest.fixture
def run(user: Any) -> Any:
    run = RunFactory(owner=user)
    RunFileFactory(run=run, source_ref=ADR, name="adrs.md")
    return run


@pytest.fixture
def on(settings: Any) -> None:
    settings.CUSTOM_CHUNKING = "local"
    settings.LLM_PROVIDER = "openai"
    settings.LLM_MODEL = "test-model"
    settings.OPENAI_API_KEY = "sk-test"


class FakeAgent:
    """The author's agent replaced: it writes a fixed splitter, no model."""

    def __init__(
        self, source: str = code.SECTIONS, summary: str = "By heading."
    ) -> None:
        self.source = source
        self.summary = summary
        self.requests: list[AuthorRequest] = []

    async def __call__(self, request: AuthorRequest) -> AgentAnswer:
        self.requests.append(request)
        return AgentAnswer(code=self.source, summary=self.summary)


@pytest.fixture
def agent(monkeypatch: pytest.MonkeyPatch, on: None) -> FakeAgent:
    fake = FakeAgent()
    monkeypatch.setattr(author, "agent_runner", lambda: fake)
    return fake


def test_it_answers_the_code_the_summary_and_the_parts(
    client: Any, run: Any, agent: FakeAgent
) -> None:
    answer = client.post(url(run), BODY, format="json")
    assert answer.status_code == 200, answer.json()
    body = answer.json()
    assert body["code"] == code.SECTIONS
    assert body["summary"] == "By heading."
    (document,) = body["documents"]
    adr = text()
    assert document["name"] == "adrs.md"
    assert document["characters"] == len(adr)
    parts = document["parts"]
    assert parts[0]["start"] == 0 and parts[-1]["end"] == len(adr)
    assert all(a["end"] == b["start"] for a, b in zip(parts, parts[1:], strict=False))
    for part in parts[1:]:
        line = adr[part["start"] : part["end"]].strip().splitlines()[0]
        assert part["starts_with"] == line[:80]
        assert len(part["starts_with"]) <= 80
    (request,) = agent.requests
    assert request.size == 4000
    assert request.reference is None
    assert request.instruction == BODY["instruction"]


def test_starts_with_comes_from_the_document_first_non_empty_line(
    client: Any, run: Any, agent: FakeAgent
) -> None:
    assert services._starts_with("\n \n  ## A heading  \nmore") == "## A heading"
    assert services._starts_with("x" * 200) == "x" * 80
    assert services._starts_with("\n\n") == ""


def test_the_size_is_passed_on_and_checked(
    client: Any, run: Any, agent: FakeAgent
) -> None:
    ok = client.post(url(run), {**BODY, "size": 2000}, format="json")
    assert ok.status_code == 200
    assert agent.requests[0].size == 2000
    assert all(
        p["end"] - p["start"] <= 2000 for p in ok.json()["documents"][0]["parts"]
    )
    for size in (5, 10**9, "x"):
        refused = client.post(url(run), {**BODY, "size": size}, format="json")
        assert refused.status_code == 422
        assert "size" in refused.json()["details"]


def test_at_most_five_documents_go_to_the_author(
    client: Any, run: Any, agent: FakeAgent
) -> None:
    for n in range(7):
        RunFileFactory(run=run, source_ref=ADR, name=f"b{n}.md")
    answer = client.post(url(run), BODY, format="json")
    assert len(answer.json()["documents"]) == 5
    assert len(agent.requests[0].documents) == 5


def test_the_reference_is_fetched_by_the_server(
    client: Any, run: Any, agent: FakeAgent, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []

    def fetched(link: str) -> str:
        seen.append(link)
        return "reference text"

    monkeypatch.setattr(services, "fetch_reference", fetched)
    client.post(
        url(run), {**BODY, "source_url": " https://example.com/a "}, format="json"
    )
    assert seen == ["https://example.com/a"]
    assert agent.requests[0].reference == "reference text"
    client.post(url(run), {**BODY, "source_url": ""}, format="json")
    assert agent.requests[1].reference is None


def test_a_refused_link_is_a_422_on_source_url(
    client: Any, run: Any, agent: FakeAgent, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(link: str) -> str:
        raise ReferenceRefused("This address is not a public one.")

    monkeypatch.setattr(services, "fetch_reference", refuse)
    answer = client.post(
        url(run), {**BODY, "source_url": "https://10.0.0.1/"}, format="json"
    )
    assert answer.status_code == 422
    assert answer.json()["code"] == "validation_error"
    assert answer.json()["details"] == {
        "source_url": ["This address is not a public one."]
    }
    assert agent.requests == []


def test_it_is_off_by_default(client: Any, run: Any, settings: Any) -> None:
    assert settings.CUSTOM_CHUNKING == "off"
    answer = client.post(url(run), BODY, format="json")
    assert answer.status_code == 409
    assert answer.json() == {
        "code": "custom_chunking_off",
        "message": "Custom chunking is turned off on this server.",
    }


def test_it_needs_a_model(client: Any, run: Any, on: None, settings: Any) -> None:
    settings.LLM_MODEL = ""
    answer = client.post(url(run), BODY, format="json")
    assert answer.status_code == 409
    assert answer.json()["code"] == "model_not_configured"
    assert answer.json()["message"] == "No language model is configured."


def test_code_that_does_not_work_on_the_documents_fails(
    client: Any, run: Any, agent: FakeAgent
) -> None:
    for source in (code.WRONG_RANGE, code.RAISES, code.FOREVER, ""):
        agent.source = source
        if source == code.FOREVER:
            pass
        answer = client.post(url(run), BODY, format="json")
        assert answer.status_code == 422, source
        assert answer.json()["code"] == "custom_chunking_failed"
        assert answer.json()["message"] == (
            "The assistant could not write splitting code that works on these "
            "documents. Try describing it differently."
        )


def test_an_agent_that_gives_up_is_a_failure(
    client: Any, run: Any, on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def gives_up(request: AuthorRequest) -> AgentAnswer:
        raise SplitterFailed("the agent did not finish")

    monkeypatch.setattr(author, "agent_runner", lambda: gives_up)
    assert client.post(url(run), BODY, format="json").status_code == 422


def test_the_generate_timeout_answers_504(
    client: Any, run: Any, on: None, settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings.CUSTOM_CHUNKING_GENERATE_TIMEOUT_SECONDS = 0.2

    async def slow(request: AuthorRequest) -> AgentAnswer:
        await asyncio.sleep(5)
        raise AssertionError("not reached")

    monkeypatch.setattr(author, "agent_runner", lambda: slow)
    answer = client.post(url(run), BODY, format="json")
    assert answer.status_code == 504
    assert answer.json()["code"] == "custom_chunking_timeout"
    assert (
        answer.json()["message"]
        == "Writing the splitting code took too long. Try again."
    )


def test_an_unreachable_model_answers_502(
    client: Any, run: Any, on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def down(request: AuthorRequest) -> AgentAnswer:
        raise APIConnectionError(
            request=httpx2.Request("POST", "https://api.example.com")
        )

    monkeypatch.setattr(author, "agent_runner", lambda: down)
    answer = client.post(url(run), BODY, format="json")
    assert answer.status_code == 502
    assert answer.json()["code"] == "model_unreachable"
    assert answer.json()["message"] == "The language model could not be reached."


def test_nothing_is_saved(client: Any, run: Any, agent: FakeAgent) -> None:
    client.post(url(run), BODY, format="json")
    definition = client.get(f"/api/v1/runs/{run.pk}/stages/extract/definition").json()
    assert definition["version"] == 1
    assert definition["chunking"]["custom"] is None


def test_someone_elses_run_is_a_404_even_when_it_is_off(
    client: Any, settings: Any
) -> None:
    other = RunFactory(owner=UserFactory())
    answer = client.post(url(other), BODY, format="json")
    assert answer.status_code == 404
    assert answer.json()["code"] == "run_not_found"


def test_it_needs_a_sign_in(api_client: Any, run: Any) -> None:
    assert api_client.post(url(run), BODY, format="json").status_code == 401


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"instruction": ""},
        {"instruction": "  "},
        {"instruction": "x" * 2001},
        {"instruction": "ok", "source_url": "u" * 2001},
    ],
)
def test_a_bad_body_is_a_422(
    client: Any, run: Any, agent: FakeAgent, body: Any
) -> None:
    assert client.post(url(run), body, format="json").status_code == 422
    assert agent.requests == []


def test_the_codes_are_registered() -> None:
    assert ERRORS["custom_chunking_off"].status == 409
    assert ERRORS["custom_chunking_failed"].status == 422
    assert ERRORS["custom_chunking_timeout"].status == 504
    assert ERRORS["model_unreachable"].status == 502


def test_the_workspace_has_the_documents_the_checker_and_the_reference() -> None:
    request = AuthorRequest(
        instruction="x",
        reference="ref",
        size=1500,
        documents=[
            author.AuthorDocument(file_id="1", name="a.md", text="a" * 70_000),
            author.AuthorDocument(file_id="2", name="b.pdf", text="b"),
        ],
    )
    entries = author.workspace(request).entries
    assert set(entries) == {
        "check.py",
        "documents/1.md",
        "documents/2.txt",
        "reference.md",
    }
    assert len(entries["documents/1.md"].content) == author.DOCUMENT_CHARS  # type: ignore[attr-defined]
    assert b"SIZE = 1500" in entries["check.py"].content  # type: ignore[attr-defined]
    assert (
        "reference.md"
        not in author.workspace(request.model_copy(update={"reference": None})).entries
    )


def test_the_real_agent_loop_with_a_scripted_model(
    on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The SandboxAgent, its shell and the workspace, driven by a scripted model."""
    from agents.testing import (
        ModelStep,
        ScriptedModel,
        assistant_message,
        function_call,
    )

    from apps.extraction.tests.test_llm import FakeClient

    write = f"cat > splitter.py <<'PY'\n{code.SECTIONS}PY"
    model = ScriptedModel(
        [
            ModelStep(
                output=[function_call("exec_command", {"cmd": write}, call_id="c1")]
            ),
            ModelStep(
                output=[
                    function_call(
                        "exec_command", {"cmd": "python3 check.py"}, call_id="c2"
                    )
                ]
            ),
            ModelStep(output=[assistant_message("Splits at each level-2 heading.")]),
        ]
    )
    client = FakeClient()
    monkeypatch.setattr("apps.core.llm.connect", lambda: (model, client))
    request = AuthorRequest(
        instruction="by heading",
        reference="a reference page",
        size=1000,
        documents=[
            author.AuthorDocument(file_id="f1", name="a.md", text=code.DOCUMENT)
        ],
    )
    authored = asyncio.run(author.author_splitter(request))
    assert authored.code == code.SECTIONS
    assert authored.summary == "Splits at each level-2 heading."
    (document,) = authored.documents
    assert document.ranges[0] == (0, code.DOCUMENT.index("## Decision 1"))
    assert client.closed
    checked = model.calls[2].input
    assert "OK" in str(checked)  # the checker's answer went back to the model
    assert "a reference page" not in str(model.calls[0].input)  # data, in a file


def test_an_agent_that_writes_no_file_is_a_failure(
    on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agents.testing import ModelStep, ScriptedModel, assistant_message

    from apps.extraction.tests.test_llm import FakeClient

    model = ScriptedModel([ModelStep(output=[assistant_message("Done.")])])
    monkeypatch.setattr("apps.core.llm.connect", lambda: (model, FakeClient()))
    request = AuthorRequest(
        instruction="x",
        reference=None,
        size=1000,
        documents=[author.AuthorDocument(file_id="f1", name="a.md", text="hi")],
    )
    with pytest.raises(SplitterFailed):
        asyncio.run(author.author_splitter(request))


def _scripted_commands(monkeypatch: pytest.MonkeyPatch, commands: list[str]) -> Any:
    from agents.testing import (
        ModelStep,
        ScriptedModel,
        assistant_message,
        function_call,
    )

    from apps.extraction.tests.test_llm import FakeClient

    steps = [
        ModelStep(output=[function_call("exec_command", {"cmd": cmd}, call_id=f"c{n}")])
        for n, cmd in enumerate(commands)
    ]
    model = ScriptedModel([*steps, ModelStep(output=[assistant_message("Done.")])])
    monkeypatch.setattr("apps.core.llm.connect", lambda: (model, FakeClient()))
    return model


def _agent_request() -> AuthorRequest:
    return AuthorRequest(
        instruction="x",
        reference=None,
        size=1000,
        documents=[author.AuthorDocument(file_id="f", name="a.md", text="hi")],
    )


def test_the_agents_shell_has_a_time_limit_an_output_cap_and_no_stdin_tool(
    on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(author, "EXEC_TIMEOUT_SECONDS", 1)
    model = _scripted_commands(
        monkeypatch,
        ["yes", "sleep 30", "echo hello", "ls"],
    )
    with pytest.raises(SplitterFailed):  # it wrote no splitter.py
        asyncio.run(author.author_splitter(_agent_request()))
    names = [t.name for t in model.calls[0].tools]
    assert "exec_command" in names and "write_stdin" not in names
    endless = str(model.calls[1].input)
    assert "[output cut]" in endless
    assert "stopped after 1 seconds" in endless
    assert len(endless) < 3 * author.EXEC_MAX_OUTPUT_BYTES
    assert "stopped after 1 seconds" in str(model.calls[2].input)
    assert "hello" in str(model.calls[3].input)


def test_nothing_the_agent_started_survives_its_command(
    on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.extraction.tests.test_custom_sandbox import _processes_running

    _scripted_commands(monkeypatch, ["(sleep 123456 &) ; echo started"])
    with pytest.raises(SplitterFailed):
        asyncio.run(author.author_splitter(_agent_request()))
    assert _processes_running("123456") == []


def test_a_cancelled_agent_run_kills_its_command(
    on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.extraction.tests.test_custom_sandbox import _processes_running

    _scripted_commands(monkeypatch, ["sleep 654321"])

    async def scenario() -> None:
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(1.5):
                await author.author_splitter(_agent_request())

    asyncio.run(scenario())
    assert _processes_running("654321") == []


def test_no_documents_is_a_422_with_a_message(client: Any, agent: FakeAgent) -> None:
    empty = RunFactory(owner=client.handler._force_user)
    answer = client.post(url(empty), BODY, format="json")
    assert answer.status_code == 422
    assert answer.json()["code"] == "validation_error"
    assert answer.json()["message"] == (
        "Add a document first: the splitting code is tested on the workspace's documents."
    )
    assert agent.requests == []


def test_a_lone_surrogate_is_a_failure_not_a_500(
    client: Any, run: Any, agent: FakeAgent, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.documents.selectors import DocumentText

    monkeypatch.setattr(
        "apps.extraction.selectors.input_text",
        lambda f: DocumentText("a\ud800b", "text/plain", "v"),
    )
    answer = client.post(url(run), BODY, format="json")
    assert answer.status_code == 422
    assert answer.json()["code"] == "custom_chunking_failed"


def test_an_unforeseen_sandbox_error_is_a_failure_not_a_500(
    client: Any, run: Any, on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def broken(request: AuthorRequest) -> AgentAnswer:
        raise RuntimeError("boom")

    monkeypatch.setattr(author, "agent_runner", lambda: broken)
    answer = client.post(url(run), BODY, format="json")
    assert answer.json()["code"] == "custom_chunking_failed"


def test_a_null_size_is_the_default(client: Any, run: Any, agent: FakeAgent) -> None:
    answer = client.post(url(run), {**BODY, "size": None}, format="json")
    assert answer.status_code == 200
    assert agent.requests[0].size == 4000


def test_the_summary_is_one_clean_line() -> None:
    assert author.clean_summary("Splits\x00 at\n\n headings.\x07\x1b[0m") == (
        "Splits at headings.[0m"
    )
    assert len(author.clean_summary("x" * 5000)) == 1000
    assert author.clean_summary("\x00\x01") == ""
