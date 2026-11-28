"""Reads for the assistant app.

A selector takes the acting user and returns only what that user may see.
"""

from typing import Any

from asgiref.sync import sync_to_async

from apps.assistant.agents.base import (
    DocumentRef,
    FileRecords,
    RecordView,
    ValueView,
)
from apps.assistant.models import Message
from apps.core.errors import ApiError
from apps.extraction import selectors as extraction
from apps.extraction.definition import Draft
from apps.iam.roles import Permission
from apps.identity.models import User
from apps.runs import selectors as runs


def list_messages(user: User, run_id: Any) -> list[Message]:
    """The conversation of a run ``user`` may view, oldest first. A run they do not
    see is a 404."""
    run = runs.get_run(user, run_id, Permission.WORKSPACE_VIEW)
    return list(Message.objects.filter(run_id=run.pk))


class StoredRunView:
    """One read-only view of a run, as an agent may look at it: for the run itself.

    It holds the run, so it reads through no person's workspace role: whoever of
    the run's editors asked, the reply sees the same run. Only the run's own files
    can be read or previewed; any other document id is ``document_not_found``. Their
    text comes as for an extraction (``extraction.input_text``). What it returns is
    plain data (``agents.base``): no model instance reaches an agent.
    """

    def __init__(self, run: Any) -> None:
        self._run = run

    async def documents(self) -> list[DocumentRef]:
        return await sync_to_async(self._documents)()

    async def read(self, document_id: str) -> str:
        return await sync_to_async(self._read)(document_id)

    async def extractions(self) -> list[FileRecords]:
        return await sync_to_async(self._extractions)()

    async def preview(self, definition: Draft, document_id: str) -> list[RecordView]:
        return await sync_to_async(self._preview)(definition, document_id)

    def _documents(self) -> list[DocumentRef]:
        return [
            DocumentRef(id=file.source_ref, name=file.name)
            for file in self._run.files.order_by("name", "id")
        ]

    def _read(self, document_id: str) -> str:
        found = self._run.files.filter(source_ref=document_id).first()
        if found is None:
            raise ApiError("document_not_found")
        return extraction.input_text(found).text

    def _extractions(self) -> list[FileRecords]:
        return [
            FileRecords(
                document_id=found.file.source_ref,
                name=found.file.name,
                definition_version=found.definition_version,
                records=[
                    _record_view(record, record.values.all())
                    for record in found.records.all()
                ],
            )
            for found in extraction.extractions_of(self._run)
        ]

    def _preview(self, definition: Draft, document_id: str) -> list[RecordView]:
        text = self._read(document_id)
        found = extraction.preview_records(self._run, text, definition)
        return [_record_view(record, record.values) for record in found]


def _record_view(record: Any, values: Any) -> RecordView:
    """A stored record, or one an extraction would store, as plain data."""
    return RecordView(
        record_type_id=record.record_type_id,
        origin=str(record.origin),
        review=str(record.review),
        values=[
            ValueView(
                field_id=value.field_id,
                value=value.value,
                origin=str(value.origin),
                review=str(value.review),
                anchored=value.anchored,
            )
            for value in values
        ],
    )


def run_run_view(message: Message) -> StoredRunView:
    """The run view of the run ``message`` belongs to."""
    return run_view_of(message.run)


def run_view_of(run: Any) -> StoredRunView:
    """The run view of ``run``, which the caller already holds."""
    return StoredRunView(run)
