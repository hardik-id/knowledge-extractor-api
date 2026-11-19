"""A fake agent and fake run documents: the smallest implementations of the interfaces."""

from collections.abc import AsyncIterator

from apps.assistant.agents.base import (
    AgentEvent,
    Definition,
    DocumentRef,
    Message,
    Proposal,
    RunDocuments,
    TextDelta,
)


class FakeAgent:
    """Says hello in two deltas and proposes the definition it was given."""

    async def reply(
        self,
        text: str,
        definition: Definition,
        history: list[Message],
        documents: RunDocuments,
    ) -> AsyncIterator[AgentEvent]:
        yield TextDelta("Hello, ")
        yield TextDelta(f"you said {text}.")
        yield Proposal(definition, [{"path": "Template", "reason": "Unchanged."}])


class FakeDocuments:
    def __init__(self, texts: dict[str, str] | None = None) -> None:
        self.texts = texts or {}

    async def list(self) -> list[DocumentRef]:
        return [DocumentRef(id=key, name=key) for key in self.texts]

    async def read(self, document_id: str) -> str:
        return self.texts[document_id]


class FailingAgent:
    """Starts a reply, then breaks."""

    async def reply(
        self,
        text: str,
        definition: Definition,
        history: list[Message],
        documents: RunDocuments,
    ) -> AsyncIterator[AgentEvent]:
        yield TextDelta("Let me see")
        raise RuntimeError("the model is down")


class SilentFailingAgent:
    """Breaks before it says anything."""

    async def reply(
        self,
        text: str,
        definition: Definition,
        history: list[Message],
        documents: RunDocuments,
    ) -> AsyncIterator[AgentEvent]:
        raise RuntimeError("the model is down")
        yield TextDelta("never")  # pragma: no cover


class RecordingAgent:
    """Remembers what it was given and reads every document; says how many it read."""

    calls: list[dict[str, object]] = []

    async def reply(
        self,
        text: str,
        definition: Definition,
        history: list[Message],
        documents: RunDocuments,
    ) -> AsyncIterator[AgentEvent]:
        refs = await documents.list()
        texts = [await documents.read(ref.id) for ref in refs]
        RecordingAgent.calls.append(
            {"text": text, "definition": definition, "history": history, "texts": texts}
        )
        yield TextDelta(f"I read {len(texts)} documents.")


class BadProposalAgent:
    """Proposes a definition that is not valid."""

    async def reply(
        self,
        text: str,
        definition: Definition,
        history: list[Message],
        documents: RunDocuments,
    ) -> AsyncIterator[AgentEvent]:
        yield TextDelta("Here you go.")
        yield Proposal({"prompt": "x"}, [])
