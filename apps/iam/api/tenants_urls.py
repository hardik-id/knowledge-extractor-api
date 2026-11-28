"""Routes for tenants, a tenant's workspaces, platform admins and the audit list."""

from django.urls import path

from . import audit_views, platform_views, tenants_views

urlpatterns = [
    path("tenants", tenants_views.tenants_list, name="tenants-list"),
    path("tenants/<str:tenant_id>", tenants_views.tenant_detail, name="tenant-detail"),
    path(
        "tenants/<str:tenant_id>/workspaces",
        tenants_views.tenant_workspaces,
        name="tenant-workspaces",
    ),
    path("platform-admins", platform_views.platform_admins, name="platform-admins"),
    path(
        "platform-admins/<int:user_id>",
        platform_views.platform_admin_detail,
        name="platform-admin-detail",
    ),
    path("audit", audit_views.audit_list, name="audit-list"),
]
