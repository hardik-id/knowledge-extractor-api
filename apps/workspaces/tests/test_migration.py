"""The rename keeps the rows: a project made before it is a workspace after it."""

import uuid

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

pytestmark = pytest.mark.django_db(transaction=True)

BEFORE = [("projects", "0001_initial")]
AFTER = [("projects", "0002_rename_project_to_workspace")]


def migrate(targets: list[tuple[str, str]]) -> MigrationExecutor:
    executor = MigrationExecutor(connection)
    executor.migrate(targets)
    return MigrationExecutor(connection)


def test_a_project_made_before_the_rename_is_read_back_as_a_workspace() -> None:
    executor = migrate(BEFORE)
    old = executor.loader.project_state(BEFORE).apps
    user = old.get_model("identity", "User").objects.create(
        username="before", oid=uuid.uuid4(), tid=uuid.uuid4()
    )
    run = old.get_model("runs", "Run").objects.create(owner=user)
    project = old.get_model("projects", "Project").objects.create(
        owner=user, name="Made before", description="d", run=run
    )
    try:
        executor = migrate(AFTER)
        new = executor.loader.project_state(AFTER).apps
        workspace = new.get_model("projects", "Workspace").objects.get(pk=project.pk)
        assert (workspace.name, workspace.description, workspace.run_id) == (
            "Made before",
            "d",
            run.pk,
        )
        assert new.get_model("projects", "Workspace")._meta.db_table == (
            "workspaces_workspace"
        )
        assert "workspaces_workspace" in connection.introspection.table_names()
        assert "projects_project" not in connection.introspection.table_names()
    finally:
        migrate(list(MigrationExecutor(connection).loader.graph.leaf_nodes()))


def test_the_rename_can_be_reversed() -> None:
    migrate(AFTER)
    try:
        migrate(BEFORE)
        tables = connection.introspection.table_names()
        assert "projects_project" in tables
        assert "workspaces_workspace" not in tables
    finally:
        migrate(list(MigrationExecutor(connection).loader.graph.leaf_nodes()))
