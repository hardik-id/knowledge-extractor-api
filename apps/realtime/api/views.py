from typing import cast

from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

from apps.iam.routes import SIGNED_IN, requires
from apps.identity.models import User
from apps.realtime import services
from apps.realtime.api.serializers import WsTicketSerializer


@requires(POST=SIGNED_IN)
@extend_schema(request=None, responses=WsTicketSerializer)
@api_view(["POST"])
def ws_ticket(request: Request) -> Response:
    """A ticket to open a WebSocket as the signed-in person. Single use, short-lived."""
    ticket = services.issue_ticket(cast(User, request.user))
    return Response(WsTicketSerializer({"ticket": ticket}).data)
