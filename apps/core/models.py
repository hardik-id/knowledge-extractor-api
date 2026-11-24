import uuid
from typing import Any, Self

from django.conf import settings
from django.db import models
from django.db.models.functions import Now


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


class ModelCall(BaseModel):
    """The outcome of the last real model call of one part (``assistant`` or ``extraction``).

    One row per part, upserted by ``apps.core.status``. ``problem`` is a short code
    (``auth_failed``, ``timeout``, ...), empty when the call worked. Never a message.
    """

    part = models.CharField(max_length=32, unique=True)
    problem = models.CharField(max_length=32, blank=True, default="", db_default="")
    checked_at = models.DateTimeField(db_default=Now())

    class Meta:
        db_table = "core_model_call"

    def __str__(self) -> str:
        return f"{self.part}: {self.problem or 'ok'}"


class StatusTestClaim(BaseModel):
    """The single row that limits ``POST /status/test`` to one real test per minute.

    ``claimed_at`` is the start of the last test. A request takes the claim with one
    conditional UPDATE, so the limit holds across processes and concurrent requests.
    """

    key = models.CharField(
        max_length=16, unique=True, default="status", db_default="status"
    )
    claimed_at = models.DateTimeField(null=True)

    class Meta:
        db_table = "core_status_test_claim"

    def __str__(self) -> str:
        return f"{self.key}: {self.claimed_at}"
