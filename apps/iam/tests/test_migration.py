"""The data migration, run on a database that already has people."""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

pytestmark = pytest.mark.django_db(transaction=True)

BEFORE = [("iam", "0001_tenants_roles_audit"), ("identity", "0001_initial")]
AFTER = [("iam", "0002_default_tenant")]


def _migrate(targets: list[tuple[str, str]]) -> MigrationExecutor:
    executor = MigrationExecutor(connection)
    executor.migrate(targets)
    return MigrationExecutor(connection)


def test_every_existing_person_becomes_a_member_of_default_and_it_reverses() -> None:
    executor = _migrate(BEFORE)
    User = executor.loader.project_state(BEFORE).apps.get_model("identity", "User")
    ids = [User.objects.create(username=f"old{i}").pk for i in range(3)]

    executor = _migrate(AFTER)
    apps = executor.loader.project_state(AFTER).apps
    Tenant = apps.get_model("iam", "Tenant")
    Membership = apps.get_model("iam", "TenantMembership")
    default = Tenant.objects.get(is_default=True)
    assert default.name == "Default"
    rows = Membership.objects.filter(tenant=default)
    assert set(rows.values_list("user_id", flat=True)) == set(ids)
    assert set(rows.values_list("role", flat=True)) == {"member"}

    executor = _migrate(BEFORE)
    apps = executor.loader.project_state(BEFORE).apps
    assert not apps.get_model("iam", "Tenant").objects.exists()
    assert not apps.get_model("iam", "TenantMembership").objects.exists()

    _migrate(list(MigrationExecutor(connection).loader.graph.leaf_nodes()))
