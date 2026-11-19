from typing import cast

from django.http import HttpResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.decorators import api_view, parser_classes, renderer_classes
from rest_framework.negotiation import DefaultContentNegotiation
from rest_framework.renderers import JSONRenderer
from rest_framework.request import Request
from rest_framework.response import Response

from apps.documents import selectors
from apps.documents.api.serializers import DocumentListSerializer, DocumentSerializer
from apps.identity.models import User

MARKDOWN = "text/markdown; charset=utf-8"

# One page, never more: the catalog is not paged (docs/documents.md).
LIST_LIMIT = 100


@extend_schema(
    operation_id="documents_list",
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


class IgnoreAccept(DefaultContentNegotiation):
    """The success body is Markdown whatever ``Accept`` says; errors stay JSON."""

    def select_renderer(self, request, renderers, format_suffix=None):  # type: ignore[no-untyped-def]
        return (JSONRenderer(), JSONRenderer.media_type)


def _etag_matches(header: str, etag: str) -> bool:
    """Whether an ``If-None-Match`` header names ``etag`` (weak prefix ignored)."""
    if header.strip() == "*":
        return True
    wanted = f'"{etag}"'
    return any(part.strip().removeprefix("W/") == wanted for part in header.split(","))


@extend_schema(
    operation_id="documents_read",
    responses={
        (200, "text/markdown"): OpenApiTypes.STR,
        304: None,
    },
    description=(
        "The document as stored (UTF-8 Markdown, front matter included). The id "
        "contains slashes and may be percent-encoded. The `ETag` header is the "
        "`etag` of the list, quoted; `If-None-Match` with it answers 304."
    ),
)
@api_view(["GET"])
@parser_classes([])
@renderer_classes([JSONRenderer])
def document_read(request: Request, document_id: str) -> HttpResponse:
    """The text of one document, with its ETag."""
    document = selectors.read_document(cast(User, request.user), document_id)
    if _etag_matches(request.headers.get("If-None-Match", ""), document.etag):
        return HttpResponse(status=304, headers={"ETag": f'"{document.etag}"'})
    return HttpResponse(
        document.text.encode("utf-8"),
        content_type=MARKDOWN,
        headers={"ETag": f'"{document.etag}"'},
    )


document_read.cls.content_negotiation_class = IgnoreAccept
