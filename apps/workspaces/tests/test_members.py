"""A workspace's members, through the API: who sees and changes them, and the rules."""

import threading
from collections.abc import Callable
from typing import Any

import pytest
from django.db import connection, transaction
from rest_framework.test import APIClient
from structlog.testing import capture_logs

from apps.core.errors import ApiError
from apps.iam import workspace_members
from apps.iam.models import AuditEntry, TenantMembership, WorkspaceMembership
from apps.iam.tests.factories import (
    PlatformAdminFactory,
    TenantFactory,
    TenantMembershipFactory,
)
from apps.identity.tests.factories import UserFactory
from apps.workspaces.tests.factories import WorkspaceFactory
from tests import shapes

pytestmark = pytest.mark.django_db


def as_user(user: Any) -> APIClient:
    client = APIClient()
    client.force_authenticate(user)
    return client


def url(workspace: Any, user: Any = None) -> str:
    base = f"/api/v1/workspaces/{workspace.pk}/members"
    return base if user is None else f"{base}/{user.pk}"


def role_of(workspace: Any, user: Any) -> str | None:
    return (
        WorkspaceMembership.objects.filter(workspace=workspace, user=user)
        .values_list("role", flat=True)
        .first()
    )


def join(workspace: Any, role: str, **kwargs: Any) -> Any:
    user = UserFactory(**kwargs)
    WorkspaceMembership.objects.create(workspace=workspace, user=user, role=role)
    return user


def tenant_admin(workspace: Any) -> Any:
    user = UserFactory()
    TenantMembership.objects.filter(user=user, tenant=workspace.tenant).update(
        role="admin"
    )
    return user


def code(response: Any) -> str:
    return str(response.json()["code"])


# --- reading ------------------------------------------------------------------


def test_the_list_has_owners_first_then_by_name() -> None:
    workspace = WorkspaceFactory(owner=UserFactory(name="Zed"))
    join(workspace, "viewer", name="Bea", preferred_username="bea@x.org")
    join(workspace, "editor", name="Al")
    join(workspace, "owner", name="Mo")

    response = as_user(workspace.owner).get(url(workspace))

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"items"}
    assert [(i["user"]["name"], i["role"]) for i in body["items"]] == [
        ("Mo", "owner"),
        ("Zed", "owner"),
        ("Al", "editor"),
        ("Bea", "viewer"),
    ]
    bea = body["items"][3]
    assert set(bea) == {"user", "role", "added_at"}
    assert set(bea["user"]) == {"id", "name", "preferred_username"}
    assert bea["user"]["preferred_username"] == "bea@x.org"
    for index, item in enumerate(body["items"]):
        shapes.check_workspace_member(item, f"items[{index}]")


@pytest.mark.parametrize("role", ["owner", "editor", "viewer"])
def test_everyone_with_a_role_reads_the_list(role: str) -> None:
    workspace = WorkspaceFactory()
    person = join(workspace, role)
    assert as_user(person).get(url(workspace)).status_code == 200


def test_a_tenant_admin_and_a_platform_admin_who_are_not_members_read_the_list() -> (
    None
):
    workspace = WorkspaceFactory()
    for person in (tenant_admin(workspace), PlatformAdminFactory().user):
        assert not WorkspaceMembership.objects.filter(user=person).exists()
        assert as_user(person).get(url(workspace)).status_code == 200


def test_a_stranger_and_an_outsider_get_404() -> None:
    workspace = WorkspaceFactory()
    stranger = UserFactory()
    outsider = TenantMembershipFactory(tenant=TenantFactory()).user
    for person in (stranger, outsider):
        response = as_user(person).get(url(workspace))
        assert (response.status_code, code(response)) == (404, "workspace_not_found")


def test_an_unknown_workspace_is_404() -> None:
    response = as_user(UserFactory()).get(
        "/api/v1/workspaces/00000000-0000-0000-0000-000000000000/members"
    )
    assert (response.status_code, code(response)) == (404, "workspace_not_found")


# --- who may change -----------------------------------------------------------


def test_an_owner_adds_and_changes_a_member() -> None:
    workspace = WorkspaceFactory()
    other = UserFactory()

    added = as_user(workspace.owner).put(
        url(workspace, other), {"role": "viewer"}, format="json"
    )
    assert added.status_code == 200
    body = added.json()
    shapes.check_workspace_member(body, "member")
    assert body["role"] == "viewer"
    assert body["user"]["id"] == other.pk

    changed = as_user(workspace.owner).put(
        url(workspace, other), {"role": "editor"}, format="json"
    )
    assert (changed.status_code, changed.json()["role"]) == (200, "editor")
    assert (
        WorkspaceMembership.objects.filter(workspace=workspace, user=other).count() == 1
    )


@pytest.mark.parametrize("role", ["editor", "viewer"])
def test_an_editor_and_a_viewer_may_not_change_members(role: str) -> None:
    workspace = WorkspaceFactory()
    person, other = join(workspace, role), UserFactory()
    client = as_user(person)
    before = AuditEntry.objects.count()

    put = client.put(url(workspace, other), {"role": "viewer"}, format="json")
    delete = client.delete(url(workspace, workspace.owner))

    assert (put.status_code, code(put)) == (403, "forbidden")
    assert (delete.status_code, code(delete)) == (403, "forbidden")
    assert role_of(workspace, other) is None
    assert AuditEntry.objects.count() == before


def test_a_stranger_and_an_outsider_cannot_change_and_cannot_tell_it_exists() -> None:
    workspace = WorkspaceFactory()
    other = UserFactory()
    for person in (UserFactory(), TenantMembershipFactory().user):
        put = as_user(person).put(
            url(workspace, other), {"role": "viewer"}, format="json"
        )
        delete = as_user(person).delete(url(workspace, workspace.owner))
        assert (put.status_code, code(put)) == (404, "workspace_not_found")
        assert (delete.status_code, code(delete)) == (404, "workspace_not_found")


@pytest.mark.parametrize("kind", ["tenant_admin", "platform_admin"])
def test_an_admin_who_is_not_a_member_manages_members_but_not_the_content(
    kind: str,
) -> None:
    workspace = WorkspaceFactory()
    person = (
        tenant_admin(workspace)
        if kind == "tenant_admin"
        else PlatformAdminFactory().user
    )
    other = UserFactory()
    client = as_user(person)

    put = client.put(url(workspace, other), {"role": "editor"}, format="json")

    assert put.status_code == 200
    assert role_of(workspace, other) == "editor"
    assert client.get(f"/api/v1/workspaces/{workspace.pk}").status_code == 404
    assert client.get(f"/api/v1/runs/{workspace.run_id}").status_code == 404
    assert client.delete(url(workspace, other)).status_code == 204


def test_an_admin_adds_themselves_and_it_is_recorded() -> None:
    workspace = WorkspaceFactory()
    admin = tenant_admin(workspace)
    client = as_user(admin)

    response = client.put(url(workspace, admin), {"role": "viewer"}, format="json")

    assert response.status_code == 200
    assert client.get(f"/api/v1/workspaces/{workspace.pk}").status_code == 200
    entry = AuditEntry.objects.get(action="workspace.role.set", target_user=admin)
    assert entry.actor == admin and entry.workspace_id == workspace.pk
    assert (entry.old_role, entry.new_role) == ("", "viewer")


# --- the rules ----------------------------------------------------------------


def test_only_a_member_of_the_tenant_can_be_given_a_role() -> None:
    workspace = WorkspaceFactory()
    client = as_user(workspace.owner)
    outsider = TenantMembershipFactory(tenant=TenantFactory()).user
    no_tenant = UserFactory(in_default_tenant=False)
    nobody = "999999999"

    answers = [
        client.put(url(workspace, outsider), {"role": "viewer"}, format="json"),
        client.put(url(workspace, no_tenant), {"role": "viewer"}, format="json"),
        client.put(
            f"/api/v1/workspaces/{workspace.pk}/members/{nobody}",
            {"role": "viewer"},
            format="json",
        ),
        client.put(
            f"/api/v1/workspaces/{workspace.pk}/members/not-a-number",
            {"role": "viewer"},
            format="json",
        ),
    ]

    assert [(a.status_code, code(a)) for a in answers] == [
        (422, "not_a_tenant_member")
    ] * 4
    assert answers[0].json() == answers[2].json()
    assert WorkspaceMembership.objects.filter(workspace=workspace).count() == 1


def test_a_role_must_be_one_of_the_three() -> None:
    workspace = WorkspaceFactory()
    response = as_user(workspace.owner).put(
        url(workspace, UserFactory()), {"role": "admin"}, format="json"
    )
    assert (response.status_code, code(response)) == (422, "validation_error")
    missing = as_user(workspace.owner).put(
        url(workspace, UserFactory()), {}, format="json"
    )
    assert missing.status_code == 422


def test_the_last_owner_cannot_step_down_or_be_removed() -> None:
    workspace = WorkspaceFactory()
    client = as_user(workspace.owner)
    before = AuditEntry.objects.count()

    down = client.put(
        url(workspace, workspace.owner), {"role": "editor"}, format="json"
    )
    out = client.delete(url(workspace, workspace.owner))

    assert [(r.status_code, code(r)) for r in (down, out)] == [(409, "last_owner")] * 2
    assert role_of(workspace, workspace.owner) == "owner"
    assert AuditEntry.objects.count() == before


def test_an_admin_cannot_remove_the_last_owner_either() -> None:
    workspace = WorkspaceFactory()
    response = as_user(tenant_admin(workspace)).delete(url(workspace, workspace.owner))
    assert (response.status_code, code(response)) == (409, "last_owner")


def test_an_owner_may_step_down_or_leave_when_another_owner_stays() -> None:
    workspace = WorkspaceFactory()
    second = join(workspace, "owner")
    third = join(workspace, "owner")

    down = as_user(second).put(
        url(workspace, second), {"role": "viewer"}, format="json"
    )
    out = as_user(workspace.owner).delete(url(workspace, workspace.owner))

    assert (down.status_code, out.status_code) == (200, 204)
    assert role_of(workspace, second) == "viewer"
    assert role_of(workspace, workspace.owner) is None
    assert role_of(workspace, third) == "owner"


def test_an_inactive_owner_does_not_count() -> None:
    workspace = WorkspaceFactory()
    join(workspace, "owner", is_active=False)
    response = as_user(workspace.owner).delete(url(workspace, workspace.owner))
    assert code(response) == "last_owner"


def test_removing_someone_who_is_not_a_member_is_404() -> None:
    workspace = WorkspaceFactory()
    for who in (UserFactory(), "999999999", "x"):
        response = as_user(workspace.owner).delete(
            url(workspace, who)
            if not isinstance(who, str)
            else f"/api/v1/workspaces/{workspace.pk}/members/{who}"
        )
        assert (response.status_code, code(response)) == (404, "user_not_found")


def test_a_removed_member_gets_404_at_the_next_request() -> None:
    workspace = WorkspaceFactory()
    editor = join(workspace, "editor")
    client = as_user(editor)
    assert client.get(f"/api/v1/workspaces/{workspace.pk}").status_code == 200

    assert as_user(workspace.owner).delete(url(workspace, editor)).status_code == 204

    for path in (
        f"/api/v1/workspaces/{workspace.pk}",
        url(workspace),
        f"/api/v1/runs/{workspace.run_id}",
    ):
        response = client.get(path)
        assert response.status_code == 404, path


def test_the_same_role_changes_nothing_and_records_nothing() -> None:
    workspace = WorkspaceFactory()
    other = join(workspace, "editor")
    before = AuditEntry.objects.count()
    response = as_user(workspace.owner).put(
        url(workspace, other), {"role": "editor"}, format="json"
    )
    assert response.status_code == 200
    assert AuditEntry.objects.count() == before


# --- the record ---------------------------------------------------------------


def test_each_change_is_one_audit_entry() -> None:
    workspace = WorkspaceFactory()
    other = UserFactory()
    client = as_user(workspace.owner)
    before = AuditEntry.objects.count()

    with capture_logs() as logs:
        client.put(url(workspace, other), {"role": "viewer"}, format="json")
        client.put(url(workspace, other), {"role": "editor"}, format="json")
        client.delete(url(workspace, other))

    entries = list(AuditEntry.objects.order_by("created_at", "pk"))[before:]
    assert [(e.action, e.old_role, e.new_role) for e in entries] == [
        ("workspace.role.set", "", "viewer"),
        ("workspace.role.set", "viewer", "editor"),
        ("workspace.member.remove", "editor", ""),
    ]
    for entry in entries:
        assert entry.actor == workspace.owner and entry.target_user == other
        assert entry.workspace_id == workspace.pk
        assert entry.tenant_id == workspace.tenant_id
    assert [e["event"] for e in logs].count("iam.changed") == 3


def test_a_refused_change_leaves_no_entry() -> None:
    workspace = WorkspaceFactory()
    before = AuditEntry.objects.count()
    as_user(workspace.owner).delete(url(workspace, workspace.owner))
    as_user(workspace.owner).put(
        url(workspace, TenantMembershipFactory().user),
        {"role": "viewer"},
        format="json",
    )
    assert AuditEntry.objects.count() == before


# --- the wire of a workspace --------------------------------------------------


def test_an_admin_with_a_role_has_the_members_permission_on_the_wire() -> None:
    workspace = WorkspaceFactory()
    admin = tenant_admin(workspace)
    WorkspaceMembership.objects.create(workspace=workspace, user=admin, role="viewer")
    viewer = join(workspace, "viewer")
    platform = PlatformAdminFactory().user
    WorkspaceMembership.objects.create(
        workspace=workspace, user=platform, role="viewer"
    )
    manage = "workspace.members.manage"

    def held(person: Any) -> list[str]:
        client = as_user(person)
        one = client.get(f"/api/v1/workspaces/{workspace.pk}").json()["permissions"]
        listed = client.get("/api/v1/workspaces").json()["items"][0]["permissions"]
        assert one == listed
        return list(one)

    assert manage in held(admin)
    assert manage in held(platform)
    assert manage in held(workspace.owner)
    assert manage not in held(viewer)
    assert held(viewer) == ["workspace.view"]


# --- two at the same moment ---------------------------------------------------


def run_together(calls: list[Callable[[], Any]]) -> list[str | None]:
    barrier = threading.Barrier(len(calls))
    results: list[str | None] = [None] * len(calls)
    crashed: list[BaseException] = []

    def run(i: int) -> None:
        try:
            barrier.wait()
            calls[i]()
        except ApiError as error:
            results[i] = error.code
        except BaseException as error:  # reported on the main thread
            crashed.append(error)
        finally:
            connection.close()

    threads = [threading.Thread(target=run, args=(i,)) for i in range(len(calls))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not crashed, crashed
    return results


@pytest.mark.django_db(transaction=True)
def test_two_owners_stepping_down_together_leave_one() -> None:
    workspace = WorkspaceFactory()
    other = join(workspace, "owner")
    a, b = workspace.owner, other
    results = run_together(
        [
            lambda: workspace_members.set_workspace_role(
                a, workspace.pk, a.pk, "viewer"
            ),
            lambda: workspace_members.set_workspace_role(
                b, workspace.pk, b.pk, "viewer"
            ),
        ]
    )
    assert sorted(r or "" for r in results) == ["", "last_owner"]
    assert (
        WorkspaceMembership.objects.filter(workspace=workspace, role="owner").count()
        == 1
    )


@pytest.mark.django_db(transaction=True)
def test_an_owner_leaving_and_the_other_stepping_down_together_leave_one() -> None:
    workspace = WorkspaceFactory()
    a, b = workspace.owner, join(workspace, "owner")
    results = run_together(
        [
            lambda: workspace_members.remove_workspace_member(a, workspace.pk, a.pk),
            lambda: workspace_members.set_workspace_role(
                b, workspace.pk, b.pk, "editor"
            ),
        ]
    )
    assert sorted(r or "" for r in results) == ["", "last_owner"]
    assert (
        WorkspaceMembership.objects.filter(workspace=workspace, role="owner").count()
        == 1
    )


@pytest.mark.django_db(transaction=True)
def test_a_role_given_while_the_person_leaves_the_tenant_waits_for_it() -> None:
    workspace = WorkspaceFactory()
    person = UserFactory()
    outcome: list[str] = []

    def put() -> None:
        try:
            workspace_members.set_workspace_role(
                workspace.owner, workspace.pk, person.pk, "viewer"
            )
            outcome.append("")
        except ApiError as error:
            outcome.append(error.code)
        finally:
            connection.close()

    with transaction.atomic():
        row = TenantMembership.objects.select_for_update().get(
            tenant=workspace.tenant, user=person
        )
        thread = threading.Thread(target=put)
        thread.start()
        thread.join(0.7)  # blocked on the row the removal holds
        assert thread.is_alive()
        row.delete()
    thread.join()

    assert outcome == ["not_a_tenant_member"]
    assert role_of(workspace, person) is None


@pytest.mark.parametrize("role", ["editor", "viewer"])
def test_a_person_may_remove_themselves_whatever_their_role(role: str) -> None:
    workspace = WorkspaceFactory()
    person, other = join(workspace, role), join(workspace, "viewer")

    assert as_user(person).delete(url(workspace, other)).status_code == 403
    assert as_user(person).delete(url(workspace, person)).status_code == 204
    assert role_of(workspace, person) is None
    assert AuditEntry.objects.filter(action="workspace.member.remove").count() == 1


def test_an_id_with_underscores_or_unicode_digits_is_not_a_person() -> None:
    workspace = WorkspaceFactory()
    person = UserFactory()
    for bad in (
        f"{person.pk}_",
        f" {person.pk}",
        "".join(chr(0x660 + int(c)) for c in str(person.pk)),
    ):
        with pytest.raises(ApiError) as error:
            workspace_members.set_workspace_role(
                workspace.owner, workspace.pk, bad, "viewer"
            )
        assert error.value.code == "not_a_tenant_member"
    assert role_of(workspace, person) is None
