"""Reads for the assistant app.

A selector takes the acting user and returns only what that user may see.
"""

from typing import Any

from asgiref.sync import sync_to_async

from apps.assistant.agents.base import (
    Definition,
    DocumentRef,
    FileRecords,
    RecordView,
    ValueView,
)
from apps.assistant.models import Message
from apps.core.errors import ApiError
from apps.documents import selectors as documents
from apps.extraction import selectors as extraction
from apps.extraction.validation import validate_draft
from apps.identity.models import User
from apps.runs import selectors as runs


def list_messages(user: User, run_id: Any) -> list[Message]:
    """The conversation of ``user``'s run, oldest first. Someone else's run is a 404."""
    run = runs.get_run(user, run_id)
    return list(Message.objects.filter(run_id=run.pk))


class OwnerWorkspace:
    """One read-only view of a run, as an agent may look at it: as the run's owner.

    Only the run's own files can be read or previewed; any other document id is
    ``document_not_found``, even one the owner could open elsewhere. What it
    returns is plain data (``agents.base``): no model instance reaches an agent.
    """

    def __init__(self, run: Any) -> None:
        self._run = run
        self._owner: User = run.owner

    async def documents(self) -> list[DocumentRef]:
        return await sync_to_async(self._documents)()

    async def read(self, document_id: str) -> str:
        return await sync_to_async(self._read)(document_id)

    async def extractions(self) -> list[FileRecords]:
        return await sync_to_async(self._extractions)()

    async def preview(
        self, definition: Definition, document_id: str
    ) -> list[RecordView]:
        return await sync_to_async(self._preview)(definition, document_id)

    def _documents(self) -> list[DocumentRef]:
        return [
            DocumentRef(id=file.source_ref, name=file.name)
            for file in self._run.files.order_by("name", "id")
        ]

    def _read(self, document_id: str) -> str:
        if not self._run.files.filter(source_ref=document_id).exists():
            raise ApiError("document_not_found")
        return documents.read_document(self._owner, document_id).text

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
            for found in extraction.list_extractions(self._owner, self._run.pk)
        ]

    def _preview(self, definition: Definition, document_id: str) -> list[RecordView]:
        text = self._read(document_id)
        found = extraction.preview_records(
            self._owner, self._run.pk, text, validate_draft(definition)
        )
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


def run_workspace(message: Message) -> OwnerWorkspace:
    """The workspace of the run ``message`` belongs to, read as the run's owner."""
    return workspace_of_run(message.run)


def workspace_of_run(run: Any) -> OwnerWorkspace:
    """The workspace of ``run``, read as its owner."""
    return OwnerWorkspace(run)
