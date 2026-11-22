"""Run the configured extractor on a run's files, without the UI, storing nothing.

    uv run python manage.py try_extractor --run <run_id> [--file <name>]

Uses the run's latest saved definition and its example records, as a real run would.
For each file it prints every record found (record type and span) and each field's
value with whether its quote was found in the text. ``EXTRACTOR`` chooses the
extractor; with ``llm`` this calls the configured model (docs/extraction.md).
"""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.core.errors import ApiError
from apps.extraction import selectors
from apps.extraction.extractors import get_extractor
from apps.extraction.extractors.base import Definition, ExtractionError
from apps.extraction.extractors.records import stored_records
from apps.runs import selectors as runs


class Command(BaseCommand):
    help = "Print what the configured extractor finds in a run's files. Stores nothing."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--run", required=True, help="a run id")
        parser.add_argument("--file", help="only the file with this name")

    def handle(self, *args: Any, **options: Any) -> None:
        try:
            run = runs.get_any_run(options["run"])
        except ApiError as error:
            raise CommandError(error.message) from None
        version = selectors.latest_version(run.pk)
        if version is None:
            raise CommandError("This run has no saved definition yet.")
        definition = Definition.from_version(version)
        files = run.files.order_by("name", "id")
        if options["file"]:
            files = files.filter(name=options["file"])
        if not files:
            raise CommandError("The run has no such file.")
        examples = selectors.example_records(run.pk)
        extractor = get_extractor()
        for run_file in files:
            self.stdout.write(f"== {run_file.name}")
            try:
                text = selectors.input_text(run_file).text
                raw = extractor.extract(text, definition, examples)
            except (ApiError, ExtractionError) as error:
                self.stdout.write(f"  failed: {error.message}")
                continue
            self._print(definition, stored_records(text, raw))

    def _print(self, definition: Definition, records: list[Any]) -> None:
        self.stdout.write(f"  {len(records)} records")
        for number, record in enumerate(records, 1):
            record_type = definition.record_type(record.record_type_id)
            span = record.span
            where = f"{span.start}-{span.end}" if span else "no span"
            name = record_type.name if record_type else record.record_type_id
            self.stdout.write(f"  [{number}] {name} ({where})")
            names = {f.id: f.name for f in (record_type.fields if record_type else [])}
            for value in record.values:
                label = names.get(value.field_id, value.field_id)
                if value.value is None:
                    self.stdout.write(f"      {label}: (not found)")
                    continue
                state = "quote found" if value.anchored else "quote NOT found"
                self.stdout.write(f"      {label}: {value.value!r} [{state}]")
