"""Live updates follow membership: every member hears the run, a removed one is cut off."""

from typing import Any

import pytest
from asgiref.sync import sync_to_async

from apps.iam import services as iam
from apps.iam import workspace_members
from apps.iam.models import TenantMembership, WorkspaceMembership
from apps.iam.roles import WorkspaceRole
from apps.identity.tests.factories import UserFactory
from apps.realtime import services
from apps.realtime.tests.communicator import WebsocketCommunicator
from apps.realtime.tests.test_run_socket import closed_with, open_socket
from apps.workspaces.tests.factories import WorkspaceFactory
from config.asgi import application

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.asyncio]

ACCESS_REMOVED = 4403


@sync_to_async
def two_members() -> Any:
    workspace = WorkspaceFactory()
    other = UserFactory()
    TenantMembership.objects.get_or_create(
        tenant=workspace.tenant, user=other, defaults={"role": "member"}
    )
    WorkspaceMembership.objects.create(
        workspace=workspace, user=other, role=WorkspaceRole.VIEWER
    )
    return workspace, workspace.owner, other


@sync_to_async
def say(run_id: Any, event: dict[str, Any]) -> None:
    services.publish_run_event(run_id, event)


@sync_to_async
def remove(workspace: Any, actor: Any, user: Any) -> None:
    workspace_members.remove_workspace_member(actor, workspace.pk, user.pk)


@sync_to_async
def remove_from_tenant(workspace: Any, user: Any) -> None:
    iam.remove_tenant_member(None, workspace.tenant_id, user.pk)


@sync_to_async
def lower(workspace: Any, actor: Any, user: Any) -> None:
    workspace_members.set_workspace_role(
        actor, workspace.pk, user.pk, WorkspaceRole.VIEWER
    )


async def try_open(user: Any, run_id: Any) -> WebsocketCommunicator:
    ticket = await sync_to_async(services.issue_ticket)(user)
    communicator = WebsocketCommunicator(
        application,
        f"/ws/runs/{run_id}/?ticket={ticket}",
        headers=[(b"origin", b"http://localhost:3000")],
    )
    assert await communicator.connect()
    return communicator


async def test_every_member_gets_every_event() -> None:
    workspace, a, b = await two_members()
    sa = await open_socket(a, workspace.run_id)
    sb = await open_socket(b, workspace.run_id)
    await say(workspace.run_id, {"type": "run.changed"})
    assert await sa.receive_json_from() == {"type": "run.changed"}
    assert await sb.receive_json_from() == {"type": "run.changed"}
    await sa.disconnect()
    await sb.disconnect()


async def test_removing_a_membership_closes_only_that_persons_socket() -> None:
    workspace, a, b = await two_members()
    sa = await open_socket(a, workspace.run_id)
    sb = await open_socket(b, workspace.run_id)
    await remove(workspace, a, b)
    await closed_with(sb, ACCESS_REMOVED)
    # a new ticket no longer opens it
    again = await try_open(b, workspace.run_id)
    await closed_with(again, 4404)
    # A is still connected and still hears
    await say(workspace.run_id, {"type": "run.changed"})
    assert await sa.receive_json_from() == {"type": "run.changed"}
    await sa.disconnect()


async def test_leaving_the_tenant_closes_the_socket() -> None:
    workspace, a, b = await two_members()
    sa = await open_socket(a, workspace.run_id)
    sb = await open_socket(b, workspace.run_id)
    await remove_from_tenant(workspace, b)
    await closed_with(sb, ACCESS_REMOVED)
    await say(workspace.run_id, {"type": "run.changed"})
    assert await sa.receive_json_from() == {"type": "run.changed"}
    await sa.disconnect()


async def test_a_role_lowered_to_viewer_keeps_the_socket() -> None:
    workspace, a, b = await two_members()
    await sync_to_async(
        WorkspaceMembership.objects.filter(workspace=workspace, user=b).update
    )(role=WorkspaceRole.EDITOR)
    sb = await open_socket(b, workspace.run_id)
    await lower(workspace, a, b)
    await say(workspace.run_id, {"type": "run.changed"})
    assert await sb.receive_json_from() == {"type": "run.changed"}
    await sb.disconnect()
