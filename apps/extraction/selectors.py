"""Reads for the extraction app.

A selector takes the acting user and returns only what that user may see.
"""

from typing import TYPE_CHECKING, Any

from django.db import IntegrityError, transaction

from apps.core.errors import ApiError
from apps.documents import selectors as documents
from apps.documents.selectors import DocumentText
from apps.extraction.definition import Draft
from apps.extraction.extractors import get_preview_extractor
from apps.extraction.extractors.base import Definition, RawRecord, RawValue
from apps.extraction.extractors.records import StoredRecord, stored_records
from apps.extraction.merge import merge_extracted_records
from apps.extraction.models import (
    DefinitionVersion,
    Extraction,
    ExtractionRecord,
    Review,
)
from apps.extraction.spans import Span
from apps.extraction.template_registry import default_template
from apps.identity.models import User
from apps.runs import selectors as runs

if TYPE_CHECKING:  # only for the annotation: apps do not import each other's models
    from apps.runs.models import RunFile


def latest_version(run_id: Any) -> DefinitionVersion | None:
    return DefinitionVersion.objects.filter(run_id=run_id).order_by("-version").first()


def get_definition(user: User, run_id: Any) -> DefinitionVersion:
    """The latest definition of ``user``'s run; the first read makes version 1.

    Someone else's run and an unknown id are both 404 ``run_not_found``.
    """
    run = runs.get_run(user, run_id)
    current = latest_version(run.pk)
    if current is not None:
        return current
    try:
        with transaction.atomic():
            start = default_template().definition.model_dump()
            return DefinitionVersion.objects.create(
                run=run,
                version=1,
                prompt=start["prompt"],
                record_types=start["record_types"],
                output=start["output"],
            )
    except IntegrityError:  # a concurrent first read made it
        current = latest_version(run.pk)
        if current is None:
            raise
        return current


def get_definition_version(run_id: Any, version: int) -> DefinitionVersion:
    """One saved version of a run's definition, for the code that ran with it."""
    try:
        return DefinitionVersion.objects.get(run_id=run_id, version=version)
    except DefinitionVersion.DoesNotExist:
        raise ApiError("not_found", "Definition version not found.") from None


def list_definition_versions(user: User, run_id: Any) -> list[DefinitionVersion]:
    """The saved versions of ``user``'s run, newest first; the first read makes version 1."""
    run_id = get_definition(user, run_id).run_id
    return list(DefinitionVersion.objects.filter(run_id=run_id).order_by("-version"))


def get_definition_version_of(
    user: User, run_id: Any, version: int
) -> DefinitionVersion:
    """One saved version of ``user``'s run.

    Someone else's run is 404 ``run_not_found``; an unknown version is 404
    ``definition_version_not_found``.
    """
    run_id = get_definition(user, run_id).run_id  # also makes version 1 on a first read
    try:
        return DefinitionVersion.objects.get(run_id=run_id, version=version)
    except DefinitionVersion.DoesNotExist:
        raise ApiError("definition_version_not_found") from None


def get_extraction(user: User, run_id: Any, file_id: Any) -> Extraction:
    """The extraction of one of ``user``'s run files, with its records and values.

    404 ``run_not_found`` or ``file_not_found`` as for the run and file, and 404
    ``extraction_not_found`` before the file's first extraction.
    """
    run_file = runs.get_run_file(user, run_id, file_id)
    try:
        return Extraction.objects.prefetch_related("records__values").get(file=run_file)
    except Extraction.DoesNotExist:
        raise ApiError("extraction_not_found") from None


def list_extractions(user: User, run_id: Any) -> list[Extraction]:
    """The extractions of ``user``'s run, with their records and values, by file name.

    Only files that have been extracted have one. Someone else's run is a 404.
    """
    run = runs.get_run(user, run_id)
    return list(
        Extraction.objects.filter(file__run_id=run.pk)
        .select_related("file")
        .prefetch_related("records__values")
        .order_by("file__name", "file_id")
    )


def preview_records(
    user: User, run_id: Any, text: str, draft: Draft
) -> list[StoredRecord]:
    """The records an extraction of ``text`` with ``draft`` would store, storing nothing.

    The configured extractor runs with the run's example records, its output is
    checked as in a real execution (``stored_records``) and merged into an empty
    extraction, so the order is the stored one. The draft is a definition without
    a version. Someone else's run is a 404.
    """
    run = runs.get_run(user, run_id)
    definition = Definition(0, draft.prompt, draft.record_types)
    raw = get_preview_extractor().extract(text, definition, example_records(run.pk))
    return merge_extracted_records([], stored_records(text, raw))


def input_text(run_file: RunFile) -> DocumentText:
    """The text and ETag of the document a run file points at, read as the run's owner."""
    return documents.read_document(run_file.run.owner, run_file.source_ref)


def example_records(run_id: Any) -> list[RawRecord]:
    """The records of the run a person accepted and marked ``use_as_example``.

    As an extractor takes them: plain data, without the values a person rejected.
    """
    records = (
        ExtractionRecord.objects.filter(
            extraction__file__run_id=run_id,
            use_as_example=True,
            review=Review.ACCEPTED,
        )
        .prefetch_related("values")
        .order_by("id")
    )
    return [
        RawRecord(
            record.record_type_id,
            Span.from_json(record.span) if record.span else None,
            [
                RawValue(
                    value.field_id,
                    value.value,
                    [Span.from_json(span) for span in value.spans],
                )
                for value in record.values.all()
                if value.review != Review.REJECTED
            ],
        )
        for record in records
    ]
