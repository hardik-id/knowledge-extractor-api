"""A tenant's members and finding people, through the API (``/tenants/{id}/members``, ``/users``)."""

from typing import Any

import pytest
from rest_framework.test import APIClient

from apps.core.errors import ApiError
from apps.iam import services
from apps.iam.models import AuditEntry, Tenant, TenantMembership, WorkspaceMembership
from apps.iam.roles import WorkspaceRole
from apps.iam.tests.factories import (
    PlatformAdminFactory,
    TenantFactory,
    TenantMembershipFactory,
)
from apps.identity.tests.factories import UserFactory
from apps.workspaces.tests.factories import WorkspaceFactory
from tests import shapes

pytestmark = pytest.mark.django_db


def as_(user: Any) -> APIClient:
    client = APIClient()
    client.force_authenticate(user)
    return client


def person_in(tenant: Tenant, role: str = "member", **fields: Any) -> Any:
    return TenantMembershipFactory(
        tenant=tenant,
        role=role,
        user__in_default_tenant=False,
        **{f"user__{k}": v for k, v in fields.items()},
    ).user


def url(tenant: Tenant, *rest: Any) -> str:
    return "/api/v1/tenants/" + "/".join([str(tenant.pk), "members", *map(str, rest)])


def role_of(tenant: Tenant, user: Any) -> str | None:
    row = TenantMembership.objects.filter(tenant=tenant, user=user).first()
    return row.role if row else None


@pytest.fixture
def tenant() -> Tenant:
    return TenantFactory()


@pytest.fixture
def admin(tenant: Tenant) -> Any:
    return person_in(tenant, "admin")


@pytest.fixture
def boss() -> Any:
    return PlatformAdminFactory().user


# --- listing -----------------------------------------------------------------


def test_every_member_lists_the_members(tenant: Tenant, admin: Any) -> None:
    member = person_in(tenant, name="Ada", preferred_username="ada@x.org")
    for caller in (member, admin):
        response = as_(caller).get(url(tenant))
        assert response.status_code == 200
        shapes.check_tenant_members(response.json())
    items = {i["user"]["id"]: i for i in response.json()["items"]}
    assert items[member.pk]["role"] == "member"
    assert items[member.pk]["user"] == {
        "id": member.pk,
        "name": "Ada",
        "preferred_username": "ada@x.org",
    }
    assert items[admin.pk]["role"] == "admin"


def test_a_platform_admin_lists_any_tenant(tenant: Tenant, boss: Any) -> None:
    assert as_(boss).get(url(tenant)).status_code == 200


def test_the_list_is_hidden_from_people_outside_the_tenant(tenant: Tenant) -> None:
    other = person_in(TenantFactory(), "admin")
    nobody = UserFactory(in_default_tenant=False)
    for caller in (other, nobody):
        response = as_(caller).get(url(tenant))
        assert response.status_code == 404
        assert response.json()["code"] == "tenant_not_found"


def test_the_list_needs_sign_in(tenant: Tenant) -> None:
    assert APIClient().get(url(tenant)).status_code == 401


def test_search_matches_name_or_sign_in_name(tenant: Tenant, admin: Any) -> None:
    person_in(tenant, name="Grace Hopper", preferred_username="gh@navy.mil")
    person_in(tenant, name="Alan", preferred_username="turing@x.org")

    def found(term: str) -> list[str]:
        items = as_(admin).get(url(tenant), {"search": term}).json()["items"]
        return sorted(i["user"]["name"] for i in items)

    assert found("hopp") == ["Grace Hopper"]
    assert found("TURING") == ["Alan"]
    assert found("nobody") == []


def test_the_list_is_paged(tenant: Tenant, admin: Any) -> None:
    for _ in range(4):
        person_in(tenant)
    first = as_(admin).get(url(tenant), {"page_size": 3}).json()
    assert len(first["items"]) == 3 and first["next"]
    second = as_(admin).get(url(tenant), {"page_size": 3, "cursor": first["next"]})
    assert len(second.json()["items"]) == 2 and second.json()["next"] is None


# --- adding ------------------------------------------------------------------


def test_a_tenant_admin_adds_a_person_by_exact_name_ignoring_case(
    tenant: Tenant, admin: Any
) -> None:
    person = UserFactory(preferred_username="Ada.Lovelace@x.org")
    response = as_(admin).post(
        url(tenant),
        {"preferred_username": "ada.lovelace@X.ORG", "role": "member"},
        format="json",
    )
    assert response.status_code == 201
    shapes.check_tenant_member(response.json())
    assert response.json()["user"]["id"] == person.pk
    assert role_of(tenant, person) == "member"
    entry = AuditEntry.objects.get(action="tenant.role.set", target_user=person)
    assert (entry.actor_id, entry.tenant_id, entry.new_role) == (
        admin.pk,
        tenant.pk,
        "member",
    )


def test_a_part_of_a_name_adds_and_finds_nobody(tenant: Tenant, admin: Any) -> None:
    person = UserFactory(preferred_username="ada.lovelace@x.org")
    for guess in (
        "ada",
        "ada.lovelace",
        "ada.lovelace@x.or",
        "%",
    ):
        response = as_(admin).post(
            url(tenant), {"preferred_username": guess, "role": "member"}, format="json"
        )
        assert response.status_code == 404, guess
        assert response.json()["code"] == "user_not_found"
    assert role_of(tenant, person) is None


def test_an_unknown_name_is_user_not_found(tenant: Tenant, admin: Any) -> None:
    response = as_(admin).post(
        url(tenant), {"preferred_username": "no@one", "role": "member"}, format="json"
    )
    assert (response.status_code, response.json()["code"]) == (404, "user_not_found")


def test_a_name_two_people_share_is_user_not_found(tenant: Tenant, admin: Any) -> None:
    UserFactory(preferred_username="twin@x.org")
    UserFactory(preferred_username="TWIN@x.org")
    response = as_(admin).post(
        url(tenant),
        {"preferred_username": "twin@x.org", "role": "member"},
        format="json",
    )
    assert (response.status_code, response.json()["code"]) == (404, "user_not_found")


def test_a_member_is_not_added_twice(tenant: Tenant, admin: Any) -> None:
    person = person_in(tenant, preferred_username="in@x.org")
    response = as_(admin).post(
        url(tenant), {"preferred_username": "in@x.org", "role": "admin"}, format="json"
    )
    assert (response.status_code, response.json()["code"]) == (409, "already_a_member")
    assert role_of(tenant, person) == "member"


def test_a_tenant_admin_cannot_add_by_id(tenant: Tenant, admin: Any) -> None:
    person = UserFactory()
    response = as_(admin).post(
        url(tenant), {"user_id": person.pk, "role": "member"}, format="json"
    )
    assert response.status_code == 403
    assert role_of(tenant, person) is None


def test_a_platform_admin_adds_by_id_or_by_name(tenant: Tenant, boss: Any) -> None:
    one, two = UserFactory(), UserFactory(preferred_username="two@x.org")
    by_id = as_(boss).post(
        url(tenant), {"user_id": one.pk, "role": "admin"}, format="json"
    )
    by_name = as_(boss).post(
        url(tenant),
        {"preferred_username": "two@x.org", "role": "member"},
        format="json",
    )
    assert (by_id.status_code, by_name.status_code) == (201, 201)
    assert (role_of(tenant, one), role_of(tenant, two)) == ("admin", "member")
    missing = as_(boss).post(
        url(tenant), {"user_id": 0 + 2**30, "role": "member"}, format="json"
    )
    assert missing.json()["code"] == "user_not_found"
    again = as_(boss).post(
        url(tenant), {"user_id": one.pk, "role": "member"}, format="json"
    )
    assert again.json()["code"] == "already_a_member"


@pytest.mark.parametrize(
    "body",
    [
        {"role": "member"},
        {"preferred_username": "a@b", "user_id": 1, "role": "member"},
        {"preferred_username": "a@b", "role": "owner"},
        {"preferred_username": "a@b"},
        {"preferred_username": "", "role": "member"},
    ],
)
def test_a_bad_body_is_422(tenant: Tenant, admin: Any, body: dict[str, Any]) -> None:
    assert as_(admin).post(url(tenant), body, format="json").status_code == 422


def test_a_member_and_an_outsider_may_not_add(tenant: Tenant) -> None:
    UserFactory(preferred_username="p@x.org")
    body = {"preferred_username": "p@x.org", "role": "member"}
    member = person_in(tenant)
    assert as_(member).post(url(tenant), body, format="json").status_code == 403
    other = person_in(TenantFactory(), "admin")
    response = as_(other).post(url(tenant), body, format="json")
    assert (response.status_code, response.json()["code"]) == (404, "tenant_not_found")
    assert APIClient().post(url(tenant), body, format="json").status_code == 401


def test_the_service_refuses_a_tenant_admin_adding_by_id(
    tenant: Tenant, admin: Any
) -> None:
    person = UserFactory()
    with pytest.raises(ApiError) as error:
        services.set_tenant_role(admin, tenant.pk, person.pk, "member")
    assert error.value.code == "user_not_found"
    services.set_tenant_role(None, tenant.pk, person.pk, "member")  # an operator may
    assert role_of(tenant, person) == "member"


# --- changing a role ---------------------------------------------------------


def test_a_tenant_admin_changes_a_role(tenant: Tenant, admin: Any) -> None:
    person = person_in(tenant)
    response = as_(admin).put(url(tenant, person.pk), {"role": "admin"}, format="json")
    assert response.status_code == 200
    shapes.check_tenant_member(response.json())
    assert role_of(tenant, person) == "admin"
    entry = AuditEntry.objects.get(target_user=person)
    assert (entry.old_role, entry.new_role) == ("member", "admin")


def test_the_last_admin_cannot_step_down(tenant: Tenant, admin: Any) -> None:
    response = as_(admin).put(url(tenant, admin.pk), {"role": "member"}, format="json")
    assert (response.status_code, response.json()["code"]) == (409, "last_tenant_admin")
    assert role_of(tenant, admin) == "admin"


def test_a_platform_admin_may_demote_the_last_admin(
    tenant: Tenant, admin: Any, boss: Any
) -> None:
    response = as_(boss).put(url(tenant, admin.pk), {"role": "member"}, format="json")
    assert response.status_code == 200


def test_changing_the_role_of_a_non_member_is_the_same_404_as_an_unknown_id(
    tenant: Tenant, admin: Any, boss: Any
) -> None:
    stranger = UserFactory()
    answers = []
    for caller in (admin, boss):
        for user_id in (stranger.pk, 2**30, "abc", "-1", "99999999999999999999"):
            response = as_(caller).put(
                url(tenant, user_id), {"role": "member"}, format="json"
            )
            answers.append((response.status_code, response.json()))
    assert {str(a) for a in answers} == {
        str((404, {"code": "user_not_found", "message": answers[0][1]["message"]}))
    }
    assert role_of(tenant, stranger) is None


def test_a_member_may_not_change_roles(tenant: Tenant) -> None:
    member, other = person_in(tenant), person_in(tenant)
    response = as_(member).put(url(tenant, other.pk), {"role": "admin"}, format="json")
    assert response.status_code == 403
    outsider = person_in(TenantFactory(), "admin")
    response = as_(outsider).put(
        url(tenant, other.pk), {"role": "admin"}, format="json"
    )
    assert response.json()["code"] == "tenant_not_found"


def test_a_bad_role_is_422(tenant: Tenant, admin: Any) -> None:
    person = person_in(tenant)
    assert (
        as_(admin)
        .put(url(tenant, person.pk), {"role": "owner"}, format="json")
        .status_code
        == 422
    )


# --- removing ----------------------------------------------------------------


def test_removing_a_member_removes_their_workspace_roles_in_that_tenant_only(
    tenant: Tenant, admin: Any
) -> None:
    person = person_in(tenant)
    mine = [WorkspaceFactory(tenant=tenant) for _ in range(2)]
    for workspace, role in zip(
        mine, (WorkspaceRole.EDITOR, WorkspaceRole.OWNER), strict=True
    ):
        WorkspaceMembership.objects.create(workspace=workspace, user=person, role=role)
    elsewhere_tenant = TenantFactory()
    TenantMembershipFactory(tenant=elsewhere_tenant, user=person)
    elsewhere = WorkspaceFactory(tenant=elsewhere_tenant)
    WorkspaceMembership.objects.create(
        workspace=elsewhere, user=person, role=WorkspaceRole.VIEWER
    )

    response = as_(admin).delete(url(tenant, person.pk))

    assert response.status_code == 204
    assert role_of(tenant, person) is None
    assert not WorkspaceMembership.objects.filter(
        user=person, workspace__tenant=tenant
    ).exists()
    assert WorkspaceMembership.objects.filter(user=person, workspace=elsewhere).exists()
    removed = AuditEntry.objects.filter(
        action="workspace.member.remove", target_user=person
    )
    assert {(e.workspace_id, e.old_role) for e in removed} == {
        (mine[0].pk, "editor"),
        (mine[1].pk, "owner"),
    }
    assert all(e.actor_id == admin.pk and e.tenant_id == tenant.pk for e in removed)
    assert AuditEntry.objects.filter(action="tenant.member.remove").count() == 1


def test_a_removed_person_gets_404_on_the_workspace_at_the_next_request(
    tenant: Tenant, admin: Any
) -> None:
    person = person_in(tenant)
    workspace = WorkspaceFactory(tenant=tenant)
    WorkspaceMembership.objects.create(
        workspace=workspace, user=person, role=WorkspaceRole.EDITOR
    )
    path = f"/api/v1/workspaces/{workspace.pk}"
    assert as_(person).get(path).status_code == 200
    as_(admin).delete(url(tenant, person.pk))
    response = as_(person).get(path)
    assert (response.status_code, response.json()["code"]) == (
        404,
        "workspace_not_found",
    )


def test_removing_a_person_may_leave_a_workspace_without_an_owner(
    tenant: Tenant, admin: Any
) -> None:
    owner = person_in(tenant)
    workspace = WorkspaceFactory(tenant=tenant, owner=owner)
    assert as_(admin).delete(url(tenant, owner.pk)).status_code == 204
    assert not WorkspaceMembership.objects.filter(workspace=workspace).exists()


def test_the_last_admin_cannot_be_removed_by_themselves(
    tenant: Tenant, admin: Any
) -> None:
    person = WorkspaceFactory(tenant=tenant, owner=admin)
    response = as_(admin).delete(url(tenant, admin.pk))
    assert (response.status_code, response.json()["code"]) == (409, "last_tenant_admin")
    assert WorkspaceMembership.objects.filter(workspace=person).exists()


def test_removing_a_non_member_is_the_same_404_as_an_unknown_id(
    tenant: Tenant, admin: Any
) -> None:
    stranger = UserFactory()
    seen = set()
    for user_id in (stranger.pk, 2**30, "abc", "99999999999999999999"):
        response = as_(admin).delete(url(tenant, user_id))
        seen.add((response.status_code, response.json()["code"]))
    assert seen == {(404, "user_not_found")}


def test_walking_ids_tells_a_tenant_admin_nothing(tenant: Tenant, admin: Any) -> None:
    """Every id that is not a member answers alike, whoever exists behind it."""
    members = {person_in(tenant).pk for _ in range(3)} | {admin.pk}
    outsiders = [UserFactory().pk for _ in range(5)]
    top = max([*members, *outsiders]) + 3
    answers: dict[int, tuple[int, str]] = {}
    for user_id in range(1, top):
        if user_id in members:
            continue
        put = as_(admin).put(url(tenant, user_id), {"role": "member"}, format="json")
        post = as_(admin).post(
            url(tenant), {"user_id": user_id, "role": "member"}, format="json"
        )
        assert post.status_code == 403  # by id is refused whoever is behind it
        delete = as_(admin).delete(url(tenant, user_id))
        answers[user_id] = (put.status_code, put.json()["code"])
        assert (delete.status_code, delete.json()["code"]) == answers[user_id]
    assert set(answers.values()) == {(404, "user_not_found")}
    assert not TenantMembership.objects.filter(
        tenant=tenant, user_id__in=outsiders
    ).exists()


def test_a_member_may_not_remove(tenant: Tenant) -> None:
    member, other = person_in(tenant), person_in(tenant)
    assert as_(member).delete(url(tenant, other.pk)).status_code == 403


# --- GET /users --------------------------------------------------------------


def test_a_platform_admin_lists_and_searches_everyone(boss: Any) -> None:
    UserFactory(name="Grace Hopper", preferred_username="gh@navy.mil")
    UserFactory(name="Alan", preferred_username="turing@x.org")
    everyone = as_(boss).get("/api/v1/users")
    assert everyone.status_code == 200
    shapes.check_people(everyone.json())
    assert len(everyone.json()["items"]) == 3
    found = as_(boss).get("/api/v1/users", {"search": "hopp"}).json()["items"]
    assert [i["name"] for i in found] == ["Grace Hopper"]


def test_a_tenant_admin_finds_one_person_by_exact_name(
    tenant: Tenant, admin: Any
) -> None:
    person = UserFactory(name="Ada", preferred_username="Ada@x.org")
    response = as_(admin).get("/api/v1/users", {"preferred_username": "ada@X.org"})
    assert response.status_code == 200
    shapes.check_people(response.json())
    assert response.json() == {
        "items": [{"id": person.pk, "name": "Ada", "preferred_username": "Ada@x.org"}],
        "next": None,
    }


def test_a_tenant_admin_learns_nothing_from_a_part_of_a_name(admin: Any) -> None:
    UserFactory(name="Ada", preferred_username="ada@x.org")
    UserFactory(preferred_username="twin@x.org")
    UserFactory(preferred_username="twin@x.org")
    for guess in ("ada", "ada@x", "@x.org", "a", "twin@x.org", "%"):
        response = as_(admin).get("/api/v1/users", {"preferred_username": guess})
        assert response.status_code == 200
        assert response.json()["items"] == [], guess


def test_a_tenant_admin_cannot_list_or_search(admin: Any) -> None:
    UserFactory(name="Ada")
    for query in ({}, {"search": "ada"}):
        assert as_(admin).get("/api/v1/users", query).status_code == 403
    # a search next to the exact name does not widen the answer
    response = as_(admin).get(
        "/api/v1/users", {"preferred_username": "nobody", "search": "ada"}
    )
    assert response.json()["items"] == []


def test_anyone_else_is_refused_the_user_list(tenant: Tenant) -> None:
    UserFactory(preferred_username="ada@x.org")
    member = person_in(tenant)
    nobody = UserFactory(in_default_tenant=False)
    for caller in (member, nobody):
        for query in ({}, {"preferred_username": "ada@x.org"}, {"search": "ada"}):
            assert as_(caller).get("/api/v1/users", query).status_code == 403
    assert APIClient().get("/api/v1/users").status_code == 401


def test_a_deactivated_person_is_not_found(
    tenant: Tenant, admin: Any, boss: Any
) -> None:
    gone = UserFactory(preferred_username="gone@x.org", is_active=False)
    response = as_(admin).post(
        url(tenant),
        {"preferred_username": "gone@x.org", "role": "member"},
        format="json",
    )
    assert response.status_code == 404
    assert gone.pk not in [
        i["id"] for i in as_(boss).get("/api/v1/users").json()["items"]
    ]


def test_a_platform_admin_can_look_up_one_exact_name(boss: Any) -> None:
    person = UserFactory(name="Ada", preferred_username="Ada@x.org")
    UserFactory(preferred_username="other@x.org")
    found = as_(boss).get("/api/v1/users", {"preferred_username": "ada@X.org"})
    assert [i["id"] for i in found.json()["items"]] == [person.pk]
    nobody = as_(boss).get("/api/v1/users", {"preferred_username": "ada"})
    assert nobody.json()["items"] == []


def test_a_person_removed_during_workspace_creation_does_not_become_owner(
    tenant: Tenant,
) -> None:
    """The creation passed its tenant check, then the removal committed: owner is refused."""
    import uuid

    from apps.iam import workspace_access

    member = person_in(tenant, "admin")
    TenantMembership.objects.filter(tenant=tenant, user=member).delete()
    with pytest.raises(ApiError) as caught:
        workspace_access.make_owner(member, uuid.uuid4(), tenant)
    assert caught.value.code == "tenant_not_found"
    assert not WorkspaceMembership.objects.filter(user=member).exists()
