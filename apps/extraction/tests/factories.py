import factory

from apps.extraction.defaults import (
    DEFAULT_OUTPUT,
    DEFAULT_PROMPT,
    DEFAULT_RECORD_TYPES,
)
from apps.extraction.models import DefinitionVersion
from apps.runs.tests.factories import RunFactory


class DefinitionVersionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = DefinitionVersion

    run = factory.SubFactory(RunFactory)
    version = 1
    prompt = DEFAULT_PROMPT
    record_types = DEFAULT_RECORD_TYPES
    output = DEFAULT_OUTPUT
