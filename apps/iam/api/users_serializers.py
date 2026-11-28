from typing import Any

from rest_framework import serializers

from apps.identity.models import User


class UserSerializer(serializers.ModelSerializer[User]):
    class Meta:
        model = User
        fields = ["id", "name", "preferred_username"]
        read_only_fields = fields


class UserListQuerySerializer(serializers.Serializer[Any]):
    search = serializers.CharField(required=False, allow_blank=True, max_length=255)
    preferred_username = serializers.CharField(
        required=False, allow_blank=False, max_length=255
    )
