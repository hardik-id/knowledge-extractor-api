"""Reads of who has which role. Other apps call these, never the models."""

from typing import Any
from uuid import UUID

from .models import PlatformAdmin, Tenant, TenantMembership
from .roles import TenantRole


def is_platform_admin(user: Any) -> bool:
    return PlatformAdmin.objects.filter(user=user).exists()


def tenant_role(user: Any, tenant_id: UUID | str) -> TenantRole | None:
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
        .order_by("tenant__name")
    )
    return [(m.tenant, TenantRole(m.role)) for m in memberships]


def default_tenant() -> Tenant:
    return Tenant.objects.get(is_default=True)
