import factory

from apps.identity.tests.factories import UserFactory
from apps.runs.tests.factories import RunFactory
from apps.workspaces.models import Workspace


class WorkspaceFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Workspace

    owner = factory.SubFactory(UserFactory)
    name = factory.Sequence(lambda n: f"Workspace {n}")
    run = factory.SubFactory(RunFactory, owner=factory.SelfAttribute("..owner"))
