"""A model's answer made into raw records. No model, no network, no database.

The model returns quotes and the first words of each record; this code finds them in
the text and gives the real offsets, because a model copies words reliably but is poor
at offsets. Nothing in the answer is trusted: ``to_raw_records`` drops, checks and
anchors, and every rule is in its docstring. Offsets count code points.
"""

import re
from dataclasses import dataclass
from datetime import date

from pydantic import BaseModel, ConfigDict

from apps.extraction.definition import Field, RecordType
from apps.extraction.extractors.base import Definition, RawRecord, RawValue
from apps.extraction.spans import Span

MAX_RECORDS = 1000

_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_NUMBER = re.compile(r"[+-]?([0-9]+(\.[0-9]*)?|\.[0-9]+)([eE][+-]?[0-9]+)?")


class _Strict(BaseModel):
    # Every key required, no defaults, no extra keys: strict JSON schema mode.
    model_config = ConfigDict(extra="forbid")


class ModelValue(_Strict):
    field_key: str
    value: str | None
    quotes: list[str]


class ModelRecord(_Strict):
    record_type_id: str
    starts_with: str
    values: list[ModelValue]


class ModelOutput(_Strict):
    records: list[ModelRecord]


@dataclass
class _Placed:
    """A record of the answer with its type and where it starts in the text."""

    record: ModelRecord
    type: RecordType
    start: int | None  # of ``starts_with``, None when not found
    region: tuple[int, int] = (0, 0)


def _inferred(field: Field, value: str | None) -> str | None:
    """The model's value if it fits the field's value type, else None."""
    text = (value or "").strip()
    if not text:
        return None
    if field.value_type == "choice":
        wanted = text.casefold()
        return next((c for c in field.choices if c.strip().casefold() == wanted), None)
    if field.value_type == "date":
        if not _DATE.fullmatch(text):
            return None
        try:
            date.fromisoformat(text)
        except ValueError:
            return None
        return text
    if field.value_type == "number":
        return text if _NUMBER.fullmatch(text) else None
    return text


def to_raw_records(
    text: str,
    definition: Definition,
    output: ModelOutput,
    start: int = 0,
    end: int | None = None,
) -> list[RawRecord]:
    """The records of ``output`` found in ``text[start:end]``, spans into the whole ``text``.

    1. A record of an unknown type, and a value of an unknown field key, are dropped.
    2. A record starts at the first ``starts_with`` at or after the previous record's
       start; its region runs to the next record's start (or ``end``). Without a
       start the region is the whole ``start..end``.
    3. A quote is looked for in the record's region, then in ``start..end``; not
       found it is ``Span(0, 0, quote)`` (stored as not anchored). Empty quotes go.
    4. A ``quote`` field's value is the quote (each quote a value if ``multiple``,
       else the first); with no quote the value counts as the quote.
    5. An ``inferred`` field's value is checked against its value type; failing
       means not found. Its quotes are its spans.
    6. A field that is not ``multiple`` keeps its first value.
    7. Every field has at least one ``RawValue``, in definition order.
    8. The record's span runs from the earliest to the latest of its start and its
       found quotes; none found, no span.
    9. A record with no found start and no value is dropped.
    10. At most ``MAX_RECORDS`` records are kept.
    """
    lo = min(max(start, 0), len(text))
    hi = len(text) if end is None else min(max(end, lo), len(text))

    placed: list[_Placed] = []
    cursor = lo
    for record in output.records:
        record_type = definition.record_type(record.record_type_id)
        if record_type is None:
            continue
        at = text.find(record.starts_with, cursor, hi) if record.starts_with else -1
        if at >= 0:
            cursor = at
        placed.append(_Placed(record, record_type, at if at >= 0 else None))

    following = hi
    for item in reversed(placed):
        if item.start is None:
            item.region = (lo, hi)
        else:
            item.region = (item.start, following)
            following = item.start

    result: list[RawRecord] = []
    for item in placed:
        raw = _raw_record(text, item, lo, hi)
        if raw is not None:
            result.append(raw)
        if len(result) >= MAX_RECORDS:
            break
    return result


def _raw_record(text: str, item: _Placed, lo: int, hi: int) -> RawRecord | None:
    def span_of(quote: str) -> Span:
        for a, b in (item.region, (lo, hi)):
            at = text.find(quote, a, b)
            if at >= 0:
                return Span(at, at + len(quote), quote)
        return Span(0, 0, quote)

    def found(span: Span) -> bool:
        return span.end > 0

    by_key: dict[str, list[ModelValue]] = {}
    for model_value in item.record.values:
        by_key.setdefault(model_value.field_key, []).append(model_value)

    values: list[RawValue] = []
    for field in item.type.fields:
        candidates: list[RawValue] = []
        for model_value in by_key.get(field.key, []):
            quotes = [q for q in model_value.quotes if q]
            if field.mode == "quote":
                if not quotes and (model_value.value or "").strip():
                    quotes = [model_value.value or ""]
                candidates += [RawValue(field.id, q, [span_of(q)]) for q in quotes]
            else:
                checked = _inferred(field, model_value.value)
                if checked is not None:
                    candidates.append(
                        RawValue(field.id, checked, [span_of(q) for q in quotes])
                    )
        if not field.multiple:
            candidates = candidates[:1]
        values += candidates or [RawValue(field.id, None, [])]

    points: list[int] = []
    if item.start is not None:
        points += [item.start, item.start + len(item.record.starts_with)]
    for value in values:
        for quote_span in value.spans:
            if found(quote_span):
                points += [quote_span.start, quote_span.end]

    if item.start is None and all(v.value is None for v in values):
        return None
    span = (
        Span(min(points), max(points), text[min(points) : max(points)])
        if points
        else None
    )
    return RawRecord(item.type.id, span, values)
