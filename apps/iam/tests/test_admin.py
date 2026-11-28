import pytest
from django.test import Client

from apps.iam import selectors
from apps.iam.tests.factories import (
    AuditEntryFactory,
    PlatformAdminFactory,
    TenantMembershipFactory,
)
from apps.identity.tests.factories import UserFactory

pytestmark = pytest.mark.django_db

MODELS = ["tenant", "tenantmembership", "platformadmin", "auditentry"]


@pytest.fixture
def client() -> Client:
    user = UserFactory(is_staff=True, is_superuser=True)
    c = Client()
    c.force_login(user)
    return c


def test_changelists_load(client: Client) -> None:
    TenantMembershipFactory()
    PlatformAdminFactory()
    AuditEntryFactory()
    for name in MODELS:
        assert client.get(f"/admin/iam/{name}/").status_code == 200


@pytest.mark.parametrize("name", ["tenantmembership", "platformadmin", "auditentry"])
def test_role_records_are_read_only(client: Client, name: str) -> None:
    assert client.get(f"/admin/iam/{name}/add/").status_code == 403


def test_the_default_tenant_cannot_be_deleted(client: Client) -> None:
    pk = selectors.default_tenant().pk
    assert client.get(f"/admin/iam/tenant/{pk}/delete/").status_code == 403
