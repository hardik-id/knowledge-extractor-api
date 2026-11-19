"""The interface every assistant agent implements.

An agent reads what the person wrote, the definition on their screen, the
conversation so far and (when it wants to) the run's documents. It answers with
a stream of events: any number of ``TextDelta`` and at most one ``Proposal``.
The stream ends when the reply is complete. An agent never saves anything:
applying a proposal is a normal save of the definition by the person.
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Literal, Protocol, TypedDict

# A validated draft (apps.extraction.validation.validate_draft): ``prompt``,
# ``record_types`` and ``output``, every record type and field with an ``id``.
Definition = dict[str, Any]


class Reason(TypedDict):
    """Why one thing changed. ``path`` names it in plain words: "ADR / Approved by"."""

    path: str
    reason: str


@dataclass(frozen=True)
class TextDelta:
    """New text for the reply. Not the text so far: the deltas joined are the reply."""

    text: str


@dataclass(frozen=True)
class Proposal:
    """A complete definition (not a patch) and a reason for each change."""

    definition: Definition
    reasons: list[Reason]


AgentEvent = TextDelta | Proposal


@dataclass(frozen=True)
class Message:
    """One turn of the conversation."""

    role: Literal["user", "assistant"]
    text: str


@dataclass(frozen=True)
class DocumentRef:
    id: str
    name: str


class RunDocuments(Protocol):
    """The run's documents, as far as an agent may read them."""

    async def list(self) -> list[DocumentRef]:
        """The documents of the run."""
        ...

    async def read(self, document_id: str) -> str:
        """The text of one document of the run."""
        ...


class Agent(Protocol):
    def reply(
        self,
        text: str,
        definition: Definition,
        history: list[Message],
        documents: RunDocuments,
    ) -> AsyncIterator[AgentEvent]:
        """The reply to ``text`` as a stream of events.

        ``definition`` is the draft on the person's screen, saved or not.
        ``history`` is the conversation so far, oldest first, without ``text``.
        Implement it as an ``async def`` that ``yield``s ``TextDelta`` and, at
        most once, ``Proposal``.
        """
        ...
