"""Writes and business rules for the workspaces app.

A service takes the acting user as its first argument.
"""

from django.db import transaction

from apps.extraction import services as extraction
from apps.identity.models import User
from apps.runs import services as runs
from apps.workspaces import selectors
from apps.workspaces.models import Workspace


@transaction.atomic
def create_workspace(
    user: User,
    *,
    name: str,
    description: str = "",
    template_id: str | None = None,
) -> Workspace:
    """A workspace with its own empty run and its configuration, made together.

    Version 1 of the definition comes from the template (the default when None).
    """
    run = runs.create_empty_run(user)
    extraction.start_definition(run, template_id)
    workspace = Workspace.objects.create(
        owner=user, name=name, description=description, run=run
    )
    return selectors.get_workspace(user, workspace.pk)


def update_workspace(
    user: User,
    workspace_id: object,
    *,
    name: str | None = None,
    description: str | None = None,
) -> Workspace:
    workspace = selectors.get_workspace(user, workspace_id)
    if name is not None:
        workspace.name = name
    if description is not None:
        workspace.description = description
    workspace.save()
    return selectors.get_workspace(user, workspace.pk)


def delete_workspace(user: User, workspace_id: object) -> None:
    """Delete the workspace, its run and everything on it. The run's sockets close."""
    workspace = selectors.get_workspace(user, workspace_id)
    run = workspace.run
    with transaction.atomic():
        workspace.delete()
        runs.delete_run(run)
