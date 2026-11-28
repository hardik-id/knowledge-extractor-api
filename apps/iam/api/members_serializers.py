from typing import Any

from rest_framework import serializers

from apps.iam.models import TenantMembership
from apps.iam.roles import TenantRole

from .users_serializers import UserSerializer

ROLES = [role.value for role in TenantRole]


def _check_role(value: str) -> None:
    if value not in ROLES:
        raise serializers.ValidationError(f"Use one of: {', '.join(ROLES)}.")


class TenantMemberSerializer(serializers.ModelSerializer[TenantMembership]):
    user = UserSerializer(read_only=True)
    role = serializers.CharField(read_only=True)
    added_at = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = TenantMembership
        fields = ["user", "role", "added_at"]
        read_only_fields = fields


class TenantMemberListQuerySerializer(serializers.Serializer[Any]):
    search = serializers.CharField(required=False, allow_blank=True, max_length=255)


class AddTenantMemberSerializer(serializers.Serializer[Any]):
    """A sign-in name; a platform admin may give ``user_id`` instead."""

    preferred_username = serializers.CharField(required=False, max_length=255)
    user_id = serializers.IntegerField(required=False, min_value=1, max_value=2**31 - 1)
    role = serializers.CharField(validators=[_check_role])

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if ("preferred_username" in attrs) == ("user_id" in attrs):
            raise serializers.ValidationError(
                "Give either preferred_username or user_id."
            )
        return attrs


class ChangeTenantRoleSerializer(serializers.Serializer[Any]):
    role = serializers.CharField(validators=[_check_role])
