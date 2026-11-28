import factory

from apps.iam.models import Tenant, WorkspaceMembership
from apps.iam.roles import WorkspaceRole
from apps.identity.tests.factories import UserFactory
from apps.runs.tests.factories import RunFactory
from apps.workspaces.models import Workspace


def default_tenant() -> Tenant:
    return Tenant.objects.get_or_create(is_default=True, defaults={"name": "Default"})[
        0
    ]


class WorkspaceFactory(factory.django.DjangoModelFactory):
    """A workspace in Default; its owner is given the owner role (``owner_role="none"`` skips it)."""

    class Meta:
        model = Workspace

    owner = factory.SubFactory(UserFactory)
    tenant = factory.LazyFunction(default_tenant)
    name = factory.Sequence(lambda n: f"Workspace {n}")
    run = factory.SubFactory(RunFactory, owner=factory.SelfAttribute("..owner"))

    @factory.post_generation  # type: ignore[untyped-decorator]
    def owner_role(self, create: bool, extracted: object, **kwargs: object) -> None:
        if create and extracted != "none":
            WorkspaceMembership.objects.create(
                workspace=self,
                user=self.owner,
                role=str(extracted or WorkspaceRole.OWNER),
            )
