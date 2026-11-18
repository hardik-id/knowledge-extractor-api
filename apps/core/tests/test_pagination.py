import pytest
from rest_framework.test import APIClient

from apps.core.pagination import DefaultPagination
from apps.core.tests.models import Note

pytestmark = [pytest.mark.urls("apps.core.tests.urls"), pytest.mark.django_db]

URL = "/api/test/notes"


def _walk(client: APIClient, query: str = "") -> list[list[str]]:
    pages = []
    cursor = None
    while True:
        params = query + (f"&cursor={cursor}" if cursor else "")
        body = client.get(f"{URL}?{params}").json()
        assert set(body) == {"items", "next"}
        pages.append([item["text"] for item in body["items"]])
        cursor = body["next"]
        if cursor is None:
            return pages


def test_empty_list() -> None:
    assert APIClient().get(URL).json() == {"items": [], "next": None}


def test_following_next_visits_every_row_once_newest_first() -> None:
    for i in range(25):
        Note.objects.create(text=f"{i:02d}")
    pages = _walk(APIClient(), "page_size=7")
    assert [len(p) for p in pages] == [7, 7, 7, 4]
    seen = [t for page in pages for t in page]
    assert seen == [f"{i:02d}" for i in reversed(range(25))]


def test_next_is_a_cursor_not_a_url() -> None:
    for i in range(3):
        Note.objects.create(text=str(i))
    body = APIClient().get(f"{URL}?page_size=2").json()
    assert body["next"] and "/" not in body["next"] and "?" not in body["next"]


def test_default_page_size() -> None:
    for i in range(DefaultPagination.page_size + 1):
        Note.objects.create(text=str(i))
    body = APIClient().get(URL).json()
    assert len(body["items"]) == DefaultPagination.page_size
    assert body["next"] is not None


def test_page_size_is_capped() -> None:
    Note.objects.bulk_create(
        [Note(text=str(i)) for i in range(DefaultPagination.max_page_size + 5)]
    )
    body = APIClient().get(f"{URL}?page_size=100000").json()
    assert len(body["items"]) == DefaultPagination.max_page_size
    assert body["next"] is not None
