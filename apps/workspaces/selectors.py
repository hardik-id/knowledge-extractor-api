"""Reads for the workspaces app.

A selector takes the acting user and returns only what that user may see.
"""

from typing import Any, cast

from django.apps import apps
from django.db.models import (
    CharField,
    Count,
    DateTimeField,
    IntegerField,
    Max,
    OuterRef,
    QuerySet,
    Subquery,
)
from django.db.models.functions import Coalesce, Greatest

from apps.core.errors import ApiError
from apps.core.permissions import get_visible_or_404
from apps.iam import selectors as iam
from apps.iam.roles import Permission
from apps.identity.models import User
from apps.workspaces.models import Workspace


def _latest(model: str, path: str, field: str = "updated_at") -> Subquery:
    """The newest ``field`` of ``model`` rows reached from the run by ``path``.

    Models of other apps are looked up by name, so this app imports none of them.
    """
    rows = apps.get_model(model).objects.filter(**{path: OuterRef("run_id")})
    return Subquery(
        rows.order_by().values(path).annotate(m=Max(field)).values("m"),
        output_field=DateTimeField(),
    )


def _annotated(workspaces: Any, user: User) -> QuerySet[Workspace]:
    """Add ``document_count``, ``configuration_version`` and ``activity``.

    Every figure is a subquery, so the number of queries does not depend on the
    number of workspaces. ``activity`` is the newest change among the workspace, the
    run's files and cells, its definition versions, its records and its messages.
    """
    files = apps.get_model("runs.RunFile").objects.filter(run=OuterRef("run_id"))
    versions = apps.get_model("extraction.DefinitionVersion").objects.filter(
        run=OuterRef("run_id")
    )
    roles = apps.get_model("iam.WorkspaceMembership").objects.filter(
        workspace=OuterRef("pk"), user=user
    )
    return workspaces.annotate(  # type: ignore[no-any-return]
        role=Subquery(roles.values("role")[:1], output_field=CharField()),
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


def list_workspaces(user: User, tenant_id: Any = None) -> QuerySet[Workspace]:
    """The person's workspaces, with the figures of the wire shape, last activity first."""
    seen = cast(QuerySet[Workspace], Workspace.objects.visible_to(user))
    if tenant_id is not None:
        seen = seen.filter(tenant_id=tenant_id)
    return _annotated(seen, user).order_by("-activity", "-id")  # type: ignore[misc]


def get_workspace(user: User, workspace_id: Any, permission: Permission) -> Workspace:
    """The workspace, if ``user`` has a role in it that gives ``permission``.

    One they have no role in and an unknown id are both 404 ``workspace_not_found``;
    one they have a role in without ``permission`` is 403 ``forbidden``.
    """
    found = get_visible_or_404(
        Workspace, user, workspace_id, code="workspace_not_found"
    )
    if permission not in iam.workspace_permissions(user, found.pk):
        raise ApiError("forbidden")
    return _annotated(Workspace.objects.filter(pk=found.pk), user).get()


def run_has_workspace(run_id: Any) -> bool:
    """Whether a workspace owns this run."""
    return Workspace.objects.filter(run_id=run_id).exists()
