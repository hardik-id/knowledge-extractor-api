import uuid
from datetime import UTC, datetime

import pytest

from apps.core.models import BaseModel
from apps.core.tests.models import Note

pytestmark = pytest.mark.django_db


def test_model_is_abstract() -> None:
    assert BaseModel._meta.abstract


def test_extending_model_gets_a_uuid7_id_and_both_timestamps() -> None:
    note = Note.objects.create(text="a")
    note.refresh_from_db()
    assert isinstance(note.id, uuid.UUID)
    assert note.id.version == 7
    assert note.created_at.tzinfo is not None
    assert abs(datetime.now(UTC) - note.created_at).total_seconds() < 60
    assert note.updated_at >= note.created_at


def test_updated_at_moves_on_save_and_created_at_does_not() -> None:
    note = Note.objects.create(text="a")
    created, updated = note.created_at, note.updated_at
    note.text = "b"
    note.save()
    assert note.created_at == created
    assert note.updated_at > updated


def test_ids_are_time_ordered() -> None:
    ids = [Note.objects.create(text=str(i)).id for i in range(20)]
    assert ids == sorted(ids)
