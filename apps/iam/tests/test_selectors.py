import uuid

import pytest

from apps.iam import selectors
from apps.iam.roles import TenantRole
from apps.iam.tests.factories import (
    PlatformAdminFactory,
    TenantFactory,
    TenantMembershipFactory,
)
from apps.identity.tests.factories import UserFactory

pytestmark = pytest.mark.django_db


def test_is_platform_admin() -> None:
    assert selectors.is_platform_admin(PlatformAdminFactory().user)
    assert not selectors.is_platform_admin(UserFactory())


def test_tenant_role() -> None:
    m = TenantMembershipFactory(role=TenantRole.ADMIN)
    assert selectors.tenant_role(m.user, m.tenant_id) == TenantRole.ADMIN
    assert selectors.tenant_role(m.user, TenantFactory().pk) is None
    assert selectors.tenant_role(m.user, uuid.uuid4()) is None


def test_tenants_of_lists_each_with_the_role() -> None:
    user = UserFactory()
    b = TenantMembershipFactory(user=user, tenant=TenantFactory(name="B"), role="admin")
    a = TenantMembershipFactory(
        user=user, tenant=TenantFactory(name="A"), role="member"
    )
    TenantMembershipFactory()
    assert selectors.tenants_of(user) == [
        (a.tenant, TenantRole.MEMBER),
        (b.tenant, TenantRole.ADMIN),
    ]


def test_default_tenant() -> None:
    tenant = selectors.default_tenant()
    assert tenant.name == "Default"
    assert tenant.is_default
