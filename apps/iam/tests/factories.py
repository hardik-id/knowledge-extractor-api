import factory

from apps.iam.models import AuditEntry, PlatformAdmin, Tenant, TenantMembership
from apps.iam.roles import TenantRole
from apps.identity.tests.factories import UserFactory


class TenantFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Tenant

    name = factory.Sequence(lambda n: f"Tenant {n}")


class TenantMembershipFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = TenantMembership

    tenant = factory.SubFactory(TenantFactory)
    # The person this makes is in this tenant only, so asking for Default works too.
    user = factory.SubFactory(UserFactory, in_default_tenant=False)
    role = TenantRole.MEMBER


class PlatformAdminFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PlatformAdmin

    user = factory.SubFactory(UserFactory)


class AuditEntryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AuditEntry

    action = "tenant_role_changed"
