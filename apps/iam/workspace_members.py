"""Who has a role in a workspace: the list, and the changes with the rules of docs/iam.md.

The two changes take the acting person first, run in one transaction with their audit
entry (``audit.record``) and lock the workspace row before counting owners, so two
requests at the same moment cannot both pass the "last owner" rule.
"""

from typing import Any
from uuid import UUID

from django.apps import apps
from django.db import transaction
from django.db.models import Case, IntegerField, QuerySet, Value, When
from django.db.models.functions import Lower

from apps.core.errors import ApiError

from . import audit
from .models import Tenant, TenantMembership, WorkspaceMembership
from .roles import Permission, WorkspaceRole, permissions_of
from .selectors import tenant_permissions, workspace_role


def list_members(user: Any, workspace_id: Any) -> QuerySet[WorkspaceMembership]:
    """The workspace's members, owners first, then by name.

    For a person with a role in the workspace, and for one who manages its members
    without a role (an admin of its tenant, a platform admin). Anyone else, and an
    unknown id: 404 ``workspace_not_found``.
    """
    workspace = _find(workspace_id)
    if not _access(user, workspace):
        raise ApiError("workspace_not_found")
    return (
        WorkspaceMembership.objects.filter(workspace_id=workspace.pk)
        .select_related("user")
        .order_by(
            Case(
                When(role=WorkspaceRole.OWNER, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            ),
            Lower("user__name"),
            "user_id",
        )
    )


def set_workspace_role(
    actor: Any, workspace_id: Any, user_id: Any, role: WorkspaceRole | str
) -> WorkspaceMembership:
    """Make the person ``role`` in the workspace, adding them when they have none.

    Needs ``workspace.members.manage``. Only a member of the workspace's tenant can be
    given a role: anyone else, and an id nobody has, is 422 ``not_a_tenant_member``.
    The last owner cannot step down (409 ``last_owner``). Setting the role a person
    already has changes nothing and records nothing.
    """
    role = WorkspaceRole(role)
    with transaction.atomic():
        workspace = _locked(actor, workspace_id)
        tenant = Tenant.objects.get(pk=workspace.tenant_id)
        target = _tenant_member(tenant, user_id)
        membership = WorkspaceMembership.objects.filter(
            workspace_id=workspace.pk, user=target
        ).first()
        old = WorkspaceRole(membership.role) if membership else None
        if membership is not None and old == role:
            return membership
        if old == WorkspaceRole.OWNER:
            _keep_an_owner(workspace.pk, target)
        if membership is None:
            membership = WorkspaceMembership.objects.create(
                workspace_id=workspace.pk, user=target, role=role
            )
        else:
            membership.role = role
            membership.save(update_fields=["role", "updated_at"])
        audit.record(
            actor=actor,
            action="workspace.role.set",
            target_user=target,
            tenant=tenant,
            workspace_id=workspace.pk,
            old_role=old or "",
            new_role=role,
        )
        return membership


def remove_workspace_member(actor: Any, workspace_id: Any, user_id: Any) -> None:
    """Take the person out of the workspace; a person may take themselves out.

    Needs ``workspace.members.manage``, except to remove oneself: any role in the
    workspace is enough for that. Not a member: 404 ``user_not_found``. The last owner
    cannot go (409 ``last_owner``).
    """
    with transaction.atomic():
        pk = _pk(user_id)
        workspace = _locked(actor, workspace_id, leaving=pk)
        membership = (
            WorkspaceMembership.objects.filter(workspace_id=workspace.pk, user_id=pk)
            .select_related("user")
            .first()
            if pk is not None
            else None
        )
        if membership is None:
            raise ApiError("user_not_found")
        if membership.role == WorkspaceRole.OWNER:
            _keep_an_owner(workspace.pk, membership.user)
        old = membership.role
        target = membership.user
        membership.delete()
        audit.record(
            actor=actor,
            action="workspace.member.remove",
            target_user=target,
            tenant=Tenant.objects.get(pk=workspace.tenant_id),
            workspace_id=workspace.pk,
            old_role=old,
        )


def _model() -> Any:
    return apps.get_model("projects.Workspace")


def _find(workspace_id: Any) -> Any:
    try:
        workspace = _model().objects.filter(pk=UUID(str(workspace_id))).first()
    except ValueError:
        workspace = None
    if workspace is None:
        raise ApiError("workspace_not_found")
    return workspace


def _access(user: Any, workspace: Any) -> frozenset[Permission]:
    """What the person may do with the workspace's members: by their role in it, and
    ``workspace.members.manage`` as an admin of its tenant or a platform admin."""
    held: set[Permission] = set()
    role = workspace_role(user, workspace.pk)
    if role is not None:
        held |= permissions_of(role)
    if Permission.WORKSPACE_MEMBERS_MANAGE in tenant_permissions(
        user, workspace.tenant_id
    ):
        held.add(Permission.WORKSPACE_MEMBERS_MANAGE)
    return frozenset(held)


def _locked(actor: Any, workspace_id: Any, leaving: int | None = None) -> Any:
    """The workspace row, locked, after checking the actor may manage its members.

    A workspace the actor may not see is 404 ``workspace_not_found``; one they see
    but may not change is 403 ``forbidden``. The permission is read after the lock,
    so a change of the actor's own role by another request is seen. ``leaving`` is the
    id of the person being removed: the actor taking themselves out needs only a role.
    """
    try:
        pk = UUID(str(workspace_id))
    except ValueError:
        raise ApiError("workspace_not_found") from None
    workspace = _model().objects.select_for_update().filter(pk=pk).first()
    if workspace is None:
        raise ApiError("workspace_not_found")
    held = _access(actor, workspace)
    if not held:
        raise ApiError("workspace_not_found")
    if Permission.WORKSPACE_MEMBERS_MANAGE not in held and not (
        leaving is not None
        and leaving == actor.pk
        and workspace_role(actor, workspace.pk) is not None
    ):
        raise ApiError("forbidden")
    return workspace


def _pk(user_id: Any) -> int | None:
    text = str(user_id)
    if not (text.isascii() and text.isdigit()):
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _tenant_member(tenant: Tenant, user_id: Any) -> Any:
    """The person, when they are in the tenant. Nobody and a stranger answer the same.

    The tenant membership row is locked, so a removal from the tenant at the same
    moment either runs first (this finds nothing) or waits and then removes the role
    this adds."""
    pk = _pk(user_id)
    if pk is not None:
        membership = (
            TenantMembership.objects.select_for_update()
            .filter(tenant=tenant, user_id=pk)
            .select_related("user")
            .first()
        )
        if membership is not None:
            return membership.user
    raise ApiError("not_a_tenant_member")


def _keep_an_owner(workspace_id: UUID, leaving: Any) -> None:
    others = (
        WorkspaceMembership.objects.filter(
            workspace_id=workspace_id, role=WorkspaceRole.OWNER
        )
        .exclude(user=leaving)
        .filter(user__is_active=True)
        .exists()
    )
    if not others:
        raise ApiError("last_owner")


__all__ = ["list_members", "remove_workspace_member", "set_workspace_role"]
