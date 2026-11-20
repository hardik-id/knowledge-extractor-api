"""The merge rule: a port of the UI's extraction-merge.test.ts, plus stored records."""

from typing import Any

import pytest

from apps.extraction.extractors.records import StoredRecord, StoredValue
from apps.extraction.merge import is_touched_by_person, merge_extracted_records
from apps.extraction.models import ExtractionRecord
from apps.extraction.spans import Span
from apps.extraction.tests.factories import (
    ExtractionFactory,
    ExtractionRecordFactory,
    FieldValueFactory,
)


def value(origin: str = "llm", review: str = "suggested") -> StoredValue:
    return StoredValue("f", "x", [], origin=origin, review=review)


def record(id: str, span: tuple[int, int] | None, **over: Any) -> StoredRecord:
    stored = StoredRecord(
        record_type_id=over.pop("record_type_id", "rt"),
        span=Span(span[0], span[1], "q") if span else None,
        values=over.pop("values", [value()]),
        **over,
    )
    stored.id = id  # type: ignore[attr-defined]
    return stored


def ids(records: list[StoredRecord]) -> list[str]:
    return [r.id for r in records]  # type: ignore[attr-defined]


def test_an_accepted_record_is_kept_unchanged_and_its_fresh_duplicate_is_not_added() -> (
    None
):
    accepted = record("old", (10, 20), review="accepted")
    merged = merge_extracted_records(
        [accepted], [record("new", (12, 22)), record("other", (30, 40))]
    )
    assert ids(merged) == ["old", "other"]
    assert merged[0] is accepted


def test_a_rejected_record_stays_rejected_and_is_not_suggested_again() -> None:
    merged = merge_extracted_records(
        [record("old", (10, 20), review="rejected")], [record("new", (10, 20))]
    )
    assert ids(merged) == ["old"]
    assert merged[0].review == "rejected"


def test_a_record_a_person_added_survives() -> None:
    human = record("mine", None, origin="human", review="accepted")
    assert ids(merge_extracted_records([human], [record("new", (1, 2))])) == [
        "new",
        "mine",
    ]


def test_untouched_suggestions_are_replaced_by_the_new_runs() -> None:
    merged = merge_extracted_records(
        [record("a", (1, 5)), record("b", (8, 9))], [record("c", (1, 5))]
    )
    assert ids(merged) == ["c"]


def test_a_record_with_one_human_edited_value_is_kept_whole() -> None:
    edited = record("old", (10, 20), values=[value(), value("human", "accepted")])
    merged = merge_extracted_records([edited], [record("new", (10, 20))])
    assert merged == [edited]


def test_a_record_whose_value_was_only_reviewed_is_kept() -> None:
    reviewed = record("old", (10, 20), values=[value("llm", "rejected")])
    assert ids(merge_extracted_records([reviewed], [])) == ["old"]


def test_only_records_of_the_same_type_block_each_other() -> None:
    kept = record("kept", (10, 20), review="accepted")
    no_span = record("nospan", None, review="accepted")
    other_type = record("other-type", (10, 20), record_type_id="rt2")
    merged = merge_extracted_records(
        [kept, no_span], [other_type, record("anywhere", (0, 100))]
    )
    assert "other-type" in ids(merged)
    assert "anywhere" not in ids(merged), "overlaps kept"


def test_a_kept_record_without_a_span_blocks_nothing() -> None:
    no_span = record("nospan", None, review="accepted")
    free = merge_extracted_records([no_span], [record("x", (10, 20))])
    assert ids(free) == ["x", "nospan"]


def test_a_fresh_record_without_a_span_is_always_added() -> None:
    kept = record("kept", (10, 20), review="accepted")
    assert ids(merge_extracted_records([kept], [record("loose", None)])) == [
        "kept",
        "loose",
    ]


def test_spans_that_only_touch_do_not_overlap() -> None:
    kept = record("kept", (10, 20), review="accepted")
    assert ids(merge_extracted_records([kept], [record("next", (20, 30))])) == [
        "kept",
        "next",
    ]


def test_the_result_is_ordered_by_span_start_no_span_last_stable_otherwise() -> None:
    merged = merge_extracted_records(
        [record("h1", None, origin="human"), record("h2", (50, 60), origin="human")],
        [record("f2", (5, 6)), record("f1", None), record("f3", (5, 7))],
    )
    assert ids(merged) == ["f2", "f3", "h2", "h1", "f1"]


@pytest.mark.django_db
def test_works_on_stored_records_with_their_values() -> None:
    extraction = ExtractionFactory()
    span = {"start": 10, "end": 20, "quote": "q"}
    untouched = ExtractionRecordFactory(extraction=extraction, span=span)
    FieldValueFactory(record=untouched)
    edited = ExtractionRecordFactory(extraction=extraction, span=span)
    FieldValueFactory(record=edited)
    FieldValueFactory(record=edited, origin="human", review="accepted")
    stored = list(
        ExtractionRecord.objects.filter(extraction=extraction).prefetch_related(
            "values"
        )
    )
    assert [is_touched_by_person(r) for r in stored] == [False, True]
    fresh = record("new", (12, 22), record_type_id="rt-adr")
    merged = merge_extracted_records(stored, [fresh])
    assert merged == [stored[1]]
