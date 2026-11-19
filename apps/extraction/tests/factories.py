import factory

from apps.extraction.defaults import (
    DEFAULT_OUTPUT,
    DEFAULT_PROMPT,
    DEFAULT_RECORD_TYPES,
)
from apps.extraction.models import (
    DefinitionVersion,
    Extraction,
    ExtractionRecord,
    FieldValue,
)
from apps.runs.tests.factories import RunFactory, RunFileFactory


class DefinitionVersionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = DefinitionVersion

    run = factory.SubFactory(RunFactory)
    version = 1
    prompt = DEFAULT_PROMPT
    record_types = DEFAULT_RECORD_TYPES
    output = DEFAULT_OUTPUT


class ExtractionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Extraction

    file = factory.SubFactory(RunFileFactory)
    revision = 1
    source_etag = "v1"
    definition_version = 1


class ExtractionRecordFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ExtractionRecord

    extraction = factory.SubFactory(ExtractionFactory)
    record_type_id = "rt-adr"
    span = None


class FieldValueFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = FieldValue

    record = factory.SubFactory(ExtractionRecordFactory)
    field_id = "f-adr-title"
    value = "Use Postgres"
    spans: list[dict[str, object]] = []
