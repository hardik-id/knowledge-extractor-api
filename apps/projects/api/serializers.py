from typing import Any

from rest_framework import serializers

from apps.projects.models import Project


class ProjectSerializer(serializers.ModelSerializer[Project]):
    """A project on the wire. Read from the annotated queryset of the selectors."""

    run_id = serializers.UUIDField(read_only=True)
    document_count = serializers.IntegerField(read_only=True)
    configuration_version = serializers.IntegerField(read_only=True, allow_null=True)
    updated_at = serializers.DateTimeField(source="activity", read_only=True)

    class Meta:
        model = Project
        fields = [
            "id",
            "name",
            "description",
            "run_id",
            "document_count",
            "configuration_version",
            "created_at",
            "updated_at",
        ]


class CreateProjectSerializer(serializers.Serializer):  # type: ignore[type-arg]
    name = serializers.CharField(max_length=120)
    description = serializers.CharField(required=False, allow_blank=True)


class UpdateProjectSerializer(serializers.Serializer):  # type: ignore[type-arg]
    name = serializers.CharField(max_length=120, required=False)
    description = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        return attrs
