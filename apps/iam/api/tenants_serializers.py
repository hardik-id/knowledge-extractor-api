from typing import Any

from rest_framework import serializers

from apps.workspaces.models import Workspace


class TenantSerializer(serializers.Serializer[Any]):
    """A tenant. The counts are the platform admin's; anyone else gets null."""

    id = serializers.UUIDField()
    name = serializers.CharField()
    is_default = serializers.BooleanField()
    role = serializers.CharField(allow_null=True)
    member_count = serializers.IntegerField(allow_null=True)
    workspace_count = serializers.IntegerField(allow_null=True)
    created_at = serializers.DateTimeField()


class TenantList(serializers.Serializer[Any]):
    items = TenantSerializer(many=True)
    next = serializers.CharField(allow_null=True)


class TenantNameSerializer(serializers.Serializer[Any]):
    name = serializers.CharField(max_length=120)


class OwnerSerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField()
    name = serializers.CharField()


class TenantWorkspaceSerializer(serializers.ModelSerializer[Workspace]):
    """A workspace as a tenant's admin sees it: who and when, never its content."""

    owners = serializers.SerializerMethodField()
    member_count = serializers.IntegerField(read_only=True)
    no_owner = serializers.SerializerMethodField()
    last_activity = serializers.DateTimeField(source="activity", read_only=True)

    class Meta:
        model = Workspace
        fields = [
            "id",
            "name",
            "owners",
            "member_count",
            "no_owner",
            "last_activity",
            "created_at",
        ]

    def get_owners(self, obj: Workspace) -> list[dict[str, Any]]:
        return [
            {"id": m.user_id, "name": m.user.name or m.user.preferred_username}
            for m in getattr(obj, "owner_rows", [])
        ]

    def get_no_owner(self, obj: Workspace) -> bool:
        return not getattr(obj, "owner_rows", [])


class TenantWorkspaceList(serializers.Serializer[Any]):
    items = TenantWorkspaceSerializer(many=True)
    next = serializers.CharField(allow_null=True)
