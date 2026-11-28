from typing import Any

from django.conf import settings
from django.db import models
from django.db.models.functions import Lower

from apps.core.models import BaseModel

from .roles import TenantRole


class Tenant(BaseModel):
    """A team or a customer inside the application (not the Entra directory)."""

    name = models.CharField(max_length=120)
    is_default = models.BooleanField(default=False, db_default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(Lower("name"), name="iam_tenant_name_ci_unique"),
            models.UniqueConstraint(
                fields=["is_default"],
                condition=models.Q(is_default=True),
                name="iam_tenant_one_default",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class TenantMembership(BaseModel):
    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name="memberships"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="tenant_memberships",
    )
    role = models.CharField(
        max_length=16, choices=[(r.value, r.value) for r in TenantRole]
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "user"], name="iam_membership_tenant_user_unique"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} is {self.role} of {self.tenant_id}"


class PlatformAdmin(BaseModel):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="platform_admin",
    )

    def __str__(self) -> str:
        return f"platform admin {self.user_id}"


class AuditEntryQuerySet(models.QuerySet):  # type: ignore[type-arg]
    """Entries are only inserted: no update, no delete."""

    def update(self, **kwargs: Any) -> int:
        raise ValueError("An audit entry is never changed.")

    def delete(self) -> tuple[int, dict[str, int]]:
        raise ValueError("An audit entry is never deleted.")


class AuditEntry(BaseModel):
    """A change of a role. Only ever inserted; people and tenants may go, entries stay."""

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    action = models.CharField(max_length=64)
    target_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    tenant = models.ForeignKey(
        Tenant, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    workspace_id = models.UUIDField(null=True)
    # Who they were, kept when the person's row is gone (docs/iam.md, rule 7).
    actor_oid = models.UUIDField(null=True)
    actor_tid = models.UUIDField(null=True)
    target_oid = models.UUIDField(null=True)
    target_tid = models.UUIDField(null=True)
    old_role = models.CharField(max_length=32, blank=True, default="", db_default="")
    new_role = models.CharField(max_length=32, blank=True, default="", db_default="")

    objects = AuditEntryQuerySet.as_manager()

    class Meta:
        verbose_name_plural = "audit entries"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise ValueError("An audit entry is never changed.")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        raise ValueError("An audit entry is never deleted.")

    def __str__(self) -> str:
        return f"{self.action} at {self.created_at}"
