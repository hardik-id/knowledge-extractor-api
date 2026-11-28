"""Workspaces belong to a tenant and are seen through membership, through the API."""

from typing import Any

import pytest
from rest_framework.test import APIClient

from apps.iam.models import Tenant, TenantMembership, WorkspaceMembership
from apps.iam.roles import TenantRole, WorkspaceRole
from apps.iam.tests.factories import TenantFactory, TenantMembershipFactory
from apps.identity.tests.factories import UserFactory
from apps.workspaces.tests.factories import WorkspaceFactory

pytestmark = pytest.mark.django_db

URL = "/api/v1/workspaces"


def as_user(user: Any) -> APIClient:
    client = APIClient()
    client.force_authenticate(user)
    return client


def in_default(user: Any) -> Any:
    tenant = Tenant.objects.get(is_default=True)
    TenantMembership.objects.get_or_create(
        tenant=tenant, user=user, defaults={"role": TenantRole.MEMBER}
    )
    return user


def run_routes(run_id: Any) -> list[tuple[str, str]]:
    base = f"/api/v1/runs/{run_id}"
    return [
        ("get", base),
        ("get", f"{base}/definition"),
        ("get", f"{base}/definition/versions"),
        ("get", f"{base}/messages"),
        ("get", f"{base}/records"),
        ("post", f"{base}/messages"),
        ("delete", base),
    ]


def test_another_person_gets_404_everywhere_until_given_a_role() -> None:
    owner, other = in_default(UserFactory()), in_default(UserFactory())
    workspace = WorkspaceFactory(owner=owner)
    run_id = workspace.run_id
    client = as_user(other)

    def answers() -> set[int]:
        out = {client.get(f"{URL}/{workspace.pk}").status_code}
        out.add(
            client.patch(
                f"{URL}/{workspace.pk}", {"name": "x"}, format="json"
            ).status_code
        )
        out.add(client.delete(f"{URL}/{workspace.pk}").status_code)
        for method, path in run_routes(run_id):
            out.add(getattr(client, method)(path, {}, format="json").status_code)
        return out

    assert answers() == {404}
    assert client.get(URL).json()["items"] == []

    row = WorkspaceMembership.objects.create(
        workspace=workspace, user=other, role=WorkspaceRole.VIEWER
    )
    assert client.get(f"{URL}/{workspace.pk}").status_code == 200
    assert client.get(f"/api/v1/runs/{run_id}").status_code == 200
    assert [w["id"] for w in client.get(URL).json()["items"]] == [str(workspace.pk)]

    row.delete()
    assert answers() == {404}


def test_a_run_without_a_workspace_stays_with_its_owner() -> None:
    from apps.runs.tests.factories import RunFactory

    owner, other = in_default(UserFactory()), in_default(UserFactory())
    run = RunFactory(owner=owner)
    assert as_user(owner).get(f"/api/v1/runs/{run.pk}").status_code == 200
    assert as_user(other).get(f"/api/v1/runs/{run.pk}").status_code == 404


def test_the_maker_keeps_no_access_without_a_role() -> None:
    owner = in_default(UserFactory())
    workspace = WorkspaceFactory(owner=owner, owner_role="none")
    client = as_user(owner)
    assert client.get(f"{URL}/{workspace.pk}").status_code == 404
    assert client.get(f"/api/v1/runs/{workspace.run_id}").status_code == 404


def test_the_creator_becomes_owner_and_it_is_audited(user: Any) -> None:
    from apps.iam.models import AuditEntry

    body = as_user(user).post(URL, {"name": "Mine"}, format="json").json()
    assert body["role"] == "owner"
    assert body["tenant_id"] == str(Tenant.objects.get(is_default=True).pk)
    assert body["permissions"] == sorted(body["permissions"])
    assert "workspace.manage" in body["permissions"]
    row = WorkspaceMembership.objects.get(workspace_id=body["id"])
    assert (row.user, row.role) == (user, "owner")
    entry = AuditEntry.objects.get(workspace_id=body["id"])
    assert (entry.action, entry.actor, entry.target_user, entry.new_role) == (
        "workspace.role.set",
        user,
        user,
        "owner",
    )


def test_role_and_permissions_follow_the_membership() -> None:
    owner, other = in_default(UserFactory()), in_default(UserFactory())
    workspace = WorkspaceFactory(owner=owner)
    WorkspaceMembership.objects.create(
        workspace=workspace, user=other, role=WorkspaceRole.VIEWER
    )
    body = as_user(other).get(f"{URL}/{workspace.pk}").json()
    assert (body["role"], body["permissions"]) == ("viewer", ["workspace.view"])
    assert as_user(other).get(URL).json()["items"][0]["permissions"] == [
        "workspace.view"
    ]


def test_a_person_in_two_tenants_must_say_which(user: Any) -> None:
    second = TenantMembershipFactory(user=user, tenant=TenantFactory()).tenant
    client = as_user(user)
    response = client.post(URL, {"name": "Which"}, format="json")
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    made = client.post(
        URL, {"name": "Which", "tenant_id": str(second.pk)}, format="json"
    )
    assert made.status_code == 201
    assert made.json()["tenant_id"] == str(second.pk)


def test_a_tenant_the_person_is_not_in_is_404(user: Any) -> None:
    other = TenantFactory()
    for value in (str(other.pk), "not-a-uuid"):
        response = as_user(user).post(
            URL, {"name": "No", "tenant_id": value}, format="json"
        )
        assert response.status_code in (404, 422)
    response = as_user(user).post(
        URL, {"name": "No", "tenant_id": str(other.pk)}, format="json"
    )
    assert (response.status_code, response.json()["code"]) == (404, "tenant_not_found")


def test_a_person_in_no_tenant_cannot_create() -> None:
    response = as_user(UserFactory(in_default_tenant=False)).post(
        URL, {"name": "None"}, format="json"
    )
    assert response.status_code == 403


def test_the_list_filters_by_tenant(user: Any) -> None:
    second = TenantMembershipFactory(user=user, tenant=TenantFactory()).tenant
    client = as_user(user)
    one = client.post(URL, {"name": "A", "tenant_id": str(second.pk)}, format="json")
    default = Tenant.objects.get(is_default=True)
    two = client.post(URL, {"name": "B", "tenant_id": str(default.pk)}, format="json")
    assert len(client.get(URL).json()["items"]) == 2
    only = client.get(URL, {"tenant_id": str(second.pk)}).json()["items"]
    assert [w["id"] for w in only] == [one.json()["id"]]
    assert two.status_code == 201
    assert client.get(URL, {"tenant_id": "x"}).status_code == 422


def test_selectors_say_the_role_and_permissions() -> None:
    from apps.iam import selectors

    owner, stranger = in_default(UserFactory()), in_default(UserFactory())
    workspace = WorkspaceFactory(owner=owner)
    assert selectors.workspace_role(owner, workspace.pk) == "owner"
    assert "workspace.manage" in selectors.workspace_permissions(owner, workspace.pk)
    assert selectors.workspace_role(stranger, workspace.pk) is None
    assert selectors.workspace_permissions(stranger, workspace.pk) == []
    assert selectors.workspace_role(owner, "nope") is None
