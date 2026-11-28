"""Tenants, a tenant's workspaces, platform admins and the audit list, through the API."""

from typing import Any

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from apps.assistant.tests.factories import MessageFactory
from apps.iam import services
from apps.iam.models import AuditEntry, PlatformAdmin, Tenant, WorkspaceMembership
from apps.iam.roles import TenantRole, WorkspaceRole
from apps.iam.tests.factories import (
    AuditEntryFactory,
    PlatformAdminFactory,
    TenantFactory,
    TenantMembershipFactory,
)
from apps.identity.tests.factories import UserFactory
from apps.workspaces.tests.factories import WorkspaceFactory

pytestmark = pytest.mark.django_db


def as_(user: Any) -> APIClient:
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def admin() -> Any:
    return PlatformAdminFactory().user


def tenant_admin(tenant: Tenant) -> Any:
    return TenantMembershipFactory(tenant=tenant, role=TenantRole.ADMIN).user


def member(tenant: Tenant) -> Any:
    return TenantMembershipFactory(tenant=tenant, role=TenantRole.MEMBER).user


def code(response: Any) -> str:
    return str(response.json()["code"])


# --- tenants -------------------------------------------------------------------


def test_a_platform_admin_lists_every_tenant_with_counts(admin: Any) -> None:
    tenant = TenantFactory(name="Acme")
    member(tenant)
    member(tenant)
    WorkspaceFactory(tenant=tenant)

    response = as_(admin).get("/api/v1/tenants")

    assert response.status_code == 200
    rows = {t["name"]: t for t in response.json()["items"]}
    assert set(rows) == {"Default", "Acme"}
    assert rows["Acme"]["member_count"] == 2
    assert rows["Acme"]["workspace_count"] == 1
    assert rows["Default"]["role"] == "member"  # a first sign-in makes them one
    assert rows["Acme"]["role"] is None
    assert response.json()["next"] is None


def test_anyone_else_lists_only_their_own_tenants_without_counts() -> None:
    mine, other = TenantFactory(name="Mine"), TenantFactory(name="Other")
    person = tenant_admin(mine)
    member(other)

    items = as_(person).get("/api/v1/tenants").json()["items"]

    assert [(t["name"], t["role"]) for t in items] == [("Mine", "admin")]
    assert items[0]["member_count"] is None
    assert items[0]["workspace_count"] is None


def test_a_platform_admin_makes_a_tenant_and_it_is_recorded(admin: Any) -> None:
    response = as_(admin).post("/api/v1/tenants", {"name": "  Acme "}, format="json")

    assert response.status_code == 201
    assert response.json()["name"] == "Acme"
    entry = AuditEntry.objects.get(action="tenant.create")
    assert str(entry.tenant_id) == response.json()["id"]
    assert entry.actor == admin


@pytest.mark.parametrize("name", ["Acme", "ACME", "acme"])
def test_a_name_is_unique_without_regard_to_case(admin: Any, name: str) -> None:
    TenantFactory(name="Acme")

    response = as_(admin).post("/api/v1/tenants", {"name": name}, format="json")

    assert response.status_code == 409
    assert code(response) == "tenant_name_taken"
    assert not AuditEntry.objects.filter(action="tenant.create").exists()


def test_a_name_is_required(admin: Any) -> None:
    assert as_(admin).post("/api/v1/tenants", {}, format="json").status_code == 422
    assert (
        as_(admin).post("/api/v1/tenants", {"name": " "}, format="json").status_code
        == 422
    )


def test_rename_a_tenant(admin: Any) -> None:
    tenant = TenantFactory(name="Acme")
    TenantFactory(name="Taken")

    renamed = as_(admin).patch(
        f"/api/v1/tenants/{tenant.pk}", {"name": "Globex"}, format="json"
    )
    clash = as_(admin).patch(
        f"/api/v1/tenants/{tenant.pk}", {"name": "TAKEN"}, format="json"
    )
    same_but_case = as_(admin).patch(
        f"/api/v1/tenants/{tenant.pk}", {"name": "GLOBEX"}, format="json"
    )

    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Globex"
    assert code(clash) == "tenant_name_taken"
    assert same_but_case.status_code == 200  # its own name, in other letters
    assert AuditEntry.objects.filter(action="tenant.rename", tenant=tenant).count() == 2


def test_an_unknown_tenant_is_404(admin: Any) -> None:
    for call in (
        as_(admin).patch("/api/v1/tenants/not-an-id", {"name": "X"}, format="json"),
        as_(admin).delete("/api/v1/tenants/018f0000-0000-7000-8000-000000000000"),
    ):
        assert call.status_code == 404
        assert code(call) == "tenant_not_found"


@pytest.mark.parametrize("method", ["post", "patch", "delete"])
def test_only_a_platform_admin_manages_tenants(method: str) -> None:
    tenant = TenantFactory()
    person = tenant_admin(tenant)
    url = "/api/v1/tenants" if method == "post" else f"/api/v1/tenants/{tenant.pk}"

    response = getattr(as_(person), method)(url, {"name": "New"}, format="json")

    assert response.status_code == 403
    assert code(response) == "forbidden"
    tenant.refresh_from_db()
    assert Tenant.objects.filter(pk=tenant.pk).exists()


def test_delete_an_empty_tenant(admin: Any) -> None:
    tenant = TenantFactory()
    member(tenant)

    response = as_(admin).delete(f"/api/v1/tenants/{tenant.pk}")

    assert response.status_code == 204
    assert not Tenant.objects.filter(pk=tenant.pk).exists()
    entry = AuditEntry.objects.get(action="tenant.delete")
    assert entry.actor == admin  # the entry stays


def test_deleting_a_tenant_records_each_member_and_keeps_its_identity(
    admin: Any,
) -> None:
    tenant = TenantFactory(name="Bank")
    boss = tenant_admin(tenant)
    person = member(tenant)

    assert as_(admin).delete(f"/api/v1/tenants/{tenant.pk}").status_code == 204

    removed = AuditEntry.objects.filter(action="tenant.member.remove")
    assert {(e.target_user_id, e.old_role) for e in removed} == {
        (boss.pk, "admin"),
        (person.pk, "member"),
    }
    gone = AuditEntry.objects.get(action="tenant.delete")
    assert gone.tenant_ref == tenant.pk
    assert gone.detail == "name=Bank"
    items = as_(admin).get("/api/v1/audit").json()["items"]
    mine = [i for i in items if i["tenant_id"] == str(tenant.pk)]
    assert len(mine) == 3


def test_a_rename_records_both_names(admin: Any) -> None:
    tenant = TenantFactory(name="Acme")

    as_(admin).patch(f"/api/v1/tenants/{tenant.pk}", {"name": "Globex"}, format="json")

    assert (
        AuditEntry.objects.get(action="tenant.rename").detail == "from=Acme; to=Globex"
    )


def test_a_workspace_made_during_the_delete_answers_409(
    admin: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from django.db.models.deletion import ProtectedError

    tenant = TenantFactory()

    def refuse(self: Any, *a: Any, **k: Any) -> Any:
        raise ProtectedError("in use", set())

    monkeypatch.setattr(Tenant, "delete", refuse)

    response = as_(admin).delete(f"/api/v1/tenants/{tenant.pk}")

    assert response.status_code == 409
    assert code(response) == "tenant_not_empty"
    assert not AuditEntry.objects.filter(action="tenant.delete").exists()


def test_a_forged_cursor_is_404_not_500(admin: Any) -> None:
    import base64

    tenant = TenantFactory()
    WorkspaceFactory(tenant=tenant)
    for position in ("x", "2026-13-99"):
        cursor = base64.b64encode(f"p={position}".encode()).decode()
        response = as_(admin).get(
            f"/api/v1/tenants/{tenant.pk}/workspaces?cursor={cursor}"
        )
        assert response.status_code == 404


def test_a_person_without_a_name_shows_no_sign_in_name(admin: Any) -> None:
    person = UserFactory(name="", preferred_username="jane.doe@bank.example")
    tenant = TenantFactory()
    services.set_tenant_role(admin, tenant.pk, person.pk, "member")

    body = as_(admin).get(f"/api/v1/audit?tenant_id={tenant.pk}").content.decode()

    assert "jane.doe" not in body
    assert f"Person {person.pk}" in body


def test_a_tenant_with_workspaces_is_not_deleted(admin: Any) -> None:
    tenant = TenantFactory()
    WorkspaceFactory(tenant=tenant)

    response = as_(admin).delete(f"/api/v1/tenants/{tenant.pk}")

    assert response.status_code == 409
    assert code(response) == "tenant_not_empty"
    assert Tenant.objects.filter(pk=tenant.pk).exists()
    assert not AuditEntry.objects.filter(action="tenant.delete").exists()


def test_the_default_tenant_is_never_deleted(admin: Any) -> None:
    default = Tenant.objects.get(is_default=True)

    response = as_(admin).delete(f"/api/v1/tenants/{default.pk}")

    assert response.status_code == 409
    assert code(response) == "default_tenant"


# --- a tenant's workspaces -----------------------------------------------------


def test_the_workspaces_of_a_tenant_show_owners_counts_and_no_content(
    admin: Any,
) -> None:
    tenant = TenantFactory()
    boss = tenant_admin(tenant)
    workspace = WorkspaceFactory(tenant=tenant, name="ADRs", description="secret text")
    WorkspaceMembership.objects.create(
        workspace=workspace, user=member(tenant), role=WorkspaceRole.VIEWER
    )
    MessageFactory(run=workspace.run, text="private conversation")

    for who in (boss, admin):
        response = as_(who).get(f"/api/v1/tenants/{tenant.pk}/workspaces")
        assert response.status_code == 200
        (item,) = response.json()["items"]
        assert set(item) == {
            "id",
            "name",
            "owners",
            "member_count",
            "no_owner",
            "last_activity",
            "created_at",
        }
        assert item["name"] == "ADRs"
        assert item["owners"] == [
            {"id": workspace.owner_id, "name": workspace.owner.name}
        ]
        assert item["member_count"] == 2
        assert item["no_owner"] is False
        assert "private conversation" not in response.content.decode()
        assert "secret text" not in response.content.decode()


def test_a_workspace_with_no_owner_says_so() -> None:
    tenant = TenantFactory()
    boss = tenant_admin(tenant)
    WorkspaceFactory(tenant=tenant, owner_role="none")

    (item,) = as_(boss).get(f"/api/v1/tenants/{tenant.pk}/workspaces").json()["items"]

    assert item["no_owner"] is True
    assert item["owners"] == []
    assert item["member_count"] == 0


def test_the_workspaces_of_a_tenant_are_only_that_tenants_and_paged() -> None:
    tenant = TenantFactory()
    boss = tenant_admin(tenant)
    for _ in range(3):
        WorkspaceFactory(tenant=tenant)
    WorkspaceFactory()  # Default's

    client = as_(boss)
    first = client.get(f"/api/v1/tenants/{tenant.pk}/workspaces?page_size=2").json()
    second = client.get(
        f"/api/v1/tenants/{tenant.pk}/workspaces?page_size=2&cursor={first['next']}"
    ).json()

    assert len(first["items"]) == 2
    assert len(second["items"]) == 1
    assert second["next"] is None
    assert not {i["id"] for i in first["items"]} & {i["id"] for i in second["items"]}


def test_a_member_may_not_list_a_tenants_workspaces_and_an_outsider_does_not_see_it() -> (
    None
):
    tenant = TenantFactory()
    url = f"/api/v1/tenants/{tenant.pk}/workspaces"

    refused = as_(member(tenant)).get(url)
    hidden = as_(UserFactory(in_default_tenant=False)).get(url)

    assert (refused.status_code, code(refused)) == (403, "forbidden")
    assert (hidden.status_code, code(hidden)) == (404, "tenant_not_found")


# --- platform admins -----------------------------------------------------------


def test_list_grant_and_revoke_platform_admins(admin: Any) -> None:
    person = UserFactory(name="Pat")
    client = as_(admin)

    granted = client.put(f"/api/v1/platform-admins/{person.pk}")
    listed = client.get("/api/v1/platform-admins").json()["items"]
    removed = client.delete(f"/api/v1/platform-admins/{person.pk}")

    assert granted.status_code == 200
    assert granted.json() == {"user_id": person.pk, "name": "Pat", "source": "row"}
    assert {"user_id": person.pk, "name": "Pat", "source": "row"} in listed
    assert removed.status_code == 204
    assert not PlatformAdmin.objects.filter(user=person).exists()
    assert [e.action for e in AuditEntry.objects.order_by("created_at")] == [
        "platform_admin.grant",
        "platform_admin.revoke",
    ]


def test_a_person_who_never_signed_in_is_404(admin: Any) -> None:
    response = as_(admin).put("/api/v1/platform-admins/999999")

    assert (response.status_code, code(response)) == (404, "user_not_found")


def test_only_a_platform_admin_reaches_the_platform_admins() -> None:
    person = UserFactory()
    client = as_(person)

    assert client.get("/api/v1/platform-admins").status_code == 403
    assert client.put(f"/api/v1/platform-admins/{person.pk}").status_code == 403
    assert client.delete(f"/api/v1/platform-admins/{person.pk}").status_code == 403
    assert not PlatformAdmin.objects.filter(user=person).exists()


def test_a_platform_admin_by_setting_is_listed_and_cannot_be_removed() -> None:
    listed_person = UserFactory(name="Sam")
    other = PlatformAdminFactory().user
    with override_settings(IAM_PLATFORM_ADMIN_OIDS=frozenset({listed_person.oid})):
        client = as_(other)

        items = client.get("/api/v1/platform-admins").json()["items"]
        removed = client.delete(f"/api/v1/platform-admins/{listed_person.pk}")

    sources = {i["user_id"]: i["source"] for i in items}
    assert sources == {listed_person.pk: "setting", other.pk: "row"}
    assert (removed.status_code, code(removed)) == (409, "platform_admin_by_setting")


def test_the_last_platform_admin_stays(admin: Any) -> None:
    response = as_(admin).delete(f"/api/v1/platform-admins/{admin.pk}")

    assert (response.status_code, code(response)) == (409, "last_platform_admin")
    assert PlatformAdmin.objects.filter(user=admin).exists()


# --- the audit list ------------------------------------------------------------


def test_a_platform_admin_sees_every_entry_newest_first(admin: Any) -> None:
    tenant = TenantFactory()
    person = UserFactory(name="Pat")
    services.set_tenant_role(admin, tenant.pk, person.pk, "member")
    services.grant_platform_admin(admin, person.pk)

    response = as_(admin).get("/api/v1/audit")

    assert response.status_code == 200
    items = response.json()["items"]
    assert [i["action"] for i in items][:2] == [
        "platform_admin.grant",
        "tenant.role.set",
    ]
    newest = items[0]
    assert set(newest) == {
        "id",
        "action",
        "actor",
        "target",
        "tenant_id",
        "workspace_id",
        "old_role",
        "new_role",
        "detail",
        "created_at",
    }
    assert newest["actor"] == {"id": admin.pk, "name": admin.name}
    assert newest["target"] == {"id": person.pk, "name": "Pat"}
    assert newest["new_role"] == "platform_admin"


def test_the_list_shows_no_sign_in_identifiers(admin: Any) -> None:
    person = UserFactory(preferred_username="pat@example.com")
    services.set_tenant_role(admin, TenantFactory().pk, person.pk, "member")

    body = as_(admin).get("/api/v1/audit").content.decode()

    assert str(person.oid) not in body
    assert str(person.tid) not in body
    assert str(admin.oid) not in body
    assert "actor_oid" not in body


def test_an_entry_outlives_a_deleted_person(admin: Any) -> None:
    person = UserFactory()
    tenant = TenantFactory()
    services.set_tenant_role(admin, tenant.pk, person.pk, "member")
    oid = person.oid
    person.delete()

    (item,) = as_(admin).get(f"/api/v1/audit?tenant_id={tenant.pk}").json()["items"]

    assert item["target"] is None
    assert AuditEntry.objects.get(action="tenant.role.set").target_oid == oid


def test_a_tenant_admin_sees_only_their_tenants_entries(admin: Any) -> None:
    mine, other = TenantFactory(), TenantFactory()
    boss = tenant_admin(mine)
    person = UserFactory()
    services.set_tenant_role(admin, mine.pk, person.pk, "member")
    services.set_tenant_role(admin, other.pk, person.pk, "member")
    AuditEntryFactory(action="platform_admin.grant")  # no tenant

    client = as_(boss)
    everything = client.get("/api/v1/audit").json()["items"]
    named = client.get(f"/api/v1/audit?tenant_id={mine.pk}").json()["items"]

    assert {i["tenant_id"] for i in everything} == {str(mine.pk)}
    assert len(everything) == len(named) >= 1
    assert all(i["tenant_id"] == str(mine.pk) for i in named)


def test_the_filter_narrows_a_platform_admins_list(admin: Any) -> None:
    mine, other = TenantFactory(), TenantFactory()
    person = UserFactory()
    services.set_tenant_role(admin, mine.pk, person.pk, "member")
    services.set_tenant_role(admin, other.pk, person.pk, "member")

    items = as_(admin).get(f"/api/v1/audit?tenant_id={other.pk}").json()["items"]

    assert {i["tenant_id"] for i in items} == {str(other.pk)}


def test_a_member_and_an_outsider_do_not_read_the_audit_list() -> None:
    tenant = TenantFactory()
    person = member(tenant)

    plain = as_(person).get("/api/v1/audit")
    named = as_(person).get(f"/api/v1/audit?tenant_id={tenant.pk}")
    hidden = as_(UserFactory(in_default_tenant=False)).get(
        f"/api/v1/audit?tenant_id={tenant.pk}"
    )

    assert (plain.status_code, code(plain)) == (403, "forbidden")
    assert (named.status_code, code(named)) == (403, "forbidden")
    assert (hidden.status_code, code(hidden)) == (404, "tenant_not_found")


def test_the_audit_list_is_paged(admin: Any) -> None:
    for _ in range(3):
        AuditEntryFactory()

    client = as_(admin)
    first = client.get("/api/v1/audit?page_size=2").json()
    second = client.get(f"/api/v1/audit?page_size=2&cursor={first['next']}").json()

    assert len(first["items"]) == 2
    assert len(second["items"]) >= 1
    assert not {i["id"] for i in first["items"]} & {i["id"] for i in second["items"]}


def test_an_anonymous_caller_is_401() -> None:
    client = APIClient()
    for url in ("/api/v1/tenants", "/api/v1/audit", "/api/v1/platform-admins"):
        assert client.get(url).status_code == 401


def test_every_answer_has_the_shape_the_checkers_describe(admin: Any) -> None:
    from tests import shapes

    tenant = TenantFactory()
    boss = tenant_admin(tenant)
    WorkspaceFactory(tenant=tenant)
    services.grant_platform_admin(admin, UserFactory().pk)
    client = as_(admin)

    shapes.check_tenants(client.get("/api/v1/tenants").json())
    shapes.check_tenants(as_(boss).get("/api/v1/tenants").json())
    shapes.check_tenant(
        client.post("/api/v1/tenants", {"name": "Shaped"}, format="json").json()
    )
    shapes.check_tenant_workspaces(
        client.get(f"/api/v1/tenants/{tenant.pk}/workspaces").json()
    )
    shapes.check_platform_admins(client.get("/api/v1/platform-admins").json())
    shapes.check_audit(client.get("/api/v1/audit").json())
