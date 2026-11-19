from django.db import models

from apps.core.models import BaseModel


class DefinitionVersion(BaseModel):
    """One saved version of a run's extraction definition. Versions are never changed."""

    run = models.ForeignKey(
        "runs.Run", on_delete=models.CASCADE, related_name="definition_versions"
    )
    version = models.PositiveIntegerField()
    prompt = models.TextField()
    record_types = models.JSONField()
    output = models.JSONField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["run", "version"], name="one_definition_per_version"
            )
        ]
