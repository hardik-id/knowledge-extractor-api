"""Ask the configured assistant agent one question in the terminal, without the UI.

    uv run python manage.py ask_assistant "<text>" [--run <id>]

The reply's text is printed as it streams, each tool call on a line of its own
(``[tool survey_documents: ok]``) as it ends, then the proposal (if any) as JSON.
Without ``--run`` the agent starts from a bare definition and has no workspace;
with it, from the run's latest saved definition and with the run's workspace.
Nothing is stored. ``ASSISTANT_AGENT`` chooses the agent (docs/assistant.md).
"""

import json
from typing import Any

from asgiref.sync import async_to_sync
from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.assistant.agents.base import (
    DocumentRef,
    FileRecords,
    RecordView,
    TextDelta,
    ToolUsed,
    Workspace,
)
from apps.assistant.agents.registry import get_agent
from apps.assistant.proposal import Proposal
from apps.assistant.selectors import workspace_of_run
from apps.core.errors import ApiError
from apps.extraction import selectors as extraction
from apps.extraction.definition import Draft
from apps.runs import selectors as runs

BARE = Draft.model_validate(
    {
        "prompt": "",
        "record_types": [],
        "output": {"format": "markdown", "template": ""},
        "chunking": {"strategy": "auto", "size": None},
    }
)


class NoWorkspace:
    """A workspace of no run: no documents and nothing extracted."""

    async def documents(self) -> list[DocumentRef]:
        return []

    async def read(self, document_id: str) -> str:
        raise ApiError("document_not_found")

    async def extractions(self) -> list[FileRecords]:
        return []

    async def preview(self, definition: Draft, document_id: str) -> list[RecordView]:
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
        workspace: Workspace = NoWorkspace()
        definition = BARE
        if options["run"]:
            try:
                run = runs.get_any_run(options["run"])
            except ApiError as error:
                raise CommandError(error.message) from None
            saved = extraction.get_definition(run.owner, run.pk)
            definition = Draft.model_validate(
                {
                    "prompt": saved.prompt,
                    "record_types": saved.record_types,
                    "output": saved.output,
                    "chunking": saved.chunking,
                }
            )
            workspace = workspace_of_run(run)
        proposal = async_to_sync(self._ask)(text, definition, workspace)
        self.stdout.write("")
        if proposal is None:
            self.stdout.write("(no proposal)")
            return
        self.stdout.write("Proposal:")
        self.stdout.write(
            json.dumps(proposal.model_dump(), ensure_ascii=False, indent=2)
        )

    async def _ask(
        self, text: str, definition: Draft, workspace: Workspace
    ) -> Proposal | None:
        proposal: Proposal | None = None
        mid_line = False  # some text is on the line and has no newline yet
        async for event in get_agent().reply(text, definition, [], workspace):
            if isinstance(event, TextDelta):
                self.stdout.write(event.text, ending="")
                self.stdout.flush()
                mid_line = not event.text.endswith("\n")
            elif isinstance(event, ToolUsed):
                self.stdout.write(
                    ("\n" if mid_line else "") + f"[tool {event.name}: {event.outcome}]"
                )
                mid_line = False
            elif isinstance(event, Proposal):
                proposal = event
        return proposal
