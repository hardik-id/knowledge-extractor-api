"""The scripted extractor: no model, the same answer every time.

A port of the UI's ``src/services/mock/mock-extractor.ts``. A record is a ``## ``
heading that starts with the record type's name, down to the next ``## ``
heading. A field is the heading text (a title), a ``**Label:** value`` line or a
``### Label`` section. Offsets are code points, which is what ``str`` indexing
counts, so no conversion is needed here.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from apps.extraction.extractors.base import (
    Definition,
    RawRecord,
    RawValue,
    Span,
)

# What JavaScript's ``\s`` matches (Python's ``\s`` differs at the edges).
WS = " \t\n\v\f\r                 　﻿"
_S = f"[{WS}]"
_NOT_S = f"[^{WS}]"
_ANY = "[^\n\r  ]"  # JavaScript's ``.``

MONTHS = [
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
]

_ISO = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})")
_DAY_FIRST = re.compile(
    rf"([0-9]{{1,2}})(?:st|nd|rd|th)?{_S}+([A-Za-z]+)\.?,?{_S}+([0-9]{{4}})"
)
_MONTH_FIRST = re.compile(
    rf"([A-Za-z]+)\.?{_S}+([0-9]{{1,2}})(?:st|nd|rd|th)?,?{_S}+([0-9]{{4}})"
)
_SEPARATORS = re.compile(rf"[_\-{WS}]+")
_TITLE_HEADING = re.compile(rf"##{_S}+(?:{_NOT_S}+-[0-9]+{_S}*[:–-]{_S}*)?")
_LABELLED = re.compile(rf"\*\*({_ANY}+?):\*\*[ \t]*({_ANY}*)\Z")
_SECTION = re.compile(rf"###{_S}+({_ANY}*)\Z")
_H2 = re.compile(rf"##{_S}")
_ANY_HEADING = re.compile(rf"#{{1,6}}{_S}")


@dataclass(frozen=True)
class _Range:
    """Indices into the text; ``end`` is exclusive."""

    start: int
    end: int


@dataclass(frozen=True)
class _Line(_Range):
    text: str


def _trim(value: str) -> str:
    return value.strip(WS)


def _norm(label: str) -> str:
    return _trim(_SEPARATORS.sub(" ", label.lower()))


def _split_lines(text: str, start: int, to: int) -> list[_Line]:
    lines: list[_Line] = []
    while start <= to:
        end = text.find("\n", start)
        if end == -1 or end > to:
            end = to
        raw = text[start:end]
        lines.append(_Line(start, end, raw[:-1] if raw.endswith("\r") else raw))
        start = end + 1
    return lines


def _trim_range(text: str, r: _Range) -> _Range:
    start, end = r.start, r.end
    while start < end and text[start] in WS:
        start += 1
    while end > start and text[end - 1] in WS:
        end -= 1
    return _Range(start, end)


def parse_date(text: str) -> str | None:
    """The ISO date for "3 November 2026", "November 3, 2026" or "2026-11-03"; None if it does not parse."""
    iso = _ISO.search(text)
    day_first = _DAY_FIRST.search(text)
    month_first = _MONTH_FIRST.search(text)
    if iso:
        y, m, d = int(iso[1]), int(iso[2]), int(iso[3])
    elif day_first and day_first[2].lower() in MONTHS:
        y = int(day_first[3])
        m = MONTHS.index(day_first[2].lower()) + 1
        d = int(day_first[1])
    elif month_first and month_first[1].lower() in MONTHS:
        y = int(month_first[3])
        m = MONTHS.index(month_first[1].lower()) + 1
        d = int(month_first[2])
    else:
        return None
    # JavaScript's Date.UTC reads the years 0 to 99 as 1900 to 1999, so the
    # TypeScript answers null for them; so do we.
    if y < 100:
        return None
    try:
        date(y, m, d)
    except ValueError:
        return None
    return f"{y:04d}-{m:02d}-{d:02d}"


def _normalise(field: dict[str, Any], text: str) -> str:
    value_type = field.get("value_type")
    if value_type == "choice":
        lower = text.lower()
        for choice in field.get("choices", []):
            if choice.lower() in lower:
                return str(choice).lower()
        return lower
    if value_type == "date":
        return parse_date(text) or text
    return text


def _find_field(
    text: str, lines: list[_Line], field: dict[str, Any]
) -> list[_Range] | None:
    """Where a field's text is inside one block: one range, or one per comma-separated item."""
    labels = {n for n in (_norm(field["name"]), _norm(field["key"])) if n}
    if "decided on" in labels:
        labels.add("date")

    # The heading text after "ADR-012: ".
    if "title" in labels:
        heading = lines[0]
        match = _TITLE_HEADING.match(heading.text)
        prefix = match.end() if match else 0
        r = _trim_range(text, _Range(heading.start + prefix, heading.end))
        if r.end > r.start:
            return [r]

    for i, line in enumerate(lines):
        labelled = _LABELLED.match(line.text)
        if labelled and _norm(labelled[1]) in labels:
            value_start = line.start + len(line.text) - len(labelled[2])
            r = _trim_range(text, _Range(value_start, line.end))
            if r.end == r.start:
                continue
            if not field.get("multiple"):
                return [r]
            items: list[_Range] = []
            pos = r.start
            for part in text[r.start : r.end].split(","):
                item = _trim_range(text, _Range(pos, pos + len(part)))
                if item.end > item.start:
                    items.append(item)
                pos += len(part) + 1
            return items or None
        section = _SECTION.match(line.text)
        if section and _norm(section[1]) in labels:
            following = next(
                (
                    j
                    for j in range(i + 1, len(lines))
                    if _ANY_HEADING.match(lines[j].text)
                ),
                -1,
            )
            end = lines[-1].end if following == -1 else lines[following].start
            r = _trim_range(text, _Range(line.end + 1, end))
            if r.end > r.start:
                return [r]
    return None


def _blocks_for(text: str, record_type: dict[str, Any]) -> list[_Range]:
    name = _trim(record_type["name"]).lower()
    if not name:
        return []
    lines = _split_lines(text, 0, len(text))
    headings = [line for line in lines if _H2.match(line.text)]
    blocks: list[_Range] = []
    for heading in headings:
        title = re.sub(rf"^##{_S}+", "", heading.text).lower()
        if not title.startswith(name):
            continue
        following = next((h for h in headings if h.start > heading.start), None)
        end = following.start if following else len(text)
        blocks.append(_trim_range(text, _Range(heading.start, end)))
    return blocks


def _span(text: str, r: _Range) -> Span:
    return {"start": r.start, "end": r.end, "quote": text[r.start : r.end]}


def extract_records(text: str, definition: Definition) -> list[RawRecord]:
    records: list[RawRecord] = []
    for record_type in definition.record_types:
        for block in _blocks_for(text, record_type):
            lines = _split_lines(text, block.start, block.end)
            values: list[RawValue] = []
            for field in record_type["fields"]:
                found = _find_field(text, lines, field)
                if not found:
                    values.append(RawValue(field["id"], None, []))
                    continue
                quoted = field.get("mode") == "quote"
                for r in found:
                    raw = text[r.start : r.end]
                    values.append(
                        RawValue(
                            field["id"],
                            raw if quoted else _normalise(field, raw),
                            [_span(text, r)],
                        )
                    )
            records.append(RawRecord(record_type["id"], _span(text, block), values))
    return records


class ScriptedExtractor:
    """Finds the records a definition describes in Markdown, without a model."""

    def extract(
        self,
        text: str,
        definition: Definition,
        examples: Sequence[RawRecord] = (),
    ) -> list[RawRecord]:
        return extract_records(text, definition)
