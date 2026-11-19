import factory
from django.utils import timezone

from apps.identity.tests.factories import UserFactory
from apps.runs.models import Cell, Run, RunFile, Stage


class RunFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Run

    owner = factory.SubFactory(UserFactory)


class RunFileFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = RunFile

    run = factory.SubFactory(RunFactory)
    source = "storage"
    source_ref = factory.Sequence(lambda n: f"enriched/doc-{n}.md")
    name = factory.Sequence(lambda n: f"doc-{n}.md")
    type = "md"
    size_bytes = 100
    location = "enriched / docs"
    modified_at = factory.LazyFunction(timezone.now)
    etag = "v1"


class CellFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Cell

    file = factory.SubFactory(RunFileFactory)
    stage = Stage.EXTRACT
