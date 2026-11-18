import uuid
from typing import Any, Self

from django.conf import settings
from django.db import models


class BaseModel(models.Model):
    """Base of every model: a time-ordered UUID primary key and both timestamps."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class OwnedQuerySet(models.QuerySet["OwnedModel"]):
    def visible_to(self, user: Any) -> Self:
        """Only the rows ``user`` may see. The default: the rows they own."""
        return self.filter(owner=user)


class OwnedModel(BaseModel):
    """Base of things that belong to one person.

    ``Model.objects.visible_to(user)`` is the only way a selector starts a query.
    A model that is visible to more than its owner overrides ``visible_to`` on its
    own queryset and ``can_be_changed_by`` here. See docs/permissions.md.
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+"
    )

    objects = OwnedQuerySet.as_manager()

    class Meta:
        abstract = True

    def can_be_changed_by(self, user: Any) -> bool:
        return bool(self.owner_id == user.pk)
