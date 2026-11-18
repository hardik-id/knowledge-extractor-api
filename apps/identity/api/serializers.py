from rest_framework import serializers

from apps.identity.models import User


class MeSerializer(serializers.ModelSerializer[User]):
    class Meta:
        model = User
        fields = ["id", "name", "preferred_username"]
        read_only_fields = fields
