import uuid
from typing import Any

import pytest
from rest_framework.test import APIClient

from apps.core.errors import ApiError
from apps.core.permissions import get_visible_or_404
from apps.core.tests.models import SharedNote
from apps.identity.tests.factories import UserFactory

pytestmark = [pytest.mark.urls("apps.core.tests.urls"), pytest.mark.django_db]

URL = "/api/test/shared-notes"


def _client(user: Any) -> APIClient:
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def alice() -> Any:
    return UserFactory()


@pytest.fixture
def bob() -> Any:
    return UserFactory()


def test_owner_reads_own_row(alice: Any) -> None:
    note = SharedNote.objects.create(owner=alice, text="mine")
    response = _client(alice).get(f"{URL}/{note.pk}")
    assert response.status_code == 200
    assert response.json()["text"] == "mine"


def test_other_person_gets_the_same_404_as_for_a_missing_id(
    alice: Any, bob: Any
) -> None:
    note = SharedNote.objects.create(owner=alice, text="private")
    foreign = _client(bob).get(f"{URL}/{note.pk}")
    missing = _client(bob).get(f"{URL}/{uuid.uuid4()}")
    assert foreign.status_code == missing.status_code == 404
    assert (
        foreign.json()
        == missing.json()
        == {
            "code": "not_found",
            "message": "Not found.",
        }
    )


def test_malformed_id_is_a_404(alice: Any) -> None:
    assert _client(alice).get(f"{URL}/nope").status_code == 404


def test_list_does_not_contain_other_peoples_rows(alice: Any, bob: Any) -> None:
    SharedNote.objects.create(owner=alice, text="a")
    mine = SharedNote.objects.create(owner=bob, text="b")
    items = _client(bob).get(URL).json()["items"]
    assert [i["id"] for i in items] == [str(mine.pk)]


def test_helper_raises_the_resources_own_code(alice: Any, bob: Any) -> None:
    note = SharedNote.objects.create(owner=alice, text="x")
    with pytest.raises(ApiError) as error:
        get_visible_or_404(SharedNote, bob, note.pk, code="conflict")
    assert error.value.code == "conflict"
