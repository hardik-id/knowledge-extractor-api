from typing import Any

from rest_framework import serializers

from apps.iam.models import AuditEntry


class AuditPersonSerializer(serializers.Serializer[Any]):
    """A person in an entry: null when their row is gone."""

    id = serializers.IntegerField()
    name = serializers.CharField()


class AuditEntrySerializer(serializers.ModelSerializer[AuditEntry]):
    """Ids, display names, roles, actions and times: nothing else."""

    actor = serializers.SerializerMethodField()
    target = serializers.SerializerMethodField()
    tenant_id = serializers.UUIDField(read_only=True, allow_null=True)
    workspace_id = serializers.UUIDField(read_only=True, allow_null=True)

    class Meta:
        model = AuditEntry
        fields = [
            "id",
            "action",
            "actor",
            "target",
            "tenant_id",
            "workspace_id",
            "old_role",
            "new_role",
            "created_at",
        ]

    def _person(self, user: Any) -> dict[str, Any] | None:
        if user is None:
            return None
        return {"id": user.pk, "name": user.name or user.preferred_username}

    def get_actor(self, obj: AuditEntry) -> dict[str, Any] | None:
        return self._person(obj.actor)

    def get_target(self, obj: AuditEntry) -> dict[str, Any] | None:
        return self._person(obj.target_user)


class AuditList(serializers.Serializer[Any]):
    items = AuditEntrySerializer(many=True)
    next = serializers.CharField(allow_null=True)


class AuditQuerySerializer(serializers.Serializer[Any]):
    tenant_id = serializers.UUIDField(required=False)
