import uuid

import pytest
from django.contrib.auth.models import AnonymousUser

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


def test_selectors_are_safe_for_anonymous_inactive_and_malformed_input() -> None:
    admin = PlatformAdminFactory().user
    m = TenantMembershipFactory()
    assert not selectors.is_platform_admin(AnonymousUser())
    assert selectors.tenant_role(AnonymousUser(), m.tenant_id) is None
    assert selectors.tenant_role(m.user, "not-a-uuid") is None
    assert selectors.tenant_role(m.user, str(m.tenant_id)) == TenantRole.MEMBER
    admin.is_active = False
    admin.save()
    assert not selectors.is_platform_admin(admin)


def test_tenants_of_orders_by_name_without_regard_to_case() -> None:
    user = UserFactory()
    TenantMembershipFactory(user=user, tenant=TenantFactory(name="b"))
    TenantMembershipFactory(user=user, tenant=TenantFactory(name="Z"))
    TenantMembershipFactory(user=user, tenant=TenantFactory(name="A"))
    names = [t.name for t, _ in selectors.tenants_of(user)]
    assert names == ["A", "b", "Z"]


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
