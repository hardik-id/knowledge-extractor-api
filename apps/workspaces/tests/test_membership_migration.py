"""The tenant and membership migrations, on a database that already has workspaces."""

import uuid

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

pytestmark = pytest.mark.django_db(transaction=True)

BEFORE = [
    ("projects", "0002_rename_project_to_workspace"),
    ("iam", "0003_audit_identity"),
]
AFTER = [
    ("projects", "0004_workspace_tenant_required"),
    ("iam", "0004_workspace_membership"),
]


def migrate(targets: list[tuple[str, str]]) -> MigrationExecutor:
    executor = MigrationExecutor(connection)
    executor.migrate(targets)
    return MigrationExecutor(connection)


def test_existing_workspaces_go_to_default_and_their_owner_becomes_owner() -> None:
    executor = migrate(BEFORE)
    old = executor.loader.project_state(BEFORE).apps
    User = old.get_model("identity", "User")
    Tenant = old.get_model("iam", "Tenant")
    Tenant.objects.get_or_create(is_default=True, defaults={"name": "Default"})
    users = [
        User.objects.create(username=f"u{i}", oid=uuid.uuid4(), tid=uuid.uuid4())
        for i in range(2)
    ]
    made = {}
    for user in users:
        run = old.get_model("runs", "Run").objects.create(owner=user)
        made[user.pk] = old.get_model("projects", "Workspace").objects.create(
            owner=user, name=f"W {user.username}", run=run
        )
    try:
        executor = migrate(AFTER)
        new = executor.loader.project_state(AFTER).apps
        default = new.get_model("iam", "Tenant").objects.get(is_default=True)
        Membership = new.get_model("iam", "WorkspaceMembership")
        for owner_id, workspace in made.items():
            row = new.get_model("projects", "Workspace").objects.get(pk=workspace.pk)
            assert row.tenant_id == default.pk
            roles = Membership.objects.filter(workspace_id=workspace.pk)
            assert [(m.user_id, m.role) for m in roles] == [(owner_id, "owner")]
    finally:
        migrate(list(MigrationExecutor(connection).loader.graph.leaf_nodes()))
