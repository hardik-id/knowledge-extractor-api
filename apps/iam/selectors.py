"""Reads of who has which role. Other apps call these, never the models."""

from typing import Any
from uuid import UUID

from django.db.models.functions import Lower

from .models import PlatformAdmin, Tenant, TenantMembership
from .roles import TenantRole


def _active(user: Any) -> bool:
    return bool(user.is_authenticated and user.is_active)


def is_platform_admin(user: Any) -> bool:
    if not _active(user):
        return False
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


def tenants_of(user: Any) -> list[tuple[Tenant, TenantRole]]:
    """The tenants the person belongs to, each with their role, by name."""
    memberships = (
        TenantMembership.objects.filter(user=user)
        .select_related("tenant")
        .order_by(Lower("tenant__name"))
    )
    return [(m.tenant, TenantRole(m.role)) for m in memberships]


def default_tenant() -> Tenant:
    return Tenant.objects.get(is_default=True)
