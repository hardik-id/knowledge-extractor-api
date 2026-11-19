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


class MergeableValue(Protocol):
    origin: str
    review: str


class Mergeable(Protocol):
    record_type_id: str
    span: Any  # {"start", "end", "quote"} or None
    origin: str
    review: str
    values: Any  # a list, or a related manager of MergeableValue


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


def _overlaps(a: Any, b: Any) -> bool:
    return bool(a["start"] < b["end"] and b["start"] < a["end"])


def merge_extracted_records[R: Mergeable](
    previous: Iterable[R], fresh: Iterable[R]
) -> list[R]:
    kept = [record for record in previous if is_touched_by_person(record)]
    added = [
        record
        for record in fresh
        if not record.span
        or not any(
            k.record_type_id == record.record_type_id
            and k.span
            and _overlaps(k.span, record.span)
            for k in kept
        )
    ]
    # sorted() is stable: records with the same start keep their order.
    return sorted(
        [*kept, *added],
        key=lambda record: record.span["start"] if record.span else math.inf,
    )
