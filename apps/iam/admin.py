from typing import Any

from django.contrib import admin

from .models import (
    AuditEntry,
    PlatformAdmin,
    Tenant,
    TenantMembership,
    WorkspaceMembership,
)


class ReadOnlyAdmin(admin.ModelAdmin):  # type: ignore[type-arg]  # generic only for stubs
    """Roles change through the iam services (audited, last-admin rules), not here."""

    def has_add_permission(self, request: Any) -> bool:
        return False

    def has_change_permission(self, request: Any, obj: Any = None) -> bool:
        return False

    def has_delete_permission(self, request: Any, obj: Any = None) -> bool:
        return False


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("name", "is_default", "created_at")

    def has_delete_permission(self, request: Any, obj: Any = None) -> bool:
        return not (obj and obj.is_default)


@admin.register(TenantMembership)
class TenantMembershipAdmin(ReadOnlyAdmin):
    list_display = ("tenant", "user", "role")
    list_filter = ("role",)


@admin.register(WorkspaceMembership)
class WorkspaceMembershipAdmin(ReadOnlyAdmin):
    list_display = ("workspace", "user", "role")
    list_filter = ("role",)


@admin.register(PlatformAdmin)
class PlatformAdminAdmin(ReadOnlyAdmin):
    list_display = ("user", "created_at")


@admin.register(AuditEntry)
class AuditEntryAdmin(ReadOnlyAdmin):
    list_display = (
        "created_at",
        "action",
        "actor",
        "target_user",
        "tenant",
        "old_role",
        "new_role",
    )
