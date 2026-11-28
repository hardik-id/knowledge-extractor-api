"""Who may start a workspace where, and the owner role of the one that was started.

Kept apart from ``services`` (which holds the granting of roles). Called by the
workspaces app inside the transaction that creates the workspace.
"""

from typing import Any
from uuid import UUID

from django.db import transaction

from apps.core.errors import ApiError

from . import audit
from .models import Tenant, WorkspaceMembership
from .roles import Permission, WorkspaceRole, permissions_of
from .selectors import tenants_of


def tenant_for_new_workspace(user: Any, tenant_id: UUID | str | None) -> Tenant:
    """The tenant a new workspace goes to.

    Without ``tenant_id`` the person's only tenant (422 when they are in several,
    403 when they are in none). A tenant the person is not in is 404 ``tenant_not_found``.
    """
    tenants = tenants_of(user)
    if tenant_id is None:
        if not tenants:
            raise ApiError("forbidden")
        if len(tenants) > 1:
            raise ApiError(
                "validation_error",
                details={"tenant_id": ["Say which tenant the workspace is for."]},
            )
        tenant, role = tenants[0]
    else:
        wanted = str(tenant_id)
        found = [(t, r) for t, r in tenants if str(t.pk) == wanted]
        if not found:
            raise ApiError("tenant_not_found")
        tenant, role = found[0]
    if Permission.WORKSPACES_CREATE not in permissions_of(role):
        raise ApiError("forbidden")
    return tenant


@transaction.atomic
def make_owner(user: Any, workspace_id: UUID, tenant: Tenant) -> WorkspaceMembership:
    """The creator of a new workspace is its owner. Recorded in the audit.

    Takes the tenant lock that removing a member takes and checks the creator is
    still allowed to create there, so a person being removed cannot keep a workspace
    made during the removal.
    """
    Tenant.objects.select_for_update().get(pk=tenant.pk)
    tenant_for_new_workspace(user, tenant.pk)
    membership = WorkspaceMembership.objects.create(
        workspace_id=workspace_id, user=user, role=WorkspaceRole.OWNER
    )
    audit.record(
        actor=user,
        action="workspace.role.set",
        target_user=user,
        workspace_id=workspace_id,
        tenant=tenant,
        new_role=WorkspaceRole.OWNER,
    )
    return membership
