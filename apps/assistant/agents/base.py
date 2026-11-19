"""The interface every assistant agent implements.

An agent reads what the person wrote, the definition on their screen, the
conversation so far and (when it wants to) the run's workspace. It answers with
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


@dataclass(frozen=True)
class ValueView:
    """One value of a field of a record, as an agent sees it."""

    field_id: str
    value: str | None  # None: nothing was found
    origin: str  # "llm" or "human"
    review: str  # "suggested", "accepted" or "rejected"
    anchored: bool  # its quote was found in the text


@dataclass(frozen=True)
class RecordView:
    """One record of a record type, as an agent sees it."""

    record_type_id: str
    origin: str  # "llm" or "human"
    review: str  # "suggested", "accepted" or "rejected"
    values: list[ValueView]


@dataclass(frozen=True)
class FileRecords:
    """What was extracted from one document of the run."""

    document_id: str
    name: str
    definition_version: int  # the definition version the records were extracted with
    records: list[RecordView]


class Workspace(Protocol):
    """What an agent can look at: one read-only view of a run.

    It is the only way a tool reaches data, and it is limited to this run and
    its owner. Everything it returns is plain data (no model instance) and
    nothing it offers writes anything.
    """

    async def documents(self) -> list[DocumentRef]:
        """The documents of the run."""
        ...

    async def read(self, document_id: str) -> str:
        """The text of one document of the run.

        A document that is not one of the run's is ``document_not_found``.
        """
        ...

    async def extractions(self) -> list[FileRecords]:
        """The records of every file of the run that has been extracted."""
        ...

    async def preview(
        self, definition: Definition, document_id: str
    ) -> list[RecordView]:
        """The records the extractor finds in a document with ``definition``.

        A dry run: nothing is stored and no cell changes. ``definition`` is a
        draft (``prompt``, ``record_types``, ``output``). The records are as an
        extraction would store them (suggested, by the model).
        """
        ...


class Agent(Protocol):
    def reply(
        self,
        text: str,
        definition: Definition,
        history: list[Message],
        workspace: Workspace,
    ) -> AsyncIterator[AgentEvent]:
        """The reply to ``text`` as a stream of events.

        ``definition`` is the draft on the person's screen, saved or not.
        ``history`` is the conversation so far, oldest first, without ``text``.
        Implement it as an ``async def`` that ``yield``s ``TextDelta`` and, at
        most once, ``Proposal``.
        """
        ...
