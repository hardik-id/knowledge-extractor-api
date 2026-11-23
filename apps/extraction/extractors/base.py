"""The interface of an extractor: text in, raw records out.

An extractor turns the text of a document into records, driven by a definition
version and the example records a person marked. It knows nothing about the
database, the network or the acting user. Everything it takes and returns is
plain data, so an implementation (the scripted one, one that calls a model, a
bridge to another service) can be swapped without touching the callers.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from apps.extraction.definition import Chunking, RecordType, stored_chunking
from apps.extraction.spans import Span
from apps.extraction.validation import parse_draft


class ExtractionError(Exception):
    """An extraction that failed for a reason a person can read.

    ``message`` goes into the failed cell as it is: one sentence, never the
    document's text, a quote or a credential.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class Definition:
    """A definition version: the prompt and the record types with their fields.

    ``record_types`` are the models of ``apps.extraction.definition``.
    """

    version: int
    prompt: str
    record_types: list[RecordType]
    chunking: Chunking = field(default_factory=Chunking)

    @classmethod
    def from_version(cls, version: Any) -> Definition:
        """Parse a stored ``DefinitionVersion`` (anything with its attributes), once, at the edge."""
        draft = parse_draft(
            {
                "prompt": version.prompt,
                "record_types": version.record_types,
                "output": version.output,
                "chunking": stored_chunking(version.chunking).model_dump(),
            }
        )
        return cls(version.version, draft.prompt, draft.record_types, draft.chunking)

    def record_type(self, record_type_id: str) -> RecordType | None:
        return next((t for t in self.record_types if t.id == record_type_id), None)


@dataclass(frozen=True)
class RawValue:
    """One value of a field: the text and the quotes it came from.

    ``value`` is None when nothing was found, and then ``spans`` is empty.
    """

    field_id: str
    value: str | None
    spans: list[Span] = field(default_factory=list)


@dataclass(frozen=True)
class RawRecord:
    """One record as an extractor found it. ``span`` is None when it has none."""

    record_type_id: str
    span: Span | None
    values: list[RawValue] = field(default_factory=list)


class Extractor(Protocol):
    def extract(
        self,
        text: str,
        definition: Definition,
        examples: Sequence[RawRecord] = (),
    ) -> list[RawRecord]:
        """The records in ``text``, in the order the extractor found them.

        ``examples`` are the records a person accepted and marked
        ``use_as_example``; an extractor may learn from them or ignore them.
        Spans are code point offsets into ``text``. They are not trusted: the
        caller checks every one (``stored_records``).
        """
        ...
