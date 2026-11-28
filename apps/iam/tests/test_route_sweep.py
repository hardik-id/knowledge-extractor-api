"""The route sweep: every route under /api/v1 says what it needs, and gets it.

It walks the URL configuration. A route or method with no ``@requires`` fails
with the route's name. Then each route is called, on a real workspace, by a
stranger, a tenant admin and a platform admin who are not members, a viewer, an
editor and the owner, and the answers are checked against the declaration and
the permission table (``apps/iam/roles.py``). docs/iam.md has the route table.
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
from apps.iam.roles import PERMISSIONS, Permission, WorkspaceRole
from apps.iam.routes import (
    APPLICATION_PERMISSIONS,
    OPEN,
    SIGNED_IN,
    methods_of,
    needs_of,
)
from apps.iam.tests.factories import PlatformAdminFactory
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
QUERIES: dict[tuple[str, str], str] = {
    (
        "runs/<str:run_id>/files/<str:file_id>/extraction/records/<str:record_id>",
        "DELETE",
    ): "?revision=1",
}

# What "may not see it" answers: the workspace or run does not exist for them.
HIDDEN = {"run_not_found", "workspace_not_found"}

# Signed-in routes that need a tenant role with ``workspaces.create``: a person in
# no tenant gets 403 on them (and nothing else is refused to that person).
NEEDS_A_TENANT = {("workspaces", "POST"), ("projects", "POST"), ("runs", "POST")}


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
    assert set(BODIES) | set(QUERIES) <= set(route_methods())


# --- calling every route ------------------------------------------------------


@dataclass
class World:
    ids: dict[str, str]
    anonymous: APIClient
    stranger: APIClient
    tenant_admin: APIClient
    platform_admin: APIClient
    no_tenant: APIClient
    viewer: APIClient
    editor: APIClient
    owner: APIClient


def _as(user: Any) -> APIClient:
    client = APIClient()
    client.force_authenticate(user)
    return client


def _member(workspace: Any, role: WorkspaceRole) -> Any:
    user = UserFactory()
    WorkspaceMembership.objects.create(workspace=workspace, user=user, role=role)
    return user


@pytest.fixture
def world(db: None) -> World:
    """A workspace with one file, an extraction, a record and a value, and people
    with every relation to it."""
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
    ids = {
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
    return World(
        ids=ids,
        anonymous=APIClient(),
        stranger=_as(UserFactory()),
        no_tenant=_as(UserFactory(in_default_tenant=False)),
        tenant_admin=_as(tenant_admin),
        platform_admin=_as(PlatformAdminFactory().user),
        viewer=_as(_member(workspace, WorkspaceRole.VIEWER)),
        editor=_as(_member(workspace, WorkspaceRole.EDITOR)),
        owner=_as(owner),
    )


def _url(route: str, ids: dict[str, str]) -> str:
    def fill(match: re.Match[str]) -> str:
        name = match.group(1)
        assert name in ids, f"{route}: the sweep has no id for <{name}>; add one"
        return ids[name]

    return "/" + PREFIX + re.sub(r"<(?:\w+:)?(\w+)>", fill, route)


def _call(client: APIClient, route: str, method: str, ids: dict[str, str]) -> Any:
    url = _url(route, ids) + QUERIES.get((route, method), "")
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


def _holds(role: WorkspaceRole, need: str) -> bool:
    return need in PERMISSIONS[role]


@pytest.mark.parametrize(("route", "method"), route_methods())
def test_each_route_gives_each_person_what_their_role_allows(
    world: World, route: str, method: str
) -> None:
    if route in NOT_CALLED:
        pytest.skip(NOT_CALLED[route])
    view = dict(api_routes())[route]
    need = needs_of(view).get(method)
    assert need is not None, f"{route} {method} declares nothing"

    def refused(client: APIClient) -> str | None:
        return _refused(_call(client, route, method, world.ids))

    def allowed(client: APIClient) -> bool:
        return _allowed(_call(client, route, method, world.ids))

    who = f"{method} {route} ({need})"
    if need == OPEN:
        assert allowed(world.anonymous), who
        return
    assert refused(world.anonymous) == "401", who
    if need == SIGNED_IN:
        # The answer does not depend on a workspace role.
        for client in (world.stranger, world.viewer, world.owner):
            assert allowed(client), who
        if (route, method) in NEEDS_A_TENANT:
            assert refused(world.no_tenant) == "403", f"{who} with no tenant"
        else:
            assert allowed(world.no_tenant), f"{who} with no tenant"
        return
    if need in APPLICATION_PERMISSIONS:
        for client in (world.stranger, world.tenant_admin, world.viewer):
            assert refused(client) == "403", who
        assert allowed(world.platform_admin), who
        return
    assert Permission(need).value.startswith("workspace."), who
    # Not a member: the workspace does not exist for them, admins included.
    for client in (world.stranger, world.tenant_admin, world.platform_admin):
        assert refused(client) == "404", who
    for role, client in (
        (WorkspaceRole.VIEWER, world.viewer),
        (WorkspaceRole.EDITOR, world.editor),
        (WorkspaceRole.OWNER, world.owner),
    ):
        if _holds(role, need):
            assert allowed(client), f"{who} as {role}"
        else:
            assert refused(client) == "403", f"{who} as {role}"


def test_the_viewer_and_the_editor_are_refused_where_the_epic_says(
    world: World,
) -> None:
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
