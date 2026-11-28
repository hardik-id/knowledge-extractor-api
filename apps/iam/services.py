"""Granting and removing roles, with the rules of docs/iam.md enforced and recorded.

Every function takes the acting person first and runs in one transaction with its
audit entry (``audit.record``), so a refused change leaves nothing behind. ``actor``
is None for an operator command: no permission is checked and the entry has no actor.
The rows a rule counts are locked first, so two requests at the same moment cannot
both pass a "last one" rule.
"""

from typing import Any
from uuid import UUID

import structlog
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import connection, transaction

from apps.core.errors import ApiError

from . import audit
from .models import PlatformAdmin, Tenant, TenantMembership
from .roles import Permission, PlatformAdminRole, TenantRole
from .selectors import is_platform_admin, tenant_permissions

log = structlog.get_logger(__name__)

# One lock for every change of who is a platform admin (there is no parent row).
_PLATFORM_ADMIN_LOCK = 483_486


def set_tenant_role(
    actor: Any | None, tenant_id: UUID, user_id: int, role: TenantRole | str
) -> TenantMembership:
    """Make the person ``role`` in the tenant, adding them when they are not a member."""
    role = TenantRole(role)
    with transaction.atomic():
        tenant = _locked_tenant(actor, tenant_id)
        target = _user(user_id)
        membership = TenantMembership.objects.filter(tenant=tenant, user=target).first()
        old = TenantRole(membership.role) if membership else None
        if membership is not None and old == role:
            return membership
        if old == TenantRole.ADMIN:
            _keep_an_admin(actor, tenant, target)
        if membership is None:
            membership = TenantMembership.objects.create(
                tenant=tenant, user=target, role=role
            )
        else:
            membership.role = role
            membership.save(update_fields=["role", "updated_at"])
        audit.record(
            actor=actor,
            action="tenant.role.set",
            target_user=target,
            tenant=tenant,
            old_role=old or "",
            new_role=role,
        )
        return membership


def remove_tenant_member(actor: Any | None, tenant_id: UUID, user_id: int) -> None:
    """Take the person out of the tenant. Not a member: answers ``user_not_found``."""
    with transaction.atomic():
        tenant = _locked_tenant(actor, tenant_id)
        target = _user(user_id)
        membership = TenantMembership.objects.filter(tenant=tenant, user=target).first()
        if membership is None:
            raise ApiError("user_not_found")
        if membership.role == TenantRole.ADMIN:
            _keep_an_admin(actor, tenant, target)
        old = membership.role
        membership.delete()
        audit.record(
            actor=actor,
            action="tenant.member.remove",
            target_user=target,
            tenant=tenant,
            old_role=old,
        )


def grant_platform_admin(actor: Any | None, user_id: int) -> None:
    """Make the person a platform admin. Already one: nothing changes, nothing is recorded."""
    with transaction.atomic():
        _lock_platform_admins()
        _require_platform_admin(actor)
        target = _user(user_id)
        # A row may exist for a deactivated person, who is not an admin while inactive.
        if (
            is_platform_admin(target)
            or PlatformAdmin.objects.filter(user=target).exists()
        ):
            return
        PlatformAdmin.objects.create(user=target)
        audit.record(
            actor=actor,
            action="platform_admin.grant",
            target_user=target,
            new_role=PlatformAdminRole.PLATFORM_ADMIN,
        )


def revoke_platform_admin(actor: Any | None, user_id: int) -> None:
    """Take the platform admin row away. The last platform admin stays (409).

    A person listed in IAM_PLATFORM_ADMIN_OIDS has no row, so there is nothing to
    take away: change the setting instead.
    """
    with transaction.atomic():
        _lock_platform_admins()
        _require_platform_admin(actor)
        target = _user(user_id)
        row = PlatformAdmin.objects.filter(user=target).first()
        if row is None:
            return
        listed = settings.IAM_PLATFORM_ADMIN_OIDS
        remaining = set(
            PlatformAdmin.objects.exclude(pk=row.pk)
            .filter(user__is_active=True)
            .values_list("user_id", flat=True)
        ) | set(
            get_user_model()
            .objects.filter(oid__in=listed, is_active=True)
            .values_list("pk", flat=True)
        )
        if not remaining:
            raise ApiError("last_platform_admin")
        row.delete()
        audit.record(
            actor=actor,
            action="platform_admin.revoke",
            target_user=target,
            old_role=PlatformAdminRole.PLATFORM_ADMIN,
        )


def join_default_tenant(user: Any) -> None:
    """First sign-in: the person gets IAM_DEFAULT_TENANT_ROLE of the default tenant.

    Called by ``apps.identity`` inside the transaction that creates the user, and
    only then: a later sign-in never adds a membership back.
    """
    role = settings.IAM_DEFAULT_TENANT_ROLE
    if not role:
        return
    tenant = Tenant.objects.filter(is_default=True).first()
    if tenant is None:  # the migration makes it; do not stop a sign-in over this
        log.warning("iam.default_tenant_missing")
        return
    TenantMembership.objects.create(tenant=tenant, user=user, role=role)
    audit.record(
        actor=None,
        action="tenant.role.set",
        target_user=user,
        tenant=tenant,
        new_role=role,
    )


def _locked_tenant(actor: Any | None, tenant_id: UUID) -> Tenant:
    """The tenant, locked, after checking the actor may manage its members.

    A tenant the actor may not see is ``tenant_not_found``; one they see but may
    not change is ``forbidden``. Locking the row makes every change of one tenant's
    members run one after the other.
    """
    tenant = Tenant.objects.select_for_update().filter(pk=tenant_id).first()
    if tenant is None:
        raise ApiError("tenant_not_found")
    if actor is not None:
        held = tenant_permissions(actor, tenant.pk)
        if not held:
            raise ApiError("tenant_not_found")
        if Permission.TENANT_MEMBERS_MANAGE not in held:
            raise ApiError("forbidden")
    return tenant


def _keep_an_admin(actor: Any | None, tenant: Tenant, leaving: Any) -> None:
    """Rule 4: a tenant keeps one admin, unless a platform admin (or an operator) acts."""
    if actor is None or is_platform_admin(actor):
        return
    others = (
        TenantMembership.objects.filter(tenant=tenant, role=TenantRole.ADMIN)
        .exclude(user=leaving)
        .filter(user__is_active=True)
        .exists()
    )
    if not others:
        raise ApiError("last_tenant_admin")


def _require_platform_admin(actor: Any | None) -> None:
    """``tenants.manage`` is the platform admin's alone."""
    if actor is not None and not is_platform_admin(actor):
        raise ApiError("forbidden")


def _lock_platform_admins() -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [_PLATFORM_ADMIN_LOCK])


def _user(user_id: int) -> Any:
    user = get_user_model().objects.filter(pk=user_id).first()
    if user is None:
        raise ApiError("user_not_found")
    return user
