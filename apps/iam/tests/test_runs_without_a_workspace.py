"""A run with no workspace (``POST /runs``): its maker may do everything on it while
they hold a tenant role with ``workspaces.create``; nobody else sees it.

A person with no tenant role (never given one, or removed) makes no such run and
cannot use one they made before: it would be content outside every tenant.
"""

from typing import Any

import pytest
from rest_framework.test import APIClient

from apps.core.errors import ApiError
from apps.documents import selectors as documents
from apps.iam.models import TenantMembership
from apps.iam.roles import Permission
from apps.identity.tests.factories import UserFactory
from apps.runs import selectors as runs
from apps.runs.tests.factories import RunFactory

pytestmark = pytest.mark.django_db

WORKSPACE_PERMISSIONS = [p for p in Permission if p.value.startswith("workspace.")]


def _client(user: Any) -> APIClient:
    client = APIClient()
    client.force_authenticate(user)
    return client


def _code(call: Any) -> str:
    with pytest.raises(ApiError) as caught:
        call()
    return caught.value.code


def _one_document(user: Any) -> list[dict[str, Any]]:
    document = documents.list_documents(user)[0]
    return [
        {
            "source": "storage",
            "source_ref": document.id,
            "name": document.name,
            "type": "md",
            "size_bytes": 1,
            "location": "nowhere",
            "modified_at": "2000-01-01T00:00:00Z",
        }
    ]


@pytest.mark.parametrize("permission", WORKSPACE_PERMISSIONS)
def test_the_maker_has_every_permission(permission: Permission) -> None:
    run = RunFactory()
    assert runs.get_run(run.owner, run.pk, permission) == run


@pytest.mark.parametrize("permission", WORKSPACE_PERMISSIONS)
def test_another_person_does_not_see_it(permission: Permission) -> None:
    run = RunFactory()
    assert _code(lambda: runs.get_run(UserFactory(), run.pk, permission)) == (
        "run_not_found"
    )


@pytest.mark.parametrize("permission", WORKSPACE_PERMISSIONS)
def test_a_maker_removed_from_every_tenant_is_refused(permission: Permission) -> None:
    run = RunFactory()
    TenantMembership.objects.filter(user=run.owner).delete()
    assert _code(lambda: runs.get_run(run.owner, run.pk, permission)) == "forbidden"


def test_a_maker_with_no_tenant_cannot_start_or_read_it() -> None:
    run = RunFactory(owner=UserFactory(in_default_tenant=False))
    client = _client(run.owner)
    assert client.get(f"/api/v1/runs/{run.pk}").json()["code"] == "forbidden"
    started = client.post(
        f"/api/v1/runs/{run.pk}/stages/extract/executions",
        {},
        format="json",
    )
    assert started.status_code == 403
    assert started.json()["code"] == "forbidden"
    definition = client.get(f"/api/v1/runs/{run.pk}/stages/extract/definition")
    assert definition.status_code == 403


def test_a_person_with_no_tenant_cannot_make_one() -> None:
    user = UserFactory(in_default_tenant=False)
    response = _client(user).post(
        "/api/v1/runs", {"items": _one_document(user)}, format="json"
    )
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


def test_a_person_removed_from_their_tenant_cannot_make_one() -> None:
    user = UserFactory()
    TenantMembership.objects.filter(user=user).delete()
    response = _client(user).post(
        "/api/v1/runs", {"items": _one_document(user)}, format="json"
    )
    assert response.status_code == 403


def test_a_tenant_member_makes_one_and_uses_it() -> None:
    user = UserFactory()
    client = _client(user)
    made = client.post("/api/v1/runs", {"items": _one_document(user)}, format="json")
    assert made.status_code == 201
    run_id = made.json()["id"]
    assert client.get(f"/api/v1/runs/{run_id}").status_code == 200
    assert _client(UserFactory()).get(f"/api/v1/runs/{run_id}").status_code == 404
