from apps.iam.roles import (
    PERMISSIONS,
    Permission,
    PlatformAdminRole,
    TenantRole,
    WorkspaceRole,
    permissions_of,
)

# The table of #483, written out again on purpose: a change to a role shows here.
EXPECTED = {
    "platform_admin": {
        "tenants.manage",
        "users.list",
        "status.test",
        "tenant.members.manage",
        "tenant.workspaces.list",
        "tenant.members.list",
        "workspace.members.manage",
    },
    "admin": {
        "tenant.members.manage",
        "tenant.workspaces.list",
        "tenant.members.list",
        "workspaces.create",
        "workspace.members.manage",
    },
    "member": {"tenant.members.list", "workspaces.create"},
    "owner": {
        "workspace.members.manage",
        "workspace.manage",
        "workspace.run",
        "workspace.edit",
        "workspace.view",
    },
    "editor": {"workspace.run", "workspace.edit", "workspace.view"},
    "viewer": {"workspace.view"},
}


def test_the_whole_permission_table_is_pinned() -> None:
    actual = {str(role): {str(p) for p in perms} for role, perms in PERMISSIONS.items()}
    assert actual == EXPECTED


def test_every_role_has_an_entry_and_every_permission_is_used() -> None:
    roles = [*PlatformAdminRole, *TenantRole, *WorkspaceRole]
    assert set(PERMISSIONS) == set(roles)
    assert set().union(*PERMISSIONS.values()) == set(Permission)
    assert permissions_of(WorkspaceRole.VIEWER) == {Permission.WORKSPACE_VIEW}
