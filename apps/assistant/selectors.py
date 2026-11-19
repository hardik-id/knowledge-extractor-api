"""Reads for the assistant app.

A selector takes the acting user and returns only what that user may see.
"""

from typing import Any

from asgiref.sync import sync_to_async

from apps.assistant.agents.base import DocumentRef
from apps.assistant.models import Message
from apps.core.errors import ApiError
from apps.documents import selectors as documents
from apps.identity.models import User
from apps.runs import selectors as runs


def list_messages(user: User, run_id: Any) -> list[Message]:
    """The conversation of ``user``'s run, oldest first. Someone else's run is a 404."""
    run = runs.get_run(user, run_id)
    return list(Message.objects.filter(run_id=run.pk))


class OwnerDocuments:
    """The documents of a run, as an agent may read them: as the run's owner.

    Only the run's own files can be read; anything else is ``document_not_found``,
    as is a document the owner may no longer open.
    """

    def __init__(self, owner: User, refs: list[DocumentRef]) -> None:
        self._owner = owner
        self._refs = refs

    async def list(self) -> list[DocumentRef]:
        return list(self._refs)

    async def read(self, document_id: str) -> str:
        if not any(ref.id == document_id for ref in self._refs):
            raise ApiError("document_not_found")
        found = await sync_to_async(documents.read_document)(self._owner, document_id)
        return found.text


def run_documents(message: Message) -> OwnerDocuments:
    """The documents of the run ``message`` belongs to, read as the run's owner."""
    return documents_of_run(message.run)


def documents_of_run(run: Any) -> OwnerDocuments:
    """The documents of ``run``, read as its owner."""
    refs = [
        DocumentRef(id=file.source_ref, name=file.name)
        for file in run.files.order_by("name", "id")
    ]
    return OwnerDocuments(run.owner, refs)
