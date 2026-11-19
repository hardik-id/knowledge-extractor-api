"""Reads for the projects app.

A selector takes the acting user and returns only what that user may see.
"""

from typing import Any, cast

from django.apps import apps
from django.db.models import (
    Count,
    DateTimeField,
    IntegerField,
    Max,
    OuterRef,
    QuerySet,
    Subquery,
)
from django.db.models.functions import Coalesce, Greatest

from apps.core.permissions import get_visible_or_404
from apps.identity.models import User
from apps.projects.models import Project


def _latest(model: str, path: str, field: str = "updated_at") -> Subquery:
    """The newest ``field`` of ``model`` rows reached from the run by ``path``.

    Models of other apps are looked up by name, so this app imports none of them.
    """
    rows = apps.get_model(model).objects.filter(**{path: OuterRef("run_id")})
    return Subquery(
        rows.order_by().values(path).annotate(m=Max(field)).values("m"),
        output_field=DateTimeField(),
    )


def _annotated(projects: Any) -> QuerySet[Project]:
    """Add ``document_count``, ``configuration_version`` and ``activity``.

    Every figure is a subquery, so the number of queries does not depend on the
    number of projects. ``activity`` is the newest change among the project, the
    run's files and cells, its definition versions, its records and its messages.
    """
    files = apps.get_model("runs.RunFile").objects.filter(run=OuterRef("run_id"))
    versions = apps.get_model("extraction.DefinitionVersion").objects.filter(
        run=OuterRef("run_id")
    )
    return projects.annotate(  # type: ignore[no-any-return]
        document_count=Coalesce(
            Subquery(
                files.order_by().values("run").annotate(n=Count("pk")).values("n"),
                output_field=IntegerField(),
            ),
            0,
        ),
        configuration_version=Subquery(
            versions.order_by().values("run").annotate(v=Max("version")).values("v"),
            output_field=IntegerField(),
        ),
        activity=Greatest(
            "updated_at",
            _latest("runs.RunFile", "run"),
            _latest("runs.Cell", "file__run"),
            _latest("extraction.DefinitionVersion", "run"),
            _latest("extraction.Extraction", "file__run"),
            _latest("extraction.ExtractionRecord", "extraction__file__run"),
            _latest("extraction.FieldValue", "record__extraction__file__run"),
            _latest("assistant.Message", "run"),
        ),
    )


def list_projects(user: User) -> QuerySet[Project]:
    """The person's projects, with the figures of the wire shape, last activity first."""
    owned = cast(QuerySet[Project], Project.objects.visible_to(user))
    return _annotated(owned).order_by("-activity", "-id")  # type: ignore[misc]


def get_project(user: User, project_id: Any) -> Project:
    """The project, if ``user`` owns it. Someone else's and an unknown id are both 404."""
    found = get_visible_or_404(Project, user, project_id, code="project_not_found")
    return _annotated(Project.objects.filter(pk=found.pk)).get()


def run_has_project(run_id: Any) -> bool:
    """Whether a project owns this run."""
    return Project.objects.filter(run_id=run_id).exists()
