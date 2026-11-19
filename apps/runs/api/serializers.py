from typing import Any

from rest_framework import serializers

from apps.runs.models import Cell, Run, RunFile


class RunItemSerializer(serializers.Serializer):  # type: ignore[type-arg]
    """One chosen document. Only the source and its id count; the rest comes from the catalog."""

    source = serializers.CharField()  # type: ignore[assignment]
    source_ref = serializers.CharField()
    name = serializers.CharField(required=False)
    type = serializers.CharField(required=False)
    size_bytes = serializers.IntegerField(required=False)
    location = serializers.CharField(required=False, allow_blank=True)
    modified_at = serializers.DateTimeField(required=False)


class CreateRunSerializer(serializers.Serializer):  # type: ignore[type-arg]
    items = RunItemSerializer(many=True, allow_empty=True)


class RunFileSerializer(serializers.ModelSerializer[RunFile]):
    class Meta:
        model = RunFile
        fields = [
            "id",
            "source_ref",
            "name",
            "source",
            "type",
            "size_bytes",
            "location",
            "modified_at",
            "etag",
        ]


class CellSerializer(serializers.ModelSerializer[Cell]):
    file_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = Cell
        fields = [
            "file_id",
            "stage",
            "status",
            "execution_id",
            "progress",
            "error",
            "output",
            "updated_at",
        ]


class RunSerializer(serializers.Serializer):  # type: ignore[type-arg]
    id = serializers.UUIDField()
    created_at = serializers.DateTimeField()
    files = serializers.SerializerMethodField()
    cells = serializers.SerializerMethodField()

    def get_files(self, run: Run) -> Any:
        files = run.files.order_by("id")
        return RunFileSerializer(files, many=True).data

    def get_cells(self, run: Run) -> Any:
        cells = Cell.objects.filter(file__run=run).order_by("file_id", "stage")
        return CellSerializer(cells, many=True).data
