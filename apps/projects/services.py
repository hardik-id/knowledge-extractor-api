"""Writes and business rules for the projects app.

A service takes the acting user as its first argument.
"""

from django.db import transaction

from apps.extraction import services as extraction
from apps.identity.models import User
from apps.projects import selectors
from apps.projects.models import Project
from apps.runs import services as runs


@transaction.atomic
def create_project(
    user: User,
    *,
    name: str,
    description: str = "",
    template_id: str | None = None,
) -> Project:
    """A project with its own empty run and its configuration, made together.

    Version 1 of the definition comes from the template (the default when None).
    """
    run = runs.create_empty_run(user)
    extraction.start_definition(run, template_id)
    project = Project.objects.create(
        owner=user, name=name, description=description, run=run
    )
    return selectors.get_project(user, project.pk)


def update_project(
    user: User,
    project_id: object,
    *,
    name: str | None = None,
    description: str | None = None,
) -> Project:
    project = selectors.get_project(user, project_id)
    if name is not None:
        project.name = name
    if description is not None:
        project.description = description
    project.save()
    return selectors.get_project(user, project.pk)


def delete_project(user: User, project_id: object) -> None:
    """Delete the project, its run and everything on it. The run's sockets close."""
    project = selectors.get_project(user, project_id)
    run = project.run
    with transaction.atomic():
        project.delete()
        runs.delete_run(run)
