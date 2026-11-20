"""What an extraction run leaves behind when records already exist.

A port of the UI's ``src/services/mock/extraction-merge.ts``.

- Every record a person touched is kept as it is.
- Untouched suggestions from the earlier run are dropped.
- A fresh record is dropped when its span overlaps a kept record of the same
  record type: it is either already accepted or already rejected.
- The result is ordered by span start, records without a span last.

The functions take stored records (``ExtractionRecord`` with its values) or the
plain ``StoredRecord`` of ``extractors.records``: anything with the attributes
of ``Mergeable``.
"""

import math
from collections.abc import Iterable
from typing import Any, Protocol

from apps.extraction.models import Origin, Review
from apps.extraction.spans import Span


class MergeableValue(Protocol):
    origin: str
    review: str


class Mergeable(Protocol):
    record_type_id: str
    origin: str
    review: str
    values: Any  # a list, or a related manager of MergeableValue

    @property
    def span(self) -> Span | dict[str, Any] | None:
        """A ``Span``, or the stored JSON of one (``ExtractionRecord``), or none."""
        ...


def _values(record: Mergeable) -> Iterable[MergeableValue]:
    values = record.values
    return values.all() if hasattr(values, "all") else values  # type: ignore[no-any-return]


def is_touched_by_person(record: Mergeable) -> bool:
    """Whether a person has had a hand in this record or any of its values."""
    return (
        record.origin == Origin.HUMAN
        or record.review != Review.SUGGESTED
        or any(
            value.origin == Origin.HUMAN or value.review != Review.SUGGESTED
            for value in _values(record)
        )
    )


def _span(record: Mergeable) -> Span | None:
    """The record's span as a ``Span``; a stored record has it as JSON (the one edge here)."""
    span = record.span
    return Span.from_json(span) if isinstance(span, dict) else span


def _overlaps(a: Span, b: Span) -> bool:
    return a.start < b.end and b.start < a.end


def _start(record: Mergeable) -> float:
    span = _span(record)
    return span.start if span else math.inf


def merge_extracted_records[R: Mergeable](
    previous: Iterable[R], fresh: Iterable[R]
) -> list[R]:
    kept = [record for record in previous if is_touched_by_person(record)]
    added = [
        record
        for record in fresh
        if (span := _span(record)) is None
        or not any(
            k.record_type_id == record.record_type_id
            and (kept_span := _span(k)) is not None
            and _overlaps(kept_span, span)
            for k in kept
        )
    ]
    # sorted() is stable: records with the same start keep their order.
    return sorted(
        [*kept, *added],
        key=_start,
    )
