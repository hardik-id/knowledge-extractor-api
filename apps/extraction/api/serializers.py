from rest_framework import serializers

from apps.extraction.models import DefinitionVersion
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
