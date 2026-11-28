from typing import Any

from rest_framework import serializers

from apps.iam.roles import WorkspaceRole, permissions_of
from apps.workspaces.models import Workspace


class WorkspaceSerializer(serializers.ModelSerializer[Workspace]):
    """A workspace on the wire. Read from the annotated queryset of the selectors."""

    run_id = serializers.UUIDField(read_only=True)
    document_count = serializers.IntegerField(read_only=True)
    configuration_version = serializers.IntegerField(read_only=True, allow_null=True)
    updated_at = serializers.DateTimeField(source="activity", read_only=True)
    tenant_id = serializers.UUIDField(read_only=True)
    role = serializers.CharField(read_only=True)
    permissions = serializers.SerializerMethodField()

    def get_permissions(self, obj: Workspace) -> list[str]:
        """The person's permission names in this workspace, sorted."""
        role = getattr(obj, "role", None)
        return sorted(permissions_of(WorkspaceRole(role))) if role else []

    class Meta:
        model = Workspace
        fields = [
            "id",
            "name",
            "description",
            "run_id",
            "tenant_id",
            "role",
            "permissions",
            "document_count",
            "configuration_version",
            "created_at",
            "updated_at",
        ]


class CreateWorkspaceSerializer(serializers.Serializer):  # type: ignore[type-arg]
    name = serializers.CharField(max_length=120)
    description = serializers.CharField(required=False, allow_blank=True)
    template_id = serializers.CharField(required=False)
    tenant_id = serializers.UUIDField(required=False)


class ListWorkspacesSerializer(serializers.Serializer):  # type: ignore[type-arg]
    tenant_id = serializers.UUIDField(required=False)


class UpdateWorkspaceSerializer(serializers.Serializer):  # type: ignore[type-arg]
    name = serializers.CharField(max_length=120, required=False)
    description = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        return attrs
