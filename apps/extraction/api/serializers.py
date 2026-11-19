from typing import Any

from rest_framework import serializers

from apps.extraction import selectors
from apps.extraction.models import (
    DefinitionVersion,
    Extraction,
    ExtractionRecord,
    FieldValue,
    Origin,
    Review,
)
from apps.extraction.validation import DraftSerializer


class DefinitionSerializer(serializers.ModelSerializer[DefinitionVersion]):
    record_types = serializers.JSONField()
    output = serializers.JSONField()

    class Meta:
        model = DefinitionVersion
        fields = ["version", "prompt", "record_types", "output"]


class SaveDefinitionSerializer(DraftSerializer):
    """The body of a save: the draft plus the version it was edited from."""

    base_version = serializers.IntegerField(min_value=1)


class SpanSerializer(serializers.Serializer):  # type: ignore[type-arg]
    start = serializers.IntegerField()
    end = serializers.IntegerField()
    quote = serializers.CharField()


class FieldValueSerializer(serializers.Serializer):  # type: ignore[type-arg]
    id = serializers.CharField()
    field_id = serializers.CharField()
    value = serializers.CharField(allow_null=True)
    spans = SpanSerializer(many=True)
    origin = serializers.ChoiceField(Origin.choices)
    review = serializers.ChoiceField(Review.choices)
    anchored = serializers.BooleanField()


class RecordSerializer(serializers.Serializer):  # type: ignore[type-arg]
    id = serializers.CharField()
    file_id = serializers.CharField()
    record_type_id = serializers.CharField()
    span = SpanSerializer(allow_null=True)
    origin = serializers.ChoiceField(Origin.choices)
    review = serializers.ChoiceField(Review.choices)
    use_as_example = serializers.BooleanField()
    fields = FieldValueSerializer(many=True)  # type: ignore[assignment]


class SpanInputSerializer(serializers.Serializer):  # type: ignore[type-arg]
    """A span a person sends: the quote is kept as sent, so it can equal the text."""

    start = serializers.IntegerField()
    end = serializers.IntegerField()
    quote = serializers.CharField(trim_whitespace=False, allow_blank=True)


class ValueInputSerializer(serializers.Serializer):  # type: ignore[type-arg]
    value = serializers.CharField(
        allow_null=True, allow_blank=True, trim_whitespace=False
    )
    spans = SpanInputSerializer(many=True)


class FieldInputSerializer(serializers.Serializer):  # type: ignore[type-arg]
    field_id = serializers.CharField()
    values = ValueInputSerializer(many=True)


class AddRecordSerializer(serializers.Serializer):  # type: ignore[type-arg]
    """The body of ``POST .../records``."""

    revision = serializers.IntegerField(min_value=0)
    record_type_id = serializers.CharField()
    span = SpanInputSerializer(allow_null=True)
    fields = FieldInputSerializer(many=True, required=False, default=list)  # type: ignore[assignment]


class UpdateRecordSerializer(serializers.Serializer):  # type: ignore[type-arg]
    """The body of ``PATCH .../records/{record_id}``: only the keys sent change."""

    revision = serializers.IntegerField(min_value=0)
    review = serializers.ChoiceField(Review.choices, required=False)
    span = SpanInputSerializer(allow_null=True, required=False)
    use_as_example = serializers.BooleanField(required=False)


class ReplaceFieldValuesSerializer(serializers.Serializer):  # type: ignore[type-arg]
    """The body of ``PUT .../records/{record_id}/fields/{field_id}``."""

    revision = serializers.IntegerField(min_value=0)
    values = ValueInputSerializer(many=True)


class ReviewValueSerializer(serializers.Serializer):  # type: ignore[type-arg]
    """The body of ``PATCH .../records/{record_id}/values/{value_id}``."""

    revision = serializers.IntegerField(min_value=0)
    review = serializers.ChoiceField(Review.choices)


class RevisionQuerySerializer(serializers.Serializer):  # type: ignore[type-arg]
    """The query of ``DELETE .../records/{record_id}``."""

    revision = serializers.IntegerField(min_value=0)


class ExtractionSerializer(serializers.Serializer):  # type: ignore[type-arg]
    """The whole extraction of a file: what the read answers and every write will."""

    file_id = serializers.CharField()
    revision = serializers.IntegerField()
    source_etag = serializers.CharField()
    definition_version = serializers.IntegerField()
    records = RecordSerializer(many=True)


def _value(value: FieldValue) -> dict[str, Any]:
    return {
        "id": str(value.pk),
        "field_id": value.field_id,
        "value": value.value,
        "spans": value.spans,
        "origin": value.origin,
        "review": value.review,
        "anchored": value.anchored,
    }


def _empty_value(record: ExtractionRecord, field_id: str) -> dict[str, Any]:
    """The value of a field that was looked for and not found."""
    return {
        "id": f"{record.pk}:{field_id}",
        "field_id": field_id,
        "value": None,
        "spans": [],
        "origin": record.origin,
        "review": Review.SUGGESTED.value,
        "anchored": True,
    }


def _record(
    record: ExtractionRecord, file_id: str, field_ids: dict[str, list[str]]
) -> dict[str, Any]:
    by_field: dict[str, list[FieldValue]] = {}
    for value in record.values.all():
        by_field.setdefault(value.field_id, []).append(value)
    fields: list[dict[str, Any]] = []
    known = field_ids.get(record.record_type_id, [])
    for field_id in known:
        stored = by_field.get(field_id)
        fields.extend(
            [_value(v) for v in stored] if stored else [_empty_value(record, field_id)]
        )
    for field_id, stored in by_field.items():  # a field the definition no longer has
        if field_id not in known:
            fields.extend(_value(v) for v in stored)
    return {
        "id": str(record.pk),
        "file_id": file_id,
        "record_type_id": record.record_type_id,
        "span": record.span,
        "origin": record.origin,
        "review": record.review,
        "use_as_example": record.use_as_example,
        "fields": fields,
    }


def serialize_extraction(extraction: Extraction) -> dict[str, Any]:
    """The one wire shape of an extraction, for the read and for every write."""
    definition = selectors.get_definition_version(
        extraction.file.run_id, extraction.definition_version
    )
    field_ids = {
        record_type["id"]: [field["id"] for field in record_type["fields"]]
        for record_type in definition.record_types
    }
    file_id = str(extraction.file_id)
    return {
        "file_id": file_id,
        "revision": extraction.revision,
        "source_etag": extraction.source_etag,
        "definition_version": extraction.definition_version,
        "records": [
            _record(record, file_id, field_ids) for record in extraction.records.all()
        ],
    }


class ExecutionConfigSerializer(serializers.Serializer):  # type: ignore[type-arg]
    """The stage settings of an execution. ``definitionVersion`` is accepted too."""

    definition_version = serializers.IntegerField(min_value=1, required=False)

    def to_internal_value(self, data: Any) -> Any:
        if isinstance(data, dict) and "definition_version" not in data:
            if "definitionVersion" in data:  # how the UI sends it today
                data = {**data, "definition_version": data["definitionVersion"]}
        return super().to_internal_value(data)


class StartExecutionSerializer(serializers.Serializer):  # type: ignore[type-arg]
    """The body of ``POST .../stages/extract/executions``. No ``file_ids``: every file."""

    file_ids = serializers.ListField(
        child=serializers.CharField(), required=False, allow_null=True
    )
    config = ExecutionConfigSerializer(required=False)


class ExecutionSerializer(serializers.Serializer):  # type: ignore[type-arg]
    execution_id = serializers.CharField()
    stage = serializers.CharField()
    file_ids = serializers.ListField(child=serializers.CharField())
