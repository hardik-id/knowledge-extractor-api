"""A fake agent and a fake workspace: the smallest implementations of the interfaces."""

from collections.abc import AsyncIterator

from apps.assistant.agents.base import (
    AgentEvent,
    DocumentRef,
    FileRecords,
    Message,
    RecordView,
    TextDelta,
    Workspace,
)
from apps.assistant.proposal import Proposal, Reason
from apps.core.errors import ApiError
from apps.extraction.definition import Draft


class FakeAgent:
    """Says hello in two deltas and proposes the definition it was given."""

    async def reply(
        self,
        text: str,
        definition: Draft,
        history: list[Message],
        workspace: Workspace,
    ) -> AsyncIterator[AgentEvent]:
        yield TextDelta("Hello, ")
        yield TextDelta(f"you said {text}.")
        yield Proposal(
            definition=definition,
            reasons=[Reason(path="Template", reason="Unchanged.")],
        )


class FakeWorkspace:
    """A workspace of a few documents, with what was extracted and what a preview finds."""

    def __init__(
        self,
        texts: dict[str, str] | None = None,
        extracted: list[FileRecords] | None = None,
        previewed: list[RecordView] | None = None,
    ) -> None:
        self.texts = texts or {}
        self.extracted = extracted or []
        self.previewed = previewed or []

    async def documents(self) -> list[DocumentRef]:
        return [DocumentRef(id=key, name=key) for key in self.texts]

    async def read(self, document_id: str) -> str:
        return self.texts[document_id]

    async def extractions(self) -> list[FileRecords]:
        return list(self.extracted)

    async def preview(self, definition: Draft, document_id: str) -> list[RecordView]:
        if document_id not in self.texts:
            raise ApiError("document_not_found")
        return list(self.previewed)


class FailingAgent:
    """Starts a reply, then breaks."""

    async def reply(
        self,
        text: str,
        definition: Draft,
        history: list[Message],
        workspace: Workspace,
    ) -> AsyncIterator[AgentEvent]:
        yield TextDelta("Let me see")
        raise RuntimeError("the model is down")


class SilentFailingAgent:
    """Breaks before it says anything."""

    async def reply(
        self,
        text: str,
        definition: Draft,
        history: list[Message],
        workspace: Workspace,
    ) -> AsyncIterator[AgentEvent]:
        raise RuntimeError("the model is down")
        yield TextDelta("never")  # pragma: no cover


class RecordingAgent:
    """Remembers what it was given and reads every document; says how many it read."""

    calls: list[dict[str, object]] = []

    async def reply(
        self,
        text: str,
        definition: Draft,
        history: list[Message],
        workspace: Workspace,
    ) -> AsyncIterator[AgentEvent]:
        refs = await workspace.documents()
        texts = [await workspace.read(ref.id) for ref in refs]
        RecordingAgent.calls.append(
            {"text": text, "definition": definition, "history": history, "texts": texts}
        )
        yield TextDelta(f"I read {len(texts)} documents.")


class BadProposalAgent:
    """Builds a proposal of a definition that is not valid, which no model allows."""

    async def reply(
        self,
        text: str,
        definition: Draft,
        history: list[Message],
        workspace: Workspace,
    ) -> AsyncIterator[AgentEvent]:
        yield TextDelta("Here you go.")
        yield Proposal.model_validate({"definition": {"prompt": "x"}, "reasons": []})
