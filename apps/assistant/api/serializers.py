from typing import Any

from rest_framework import serializers

from apps.assistant.models import Message
from apps.extraction.definition import stored_chunking
from apps.extraction.validation import DraftAnswerSerializer, DraftSerializer


class ReasonSerializer(serializers.Serializer):  # type: ignore[type-arg]
    path = serializers.CharField()
    reason = serializers.CharField()


class ProposalSerializer(serializers.Serializer):  # type: ignore[type-arg]
    """A complete definition (no ``version``) and why each thing changed."""

    definition = DraftAnswerSerializer()
    reasons = ReasonSerializer(many=True)

    def to_representation(self, instance: Any) -> Any:
        """A proposal stored before configurations had a chunking reads as ``auto``."""
        if isinstance(instance, dict) and isinstance(instance.get("definition"), dict):
            chunking = stored_chunking(instance["definition"].get("chunking"))
            definition = {**instance["definition"], "chunking": chunking.model_dump()}
            instance = {**instance, "definition": definition}
        return super().to_representation(instance)


class MessageSerializer(serializers.ModelSerializer[Message]):
    proposal = ProposalSerializer(allow_null=True, read_only=True)

    class Meta:
        model = Message
        fields = ["id", "role", "text", "proposal", "status", "created_at"]


class MessageListSerializer(serializers.Serializer):  # type: ignore[type-arg]
    messages = MessageSerializer(many=True)


class SendMessageSerializer(serializers.Serializer):  # type: ignore[type-arg]
    """The body of a POST: what the person wrote and the draft on their screen."""

    text = serializers.CharField(allow_blank=True)
    definition = DraftSerializer()
