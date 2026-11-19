"""The shape and rules of a definition, shared by the API and the assistant."""

import uuid
from typing import Any

from rest_framework import serializers

from apps.core.errors import ApiError

MODES = ("quote", "inferred")
VALUE_TYPES = ("text", "date", "number", "choice")
FORMATS = ("json", "markdown", "csv")


class FieldSerializer(serializers.Serializer):  # type: ignore[type-arg]
    id = serializers.CharField(required=False, allow_blank=True)
    key = serializers.CharField(allow_blank=True)
    name = serializers.CharField(allow_blank=True)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    mode = serializers.ChoiceField(MODES)
    value_type = serializers.ChoiceField(VALUE_TYPES)
    choices = serializers.ListField(
        child=serializers.CharField(allow_blank=True), required=False, default=list
    )
    multiple = serializers.BooleanField(required=False, default=False)


class RecordTypeSerializer(serializers.Serializer):  # type: ignore[type-arg]
    id = serializers.CharField(required=False, allow_blank=True)
    name = serializers.CharField(allow_blank=True)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    fields = FieldSerializer(many=True)  # type: ignore[assignment]


class OutputSerializer(serializers.Serializer):  # type: ignore[type-arg]
    format = serializers.ChoiceField(FORMATS)
    template = serializers.CharField(allow_blank=True)


class DraftSerializer(serializers.Serializer):  # type: ignore[type-arg]
    """A definition without ``version`` and ``base_version``."""

    prompt = serializers.CharField(allow_blank=True)
    record_types = RecordTypeSerializer(many=True)
    output = OutputSerializer()


def _invalid(message: str, details: dict[str, Any] | None = None) -> ApiError:
    return ApiError("invalid_definition", message, details)


def validate_draft(data: Any) -> dict[str, Any]:
    """The draft with ids filled in and defaults applied, or 422 ``invalid_definition``."""
    serializer = DraftSerializer(data=data)
    if not serializer.is_valid():
        raise _invalid("The definition is not valid.", {"errors": serializer.errors})
    draft: dict[str, Any] = _plain(serializer.validated_data)
    for record_type in draft["record_types"]:
        record_type["id"] = record_type.get("id") or f"rt-{uuid.uuid4().hex[:12]}"
        keys = [field["key"].strip() for field in record_type["fields"]]
        if not all(keys) or len(set(keys)) != len(keys):
            raise _invalid(
                f'The fields of "{record_type["name"]}" need a key each, '
                "and no two may share one."
            )
        for field in record_type["fields"]:
            field["id"] = field.get("id") or f"f-{uuid.uuid4().hex[:12]}"
            field["key"] = field["key"].strip()
    return draft


def _plain(value: Any) -> Any:
    """Ordered dicts and lists from the serializer as plain JSON data."""
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value
