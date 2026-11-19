"""Background jobs of the extraction app (docs/jobs.md)."""

from apps.core.jobs import job
from apps.extraction import services


@job()
def extract_file(file_id: str, execution_id: str, definition_version: int) -> None:
    """Extract one file of an execution. See ``services.run_extraction``."""
    services.run_extraction(file_id, execution_id, definition_version)
