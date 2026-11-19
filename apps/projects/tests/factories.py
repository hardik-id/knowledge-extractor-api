import factory

from apps.identity.tests.factories import UserFactory
from apps.projects.models import Project
from apps.runs.tests.factories import RunFactory


class ProjectFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Project

    owner = factory.SubFactory(UserFactory)
    name = factory.Sequence(lambda n: f"Project {n}")
    run = factory.SubFactory(RunFactory, owner=factory.SelfAttribute("..owner"))
