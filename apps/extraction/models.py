from typing import Any

from django.db import models

from apps.core.models import BaseModel


def auto_chunking() -> dict[str, Any]:
    """The chunking of a version that never had one (and of the rows before it existed)."""
    return {"strategy": "auto", "size": None}


class DefinitionVersion(BaseModel):
    """One saved version of a run's extraction definition. Versions are never changed."""

    run = models.ForeignKey(
        "runs.Run", on_delete=models.CASCADE, related_name="definition_versions"
    )
    version = models.PositiveIntegerField()
    prompt = models.TextField()
    record_types = models.JSONField()
    output = models.JSONField()
    chunking = models.JSONField(default=auto_chunking)
    note = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["run", "version"], name="one_definition_per_version"
            )
        ]


class Origin(models.TextChoices):
    LLM = "llm"
    HUMAN = "human"


class Review(models.TextChoices):
    SUGGESTED = "suggested"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class Extraction(BaseModel):
    """The records of one run file. ``revision`` goes up on every change to them."""

    file = models.OneToOneField(
        "runs.RunFile", on_delete=models.CASCADE, related_name="extraction"
    )
    revision = models.PositiveIntegerField(default=1)
    source_etag = models.CharField(max_length=255)
    definition_version = models.PositiveIntegerField()


class ExtractionRecord(BaseModel):
    """One record of a record type. ``span`` is ``{start, end, quote}`` or null."""

    extraction = models.ForeignKey(
        Extraction, on_delete=models.CASCADE, related_name="records"
    )
    record_type_id = models.CharField(max_length=64)
    span = models.JSONField(null=True, blank=True)
    origin = models.CharField(max_length=8, choices=Origin.choices, default=Origin.LLM)
    review = models.CharField(
        max_length=16, choices=Review.choices, default=Review.SUGGESTED
    )
    use_as_example = models.BooleanField(default=False)

    class Meta:
        ordering = ["id"]


class FieldValue(BaseModel):
    """One value of a field of a record. ``value`` is null when nothing was found."""

    record = models.ForeignKey(
        ExtractionRecord, on_delete=models.CASCADE, related_name="values"
    )
    field_id = models.CharField(max_length=64)
    value = models.TextField(null=True, blank=True)  # noqa: DJ001  (null is "not found", on the wire too)
    spans = models.JSONField(default=list)
    origin = models.CharField(max_length=8, choices=Origin.choices, default=Origin.LLM)
    review = models.CharField(
        max_length=16, choices=Review.choices, default=Review.SUGGESTED
    )
    anchored = models.BooleanField(default=True)

    class Meta:
        ordering = ["id"]
