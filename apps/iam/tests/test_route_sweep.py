"""The route sweep: every route under /api/v1 says what it needs, and gets it.

It walks the URL configuration. A route or method with no ``@requires`` fails
with the route's name. Then each route is called, on a real tenant and workspace,
by every kind of person (``PEOPLE``), and the answers are checked against the
declaration and the permission table (``apps/iam/roles.py``): a person whose roles
hold the permission is answered, one who sees the tenant or the workspace without
it gets 403, and for anyone else it does not exist (404). A route whose rule is
not one permission says what each person gets in ``EXPECTED``. docs/iam.md has
the route table.
"""

import json
import re
from dataclasses import dataclass
from typing import Any

import pytest
from asgiref.sync import sync_to_async
from django.urls import URLPattern, URLResolver, get_resolver
from rest_framework.test import APIClient

from apps.documents import selectors as documents
from apps.extraction.tests.factories import (
    DefinitionVersionFactory,
    ExtractionFactory,
    ExtractionRecordFactory,
    FieldValueFactory,
)
from apps.iam.models import TenantMembership, WorkspaceMembership
from apps.iam.roles import (
    PERMISSIONS,
    Permission,
    PlatformAdminRole,
    TenantRole,
    WorkspaceRole,
)
from apps.iam.routes import (
    APPLICATION_PERMISSIONS,
    OPEN,
    SIGNED_IN,
    methods_of,
    needs_of,
)
from apps.iam.tests.factories import PlatformAdminFactory, TenantMembershipFactory
from apps.identity.tests.factories import UserFactory
from apps.realtime import services as realtime
from apps.realtime.tests.communicator import WebsocketCommunicator
from apps.runs.tests.factories import CellFactory, RunFileFactory
from apps.workspaces.tests.factories import WorkspaceFactory
from config.asgi import application

PREFIX = "api/v1/"

# Routes the sweep cannot call, each with the reason. Keep it short.
NOT_CALLED: dict[str, str] = {}

# The bodies that get a request past its own validation, so that it reaches the
# permission check. A route not listed is called without a body.
BODIES: dict[tuple[str, str], dict[str, Any]] = {
    ("workspaces", "POST"): {"name": "Swept"},
    ("workspaces/<str:workspace_id>", "PATCH"): {"name": "Renamed"},
    ("projects", "POST"): {"name": "Swept"},
    ("projects/<str:project_id>", "PATCH"): {"name": "Renamed"},
    ("runs", "POST"): {"items": []},
    ("tenants", "POST"): {"name": "Swept"},
    ("tenants/<str:tenant_id>", "PATCH"): {"name": "Renamed"},
    ("runs/<str:run_id>/documents", "PUT"): {"items": []},
    ("runs/<str:run_id>/stages/extract/definition", "PUT"): {"base_version": 1},
    ("runs/<str:run_id>/stages/extract/chunking/generate", "POST"): {
        "instruction": "One part per heading."
    },
    ("runs/<str:run_id>/files/<str:file_id>/extraction/records", "POST"): {
        "revision": 1,
        "record_type_id": "rt-adr",
        "span": None,
    },
    (
        "runs/<str:run_id>/files/<str:file_id>/extraction/records/<str:record_id>",
        "PATCH",
    ): {"revision": 1},
    (
        "runs/<str:run_id>/files/<str:file_id>/extraction/records/<str:record_id>"
        "/fields/<str:field_id>",
        "PUT",
    ): {"revision": 1, "values": []},
    (
        "runs/<str:run_id>/files/<str:file_id>/extraction/records/<str:record_id>"
        "/values/<str:value_id>",
        "PATCH",
    ): {"revision": 1, "review": "accepted"},
    ("runs/<str:run_id>/extraction/assistant/messages", "POST"): {"text": "Hello"},
}
# A query may name an id of the world as ``{tenant_id}``.
QUERIES: dict[tuple[str, str], str] = {
    ("audit", "GET"): "?tenant_id={tenant_id}",
    (
        "runs/<str:run_id>/files/<str:file_id>/extraction/records/<str:record_id>",
        "DELETE",
    ): "?revision=1",
}

# What "may not see it" answers: the tenant, workspace or run does not exist for them.
HIDDEN = {"run_not_found", "workspace_not_found", "tenant_not_found"}

# Signed-in routes that need a tenant role with ``workspaces.create``: a person in
# no tenant gets 403 on them (and nothing else is refused to that person).
NEEDS_A_TENANT = {("workspaces", "POST"), ("projects", "POST"), ("runs", "POST")}

# The people of the world, with the roles each holds towards its tenant and its
# workspace. The order is the order of the calls.
ROLES: dict[str, tuple[PlatformAdminRole | TenantRole | WorkspaceRole, ...]] = {
    "outsider": (),  # a member of another tenant only
    "no_tenant": (),  # in no tenant at all
    "stranger": (TenantRole.MEMBER,),  # in the tenant, no role in the workspace
    "tenant_admin": (TenantRole.ADMIN,),  # not a member of the workspace
    "platform_admin": (PlatformAdminRole.PLATFORM_ADMIN, TenantRole.MEMBER),
    "viewer": (TenantRole.MEMBER, WorkspaceRole.VIEWER),
    "editor": (TenantRole.MEMBER, WorkspaceRole.EDITOR),
    "owner": (TenantRole.MEMBER, WorkspaceRole.OWNER),
}
PEOPLE = tuple(ROLES)
# The outsider's sign-in name, for a body that must name a person outside the tenant.
OUTSIDER = "outsider@example.com"

# Routes whose rule is not "one permission on the tenant or the workspace": what
# every person of PEOPLE gets, spelled out as "allowed", "403" or "404".
EXPECTED: dict[tuple[str, str], dict[str, str]] = {
    # With the tenant named: whoever manages its members (see ``tenants.list_audit``).
    ("audit", "GET"): {
        "outsider": "404",
        "no_tenant": "404",
        "stranger": "403",
        "tenant_admin": "allowed",
        "platform_admin": "allowed",
        "viewer": "403",
        "editor": "403",
        "owner": "403",
    },
}


def _walk(patterns: list[Any], prefix: str = "") -> list[tuple[str, Any]]:
    found: list[tuple[str, Any]] = []
    for pattern in patterns:
        route = prefix + str(pattern.pattern)
        if isinstance(pattern, URLResolver):
            found += _walk(pattern.url_patterns, route)
        elif isinstance(pattern, URLPattern):
            found.append((route, pattern.callback))
    return found


def api_routes() -> list[tuple[str, Any]]:
    """Every route under /api/v1, as ``("runs/<str:run_id>", view)``."""
    return [
        (route.removeprefix(PREFIX), view)
        for route, view in _walk(get_resolver().url_patterns)
        if route.startswith(PREFIX)
    ]


def route_methods() -> list[tuple[str, str]]:
    return [
        (route, method)
        for route, view in api_routes()
        for method in sorted(methods_of(view))
    ]


def test_every_route_declares_every_method() -> None:
    undeclared = []
    for route, view in api_routes():
        methods = methods_of(view)
        needs = needs_of(view)
        if not methods:
            undeclared.append(f"{route}: not an @api_view")
        for method in sorted(methods - set(needs)):
            undeclared.append(f"{route} {method}")
    assert undeclared == [], f"declare these with @requires: {undeclared}"


def test_the_routes_not_called_are_real_routes() -> None:
    routes = {route for route, _ in api_routes()}
    assert set(NOT_CALLED) <= routes
    assert len(NOT_CALLED) <= 3


def test_the_bodies_belong_to_real_routes() -> None:
    assert set(BODIES) | set(QUERIES) | set(EXPECTED) <= set(route_methods())
    for route_method, answers in EXPECTED.items():
        assert set(answers) == set(PEOPLE), (
            f"{route_method}: say what every person gets"
        )
        assert set(answers.values()) <= {"allowed", "403", "404"}, route_method


# --- calling every route ------------------------------------------------------


@dataclass
class World:
    ids: dict[str, str]
    anonymous: APIClient
    people: dict[str, APIClient]


def _as(user: Any) -> APIClient:
    client = APIClient()
    client.force_authenticate(user)
    return client


def _member(workspace: Any, role: WorkspaceRole) -> Any:
    user = UserFactory()
    WorkspaceMembership.objects.create(workspace=workspace, user=user, role=role)
    return user


def make_world() -> World:
    """A tenant with a workspace that has one file, an extraction, a record and a
    value; a person to act on (``user_id``: in the tenant, an editor of the
    workspace); and people with every relation to them (``ROLES``)."""
    workspace = WorkspaceFactory()
    run = workspace.run
    owner = workspace.owner
    document = documents.list_documents(owner)[0]
    file = RunFileFactory(run=run, source_ref=document.id, name=document.name)
    CellFactory(file=file)
    DefinitionVersionFactory(run=run)
    record = ExtractionRecordFactory(extraction=ExtractionFactory(file=file))
    value = FieldValueFactory(record=record)
    tenant_admin = UserFactory()
    TenantMembership.objects.filter(user=tenant_admin, tenant=workspace.tenant).update(
        role="admin"
    )
    acted_on = _member(workspace, WorkspaceRole.EDITOR)
    ids = {
        "tenant_id": str(workspace.tenant_id),
        "user_id": str(acted_on.pk),
        "workspace_id": str(workspace.pk),
        "project_id": str(workspace.pk),
        "run_id": str(run.pk),
        "file_id": str(file.pk),
        "record_id": str(record.pk),
        "value_id": str(value.pk),
        "field_id": value.field_id,
        "version": "1",
        "stage": "extract",
        "document_id": document.id,
    }
    people = {
        "outsider": TenantMembershipFactory(
            user=UserFactory(in_default_tenant=False, preferred_username=OUTSIDER)
        ).user,
        "no_tenant": UserFactory(in_default_tenant=False),
        "stranger": UserFactory(),
        "tenant_admin": tenant_admin,
        "platform_admin": PlatformAdminFactory().user,
        "viewer": _member(workspace, WorkspaceRole.VIEWER),
        "editor": _member(workspace, WorkspaceRole.EDITOR),
        "owner": owner,
    }
    assert tuple(people) == PEOPLE
    return World(
        ids=ids,
        anonymous=APIClient(),
        people={name: _as(user) for name, user in people.items()},
    )


def _url(route: str, ids: dict[str, str]) -> str:
    def fill(match: re.Match[str]) -> str:
        name = match.group(1)
        assert name in ids, f"{route}: the sweep has no id for <{name}>; add one"
        return ids[name]

    return "/" + PREFIX + re.sub(r"<(?:\w+:)?(\w+)>", fill, route)


def _call(client: APIClient, route: str, method: str, ids: dict[str, str]) -> Any:
    url = _url(route, ids) + QUERIES.get((route, method), "").format(**ids)
    body = BODIES.get((route, method))
    data = "" if body is None else json.dumps(body)
    return client.generic(method, url, data, content_type="application/json")


def _code(response: Any) -> str | None:
    try:
        return response.json().get("code")  # type: ignore[no-any-return]
    except ValueError, AttributeError:
        return None


def _refused(response: Any) -> str | None:
    """How a person was refused (``"401"``, ``"403"``, ``"404"``), or None."""
    if response.status_code == 401:
        return "401"
    if response.status_code == 403:
        return "403"
    if response.status_code == 404 and _code(response) in HIDDEN:
        return "404"
    return None


def _allowed(response: Any) -> bool:
    """A permitted call is answered: not refused, not a crash, not a stray 404.

    A 404 other than "hidden" (a wrong id in the sweep) or a 5xx fails, so a route
    that breaks after its permission check does not pass as allowed. A 400, 409 or
    422 is an answer of the route itself (a body it rejects, a run of a workspace).
    """
    return (
        _refused(response) is None
        and response.status_code not in (404,)
        and (response.status_code < 500)
    )


def _expected(route: str, method: str, need: str) -> dict[str, str]:
    """What each person gets on a route: "allowed", "403" or "404"."""
    if (route, method) in EXPECTED:
        return EXPECTED[(route, method)]
    if need == SIGNED_IN:
        # The answer does not depend on a role, except where a tenant role is needed.
        needs_a_tenant = (route, method) in NEEDS_A_TENANT
        return {
            person: "403" if needs_a_tenant and person == "no_tenant" else "allowed"
            for person in PEOPLE
        }
    if need in APPLICATION_PERMISSIONS:
        return {p: "allowed" if p == "platform_admin" else "403" for p in PEOPLE}
    scope = Permission(need).value.split(".")[0]
    assert scope in ("workspace", "tenant"), f"{need}: add its rule to the sweep"
    # A workspace is seen through a role in it (admins included: without one it
    # does not exist for them); a tenant through a role in it or as a platform admin.
    sees = (WorkspaceRole,) if scope == "workspace" else (TenantRole, PlatformAdminRole)
    answers = {}
    for person, roles in ROLES.items():
        if any(need in PERMISSIONS[role] for role in roles):
            answers[person] = "allowed"
        elif any(isinstance(role, sees) for role in roles):
            answers[person] = "403"
        else:
            answers[person] = "404"
    return answers


@pytest.mark.django_db
@pytest.mark.parametrize(("route", "method"), route_methods())
def test_each_route_gives_each_person_what_their_role_allows(
    route: str, method: str
) -> None:
    if route in NOT_CALLED:
        pytest.skip(NOT_CALLED[route])
    view = dict(api_routes())[route]
    need = needs_of(view).get(method)
    assert need is not None, f"{route} {method} declares nothing"
    who = f"{method} {route} ({need})"
    world = make_world()

    def call(w: World, person: str) -> Any:
        return _call(w.people[person], route, method, w.ids)

    if need == OPEN:
        assert _allowed(_call(world.anonymous, route, method, world.ids)), who
        return
    assert _refused(_call(world.anonymous, route, method, world.ids)) == "401", who
    expected = _expected(route, method, need)
    # The refused first, so that a permitted call that changes things comes after.
    for person in PEOPLE:
        if expected[person] != "allowed":
            assert _refused(call(world, person)) == expected[person], (
                f"{who} as {person}"
            )
    for person in PEOPLE:
        if expected[person] == "allowed":
            # A DELETE takes away what the next person would act on: a world each.
            w = make_world() if method == "DELETE" else world
            assert _allowed(call(w, person)), f"{who} as {person}"


def test_the_generic_rule_matches_the_epic() -> None:
    """The rule of ``_expected``, spelled out on the cases that matter most."""
    content = _expected("x", "GET", Permission.WORKSPACE_VIEW)
    assert content == {
        "outsider": "404",
        "no_tenant": "404",
        "stranger": "404",
        "tenant_admin": "404",  # an admin reads content only with a workspace role
        "platform_admin": "404",
        "viewer": "allowed",
        "editor": "allowed",
        "owner": "allowed",
    }
    sharing = _expected("x", "PUT", Permission.WORKSPACE_MEMBERS_MANAGE)
    assert sharing == {
        "outsider": "404",
        "no_tenant": "404",
        "stranger": "404",
        "tenant_admin": "allowed",  # manages access without being a member
        "platform_admin": "allowed",
        "viewer": "403",
        "editor": "403",
        "owner": "allowed",
    }
    members = _expected("x", "PUT", Permission.TENANT_MEMBERS_MANAGE)
    assert members == {
        "outsider": "404",
        "no_tenant": "404",
        "stranger": "403",
        "tenant_admin": "allowed",
        "platform_admin": "allowed",
        "viewer": "403",
        "editor": "403",
        "owner": "403",
    }
    listing = _expected("x", "GET", Permission.TENANT_MEMBERS_LIST)
    assert {p for p, answer in listing.items() if answer == "404"} == {
        "outsider",
        "no_tenant",
    }
    assert set(listing.values()) == {"allowed", "404"}


def test_the_viewer_and_the_editor_are_refused_where_the_epic_says() -> None:
    """The mapping of task 3, spelled out: a reader of the sweep sees the rule."""
    needs = {
        (route, method): need
        for route, view in api_routes()
        for method, need in needs_of(view).items()
    }
    viewer_may = {k for k, n in needs.items() if n == Permission.WORKSPACE_VIEW}
    editor_may_not = {k for k, n in needs.items() if n == Permission.WORKSPACE_MANAGE}
    assert ("runs/<str:run_id>", "GET") in viewer_may
    assert ("runs/<str:run_id>/stages/extract/definition", "GET") in viewer_may
    assert ("runs/<str:run_id>/extraction/assistant/messages", "GET") in viewer_may
    assert editor_may_not == {
        ("workspaces/<str:workspace_id>", "PATCH"),
        ("workspaces/<str:workspace_id>", "DELETE"),
        ("projects/<str:project_id>", "PATCH"),
        ("projects/<str:project_id>", "DELETE"),
        ("runs/<str:run_id>", "DELETE"),
    }
    assert needs[("status/test", "POST")] == Permission.STATUS_TEST
    assert needs[("health", "GET")] == needs[("ready", "GET")] == OPEN
    for route in ("me", "documents", "definition-templates", "ws-ticket"):
        assert SIGNED_IN in {n for (r, _), n in needs.items() if r == route}, route
    assert needs[("runs/<str:run_id>/stages/<str:stage>/executions", "POST")] == (
        Permission.WORKSPACE_RUN
    )
    assert needs[("runs/<str:run_id>/stages/extract/chunking/generate", "POST")] == (
        Permission.WORKSPACE_RUN
    )


# --- the live-update socket ---------------------------------------------------


@sync_to_async
def _socket_world() -> dict[str, Any]:
    workspace = WorkspaceFactory()
    tenant_admin = UserFactory()
    TenantMembership.objects.filter(user=tenant_admin, tenant=workspace.tenant).update(
        role="admin"
    )
    return {
        "run_id": workspace.run_id,
        "stranger": UserFactory(),
        "tenant_admin": tenant_admin,
        "platform_admin": PlatformAdminFactory().user,
        "viewer": _member(workspace, WorkspaceRole.VIEWER),
        "editor": _member(workspace, WorkspaceRole.EDITOR),
        "owner": workspace.owner,
    }


async def _connects(user: Any, run_id: Any) -> bool:
    """True when the socket follows the run: it gets the run's next event."""
    ticket = await sync_to_async(realtime.issue_ticket)(user)
    socket = WebsocketCommunicator(
        application,
        f"/ws/runs/{run_id}/?ticket={ticket}",
        headers=[(b"origin", b"http://localhost:3000")],
    )
    assert await socket.connect()  # accepted first, so a close code reaches the browser
    await realtime.apublish_run_event(run_id, {"type": "run.changed"})
    output = await socket.receive_output()  # type: ignore[no-untyped-call]
    if output == {"type": "websocket.close", "code": 4404}:
        return False
    assert json.loads(output["text"]) == {"type": "run.changed"}
    await socket.disconnect()
    return True


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_socket_needs_workspace_view() -> None:
    found = await _socket_world()
    run_id = found["run_id"]
    for name in ("stranger", "tenant_admin", "platform_admin"):
        assert not await _connects(found[name], run_id), name
    for name in ("viewer", "editor", "owner"):
        assert await _connects(found[name], run_id), name
