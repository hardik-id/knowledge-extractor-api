from typing import Any

from rest_framework import serializers


class PlatformAdminSerializer(serializers.Serializer[Any]):
    user_id = serializers.IntegerField()
    name = serializers.CharField()
    source = serializers.ChoiceField(choices=["row", "setting"])  # type: ignore[assignment]


class PlatformAdminList(serializers.Serializer[Any]):
    items = PlatformAdminSerializer(many=True)
    next = serializers.CharField(allow_null=True)
