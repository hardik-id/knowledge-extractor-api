from typing import Any, cast

from rest_framework import serializers

from apps.iam.roles import Permission, WorkspaceRole, permissions_of
from apps.iam.selectors import tenant_permissions
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
        if not role:
            return []
        held = set(permissions_of(WorkspaceRole(role)))
        if self._manages_members(obj):
            held.add(Permission.WORKSPACE_MEMBERS_MANAGE)
        return sorted(held)

    def _manages_members(self, obj: Workspace) -> bool:
        """An admin of the tenant or a platform admin: asked once per tenant per request."""
        request = self.context.get("request")
        if request is None:
            return False
        context = cast(dict[str, Any], self.context)
        asked: dict[Any, bool] = context.setdefault("members_manage", {})
        if obj.tenant_id not in asked:
            asked[obj.tenant_id] = (
                Permission.WORKSPACE_MEMBERS_MANAGE
                in tenant_permissions(request.user, obj.tenant_id)
            )
        return asked[obj.tenant_id]

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


class MemberUserSerializer(serializers.Serializer):  # type: ignore[type-arg]
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(read_only=True)
    preferred_username = serializers.CharField(read_only=True)


class WorkspaceMemberSerializer(serializers.Serializer):  # type: ignore[type-arg]
    """A person's role in a workspace on the wire."""

    user = MemberUserSerializer(read_only=True)
    role = serializers.CharField(read_only=True)
    added_at = serializers.DateTimeField(source="created_at", read_only=True)


class WorkspaceMemberListSerializer(serializers.Serializer):  # type: ignore[type-arg]
    items = WorkspaceMemberSerializer(many=True, read_only=True)


class SetWorkspaceRoleSerializer(serializers.Serializer):  # type: ignore[type-arg]
    role = serializers.ChoiceField(choices=[r.value for r in WorkspaceRole])
