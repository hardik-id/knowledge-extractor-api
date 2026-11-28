from typing import Any

from django.contrib import admin

from .models import AuditEntry, PlatformAdmin, Tenant, TenantMembership


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):  # type: ignore[type-arg]  # generic only for stubs
    list_display = ("name", "is_default", "created_at")


@admin.register(TenantMembership)
class TenantMembershipAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("tenant", "user", "role")
    list_filter = ("role",)


@admin.register(PlatformAdmin)
class PlatformAdminAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = ("user", "created_at")


@admin.register(AuditEntry)
class AuditEntryAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    list_display = (
        "created_at",
        "action",
        "actor",
        "target_user",
        "tenant",
        "old_role",
        "new_role",
    )

    def has_add_permission(self, request: Any) -> bool:
        return False

    def has_change_permission(self, request: Any, obj: Any = None) -> bool:
        return False

    def has_delete_permission(self, request: Any, obj: Any = None) -> bool:
        return False
