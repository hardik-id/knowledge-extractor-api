"""Reads of who has which role. Other apps call these, never the models."""

from typing import Any
from uuid import UUID

from django.conf import settings
from django.db.models.functions import Lower

from apps.core.errors import ApiError

from .models import PlatformAdmin, Tenant, TenantMembership, WorkspaceMembership
from .roles import (
    Permission,
    PlatformAdminRole,
    TenantRole,
    WorkspaceRole,
    permissions_of,
)


def _active(user: Any) -> bool:
    return bool(user.is_authenticated and user.is_active)


def is_platform_admin(user: Any) -> bool:
    """True for a listed ``oid`` (IAM_PLATFORM_ADMIN_OIDS) or a ``PlatformAdmin`` row."""
    if not _active(user):
        return False
    if user.oid is not None and user.oid in settings.IAM_PLATFORM_ADMIN_OIDS:
        return True
    return PlatformAdmin.objects.filter(user=user).exists()


def tenant_role(user: Any, tenant_id: UUID | str) -> TenantRole | None:
    if not _active(user):
        return None
    try:
        tenant_id = UUID(str(tenant_id))
    except ValueError:
        return None
    role = (
        TenantMembership.objects.filter(user=user, tenant_id=tenant_id)
        .values_list("role", flat=True)
        .first()
    )
    return TenantRole(role) if role else None


def tenant_permissions(user: Any, tenant_id: UUID | str) -> frozenset[Permission]:
    """What the person may do in the tenant: by their role in it, and as a platform admin.

    Empty means the tenant is not theirs to see. A platform admin sees every tenant.
    """
    held: set[Permission] = set()
    role = tenant_role(user, tenant_id)
    if role is not None:
        held |= permissions_of(role)
    if is_platform_admin(user):
        held |= permissions_of(PlatformAdminRole.PLATFORM_ADMIN)
    return frozenset(held)


def get_tenant(user: Any, tenant_id: UUID | str, permission: Permission) -> Tenant:
    """The tenant, if ``user`` sees it and has ``permission`` in it.

    A tenant not seen and an unknown id are both 404 ``tenant_not_found``; a tenant
    seen without ``permission`` is 403 ``forbidden``. Every request that names a
    tenant fetches it here, with the permission of what it does.
    """
    held = tenant_permissions(user, tenant_id)
    try:
        tenant = Tenant.objects.filter(pk=UUID(str(tenant_id))).first()
    except ValueError:
        tenant = None
    if tenant is None or not held:
        raise ApiError("tenant_not_found")
    if permission not in held:
        raise ApiError("forbidden")
    return tenant


def tenant_of_workspace(workspace_id: UUID | str) -> Tenant | None:
    """The tenant a workspace belongs to, or None for an unknown id."""
    try:
        workspace_id = UUID(str(workspace_id))
    except ValueError:
        return None
    return Tenant.objects.filter(workspaces__pk=workspace_id).first()


def tenants_of(user: Any) -> list[tuple[Tenant, TenantRole]]:
    """The tenants the person belongs to, each with their role, by name."""
    memberships = (
        TenantMembership.objects.filter(user=user)
        .select_related("tenant")
        .order_by(Lower("tenant__name"))
    )
    return [(m.tenant, TenantRole(m.role)) for m in memberships]


def may_create_workspaces(user: Any) -> bool:
    """True when the person holds, in some tenant, a role with ``workspaces.create``.

    The same right makes a run with no workspace (``POST /runs``) and keeps it usable.
    """
    if not _active(user):
        return False
    return any(
        Permission.WORKSPACES_CREATE in permissions_of(role)
        for _, role in tenants_of(user)
    )


def default_tenant() -> Tenant:
    return Tenant.objects.get(is_default=True)


def workspace_role(user: Any, workspace_id: UUID | str) -> WorkspaceRole | None:
    """The person's role in the workspace, or None when they have none."""
    if not _active(user):
        return None
    try:
        workspace_id = UUID(str(workspace_id))
    except ValueError:
        return None
    role = (
        WorkspaceMembership.objects.filter(user=user, workspace_id=workspace_id)
        .values_list("role", flat=True)
        .first()
    )
    return WorkspaceRole(role) if role else None


def workspace_permissions(user: Any, workspace_id: UUID | str) -> list[Permission]:
    """The person's permissions in the workspace, sorted by name.

    Empty without a role in it. An admin of the workspace's tenant and a platform admin
    who have a role also hold ``workspace.members.manage`` (they hold it without one).
    """
    role = workspace_role(user, workspace_id)
    if role is None:
        return []
    held = set(permissions_of(role))
    if Permission.WORKSPACE_MEMBERS_MANAGE not in held:
        tenant = tenant_of_workspace(workspace_id)
        if (
            tenant is not None
            and Permission.WORKSPACE_MEMBERS_MANAGE
            in tenant_permissions(user, tenant.pk)
        ):
            held.add(Permission.WORKSPACE_MEMBERS_MANAGE)
    return sorted(held)
