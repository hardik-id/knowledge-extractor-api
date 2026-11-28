from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.iam import selectors as iam
from apps.identity.models import User


class MeTenantSerializer(serializers.Serializer[Any]):
    id = serializers.UUIDField()
    name = serializers.CharField()
    role = serializers.CharField()


class MeSerializer(serializers.ModelSerializer[User]):
    platform_admin = serializers.SerializerMethodField()
    tenants = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "name", "preferred_username", "platform_admin", "tenants"]
        read_only_fields = fields

    def get_platform_admin(self, user: User) -> bool:
        return iam.is_platform_admin(user)

    @extend_schema_field(MeTenantSerializer(many=True))
    def get_tenants(self, user: User) -> list[dict[str, Any]]:
        return [
            {"id": str(tenant.pk), "name": tenant.name, "role": role.value}
            for tenant, role in iam.tenants_of(user)
        ]
