import uuid

import pytest
from django.contrib.auth.models import AnonymousUser

from apps.core.errors import ApiError
from apps.iam import selectors
from apps.iam.roles import Permission, PlatformAdminRole, TenantRole, permissions_of
from apps.iam.tests.factories import (
    PlatformAdminFactory,
    TenantFactory,
    TenantMembershipFactory,
)
from apps.identity.tests.factories import UserFactory
from apps.workspaces.tests.factories import WorkspaceFactory

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
    user = UserFactory(in_default_tenant=False)
    TenantMembershipFactory(user=user, tenant=TenantFactory(name="b"))
    TenantMembershipFactory(user=user, tenant=TenantFactory(name="Z"))
    TenantMembershipFactory(user=user, tenant=TenantFactory(name="A"))
    names = [t.name for t, _ in selectors.tenants_of(user)]
    assert names == ["A", "b", "Z"]


def test_tenants_of_lists_each_with_the_role() -> None:
    user = UserFactory(in_default_tenant=False)
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


def test_a_listed_oid_is_a_platform_admin_without_a_row(settings: object) -> None:
    person = UserFactory()
    settings.IAM_PLATFORM_ADMIN_OIDS = frozenset({person.oid})  # type: ignore[attr-defined]
    assert selectors.is_platform_admin(person)
    assert not selectors.is_platform_admin(UserFactory())


def test_tenant_permissions_come_from_the_role_and_from_being_a_platform_admin() -> (
    None
):
    tenant = TenantFactory()
    admin = TenantMembershipFactory(tenant=tenant, role=TenantRole.ADMIN).user
    member = TenantMembershipFactory(tenant=tenant).user
    outsider = TenantMembershipFactory().user
    boss = PlatformAdminFactory(user=UserFactory(in_default_tenant=False)).user
    assert Permission.TENANT_MEMBERS_MANAGE in selectors.tenant_permissions(
        admin, tenant.pk
    )
    assert selectors.tenant_permissions(member, tenant.pk) == permissions_of(
        TenantRole.MEMBER
    )
    assert selectors.tenant_permissions(outsider, tenant.pk) == frozenset()
    assert selectors.tenant_permissions(boss, tenant.pk) == permissions_of(
        PlatformAdminRole.PLATFORM_ADMIN
    )
    assert selectors.tenant_permissions(AnonymousUser(), tenant.pk) == frozenset()


def test_get_tenant_is_404_when_not_seen_and_403_without_the_permission() -> None:
    tenant = TenantFactory()
    admin = TenantMembershipFactory(tenant=tenant, role=TenantRole.ADMIN).user
    member = TenantMembershipFactory(tenant=tenant).user
    outsider = TenantMembershipFactory().user
    boss = PlatformAdminFactory().user
    manage, see = Permission.TENANT_MEMBERS_MANAGE, Permission.TENANT_MEMBERS_LIST
    assert selectors.get_tenant(admin, tenant.pk, manage) == tenant
    assert selectors.get_tenant(member, str(tenant.pk), see) == tenant
    assert selectors.get_tenant(boss, tenant.pk, manage) == tenant
    with pytest.raises(ApiError) as refused:
        selectors.get_tenant(member, tenant.pk, manage)
    assert refused.value.code == "forbidden"
    for person, tenant_id in (
        (outsider, tenant.pk),
        (admin, uuid.uuid4()),
        (boss, uuid.uuid4()),  # a platform admin sees every tenant that exists
        (admin, "not-a-uuid"),
    ):
        with pytest.raises(ApiError) as hidden:
            selectors.get_tenant(person, tenant_id, see)
        assert hidden.value.code == "tenant_not_found"


def test_tenant_of_workspace() -> None:
    workspace = WorkspaceFactory()
    assert selectors.tenant_of_workspace(workspace.pk) == workspace.tenant
    assert selectors.tenant_of_workspace(uuid.uuid4()) is None
    assert selectors.tenant_of_workspace("not-a-uuid") is None
