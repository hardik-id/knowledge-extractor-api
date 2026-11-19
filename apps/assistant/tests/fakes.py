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
