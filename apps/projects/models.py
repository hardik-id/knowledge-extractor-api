from django.db import models

from apps.core.models import OwnedModel


class Project(OwnedModel):
    """A name on one run: its documents, configuration, conversation and records.

    ``updated_at`` is when the project itself changed. The last activity, which
    includes the run's work, is worked out by ``selectors``.
    """

    name = models.CharField(max_length=120)
    description = models.TextField(blank=True, default="")
    run = models.OneToOneField(
        "runs.Run", on_delete=models.PROTECT, related_name="project"
    )
