from django.db import models

from apps.core.models import BaseModel, OwnedModel


class Run(OwnedModel):
    """A set of files a person works on, one cell per file and stage."""


class RunFile(BaseModel):
    """A file in a run. Its facts are copied from the catalog when the run is made."""

    run = models.ForeignKey(Run, on_delete=models.CASCADE, related_name="files")
    source = models.CharField(max_length=32)
    source_ref = models.CharField(max_length=1024)
    name = models.CharField(max_length=255)
    type = models.CharField(max_length=16)
    size_bytes = models.BigIntegerField()
    location = models.CharField(max_length=1024)
    modified_at = models.DateTimeField()
    etag = models.CharField(max_length=255)


class Stage(models.TextChoices):
    EXTRACT = "extract"


class CellStatus(models.TextChoices):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    STALE = "stale"


class Cell(BaseModel):
    """The state of one stage for one file. ``updated_at`` is when it last changed."""

    file = models.ForeignKey(RunFile, on_delete=models.CASCADE, related_name="cells")
    stage = models.CharField(max_length=32, choices=Stage.choices)
    status = models.CharField(
        max_length=16, choices=CellStatus.choices, default=CellStatus.PENDING
    )
    execution_id = models.CharField(  # noqa: DJ001  (null means none, on the wire too)
        max_length=64, null=True, blank=True
    )
    progress = models.IntegerField(null=True, blank=True)
    error = models.JSONField(null=True, blank=True)  # {code, message}
    output = models.JSONField(null=True, blank=True)  # {name, content_type, size, etag}

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["file", "stage"], name="one_cell_per_stage")
        ]
