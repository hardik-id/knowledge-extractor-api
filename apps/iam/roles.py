"""Who may do what: the fixed roles and the one table of their permissions.

No database access here. The table is `docs/iam.md` in code; a test pins it.
"""

from enum import StrEnum


class Permission(StrEnum):
    TENANTS_MANAGE = "tenants.manage"
    USERS_LIST = "users.list"
    STATUS_TEST = "status.test"
    TENANT_MEMBERS_MANAGE = "tenant.members.manage"
    TENANT_WORKSPACES_LIST = "tenant.workspaces.list"
    TENANT_MEMBERS_LIST = "tenant.members.list"
    WORKSPACES_CREATE = "workspaces.create"
    WORKSPACE_MEMBERS_MANAGE = "workspace.members.manage"
    WORKSPACE_MANAGE = "workspace.manage"
    WORKSPACE_RUN = "workspace.run"
    WORKSPACE_EDIT = "workspace.edit"
    WORKSPACE_VIEW = "workspace.view"


class TenantRole(StrEnum):
    ADMIN = "admin"
    MEMBER = "member"


class WorkspaceRole(StrEnum):
    OWNER = "owner"
    EDITOR = "editor"
    VIEWER = "viewer"


class PlatformAdminRole(StrEnum):
    PLATFORM_ADMIN = "platform_admin"


P = Permission

PERMISSIONS: dict[
    PlatformAdminRole | TenantRole | WorkspaceRole, frozenset[Permission]
] = {
    PlatformAdminRole.PLATFORM_ADMIN: frozenset(
        {
            P.TENANTS_MANAGE,
            P.USERS_LIST,
            P.STATUS_TEST,
            P.TENANT_MEMBERS_MANAGE,
            P.TENANT_WORKSPACES_LIST,
            P.TENANT_MEMBERS_LIST,
            P.WORKSPACE_MEMBERS_MANAGE,
        }
    ),
    TenantRole.ADMIN: frozenset(
        {
            P.TENANT_MEMBERS_MANAGE,
            P.TENANT_WORKSPACES_LIST,
            P.TENANT_MEMBERS_LIST,
            P.WORKSPACES_CREATE,
            P.WORKSPACE_MEMBERS_MANAGE,
        }
    ),
    TenantRole.MEMBER: frozenset({P.TENANT_MEMBERS_LIST, P.WORKSPACES_CREATE}),
    WorkspaceRole.OWNER: frozenset(
        {
            P.WORKSPACE_MEMBERS_MANAGE,
            P.WORKSPACE_MANAGE,
            P.WORKSPACE_RUN,
            P.WORKSPACE_EDIT,
            P.WORKSPACE_VIEW,
        }
    ),
    WorkspaceRole.EDITOR: frozenset(
        {P.WORKSPACE_RUN, P.WORKSPACE_EDIT, P.WORKSPACE_VIEW}
    ),
    WorkspaceRole.VIEWER: frozenset({P.WORKSPACE_VIEW}),
}


def permissions_of(
    role: PlatformAdminRole | TenantRole | WorkspaceRole,
) -> frozenset[Permission]:
    return PERMISSIONS[role]
