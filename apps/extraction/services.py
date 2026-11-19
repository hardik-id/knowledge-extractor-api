"""Writes and business rules for the extraction app.

A service takes the acting user as its first argument.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from django.db import IntegrityError, transaction

from apps.core.errors import ApiError
from apps.extraction import selectors
from apps.extraction.models import (
    DefinitionVersion,
    Extraction,
    ExtractionRecord,
    FieldValue,
    Origin,
    Review,
)
from apps.extraction.spans import check_span
from apps.extraction.validation import validate_draft
from apps.identity.models import User
from apps.realtime import services as realtime
from apps.runs import selectors as runs


def save_definition(
    user: User, run_id: Any, *, base_version: int, data: Any
) -> DefinitionVersion:
    """Save ``data`` as the next version, if ``base_version`` is still the latest.

    Otherwise 409 ``definition_conflict``. Two saves on the same base cannot both
    succeed: the database refuses a second row for one version number.
    """
    current = selectors.get_definition(user, run_id)
    draft = validate_draft(data)
    if base_version != current.version:
        raise _conflict(current.version)
    try:
        with transaction.atomic():
            return DefinitionVersion.objects.create(
                run_id=current.run_id, version=current.version + 1, **draft
            )
    except IntegrityError:
        latest = selectors.latest_version(current.run_id)
        raise _conflict(latest.version if latest else current.version) from None


def _conflict(version: int) -> ApiError:
    return ApiError(
        "definition_conflict",
        "Someone saved a newer version of this definition.",
        {"version": version},
    )


# ---------------------------------------------------------------------------
# Corrections: what a person changes in the records of a file.
# ---------------------------------------------------------------------------


@dataclass
class Change:
    """What a change sees: the extraction being changed and the rules it is checked against."""

    extraction: Extraction
    definition: DefinitionVersion
    _text: Callable[[], str]

    def text(self) -> str:
        """The document's text, to check spans against. 422 ``upstream_not_ready`` without one."""
        return self._text()

    def record(self, record_id: Any) -> ExtractionRecord:
        try:
            return self.extraction.records.get(pk=UUID(str(record_id)))
        except ExtractionRecord.DoesNotExist, ValueError:
            raise ApiError("record_not_found") from None


def change_extraction(
    user: User,
    run_id: Any,
    file_id: Any,
    revision: int,
    apply: Callable[[Change], None],
    *,
    creates: bool = False,
) -> Extraction:
    """The one function every correction goes through.

    In this order: the file is in the run (404); the extraction exists (404
    ``extraction_not_found``, unless ``creates``: then it is made from the
    document's text and ETag, 422 ``upstream_not_ready`` without a text); the
    ``revision`` is the current one (409 ``revision_conflict``, ``details`` carry
    the current one); ``apply`` changes the records; the revision goes up by one.
    All or nothing. The row is locked while it changes, so of two writes with the
    same revision one succeeds and the other is a conflict. The change is announced
    on the run's socket once it is committed, and never when it was refused.
    """
    with transaction.atomic():
        run_file = runs.get_run_file(user, run_id, file_id)
        extraction = (
            Extraction.objects.select_for_update().filter(file=run_file).first()
        )
        if extraction is None:
            if not creates:
                raise ApiError("extraction_not_found")
            document = _document(run_file)
            if revision != 0:
                raise _revision_conflict(0)
            definition = selectors.get_definition(user, run_id)
            try:
                with transaction.atomic():
                    extraction = Extraction.objects.create(
                        file=run_file,
                        revision=0,
                        source_etag=document.etag,
                        definition_version=definition.version,
                    )
            except IntegrityError:  # a concurrent first add made it
                current = Extraction.objects.get(file=run_file).revision
                raise _revision_conflict(current) from None
        else:
            if revision != extraction.revision:
                raise _revision_conflict(extraction.revision)
            definition = selectors.get_definition_version(
                run_file.run_id, extraction.definition_version
            )

        apply(Change(extraction, definition, lambda: _document(run_file).text))
        extraction.revision += 1
        extraction.save()
        realtime.publish_run_event(
            run_file.run_id,
            {
                "type": "extraction.changed",
                "file_id": str(run_file.pk),
                "revision": extraction.revision,
            },
        )
    return selectors.get_extraction(user, run_id, file_id)


def _document(run_file: Any) -> Any:
    try:
        return selectors.input_text(run_file)
    except ApiError as error:
        if error.code == "document_not_found":
            raise ApiError("upstream_not_ready") from None
        raise


def _revision_conflict(revision: int) -> ApiError:
    return ApiError("revision_conflict", details={"revision": revision})


def add_record(
    user: User,
    run_id: Any,
    file_id: Any,
    *,
    revision: int,
    record_type_id: str,
    span: dict[str, Any] | None,
    fields: list[dict[str, Any]],
) -> Extraction:
    """Add a record a person marked. With ``revision`` 0 on a fresh file it makes the extraction."""

    def apply(change: Change) -> None:
        record_type = next(
            (t for t in change.definition.record_types if t["id"] == record_type_id),
            None,
        )
        if record_type is None:
            raise ApiError("unknown_field")
        known = {field["id"] for field in record_type["fields"]}
        if any(given["field_id"] not in known for given in fields):
            raise ApiError("unknown_field")
        checked_span = check_span(change.text(), span) if span else None
        values: list[FieldValue] = []
        for field in record_type["fields"]:
            given = [g for g in fields if g["field_id"] == field["id"]]
            # a field left out is one stored "not found": human, accepted
            inputs = [value for g in given for value in g["values"]]
            values.extend(_human_values(change, field, inputs))
        record = ExtractionRecord.objects.create(
            extraction=change.extraction,
            record_type_id=record_type_id,
            span=checked_span,
            origin=Origin.HUMAN,
            review=Review.ACCEPTED,
        )
        for value in values:
            value.record = record
        FieldValue.objects.bulk_create(values)

    return change_extraction(user, run_id, file_id, revision, apply, creates=True)


def _human_values(
    change: Change, field: dict[str, Any], inputs: list[dict[str, Any]]
) -> list[FieldValue]:
    """The values a person wrote for one field. No values at all is one "not found"."""
    if not field["multiple"] and len(inputs) > 1:
        raise ApiError("too_many_values", f'"{field["name"]}" takes a single value.')
    return [
        FieldValue(
            field_id=field["id"],
            value=given["value"],
            spans=[check_span(change.text(), span) for span in given["spans"]],
            origin=Origin.HUMAN,
            review=Review.ACCEPTED,
            anchored=True,
        )
        for given in inputs or [{"value": None, "spans": []}]
    ]


def update_record(
    user: User,
    run_id: Any,
    file_id: Any,
    record_id: Any,
    *,
    revision: int,
    patch: dict[str, Any],
) -> Extraction:
    """Change the keys of ``patch`` (``review``, ``span``, ``use_as_example``) and no others.

    Accepting a record also accepts its values that are still suggested.
    """

    def apply(change: Change) -> None:
        record = change.record(record_id)
        if "span" in patch:
            span = patch["span"]
            record.span = check_span(change.text(), span) if span else None
        if "use_as_example" in patch:
            record.use_as_example = patch["use_as_example"]
        if "review" in patch:
            record.review = patch["review"]
            if patch["review"] == Review.ACCEPTED:
                record.values.filter(review=Review.SUGGESTED).update(
                    review=Review.ACCEPTED
                )
        record.save()

    return change_extraction(user, run_id, file_id, revision, apply)


def delete_record(
    user: User, run_id: Any, file_id: Any, record_id: Any, *, revision: int
) -> Extraction:
    """Remove a record a person added. A model's suggestion is rejected instead: 422 ``not_deletable``."""

    def apply(change: Change) -> None:
        record = change.record(record_id)
        if record.origin != Origin.HUMAN:
            raise ApiError("not_deletable")
        record.delete()

    return change_extraction(user, run_id, file_id, revision, apply)


def replace_field_values(
    user: User,
    run_id: Any,
    file_id: Any,
    record_id: Any,
    field_id: str,
    *,
    revision: int,
    values: list[dict[str, Any]],
) -> Extraction:
    """Replace all values of one field with ``values``.

    A value sent back unchanged (same ``value``, same spans) as one the field has
    keeps its id, origin and review. The others are new: ``human`` and ``accepted``.
    Stored values that are not sent back are removed. No values at all resets the
    field to one "not found" value a later run does not fill again.
    """

    def apply(change: Change) -> None:
        record = change.record(record_id)
        record_type = next(
            (
                t
                for t in change.definition.record_types
                if t["id"] == record.record_type_id
            ),
            None,
        )
        field = next(
            (
                f
                for f in (record_type or {"fields": []})["fields"]
                if f["id"] == field_id
            ),
            None,
        )
        if field is None:
            raise ApiError("unknown_field")
        inputs = values or [{"value": None, "spans": []}]
        if not field["multiple"] and len(inputs) > 1:
            raise ApiError(
                "too_many_values", f'"{field["name"]}" takes a single value.'
            )
        stored = list(record.values.filter(field_id=field_id))
        keep: list[FieldValue] = []
        new: list[FieldValue] = []
        for given in inputs:
            wanted = [_plain_span(span) for span in given["spans"]]
            same = next(
                (
                    v
                    for v in stored
                    if v not in keep
                    and v.value == given["value"]
                    and [_plain_span(s) for s in v.spans] == wanted
                ),
                None,
            )
            if same is not None:
                keep.append(same)
                continue
            new.append(
                FieldValue(
                    record=record,
                    field_id=field_id,
                    value=given["value"],
                    spans=[check_span(change.text(), span) for span in given["spans"]],
                    origin=Origin.HUMAN,
                    review=Review.ACCEPTED,
                    anchored=True,
                )
            )
        record.values.filter(field_id=field_id).exclude(
            pk__in=[v.pk for v in keep]
        ).delete()
        FieldValue.objects.bulk_create(new)

    return change_extraction(user, run_id, file_id, revision, apply)


def _plain_span(span: Any) -> tuple[Any, Any, Any]:
    get = span.get if isinstance(span, dict) else lambda _key: None
    return (get("start"), get("end"), get("quote"))


def review_value(
    user: User,
    run_id: Any,
    file_id: Any,
    record_id: Any,
    value_id: Any,
    *,
    revision: int,
    review: str,
) -> Extraction:
    """Accept or reject one value of a record. 404 ``value_not_found`` for an unknown one."""

    def apply(change: Change) -> None:
        record = change.record(record_id)
        try:
            value = record.values.get(pk=UUID(str(value_id)))
        except FieldValue.DoesNotExist, ValueError:
            raise ApiError("value_not_found") from None
        value.review = review
        value.save()

    return change_extraction(user, run_id, file_id, revision, apply)
