"""Bearer authentication through the API: header in, user out."""

import io
import json
import logging
import threading
import time
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps.core.logging import make_formatter
from apps.identity.tests.conftest import LocalKeys, MakeToken

pytestmark = [
    pytest.mark.urls("apps.core.tests.urls"),
    pytest.mark.django_db,
    pytest.mark.usefixtures("token_config"),
]

User = get_user_model()
CLOSED = "/api/test/whoami"  # declares nothing, so it takes the defaults
UNAUTHENTICATED = {"code": "unauthenticated", "message": "Authentication is required."}


def get(token: str | None = None, url: str = CLOSED, scheme: str = "Bearer") -> Any:
    client = APIClient(raise_request_exception=False)
    if token is not None:
        client.credentials(HTTP_AUTHORIZATION=f"{scheme} {token}")
    return client.get(url)


def assert_unauthenticated(response: Any) -> None:
    assert response.status_code == 401
    assert response.json() == UNAUTHENTICATED
    assert response["WWW-Authenticate"] == "Bearer"


def test_no_token_is_401(make_token: MakeToken) -> None:
    assert_unauthenticated(get())


def test_expired_token_is_401(make_token: MakeToken) -> None:
    assert_unauthenticated(get(make_token(exp=int(time.time()) - 3600)))


def test_token_for_another_audience_is_401(make_token: MakeToken) -> None:
    assert_unauthenticated(get(make_token(aud=str(uuid.uuid4()))))


def test_token_without_the_scope_is_401(make_token: MakeToken) -> None:
    assert_unauthenticated(get(make_token(scp="other")))


def test_garbage_token_is_401() -> None:
    assert_unauthenticated(get("not.a.token"))


def test_another_scheme_is_401(make_token: MakeToken) -> None:
    assert_unauthenticated(get(make_token(), scheme="Basic"))


def test_bearer_without_a_token_is_401() -> None:
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Bearer")
    assert_unauthenticated(client.get(CLOSED))


def test_bearer_with_two_tokens_is_401(make_token: MakeToken) -> None:
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {make_token()} extra")
    assert_unauthenticated(client.get(CLOSED))


def test_non_ascii_token_is_401() -> None:
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION="Bearer tökén")
    assert_unauthenticated(client.get(CLOSED))


def test_a_token_whose_oid_is_not_a_uuid_is_401(make_token: MakeToken) -> None:
    assert_unauthenticated(get(make_token(oid="oid-1")))
    assert not User.objects.exists()


def test_a_refused_token_creates_no_user(make_token: MakeToken) -> None:
    get(make_token(aud=str(uuid.uuid4())))
    assert not User.objects.exists()


def test_keys_that_cannot_be_fetched_are_503_not_401(
    make_token: MakeToken, key_source: LocalKeys
) -> None:
    key_source.broken = True
    response = get(make_token())
    assert response.status_code == 503
    assert response.json() == {
        "code": "not_ready",
        "message": "Sign-in is not available right now.",
    }
    assert "WWW-Authenticate" not in response


def test_a_session_login_is_not_a_sign_in() -> None:
    user = User.objects.create(username="admin")
    client = APIClient()
    client.force_login(user)
    assert_unauthenticated(client.get(CLOSED))


def test_health_stays_open() -> None:
    response = get(url="/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_a_view_that_declares_nothing_is_closed() -> None:
    assert get().status_code == 401


def test_first_valid_token_creates_the_user(make_token: MakeToken) -> None:
    oid, tid = uuid.uuid4(), uuid.UUID("11111111-1111-1111-1111-111111111111")
    response = get(make_token(oid=str(oid)))

    assert response.status_code == 200
    user = User.objects.get()
    assert response.json() == {"id": user.pk}
    assert (user.oid, user.tid) == (oid, tid)
    assert user.name == "Ada Lovelace"
    assert user.preferred_username == "ada@example.com"
    assert user.is_active
    assert not user.has_usable_password()


def test_later_calls_reuse_the_user(make_token: MakeToken) -> None:
    token = make_token()
    ids = {get(token).json()["id"] for _ in range(3)}
    assert len(ids) == 1
    assert User.objects.count() == 1


def test_another_person_is_another_user(make_token: MakeToken) -> None:
    get(make_token())
    get(make_token())
    assert User.objects.count() == 2


@pytest.mark.django_db(transaction=True)
def test_two_first_requests_at_the_same_moment_make_one_user(
    make_token: MakeToken,
) -> None:
    token = make_token()
    workers = 8
    barrier = threading.Barrier(workers)
    statuses: list[int] = []
    failures: list[BaseException] = []

    def call() -> None:
        try:
            barrier.wait()
            statuses.append(get(token).status_code)
        except BaseException as error:  # reported below, on the main thread
            failures.append(error)
        finally:
            connection.close()

    threads = [threading.Thread(target=call) for _ in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not failures
    assert statuses == [200] * workers
    assert User.objects.count() == 1


def test_a_changed_name_updates_the_record(make_token: MakeToken) -> None:
    oid = str(uuid.uuid4())
    get(make_token(oid=oid))

    get(make_token(oid=oid, name="Ada King", preferred_username="ada@king.example"))

    user = User.objects.get()
    assert user.name == "Ada King"
    assert user.preferred_username == "ada@king.example"


def test_an_unchanged_name_writes_nothing(make_token: MakeToken) -> None:
    token = make_token()
    get(token)

    with CaptureQueriesContext(connection) as queries:
        assert get(token).status_code == 200

    statements = [query["sql"] for query in queries.captured_queries]
    assert len(statements) == 1, statements
    assert statements[0].startswith("SELECT")


def test_a_claim_the_token_lacks_changes_nothing(make_token: MakeToken) -> None:
    oid = str(uuid.uuid4())
    get(make_token(oid=oid))

    get(make_token(oid=oid, name=None, preferred_username=None))

    user = User.objects.get()
    assert user.name == "Ada Lovelace"
    assert user.preferred_username == "ada@example.com"


def test_a_name_longer_than_the_column_is_cut(make_token: MakeToken) -> None:
    assert get(make_token(name="x" * 400)).status_code == 200
    assert User.objects.get().name == "x" * 255


def test_a_deactivated_user_is_403(make_token: MakeToken) -> None:
    oid = str(uuid.uuid4())
    get(make_token(oid=oid))
    User.objects.update(is_active=False)

    response = get(make_token(oid=oid))

    assert response.status_code == 403
    assert response.json() == {
        "code": "forbidden",
        "message": "You do not have permission to do this.",
    }
    assert User.objects.count() == 1


@pytest.fixture
def log_lines() -> Iterator[io.StringIO]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(make_formatter("json"))
    root = logging.getLogger()
    old_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    try:
        yield stream
    finally:
        root.removeHandler(handler)
        root.setLevel(old_level)


def test_the_person_is_in_the_log_lines(
    make_token: MakeToken, log_lines: io.StringIO
) -> None:
    token = make_token()
    user_id = get(token).json()["id"]

    lines = [json.loads(line) for line in log_lines.getvalue().splitlines() if line]
    inside = next(line for line in lines if line["event"] == "inside_whoami")
    finished = next(line for line in lines if line["event"] == "request_finished")
    assert inside["user_id"] == user_id
    assert finished["user_id"] == user_id
    assert token not in log_lines.getvalue()
