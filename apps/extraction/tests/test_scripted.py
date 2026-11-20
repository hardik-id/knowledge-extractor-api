"""The scripted extractor: a port of the UI's mock-extractor.test.ts.

Each test names the TypeScript test it ports. ``unanchorFirst`` is a test hook of
the UI's mock and has no counterpart here; the anchoring of a quote that is not
found is tested in ``test_records.py``.
"""

import copy
from typing import Any

import pytest

from apps.documents import selectors as documents
from apps.extraction.extractors.base import Definition, RawRecord, RawValue
from apps.extraction.extractors.scripted import ScriptedExtractor, parse_date
from apps.extraction.spans import Span
from apps.extraction.tests.default_definition import (
    DEFAULT_OUTPUT,
    DEFAULT_RECORD_TYPES,
)
from apps.extraction.validation import parse_draft

DECISIONS = "enriched/engineering/architecture/architecture-decisions-2026.md"
PLATFORM = "enriched/engineering/architecture/platform-adrs.md"


def definition_of(record_types: list[dict[str, Any]] | None = None) -> Definition:
    """A definition from the dict form of record types, through ``parse_draft``."""
    draft = parse_draft(
        {
            "prompt": "",
            "record_types": record_types or DEFAULT_RECORD_TYPES,
            "output": DEFAULT_OUTPUT,
        }
    )
    return Definition(1, "", draft.record_types)


DEFINITION = definition_of()


def extract(
    text: str, record_types: list[dict[str, Any]] | None = None
) -> list[RawRecord]:
    definition = definition_of(record_types)
    return ScriptedExtractor().extract(text, definition)


def field(record: RawRecord, key: str) -> list[RawValue]:
    fields = DEFAULT_RECORD_TYPES[0]["fields"]
    field_id = next(f["id"] for f in fields if f["key"] == key)
    return [v for v in record.values if v.field_id == field_id]


@pytest.fixture
def decisions(user: Any) -> str:
    return documents.read_document(user, DECISIONS).text


def test_finds_the_three_adrs_of_the_sample_in_order(decisions: str) -> None:
    records = extract(decisions)
    assert len(records) == 3
    assert [field(r, "title")[0].value for r in records] == [
        "Use Postgres for the orders service",
        "Adopt OpenTelemetry for tracing",
        "Retire the legacy SOAP gateway",
    ]
    assert all(r.record_type_id == "rt-adr" for r in records)
    assert all(r.span and r.span.quote.startswith("## ADR-") for r in records)


def test_the_decisions_sample_has_a_character_outside_the_bmp(decisions: str) -> None:
    assert len(decisions.encode("utf-16-le")) // 2 > len(decisions)


@pytest.mark.parametrize("document_id", [DECISIONS, PLATFORM])
def test_every_span_is_the_text_at_its_offsets_past_the_emoji_too(
    user: Any, document_id: str
) -> None:
    text = documents.read_document(user, document_id).text
    records = extract(text)
    assert records
    for record in records:
        assert record.span
        spans = [record.span, *(s for v in record.values for s in v.spans)]
        for span in spans:
            assert span
            assert text[span.start : span.end] == span.quote


def test_a_multiple_field_gives_one_value_per_approver(decisions: str) -> None:
    records = extract(decisions)
    assert [v.value for v in field(records[0], "approved_by")] == [
        "J. Smit",
        "A. de Vries",
    ]
    assert [v.value for v in field(records[2], "approved_by")] == ["M. Jansen"]


def test_a_missing_field_gives_one_null_value_without_spans(decisions: str) -> None:
    missing = field(extract(decisions)[1], "approved_by")
    assert len(missing) == 1
    assert missing[0].value is None
    assert missing[0].spans == []


def test_inferred_values_are_normalised_and_keep_their_evidence(
    decisions: str,
) -> None:
    records = extract(decisions)
    assert [field(r, "status")[0].value for r in records] == [
        "accepted",
        "proposed",
        "superseded",
    ]
    assert [field(r, "decided_on")[0].value for r in records] == [
        "2026-11-03",
        "2026-11-10",
        "2026-09-14",
    ]
    assert field(records[0], "status")[0].spans[0].quote == "Accepted"
    assert field(records[0], "decided_on")[0].spans[0].quote == "3 November 2026"


def test_quote_fields_hold_the_exact_text_of_sections(decisions: str) -> None:
    assert (
        field(extract(decisions)[0], "decision")[0].value
        == "We store orders in Postgres and drop the document store pilot."
    )


def test_another_record_type_name_finds_nothing(decisions: str) -> None:
    record_types = copy.deepcopy(DEFAULT_RECORD_TYPES)
    record_types[0].update(id="rt-x", name="Policy")
    assert extract(decisions, record_types) == []


def test_an_unknown_field_gives_null(decisions: str) -> None:
    record_types = copy.deepcopy(DEFAULT_RECORD_TYPES)
    record_types[0]["fields"] = [
        {**record_types[0]["fields"][0], "id": "f-x", "key": "owner", "name": "Owner"}
    ]
    records = extract(decisions, record_types)
    assert len(records) == 3
    assert all(len(r.values) == 1 and r.values[0].value is None for r in records)


def test_a_record_type_without_fields_is_just_its_block(decisions: str) -> None:
    record_types = copy.deepcopy(DEFAULT_RECORD_TYPES)
    record_types[0]["fields"] = []
    records = extract(decisions, record_types)
    assert len(records) == 3
    assert all(r.values == [] and r.span for r in records)


def test_a_file_without_adrs_gives_no_records(user: Any) -> None:
    text = documents.read_document(
        user, "enriched/hr/policies/leave-policy-2026.md"
    ).text
    assert extract(text) == []


def test_offsets_count_code_points_after_non_ascii_text() -> None:
    # "🚀" is two UTF-16 units, "é" two UTF-8 bytes: only code points give 0-based str offsets.
    text = "Intro 🚀 é 日本語\n\n## ADR-1: Écrire ✨\n**Status:** Accepted\n"
    (record,) = extract(text)
    start = 15  # "Intro 🚀 é 日本語" is 13 code points, then two newlines
    assert text[start:].startswith("## ADR-1")
    assert record.span == Span(start, len(text) - 1, text[start:-1])
    title = field(record, "title")[0]
    assert title.value == "Écrire ✨"
    assert title.spans[0].quote == "Écrire ✨"
    assert title.spans[0].start == text.index("Écrire")
    for span in (record.span, *(s for v in record.values for s in v.spans)):
        assert span
        assert text[span.start : span.end] == span.quote


def test_crlf_lines_and_labels_in_other_cases() -> None:
    text = "## ADR-9: crlf\r\n**STATUS:** Accepted\r\n**Date:** 2026-01-02\r\n### Decision\r\nText here\r\n"
    (record,) = extract(text)
    assert field(record, "status")[0].value == "accepted"
    assert field(record, "decided_on")[0].value == "2026-01-02"
    assert field(record, "decision")[0].value == "Text here"
    assert field(record, "title")[0].value == "crlf"


@pytest.mark.parametrize(
    ("text", "iso"),
    [
        ("3 November 2026", "2026-11-03"),
        ("November 3, 2026", "2026-11-03"),
        ("Nov 3rd 2026", None),  # only full month names
        ("1st September 2025", "2025-09-01"),
        ("on 2026-09-14.", "2026-09-14"),
        ("31 February 2026", None),
        ("2026-13-01", None),
        ("0050-01-01", None),  # the TypeScript reads year 50 as 1950 and answers null
        ("nothing", None),
    ],
)
def test_parse_date(text: str, iso: str | None) -> None:
    assert parse_date(text) == iso
