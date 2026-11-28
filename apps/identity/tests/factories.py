import uuid

import factory
from django.contrib.auth import get_user_model


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = get_user_model()

    username = factory.Sequence(lambda n: f"user{n}")
    oid = factory.LazyFunction(uuid.uuid4)
    tid = factory.LazyFunction(uuid.uuid4)
    name = factory.Faker("name")

    @factory.post_generation  # type: ignore[untyped-decorator]
    def in_default_tenant(
        self, create: bool, extracted: object, **kwargs: object
    ) -> None:
        """A new person is a member of Default, as a first sign-in makes them.

        ``UserFactory(in_default_tenant=False)`` makes one with no tenant.
        """
        if create and extracted is not False:
            from apps.iam.models import Tenant, TenantMembership

            default = Tenant.objects.get_or_create(
                is_default=True, defaults={"name": "Default"}
            )[0]
            TenantMembership.objects.create(tenant=default, user=self, role="member")
