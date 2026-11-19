from rest_framework import serializers


class DocumentSerializer(serializers.Serializer):  # type: ignore[type-arg]
    """A listed document, as the UI's parser reads it."""

    id = serializers.CharField()
    name = serializers.CharField()
    source = serializers.CharField(read_only=True, default="storage")  # type: ignore[assignment]
    type = serializers.CharField()
    size_bytes = serializers.IntegerField()
    location = serializers.CharField()
    modified_at = serializers.DateTimeField()
    etag = serializers.CharField()


class DocumentListSerializer(serializers.Serializer):  # type: ignore[type-arg]
    items = DocumentSerializer(many=True)
