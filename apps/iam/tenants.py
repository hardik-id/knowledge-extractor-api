"""Tenants, platform admins and the audit list: the services and reads of #492.

Services take the acting person first and run in one transaction with their audit
entry (``audit.record``), like ``services.py``. Platform admins are granted and
revoked by ``services.grant_platform_admin`` and ``revoke_platform_admin``; this
module only adds what the routes need around them.
"""

from typing import Any
from uuid import UUID

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import Count, OuterRef, Q, QuerySet, Subquery
from django.db.models.deletion import ProtectedError
from django.db.models.functions import Coalesce, Lower

from apps.core.errors import ApiError
from apps.workspaces.models import Workspace

from . import audit, services
from .models import AuditEntry, Tenant, TenantMembership
from .roles import Permission, TenantRole
from .selectors import get_tenant, is_platform_admin, tenants_of

# --- tenants -------------------------------------------------------------------


def list_tenants(user: Any) -> list[tuple[Tenant, TenantRole | None, bool]]:
    """Each tenant with the person's role in it and whether to show its counts.

    A platform admin gets every tenant, with ``member_count`` and
    ``workspace_count`` annotated; anyone else gets the tenants they belong to.
    """
    if is_platform_admin(user):
        members = (
            TenantMembership.objects.filter(tenant=OuterRef("pk"))
            .order_by()
            .values("tenant")
            .annotate(n=Count("pk"))
            .values("n")
        )
        workspaces = (
            Workspace.objects.filter(tenant=OuterRef("pk"))
            .order_by()
            .values("tenant")
            .annotate(n=Count("pk"))
            .values("n")
        )
        tenants = Tenant.objects.annotate(
            member_count=Coalesce(Subquery(members), 0),
            workspace_count=Coalesce(Subquery(workspaces), 0),
        ).order_by(Lower("name"))
        roles = dict(
            TenantMembership.objects.filter(user=user).values_list("tenant_id", "role")
        )
        return [
            (t, TenantRole(roles[t.pk]) if t.pk in roles else None, True)
            for t in tenants
        ]
    return [(tenant, role, False) for tenant, role in tenants_of(user)]


def create_tenant(actor: Any, name: str) -> Tenant:
    """Make a tenant (``tenants.manage``). A name taken, ignoring case, is 409."""
    _require_manage(actor)
    with transaction.atomic():
        _require_free_name(name)
        try:
            with transaction.atomic():
                tenant = Tenant.objects.create(name=name)
        except IntegrityError:  # a request at the same moment took the name
            raise ApiError("tenant_name_taken") from None
        audit.record(
            actor=actor, action="tenant.create", tenant=tenant, detail=f"name={name}"
        )
        return tenant


def rename_tenant(actor: Any, tenant_id: UUID | str, name: str) -> Tenant:
    _require_manage(actor)
    with transaction.atomic():
        tenant = _locked(actor, tenant_id)
        if tenant.name == name:
            return tenant
        _require_free_name(name, besides=tenant)
        old_name = tenant.name
        tenant.name = name
        try:
            with transaction.atomic():
                tenant.save(update_fields=["name", "updated_at"])
        except IntegrityError:
            raise ApiError("tenant_name_taken") from None
        audit.record(
            actor=actor,
            action="tenant.rename",
            tenant=tenant,
            detail=f"from={old_name}; to={name}",
        )
        return tenant


def delete_tenant(actor: Any, tenant_id: UUID | str) -> None:
    """Delete a tenant that has no workspaces, and is not the default one."""
    _require_manage(actor)
    with transaction.atomic():
        tenant = _locked(actor, tenant_id)
        if tenant.is_default:
            raise ApiError("default_tenant")
        if tenant.workspaces.exists():
            raise ApiError("tenant_not_empty")
        # Recorded first. The delete clears the tenant link of every entry, so each
        # entry also keeps the tenant id (tenant_ref) and the delete keeps the name.
        for m in tenant.memberships.select_related("user"):
            audit.record(
                actor=actor,
                action="tenant.member.remove",
                target_user=m.user,
                tenant=tenant,
                old_role=m.role,
            )
        audit.record(
            actor=actor,
            action="tenant.delete",
            tenant=tenant,
            detail=f"name={tenant.name}",
        )
        try:
            with transaction.atomic():
                tenant.delete()
        except (
            ProtectedError,
            IntegrityError,
        ):  # a workspace was made at the same moment
            raise ApiError("tenant_not_empty") from None


def _require_manage(actor: Any) -> None:
    if not is_platform_admin(actor):
        raise ApiError("forbidden")


def _locked(actor: Any, tenant_id: UUID | str) -> Tenant:
    tenant = get_tenant(actor, tenant_id, Permission.TENANTS_MANAGE)
    return Tenant.objects.select_for_update().get(pk=tenant.pk)


def _require_free_name(name: str, besides: Tenant | None = None) -> None:
    taken = Tenant.objects.filter(name__iexact=name)
    if besides is not None:
        taken = taken.exclude(pk=besides.pk)
    if taken.exists():
        raise ApiError("tenant_name_taken")


# --- platform admins -----------------------------------------------------------


def list_platform_admins() -> list[tuple[Any, str]]:
    """Every active platform admin who has signed in, with ``"setting"`` or ``"row"``.

    A person listed in IAM_PLATFORM_ADMIN_OIDS is ``"setting"`` even when they
    also have a row. A listed person who never signed in has no row to show.
    """
    listed = set(settings.IAM_PLATFORM_ADMIN_OIDS)
    users = (
        get_user_model()
        .objects.filter(is_active=True)
        .filter(Q(oid__in=listed) | Q(platform_admin__isnull=False))
        .order_by("pk")
    )
    return [(u, "setting" if u.oid in listed else "row") for u in users]


def platform_admin_item(user_id: int) -> tuple[Any, str]:
    user = _user(user_id)
    return user, ("setting" if _listed(user) else "row")


def add_platform_admin(actor: Any, user_id: int) -> None:
    services.grant_platform_admin(actor, user_id)


def remove_platform_admin(actor: Any, user_id: int) -> None:
    """Take the row away. A person who is an admin through the setting stays: 409."""
    target = _user(user_id)
    if is_platform_admin(actor) and _listed(target):
        raise ApiError("platform_admin_by_setting")
    services.revoke_platform_admin(actor, user_id)


def _listed(user: Any) -> bool:
    return user.oid is not None and user.oid in settings.IAM_PLATFORM_ADMIN_OIDS


def _user(user_id: int) -> Any:
    user = get_user_model().objects.filter(pk=user_id).first()
    if user is None:
        raise ApiError("user_not_found")
    return user


# --- the audit list ------------------------------------------------------------


def list_audit(user: Any, tenant_id: UUID | str | None) -> QuerySet[AuditEntry]:
    """The entries the person may read, with the people loaded (newest first by id).

    With a tenant: its entries, for someone who manages its members (404 for a
    tenant they do not see, 403 for one they see without that right). Without:
    a platform admin gets everything, a tenant admin the entries of the tenants they
    administer, anyone else 403.
    """
    entries = AuditEntry.objects.select_related("actor", "target_user")
    if tenant_id is not None:
        tenant = get_tenant(user, tenant_id, Permission.TENANT_MEMBERS_MANAGE)
        return entries.filter(Q(tenant=tenant) | Q(tenant_ref=tenant.pk))
    if is_platform_admin(user):
        return entries.all()
    administered = TenantMembership.objects.filter(
        user=user, role=TenantRole.ADMIN
    ).values("tenant_id")
    if not administered:
        raise ApiError("forbidden")
    return entries.filter(
        Q(tenant_id__in=administered) | Q(tenant_ref__in=administered)
    )
