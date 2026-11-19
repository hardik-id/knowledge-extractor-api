from typing import cast

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

from apps.documents import selectors
from apps.documents.api.serializers import DocumentListSerializer, DocumentSerializer
from apps.identity.models import User

# One page, never more: the catalog is not paged (docs/documents.md).
LIST_LIMIT = 100


@extend_schema(
    parameters=[
        OpenApiParameter(
            "q", str, description="Substring of the name or location, any case."
        )
    ],
    responses=DocumentListSerializer,
)
@api_view(["GET"])
def document_list(request: Request) -> Response:
    """The documents the signed-in person may open, newest first."""
    entries = selectors.list_documents(
        cast(User, request.user), request.query_params.get("q", "")
    )
    items = DocumentSerializer(entries[:LIST_LIMIT], many=True).data
    return Response({"items": items})
