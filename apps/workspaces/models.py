from typing import Any, Self

from django.db import models

from apps.core.models import OwnedModel, OwnedQuerySet


class WorkspaceQuerySet(OwnedQuerySet):
    def visible_to(self, user: Any) -> Self:
        """The workspaces the person has a role in. ``owner`` is who made it, not access."""
        return self.filter(memberships__user=user)


class Workspace(OwnedModel):
    """A name on one run: its documents, configuration, conversation and records.

    ``updated_at`` is when the workspace itself changed. The last activity, which
    includes the run's work, is worked out by ``selectors``.
    """

    name = models.CharField(max_length=120)
    description = models.TextField(blank=True, default="")
    run = models.OneToOneField(
        "runs.Run", on_delete=models.PROTECT, related_name="workspace"
    )

    tenant = models.ForeignKey(
        "iam.Tenant", on_delete=models.PROTECT, related_name="workspaces"
    )

    objects = WorkspaceQuerySet.as_manager()  # type: ignore[misc]

    class Meta:
        db_table = "workspaces_workspace"
