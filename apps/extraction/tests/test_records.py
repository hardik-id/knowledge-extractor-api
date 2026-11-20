"""Raw records made into stored ones: spans checked, quotes anchored."""

from apps.extraction.extractors.base import RawRecord, RawValue
from apps.extraction.extractors.records import stored_records
from apps.extraction.spans import Span

TEXT = "Intro 🚀\n\n## ADR-1: Title\n**Status:** Accepted\n"


def span(start: int, end: int, quote: str | None = None) -> Span:
    return Span(start, end, TEXT[start:end] if quote is None else quote)


def test_a_span_that_fits_is_kept_and_everything_is_llm_and_suggested() -> None:
    start = TEXT.index("## ADR")
    raw = RawRecord(
        "rt-adr",
        span(start, len(TEXT) - 1),
        [RawValue("f-title", "Title", [span(start + 10, start + 15)])],
    )
    (record,) = stored_records(TEXT, [raw])
    assert record.span == raw.span
    assert (record.origin, record.review, record.use_as_example) == (
        "llm",
        "suggested",
        False,
    )
    (value,) = record.values
    assert value.spans == [span(start + 10, start + 15)]
    assert (value.origin, value.review, value.anchored) == ("llm", "suggested", True)


def test_a_quote_whose_offsets_are_wrong_is_anchored_by_its_text() -> None:
    raw = RawRecord(
        "rt-adr", None, [RawValue("f-status", "accepted", [span(0, 8, "Accepted")])]
    )
    (record,) = stored_records(TEXT, [raw])
    (value,) = record.values
    found = TEXT.index("Accepted")
    assert value.spans == [span(found, found + 8)]
    assert value.anchored is True


def test_a_quote_that_is_not_in_the_text_is_kept_not_anchored() -> None:
    nowhere = Span(3, 9, "Not in the document")
    raw = RawRecord("rt-adr", None, [RawValue("f", "Not in the document", [nowhere])])
    (record,) = stored_records(TEXT, [raw])
    (value,) = record.values
    assert value.value == "Not in the document"
    assert value.spans == [nowhere]
    assert value.anchored is False


def test_a_value_is_anchored_only_when_every_span_is() -> None:
    raw = RawRecord(
        "rt",
        None,
        [RawValue("f", "x", [span(0, 5), Span(0, 1, "zzz")])],
    )
    (record,) = stored_records(TEXT, [raw])
    assert record.values[0].anchored is False
    assert len(record.values[0].spans) == 2


def test_a_value_without_spans_is_anchored() -> None:
    (record,) = stored_records(TEXT, [RawRecord("rt", None, [RawValue("f", None)])])
    assert record.values[0].anchored is True
    assert record.values[0].spans == []


def test_a_record_span_that_cannot_be_placed_is_dropped_from_the_record() -> None:
    bad = Span(0, 4, "nowhere")
    (record,) = stored_records(TEXT, [RawRecord("rt", bad)])
    assert record.span is None
    anchored = stored_records(TEXT, [RawRecord("rt", Span(0, 4, "ADR-1"))])[0]
    assert anchored.span == span(TEXT.index("ADR-1"), TEXT.index("ADR-1") + 5)
