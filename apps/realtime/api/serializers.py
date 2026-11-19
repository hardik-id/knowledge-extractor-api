from rest_framework import serializers


class WsTicketSerializer(serializers.Serializer):  # type: ignore[type-arg]
    ticket = serializers.CharField(
        read_only=True,
        help_text="Single use. Valid for WS_TICKET_TTL_SECONDS. Goes in the socket URL as ?ticket=.",
    )
