"""The way a definition gets in: untrusted data to a ``Draft``, or 422.

The shape and its rules are the models in ``definition.py``. The DRF serializers
here describe the same shape for the OpenAPI schema (and the body of a save); a
test feeds both the same samples.
"""

from typing import Any

from pydantic import ValidationError
from rest_framework import serializers

from apps.core.errors import ApiError
from apps.extraction.definition import (
    CHUNK_STRATEGIES,
    FORMATS,
    MODES,
    VALUE_TYPES,
    Draft,
)

NOTE_MAX_LENGTH = 200

__all__ = [
    "FORMATS",
    "MODES",
    "NOTE_MAX_LENGTH",
    "VALUE_TYPES",
    "ChunkingSerializer",
    "DraftSerializer",
    "parse_draft",
]


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


class ChunkingSerializer(serializers.Serializer):  # type: ignore[type-arg]
    """How a long document is cut into parts. ``size`` is null for ``auto``."""

    strategy = serializers.ChoiceField(CHUNK_STRATEGIES, required=False, default="auto")
    size = serializers.IntegerField(required=False, allow_null=True, default=None)


class DraftSerializer(serializers.Serializer):  # type: ignore[type-arg]
    """A definition without ``version`` and ``base_version``."""

    prompt = serializers.CharField(allow_blank=True)
    record_types = RecordTypeSerializer(many=True)
    output = OutputSerializer()
    chunking = ChunkingSerializer(required=False)


def parse_draft(data: Any) -> Draft:
    """The draft with ids filled in and defaults applied, or 422 ``invalid_definition``.

    ``details.errors`` lists each problem with the path to the value, for example
    ``record_types.0.fields.2.mode``.
    """
    try:
        return Draft.model_validate(data)
    except ValidationError as error:
        problems = [
            {
                "path": ".".join(str(part) for part in problem["loc"]),
                "message": _message(problem),
            }
            for problem in error.errors()
        ]
        raise ApiError(
            "invalid_definition", "The definition is not valid.", {"errors": problems}
        ) from None


def _message(problem: Any) -> str:
    if problem["type"] == "value_error":  # a rule of ours: its text is the message
        return str(problem["ctx"]["error"])
    return str(problem["msg"])
