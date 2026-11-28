import threading
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from django.db import connection
from structlog.testing import capture_logs

from apps.core.errors import ApiError
from apps.iam import services
from apps.iam.models import AuditEntry, PlatformAdmin, Tenant, TenantMembership
from apps.iam.roles import TenantRole
from apps.iam.selectors import is_platform_admin
from apps.iam.tests.factories import (
    PlatformAdminFactory,
    TenantFactory,
    TenantMembershipFactory,
)
from apps.identity.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def code_of(call: Callable[[], Any]) -> str:
    with pytest.raises(ApiError) as error:
        call()
    return error.value.code


def role_of(tenant: Tenant, user: Any) -> str | None:
    row = TenantMembership.objects.filter(tenant=tenant, user=user).first()
    return row.role if row else None


def tenant_admin(tenant: Tenant) -> Any:
    return TenantMembershipFactory(tenant=tenant, role=TenantRole.ADMIN).user


def member(tenant: Tenant) -> Any:
    return TenantMembershipFactory(tenant=tenant, role=TenantRole.MEMBER).user


def platform_admin() -> Any:
    return PlatformAdminFactory().user


# --- set_tenant_role -------------------------------------------------------


def test_a_tenant_admin_adds_and_changes_a_member() -> None:
    tenant = TenantFactory()
    admin, person = tenant_admin(tenant), UserFactory()

    services.set_tenant_role(admin, tenant.pk, person.pk, "member")
    assert role_of(tenant, person) == "member"
    services.set_tenant_role(admin, tenant.pk, person.pk, TenantRole.ADMIN)
    assert role_of(tenant, person) == "admin"

    first, second = AuditEntry.objects.order_by("created_at")
    assert (first.action, first.old_role, first.new_role) == (
        "tenant.role.set",
        "",
        "member",
    )
    assert (second.old_role, second.new_role) == ("member", "admin")
    assert second.actor_id == admin.pk and second.target_user_id == person.pk
    assert second.tenant_id == tenant.pk


def test_a_platform_admin_names_the_first_admin_of_a_tenant() -> None:
    tenant, person = TenantFactory(), UserFactory()
    services.set_tenant_role(platform_admin(), tenant.pk, person.pk, "admin")
    assert role_of(tenant, person) == "admin"


def test_a_member_may_not_grant() -> None:
    tenant = TenantFactory()
    person = member(tenant)
    assert (
        code_of(lambda: services.set_tenant_role(person, tenant.pk, person.pk, "admin"))
        == "forbidden"
    )
    assert role_of(tenant, person) == "member"
    assert AuditEntry.objects.count() == 0


def test_a_tenant_the_actor_may_not_see_is_not_found() -> None:
    tenant, other = TenantFactory(), TenantFactory()
    outsider = tenant_admin(other)  # admin elsewhere, nothing here
    target = UserFactory()
    assert (
        code_of(
            lambda: services.set_tenant_role(outsider, tenant.pk, target.pk, "member")
        )
        == "tenant_not_found"
    )
    assert (
        code_of(lambda: services.remove_tenant_member(outsider, tenant.pk, target.pk))
        == "tenant_not_found"
    )
    assert (
        code_of(
            lambda: services.set_tenant_role(
                platform_admin(), uuid.uuid4(), target.pk, "member"
            )
        )
        == "tenant_not_found"
    )
    assert AuditEntry.objects.count() == 0


def test_an_unknown_person_is_not_found() -> None:
    tenant = TenantFactory()
    assert (
        code_of(
            lambda: services.set_tenant_role(
                tenant_admin(tenant), tenant.pk, 0, "member"
            )
        )
        == "user_not_found"
    )
    assert AuditEntry.objects.count() == 0


def test_the_same_role_again_changes_and_records_nothing() -> None:
    tenant = TenantFactory()
    person = member(tenant)
    services.set_tenant_role(tenant_admin(tenant), tenant.pk, person.pk, "member")
    assert AuditEntry.objects.count() == 0


def test_the_last_tenant_admin_cannot_step_down_or_leave() -> None:
    tenant = TenantFactory()
    admin = tenant_admin(tenant)
    assert (
        code_of(lambda: services.set_tenant_role(admin, tenant.pk, admin.pk, "member"))
        == "last_tenant_admin"
    )
    assert (
        code_of(lambda: services.remove_tenant_member(admin, tenant.pk, admin.pk))
        == "last_tenant_admin"
    )
    assert role_of(tenant, admin) == "admin" and AuditEntry.objects.count() == 0


def test_an_admin_may_step_down_when_another_admin_stays() -> None:
    tenant = TenantFactory()
    admin, other = tenant_admin(tenant), tenant_admin(tenant)
    services.set_tenant_role(admin, tenant.pk, admin.pk, "member")
    assert role_of(tenant, admin) == "member" and role_of(tenant, other) == "admin"


def test_a_platform_admin_may_remove_the_last_tenant_admin() -> None:
    tenant = TenantFactory()
    admin = tenant_admin(tenant)
    services.remove_tenant_member(platform_admin(), tenant.pk, admin.pk)
    assert role_of(tenant, admin) is None


# --- remove_tenant_member --------------------------------------------------


def test_remove_a_member_records_who_and_logs_ids_only() -> None:
    tenant = TenantFactory()
    admin, person = tenant_admin(tenant), member(tenant)
    person.name = "Grace Hopper"
    person.save()

    with capture_logs() as logs:
        services.remove_tenant_member(admin, tenant.pk, person.pk)

    assert role_of(tenant, person) is None
    entry = AuditEntry.objects.get()
    assert (entry.action, entry.old_role, entry.new_role) == (
        "tenant.member.remove",
        "member",
        "",
    )
    (line,) = [log for log in logs if log["event"] == "iam.changed"]
    assert line["target_user_id"] == person.pk and "Grace" not in str(line)


def test_remove_someone_who_is_not_a_member_is_not_found() -> None:
    tenant = TenantFactory()
    assert (
        code_of(
            lambda: services.remove_tenant_member(
                tenant_admin(tenant), tenant.pk, UserFactory().pk
            )
        )
        == "user_not_found"
    )
    assert AuditEntry.objects.count() == 0


def test_a_member_may_not_remove() -> None:
    tenant = TenantFactory()
    person, other = member(tenant), member(tenant)
    assert (
        code_of(lambda: services.remove_tenant_member(person, tenant.pk, other.pk))
        == "forbidden"
    )


# --- platform admins -------------------------------------------------------


def test_grant_and_revoke_platform_admin() -> None:
    boss, other, person = platform_admin(), platform_admin(), UserFactory()
    services.grant_platform_admin(boss, person.pk)
    assert is_platform_admin(person)
    services.revoke_platform_admin(boss, person.pk)
    assert not is_platform_admin(person)
    grant, revoke = AuditEntry.objects.order_by("created_at")
    assert (grant.action, grant.new_role) == ("platform_admin.grant", "platform_admin")
    assert (revoke.action, revoke.old_role) == (
        "platform_admin.revoke",
        "platform_admin",
    )
    assert grant.target_oid == person.oid and other


def test_granting_again_records_nothing() -> None:
    boss = platform_admin()
    services.grant_platform_admin(boss, boss.pk)
    assert AuditEntry.objects.count() == 0


def test_only_a_platform_admin_may_grant_or_revoke() -> None:
    tenant = TenantFactory()
    admin, person = tenant_admin(tenant), UserFactory()
    assert (
        code_of(lambda: services.grant_platform_admin(admin, person.pk)) == "forbidden"
    )
    assert (
        code_of(lambda: services.revoke_platform_admin(admin, person.pk)) == "forbidden"
    )
    assert not PlatformAdmin.objects.filter(user=person).exists()
    assert AuditEntry.objects.count() == 0


def test_the_last_platform_admin_cannot_be_revoked() -> None:
    boss = platform_admin()
    assert (
        code_of(lambda: services.revoke_platform_admin(boss, boss.pk))
        == "last_platform_admin"
    )
    assert is_platform_admin(boss) and AuditEntry.objects.count() == 0


def test_a_listed_person_counts_as_a_platform_admin_for_the_last_rule(
    settings: Any,
) -> None:
    listed, row = UserFactory(), platform_admin()
    settings.IAM_PLATFORM_ADMIN_OIDS = frozenset({listed.oid})
    services.revoke_platform_admin(listed, row.pk)
    assert not PlatformAdmin.objects.exists()
    # the listed person has no row to take away, and stays an admin
    services.revoke_platform_admin(listed, listed.pk)
    assert is_platform_admin(listed)


def test_a_command_acts_without_an_actor_and_without_a_permission_check() -> None:
    person = UserFactory()
    services.grant_platform_admin(None, person.pk)
    entry = AuditEntry.objects.get()
    assert entry.actor is None and entry.target_oid == person.oid


def test_an_unknown_person_cannot_be_made_a_platform_admin() -> None:
    assert code_of(lambda: services.grant_platform_admin(None, 0)) == "user_not_found"


# --- two requests at the same moment --------------------------------------


def run_together(calls: list[Callable[[], Any]]) -> list[str | None]:
    """Run each call on its own thread and connection; the error code, or None."""
    barrier = threading.Barrier(len(calls))
    results: list[str | None] = [None] * len(calls)
    crashed: list[BaseException] = []

    def run(i: int) -> None:
        try:
            barrier.wait()
            calls[i]()
        except ApiError as error:
            results[i] = error.code
        except BaseException as error:  # reported on the main thread
            crashed.append(error)
        finally:
            connection.close()

    threads = [threading.Thread(target=run, args=(i,)) for i in range(len(calls))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not crashed, crashed
    return results


@pytest.mark.django_db(transaction=True)
def test_two_admins_stepping_down_together_leave_one() -> None:
    tenant = Tenant.objects.create(name="Race")
    a, b = tenant_admin(tenant), tenant_admin(tenant)
    results = run_together(
        [
            lambda: services.set_tenant_role(a, tenant.pk, a.pk, "member"),
            lambda: services.set_tenant_role(b, tenant.pk, b.pk, "member"),
        ]
    )
    assert sorted(r or "" for r in results) == ["", "last_tenant_admin"]
    assert TenantMembership.objects.filter(tenant=tenant, role="admin").count() == 1
    assert AuditEntry.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_two_revokes_of_the_two_platform_admins_leave_one() -> None:
    a, b = platform_admin(), platform_admin()
    results = run_together(
        [
            lambda: services.revoke_platform_admin(None, a.pk),
            lambda: services.revoke_platform_admin(None, b.pk),
        ]
    )
    assert sorted(r or "" for r in results) == ["", "last_platform_admin"]
    assert PlatformAdmin.objects.count() == 1
    assert AuditEntry.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_the_same_person_added_twice_together_is_one_membership() -> None:
    tenant = Tenant.objects.create(name="Race")
    admin, person = tenant_admin(tenant), UserFactory()
    results = run_together(
        [lambda: services.set_tenant_role(admin, tenant.pk, person.pk, "member")] * 2
    )
    assert results == [None, None]
    assert TenantMembership.objects.filter(tenant=tenant, user=person).count() == 1
    assert AuditEntry.objects.count() == 1


def test_a_deactivated_tenant_admin_does_not_count_as_another_admin() -> None:
    tenant = TenantFactory()
    admin, other = tenant_admin(tenant), tenant_admin(tenant)
    other.is_active = False
    other.save()
    assert (
        code_of(lambda: services.set_tenant_role(admin, tenant.pk, admin.pk, "member"))
        == "last_tenant_admin"
    )
    assert role_of(tenant, admin) == "admin"


def test_a_deactivated_platform_admin_does_not_count_for_the_last_rule() -> None:
    boss, gone = platform_admin(), platform_admin()
    gone.is_active = False
    gone.save()
    assert (
        code_of(lambda: services.revoke_platform_admin(boss, boss.pk))
        == "last_platform_admin"
    )
    assert is_platform_admin(boss)
