from typing import cast

from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

from apps.assistant import selectors, services
from apps.assistant.api.serializers import (
    MessageListSerializer,
    MessageSerializer,
    SendMessageSerializer,
)
from apps.core.errors import ApiError
from apps.identity.models import User


@extend_schema(methods=["GET"], responses=MessageListSerializer)
@extend_schema(methods=["DELETE"], request=None, responses={204: None})
@extend_schema(
    methods=["POST"], request=SendMessageSerializer, responses={201: MessageSerializer}
)
@api_view(["GET", "POST", "DELETE"])
def messages(request: Request, run_id: str) -> Response:
    """The conversation with the assistant (GET), send it a message (POST), or clear it (DELETE).

    The POST answers with the person's message; the reply arrives on the run's
    socket as ``assistant.delta``, ``assistant.proposal`` and ``assistant.done``.
    """
    user = cast(User, request.user)
    if request.method == "DELETE":
        services.clear_messages(user, run_id)
        return Response(status=204)
    if request.method == "POST":
        body = request.data if isinstance(request.data, dict) else {}
        text = body.get("text") or ""
        if not isinstance(text, str):
            raise ApiError("validation_error", "text must be text.")
        sent = services.send_message(
            user, run_id, text=text, definition=body.get("definition")
        )
        return Response(MessageSerializer(sent).data, status=201)
    services.close_stale_replies(user, run_id)
    found = selectors.list_messages(user, run_id)
    return Response({"messages": MessageSerializer(found, many=True).data})
