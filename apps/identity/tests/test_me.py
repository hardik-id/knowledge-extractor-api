"""GET /api/v1/me through the API with a signed token."""

import threading
import uuid
from typing import Any

import pytest
from django.db import connection
from rest_framework.test import APIClient

from apps.iam import services
from apps.iam.models import AuditEntry, Tenant, TenantMembership
from apps.iam.tests.factories import (
    PlatformAdminFactory,
    TenantFactory,
    TenantMembershipFactory,
)
from apps.identity.models import User
from apps.identity.tests.conftest import TENANT, MakeToken
from tests.shapes import check_me

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("token_config")]

URL = "/api/v1/me"


def get(token: str | None = None, url: str = URL) -> Any:
    client = APIClient(raise_request_exception=False)
    if token is not None:
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client.get(url)


def test_returns_the_signed_in_person(make_token: MakeToken) -> None:
    response = get(
        make_token(name="Ada Lovelace", preferred_username="ada@example.com")
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "id",
        "name",
        "preferred_username",
        "platform_admin",
        "tenants",
    }
    assert body["name"] == "Ada Lovelace"
    assert body["preferred_username"] == "ada@example.com"


def test_returns_only_the_callers_own_data(make_token: MakeToken) -> None:
    get(make_token(oid=str(uuid.uuid4()), name="Other", tid=TENANT))
    body = get(make_token(oid=str(uuid.uuid4()), name="Me")).json()
    assert body["name"] == "Me"


def test_without_a_token_is_401() -> None:
    response = get()
    assert response.status_code == 401
    assert response.json()["code"] == "unauthenticated"


def test_trailing_slash_is_not_a_route(make_token: MakeToken) -> None:
    assert get(make_token(), URL + "/").status_code == 404


def test_a_new_person_is_a_member_of_the_default_tenant(make_token: MakeToken) -> None:
    default = Tenant.objects.get(is_default=True)
    body = get(make_token()).json()
    check_me(body)
    assert body["platform_admin"] is False
    assert body["tenants"] == [
        {"id": str(default.pk), "name": "Default", "role": "member"}
    ]


def test_tenants_are_listed_by_name(make_token: MakeToken) -> None:
    token = make_token()
    me = get(token).json()
    user = User.objects.get(pk=me["id"])
    TenantMembershipFactory(user=user, tenant=TenantFactory(name="Alpha"), role="admin")
    names = [(t["name"], t["role"]) for t in get(token).json()["tenants"]]
    assert names == [("Alpha", "admin"), ("Default", "member")]


def test_a_listed_oid_is_a_platform_admin(make_token: MakeToken, settings: Any) -> None:
    oid = str(uuid.uuid4())
    settings.IAM_PLATFORM_ADMIN_OIDS = frozenset({uuid.UUID(oid)})
    assert get(make_token(oid=oid)).json()["platform_admin"] is True
    assert get(make_token()).json()["platform_admin"] is False


def test_a_platform_admin_row_makes_a_platform_admin(make_token: MakeToken) -> None:
    token = make_token()
    user = User.objects.get(pk=get(token).json()["id"])
    PlatformAdminFactory(user=user)
    assert get(token).json()["platform_admin"] is True


def test_a_person_removed_from_the_default_tenant_stays_removed(
    make_token: MakeToken,
) -> None:
    token = make_token()
    me = get(token).json()
    default = Tenant.objects.get(is_default=True)
    admin = TenantMembershipFactory(tenant=default, role="admin").user
    services.remove_tenant_member(admin, default.pk, me["id"])
    assert get(token).json()["tenants"] == []
    assert get(token).json()["tenants"] == []


def test_the_default_role_comes_from_the_setting(
    make_token: MakeToken, settings: Any
) -> None:
    settings.IAM_DEFAULT_TENANT_ROLE = "admin"
    assert get(make_token()).json()["tenants"][0]["role"] == "admin"
    settings.IAM_DEFAULT_TENANT_ROLE = ""
    assert get(make_token()).json()["tenants"] == []


def test_the_first_role_is_recorded_without_an_actor(make_token: MakeToken) -> None:
    get(make_token())
    entry = AuditEntry.objects.get()
    assert entry.actor is None and entry.new_role == "member"


@pytest.mark.django_db(transaction=True)
def test_two_first_requests_together_make_one_user_and_one_membership(
    make_token: MakeToken,
) -> None:
    Tenant.objects.get_or_create(is_default=True, defaults={"name": "Default"})
    token = make_token()
    barrier = threading.Barrier(6)
    failures: list[BaseException] = []

    def call() -> None:
        try:
            barrier.wait()
            assert get(token).status_code == 200
        except BaseException as error:
            failures.append(error)
        finally:
            connection.close()

    threads = [threading.Thread(target=call) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not failures
    assert User.objects.count() == 1
    assert TenantMembership.objects.count() == 1
    assert AuditEntry.objects.count() == 1
