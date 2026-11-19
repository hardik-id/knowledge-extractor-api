"""Ask the configured assistant agent one question in the terminal, without the UI.

    uv run python manage.py ask_assistant "<text>" [--run <id>]

The reply's text is printed as it streams, then the proposal (if any) as JSON.
Without ``--run`` the agent starts from a bare definition and has no documents;
with it, from the run's latest saved definition and with the run's documents.
Nothing is stored. ``ASSISTANT_AGENT`` chooses the agent (docs/assistant.md).
"""

import asyncio
import json
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.assistant.agents.base import (
    Definition,
    DocumentRef,
    Proposal,
    RunDocuments,
    TextDelta,
)
from apps.assistant.agents.registry import get_agent
from apps.assistant.selectors import documents_of_run
from apps.core.errors import ApiError
from apps.extraction import selectors as extraction
from apps.extraction.validation import validate_draft
from apps.runs import selectors as runs

BARE: Definition = {
    "prompt": "",
    "record_types": [],
    "output": {"format": "markdown", "template": ""},
}


class NoDocuments:
    async def list(self) -> list[DocumentRef]:
        return []

    async def read(self, document_id: str) -> str:
        raise ApiError("document_not_found")


class Command(BaseCommand):
    help = "Ask the assistant agent one question and print its reply and proposal."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("text", help="what to ask the assistant")
        parser.add_argument(
            "--run",
            help="a run id: its latest definition and its documents are used",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        text = options["text"].strip()
        if not text:
            raise CommandError("Say what to ask.")
        documents: RunDocuments = NoDocuments()
        definition = validate_draft(BARE)
        if options["run"]:
            try:
                run = runs.get_any_run(options["run"])
            except ApiError as error:
                raise CommandError(error.message) from None
            saved = extraction.get_definition(run.owner, run.pk)
            definition = validate_draft(
                {
                    "prompt": saved.prompt,
                    "record_types": saved.record_types,
                    "output": saved.output,
                }
            )
            documents = documents_of_run(run)
        proposal = asyncio.run(self._ask(text, definition, documents))
        self.stdout.write("")
        if proposal is None:
            self.stdout.write("(no proposal)")
            return
        validate_draft(proposal.definition)
        self.stdout.write("Proposal:")
        self.stdout.write(
            json.dumps(
                {"definition": proposal.definition, "reasons": proposal.reasons},
                ensure_ascii=False,
                indent=2,
            )
        )

    async def _ask(
        self, text: str, definition: Definition, documents: RunDocuments
    ) -> Proposal | None:
        proposal: Proposal | None = None
        async for event in get_agent().reply(text, definition, [], documents):
            if isinstance(event, TextDelta):
                self.stdout.write(event.text, ending="")
                self.stdout.flush()
            elif isinstance(event, Proposal):
                proposal = event
        return proposal
