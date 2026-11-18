"""The default pagination: ``{ "items": [...], "next": <cursor or null> }``, newest first."""

from typing import Any
from urllib.parse import parse_qs, urlparse

from rest_framework.pagination import CursorPagination
from rest_framework.response import Response


class DefaultPagination(CursorPagination):
    """Cursor paging. Ask for the next page with ``?cursor=<next>``.

    The id is a time-ordered UUID, so ordering by it descending is newest first
    and, unlike a timestamp, never ties.
    """

    ordering = "-id"
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100
    cursor_query_param = "cursor"

    def get_paginated_response(self, data: Any) -> Response:
        return Response({"items": data, "next": self._next_cursor()})

    def _next_cursor(self) -> str | None:
        link = self.get_next_link()
        if link is None:
            return None
        return parse_qs(urlparse(link).query)[self.cursor_query_param][0]
