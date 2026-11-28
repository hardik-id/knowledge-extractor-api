import uuid

import pytest
from structlog.testing import capture_logs

from apps.iam import audit
from apps.iam.models import AuditEntry
from apps.iam.tests.factories import TenantFactory
from apps.identity.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_record_keeps_who_they_were_after_the_people_are_deleted() -> None:
    actor = UserFactory(oid=uuid.uuid4(), tid=uuid.uuid4())
    target = UserFactory(oid=uuid.uuid4(), tid=uuid.uuid4())
    actor_oid, target_oid, target_tid = actor.oid, target.oid, target.tid
    tenant = TenantFactory()

    entry = audit.record(
        actor=actor,
        action="tenant.role.set",
        target_user=target,
        tenant=tenant,
        old_role="member",
        new_role="admin",
    )
    actor.delete()
    target.delete()

    entry = AuditEntry.objects.get(pk=entry.pk)
    assert entry.actor is None and entry.target_user is None
    assert entry.actor_oid == actor_oid
    assert (entry.target_oid, entry.target_tid) == (target_oid, target_tid)
    assert (entry.old_role, entry.new_role) == ("member", "admin")


def test_record_without_an_actor_is_a_command_or_a_migration() -> None:
    target = UserFactory()
    entry = audit.record(actor=None, action="platform_admin.grant", target_user=target)
    assert entry.actor is None and entry.actor_oid is None


def test_record_logs_ids_and_roles_and_no_names() -> None:
    actor = UserFactory(name="Ada Lovelace", preferred_username="ada@example.com")
    target = UserFactory(name="Grace Hopper", preferred_username="grace@example.com")
    workspace_id = uuid.uuid4()

    with capture_logs() as logs:
        audit.record(
            actor=actor,
            action="workspace.role.set",
            target_user=target,
            workspace_id=workspace_id,
            new_role="viewer",
        )

    (line,) = [entry for entry in logs if entry["event"] == "iam.changed"]
    assert line["actor_id"] == actor.pk and line["target_user_id"] == target.pk
    assert line["workspace_id"] == str(workspace_id) and line["new_role"] == "viewer"
    assert "Ada" not in str(line) and "grace@" not in str(line)
