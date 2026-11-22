"""``to_raw_records``: a model's answer made into raw records, rule by rule."""

from typing import Any

from apps.extraction.extractors import llm_output
from apps.extraction.extractors.base import Definition, RawRecord, RawValue
from apps.extraction.extractors.llm_output import (
    ModelOutput,
    ModelRecord,
    ModelValue,
    to_raw_records,
)
from apps.extraction.extractors.records import stored_records
from apps.extraction.spans import Span
from apps.extraction.validation import parse_draft

FIELDS: list[dict[str, Any]] = [
    {
        "id": "f-title",
        "key": "title",
        "name": "Title",
        "mode": "quote",
        "value_type": "text",
    },
    {
        "id": "f-status",
        "key": "status",
        "name": "Status",
        "mode": "inferred",
        "value_type": "choice",
        "choices": ["Accepted", "Rejected"],
    },
    {
        "id": "f-date",
        "key": "date",
        "name": "Date",
        "mode": "inferred",
        "value_type": "date",
    },
    {
        "id": "f-amount",
        "key": "amount",
        "name": "Amount",
        "mode": "inferred",
        "value_type": "number",
    },
    {
        "id": "f-note",
        "key": "note",
        "name": "Note",
        "mode": "inferred",
        "value_type": "text",
    },
    {
        "id": "f-tags",
        "key": "tags",
        "name": "Tags",
        "mode": "quote",
        "value_type": "text",
        "multiple": True,
    },
    {
        "id": "f-owners",
        "key": "owners",
        "name": "Owners",
        "mode": "inferred",
        "value_type": "text",
        "multiple": True,
    },
]


def definition() -> Definition:
    draft = parse_draft(
        {
            "prompt": "",
            "record_types": [{"id": "rt-a", "name": "A", "fields": FIELDS}],
            "output": {"format": "json", "template": ""},
        }
    )
    return Definition(1, "", draft.record_types)


DEFINITION = definition()


def val(key: str, value: str | None = None, *quotes: str) -> ModelValue:
    return ModelValue(field_key=key, value=value, quotes=list(quotes))


def rec(starts_with: str, *values: ModelValue, type_id: str = "rt-a") -> ModelRecord:
    return ModelRecord(
        record_type_id=type_id, starts_with=starts_with, values=list(values)
    )


def run(
    text: str, *records: ModelRecord, start: int = 0, end: int | None = None
) -> list[RawRecord]:
    return llm_output.to_raw_records(
        text, DEFINITION, ModelOutput(records=list(records)), start, end
    )


def by_field(record: RawRecord) -> dict[str, list[RawValue]]:
    out: dict[str, list[RawValue]] = {}
    for v in record.values:
        out.setdefault(v.field_id, []).append(v)
    return out


def test_the_answer_needs_every_key_and_no_extra() -> None:
    schema = ModelOutput.model_json_schema()
    assert schema["$defs"]["ModelValue"]["required"] == ["field_key", "value", "quotes"]
    assert schema["$defs"]["ModelValue"]["additionalProperties"] is False
    assert schema["$defs"]["ModelRecord"]["required"] == [
        "record_type_id",
        "starts_with",
        "values",
    ]


def test_rule1_unknown_record_type_and_field_key_are_dropped() -> None:
    text = "ADR one title"
    result = run(
        text,
        rec("ADR", val("title", None, "title")),
        rec("ADR", val("title", None, "one"), type_id="rt-nope"),
        rec("ADR", val("bogus", "x", "one"), val("title", None, "one")),
    )
    assert len(result) == 2
    assert all(r.record_type_id == "rt-a" for r in result)
    assert all(v.field_id.startswith("f-") for r in result for v in r.values)
    assert by_field(result[1])["f-title"][0].value == "one"


def test_rule1_field_id_is_the_fields_id() -> None:
    (record,) = run("ADR x", rec("ADR", val("title", None, "x")))
    assert by_field(record)["f-title"][0].field_id == "f-title"


def test_rule2_a_record_starts_at_the_first_starts_with_after_the_previous() -> None:
    text = "AA one\nBB two\nAA three"
    first, second, third = run(
        text,
        rec("AA", val("title", None, "one")),
        rec("BB", val("title", None, "two")),
        rec("AA", val("title", None, "three")),
    )
    assert first.span == Span(0, 6, "AA one")
    assert second.span is not None and second.span.start == 7
    assert third.span is not None and third.span.start == text.rindex("AA")


def test_rule2_starts_with_before_the_previous_start_is_not_found() -> None:
    text = "AA x\nBB y"
    _, second = run(
        text, rec("BB", val("title", None, "y")), rec("AA", val("title", None, "x"))
    )
    # AA is only before BB: not found, so the record is judged without a start.
    assert second.span is None  # no start, so no span (rule 8)
    assert by_field(second)["f-title"][0].spans == [Span(3, 4, "x")]


def test_rule2_region_ends_at_the_next_records_start() -> None:
    text = "AA one\nBB one"
    first, second = run(
        text, rec("AA", val("title", None, "one")), rec("BB", val("title", None, "one"))
    )
    assert by_field(first)["f-title"][0].spans == [Span(3, 6, "one")]
    assert by_field(second)["f-title"][0].spans == [Span(10, 13, "one")]


def test_rule2_a_record_without_a_found_start_has_the_whole_range_as_region() -> None:
    text = "AA one\nBB two"
    (record,) = run(text, rec("ZZ", val("title", None, "two")))
    assert by_field(record)["f-title"][0].spans == [Span(10, 13, "two")]


def test_rule3_a_quote_not_in_its_region_is_found_elsewhere_in_range() -> None:
    text = "AA one\nBB two"
    first, _ = run(
        text, rec("AA", val("title", None, "two")), rec("BB", val("note", "n"))
    )
    assert by_field(first)["f-title"][0].spans == [Span(10, 13, "two")]


def test_rule3_a_quote_not_found_is_span_zero_and_stored_not_anchored() -> None:
    text = "AA one"
    (record,) = run(text, rec("AA", val("title", None, "missing")))
    assert by_field(record)["f-title"][0].spans == [Span(0, 0, "missing")]
    (stored,) = stored_records(text, [record])
    title = next(v for v in stored.values if v.field_id == "f-title")
    assert title.anchored is False


def test_rule3_empty_quotes_are_dropped() -> None:
    (record,) = run("AA one", rec("AA", val("note", "n", "", "one")))
    assert by_field(record)["f-note"][0].spans == [Span(3, 6, "one")]


def test_rule3_offsets_are_code_points() -> None:
    text = "🚀🚀 AA one"
    (record,) = run(text, rec("AA", val("title", None, "one")))
    assert by_field(record)["f-title"][0].spans == [Span(6, 9, "one")]


def test_rule4_a_quote_field_has_the_quote_as_its_value() -> None:
    (record,) = run("AA one", rec("AA", val("title", "model words", "one")))
    assert by_field(record)["f-title"] == [
        RawValue("f-title", "one", [Span(3, 6, "one")])
    ]


def test_rule4_several_quotes_are_several_values_when_multiple() -> None:
    (record,) = run("AA red blue", rec("AA", val("tags", None, "red", "blue")))
    assert [v.value for v in by_field(record)["f-tags"]] == ["red", "blue"]


def test_rule4_several_quotes_first_counts_when_not_multiple() -> None:
    (record,) = run("AA one two", rec("AA", val("title", None, "one", "two")))
    assert [v.value for v in by_field(record)["f-title"]] == ["one"]


def test_rule4_with_no_quote_the_value_is_the_quote() -> None:
    (record,) = run("AA one", rec("AA", val("title", "one")))
    assert by_field(record)["f-title"] == [
        RawValue("f-title", "one", [Span(3, 6, "one")])
    ]


def test_rule5_a_choice_matches_loosely_and_is_stored_as_defined() -> None:
    (record,) = run("AA accepted", rec("AA", val("status", "  ACCEPTED ", "accepted")))
    assert by_field(record)["f-status"] == [
        RawValue("f-status", "Accepted", [Span(3, 11, "accepted")])
    ]


def test_rule5_a_choice_not_among_the_choices_is_not_found() -> None:
    (record,) = run("AA maybe", rec("AA", val("status", "Maybe", "maybe")))
    assert by_field(record)["f-status"] == [RawValue("f-status", None, [])]


def test_rule5_a_date_must_be_iso_and_real() -> None:
    text = "AA d"
    for bad in ("2026-02-30", "22/11/2026", "2026-1-5", "tomorrow"):
        (record,) = run(text, rec("AA", val("date", bad, "d")))
        assert by_field(record)["f-date"] == [RawValue("f-date", None, [])], bad
    (record,) = run(text, rec("AA", val("date", "2026-11-22", "d")))
    assert by_field(record)["f-date"][0].value == "2026-11-22"


def test_rule5_a_number_must_parse() -> None:
    text = "AA n"
    for bad in ("many", "nan", "1_000", "12abc", "inf"):
        (record,) = run(text, rec("AA", val("amount", bad, "n")))
        assert by_field(record)["f-amount"][0].value is None, bad
    for good in ("12", "-3.5", " 1e3 "):
        (record,) = run(text, rec("AA", val("amount", good, "n")))
        assert by_field(record)["f-amount"][0].value == good.strip()


def test_rule5_text_is_kept_trimmed_and_its_quotes_are_its_spans() -> None:
    (record,) = run("AA one two", rec("AA", val("note", "  a note ", "one", "two")))
    assert by_field(record)["f-note"] == [
        RawValue("f-note", "a note", [Span(3, 6, "one"), Span(7, 10, "two")])
    ]


def test_rule5_an_inferred_value_with_no_quote_has_no_spans() -> None:
    (record,) = run("AA", rec("AA", val("note", "free")))
    assert by_field(record)["f-note"] == [RawValue("f-note", "free", [])]


def test_rule6_a_field_that_is_not_multiple_keeps_its_first_value() -> None:
    (record,) = run("AA x", rec("AA", val("note", "first", "x"), val("note", "second")))
    assert [v.value for v in by_field(record)["f-note"]] == ["first"]


def test_rule6_a_multiple_field_keeps_every_value() -> None:
    (record,) = run("AA x", rec("AA", val("owners", "ann", "x"), val("owners", "bob")))
    assert [v.value for v in by_field(record)["f-owners"]] == ["ann", "bob"]


def test_rule7_every_field_has_a_value_in_definition_order() -> None:
    (record,) = run("AA one", rec("AA", val("note", "z"), val("title", None, "one")))
    assert [v.field_id for v in record.values] == [f["id"] for f in FIELDS]
    assert by_field(record)["f-status"] == [RawValue("f-status", None, [])]


def test_rule7_null_and_empty_values_are_not_found() -> None:
    (record,) = run("AA one", rec("AA", val("note", None, "one"), val("title", "")))
    assert by_field(record)["f-note"] == [RawValue("f-note", None, [])]
    assert by_field(record)["f-title"] == [RawValue("f-title", None, [])]


def test_rule8_the_record_span_runs_from_start_to_the_last_quote() -> None:
    text = "xx AA one\nmore two end"
    (record,) = run(text, rec("AA", val("title", None, "one"), val("note", "n", "two")))
    assert record.span == Span(3, 18, text[3:18])


def test_rule8_a_quote_outside_the_region_does_not_widen_the_span() -> None:
    text = "pre AA one"
    (record,) = run(text, rec("AA", val("title", None, "one"), val("note", "n", "pre")))
    assert record.span == Span(4, 10, "AA one")
    assert by_field(record)["f-note"][0].spans == [Span(0, 3, "pre")]


def test_rule8_a_record_without_a_start_has_no_span() -> None:
    (record,) = run("AA one", rec("ZZ", val("title", None, "one")))
    assert record.span is None


def test_rule8_one_far_quote_shared_by_many_records_stays_bounded() -> None:
    text = "HEAD" + "x" * 10000 + "TAIL"
    records = run(text, *[rec("HEAD", val("title", None, "TAIL")) for _ in range(300)])
    assert len(records) == 300
    assert sum(len(r.span.quote) for r in records if r.span) <= 2 * len(text)


def test_rule8_nothing_found_means_no_span() -> None:
    (record,) = run("text", rec("ZZ", val("note", "kept")))
    assert record.span is None


def test_rule9_no_start_and_no_value_drops_the_record() -> None:
    assert run("text", rec("ZZ"), rec("ZZ", val("status", "Maybe"))) == []


def test_rule9_a_start_alone_keeps_the_record() -> None:
    (record,) = run("AA text", rec("AA"))
    assert record.span == Span(0, 2, "AA")
    assert all(v.value is None for v in record.values)


def test_rule10_at_most_the_constant_are_kept(monkeypatch: Any) -> None:
    monkeypatch.setattr(llm_output, "MAX_RECORDS", 3)
    records = [rec("AA", val("note", str(i))) for i in range(10)]
    assert len(run("AA", *records)) == 3


def test_rule10_the_constant_is_1000() -> None:
    assert llm_output.MAX_RECORDS == 1000


def test_start_and_end_limit_where_records_and_quotes_are_looked_for() -> None:
    text = "AA one\nAA two\nAA three"
    (record,) = run(
        text, rec("AA", val("title", None, "one", "three")), start=7, end=13
    )
    assert record.span is not None and record.span.start == 7
    assert by_field(record)["f-title"][0].spans == [Span(0, 0, "one")]


def test_start_and_end_spans_are_offsets_into_the_whole_text() -> None:
    text = "AA one\nAA two"
    (record,) = run(text, rec("AA", val("title", None, "two")), start=7)
    assert by_field(record)["f-title"][0].spans == [Span(10, 13, "two")]


def test_a_repeated_quote_is_found_in_its_own_records_region() -> None:
    text = "AA Accepted\nBB Accepted"
    first, second = run(
        text,
        rec("AA", val("title", None, "Accepted")),
        rec("BB", val("title", None, "Accepted")),
    )
    assert by_field(first)["f-title"][0].spans == [Span(3, 11, "Accepted")]
    assert by_field(second)["f-title"][0].spans == [Span(15, 23, "Accepted")]


def test_the_result_goes_through_stored_records() -> None:
    text = "AA one\nBB two"
    raw = run(
        text,
        rec("AA", val("title", None, "one"), val("note", "n", "not in the text")),
        rec("BB", val("title", None, "two")),
    )
    first, second = stored_records(text, raw)
    values = {v.field_id: v for v in first.values}
    assert values["f-title"].anchored is True
    assert values["f-title"].spans == [Span(3, 6, "one")]
    assert values["f-note"].anchored is False
    assert first.span == Span(0, 6, "AA one")
    assert second.span is not None and second.span.start == 7


def test_to_raw_records_is_the_exported_function() -> None:
    assert to_raw_records is llm_output.to_raw_records


def test_rule6_a_non_multiple_inferred_field_keeps_a_first_invalid_value() -> None:
    (record,) = run("AA", rec("AA", val("amount", "x"), val("amount", "5")))
    assert by_field(record)["f-amount"] == [RawValue("f-amount", None, [])]


def test_rule11_nul_in_a_value_or_quote_is_not_found() -> None:
    (record,) = run(
        "AA one",
        rec("AA", val("note", "a\x00b", "one"), val("title", None, "no\x00pe")),
    )
    fields = by_field(record)
    assert fields["f-note"] == [RawValue("f-note", None, [])]
    assert fields["f-title"] == [RawValue("f-title", None, [])]


def test_rule11_nul_in_starts_with_is_not_found() -> None:
    (record,) = run("AA one", rec("A\x00", val("note", "kept")))
    assert record.span is None
