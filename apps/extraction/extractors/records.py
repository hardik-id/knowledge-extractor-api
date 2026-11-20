"""Raw records from an extractor, made into records ready to be stored.

One function, ``stored_records``, does it for a file: it checks every span against
the text, tries to anchor a quote that does not fit, keeps a quote that is not
found with ``anchored`` false, and marks everything ``llm`` and ``suggested``.
It touches no database: it returns plain data that the caller writes.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field

from apps.extraction.extractors.base import RawRecord, RawValue
from apps.extraction.models import Origin, Review
from apps.extraction.spans import Span, resolve_span


@dataclass
class StoredValue:
    field_id: str
    value: str | None
    spans: list[Span]
    origin: str = Origin.LLM
    review: str = Review.SUGGESTED
    anchored: bool = True


@dataclass
class StoredRecord:
    record_type_id: str
    span: Span | None
    values: list[StoredValue] = field(default_factory=list)
    origin: str = Origin.LLM
    review: str = Review.SUGGESTED
    use_as_example: bool = False


def _value(text: str, raw: RawValue) -> StoredValue:
    spans: list[Span] = []
    anchored = True
    for span in raw.spans:
        resolved, fits = resolve_span(text, span)
        spans.append(resolved)
        anchored = anchored and fits
    return StoredValue(raw.field_id, raw.value, spans, anchored=anchored)


def _record_span(text: str, span: Span | None) -> Span | None:
    """The record's span if it fits or can be anchored by its quote, else none."""
    if span is None:
        return None
    resolved, fits = resolve_span(text, span)
    return resolved if fits else None


def stored_records(text: str, raw_records: Iterable[RawRecord]) -> list[StoredRecord]:
    """The records of one file, as they are stored for review.

    - A span that fits (``text[start:end] == quote``) is kept.
    - One whose offsets do not fit is searched for by its quote and its offsets
      corrected.
    - A value whose quote is not in the text is kept as returned, with
      ``anchored`` false, so a person can see it. A record whose own span cannot
      be placed is kept without a span.
    - Every record and value is ``llm`` and ``suggested``.
    """
    return [
        StoredRecord(
            raw.record_type_id,
            _record_span(text, raw.span),
            [_value(text, value) for value in raw.values],
        )
        for raw in raw_records
    ]
