import pytest
from django.db import IntegrityError, transaction

from apps.iam.models import AuditEntry
from apps.iam.tests.factories import (
    AuditEntryFactory,
    PlatformAdminFactory,
    TenantFactory,
    TenantMembershipFactory,
)
from apps.identity.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_tenant_names_are_unique_without_regard_to_case() -> None:
    TenantFactory(name="Team A")
    with pytest.raises(IntegrityError), transaction.atomic():
        TenantFactory(name="team a")


def test_at_most_one_default_tenant() -> None:
    # The migration already made one.
    with pytest.raises(IntegrityError), transaction.atomic():
        TenantFactory(is_default=True)
    TenantFactory(is_default=False)


def test_one_membership_per_tenant_and_user() -> None:
    m = TenantMembershipFactory()
    with pytest.raises(IntegrityError), transaction.atomic():
        TenantMembershipFactory(tenant=m.tenant, user=m.user)


def test_one_platform_admin_row_per_user() -> None:
    p = PlatformAdminFactory()
    with pytest.raises(IntegrityError), transaction.atomic():
        PlatformAdminFactory(user=p.user)


def test_audit_entries_survive_the_person_and_the_tenant() -> None:
    actor, target, tenant = UserFactory(), UserFactory(), TenantFactory()
    entry = AuditEntryFactory(actor=actor, target_user=target, tenant=tenant)
    actor.delete()
    target.delete()
    tenant.delete()
    entry.refresh_from_db()
    assert (entry.actor, entry.target_user, entry.tenant) == (None, None, None)


def test_an_audit_entry_is_never_updated() -> None:
    entry = AuditEntryFactory()
    entry.new_role = "admin"
    with pytest.raises(ValueError):
        entry.save()
    assert AuditEntry.objects.get(pk=entry.pk).new_role == ""
