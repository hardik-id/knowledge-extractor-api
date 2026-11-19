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

Span = dict[str, Any]  # {"start", "end", "quote"}; offsets count code points


@dataclass(frozen=True)
class Definition:
    """A definition version: the prompt and the record types with their fields.

    ``record_types`` has the shape of the stored definition (``docs`` of the UI,
    snake_case): each record type has ``id``, ``name``, ``fields``; each field
    has ``id``, ``key``, ``name``, ``mode``, ``value_type``, ``choices``,
    ``multiple``.
    """

    version: int
    prompt: str
    record_types: list[dict[str, Any]]

    @classmethod
    def from_version(cls, version: Any) -> Definition:
        """Plain data from a stored ``DefinitionVersion`` (anything with its attributes)."""
        return cls(version.version, version.prompt, list(version.record_types))


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
