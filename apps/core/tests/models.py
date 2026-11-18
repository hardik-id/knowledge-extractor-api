from typing import Any, Self

from django.db import models
from django.db.models import Q

from apps.core.models import BaseModel, OwnedModel, OwnedQuerySet


class Note(BaseModel):
    text = models.CharField(max_length=100)


class SharedNoteQuerySet(OwnedQuerySet):
    def visible_to(self, user: Any) -> Self:
        return self.filter(Q(owner=user) | Q(shared=True))


class SharedNote(OwnedModel):
    """Visible to everyone when ``shared``, changeable only by its owner."""

    text = models.CharField(max_length=100)
    shared = models.BooleanField(default=False)

    objects = SharedNoteQuerySet.as_manager()  # type: ignore[misc]
