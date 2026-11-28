"""Run one tool of the assistant by hand and print what the model would get.

    uv run python manage.py assistant_tool --list
    uv run python manage.py assistant_tool <tool> --run <id> [name=value ...]

``--list`` names the tools with their descriptions. Otherwise the tool runs on the
documents and the extractions of the run, exactly as in a reply (same limits, same
wrapping of document text), and its result is printed as it is. A value that starts
with ``{`` or ``[`` is read as JSON, any other value is text. No language model and
no key are needed. Nothing is stored.
"""

import json
from typing import Any

from agents import FunctionTool
from agents.tool_context import ToolContext
from asgiref.sync import async_to_sync
from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.assistant.agents.base import RunView
from apps.assistant.agents.openai_sdk.context import ReplyContext
from apps.assistant.agents.openai_sdk.tools import TOOLS
from apps.assistant.selectors import run_view_of
from apps.core.errors import ApiError
from apps.runs import selectors as runs


def parse_arguments(pairs: list[str]) -> dict[str, Any]:
    """``name=value`` pairs as the arguments of a tool call."""
    arguments: dict[str, Any] = {}
    for pair in pairs:
        name, equals, value = pair.partition("=")
        if not equals or not name:
            raise CommandError(f"Give each argument as name=value, not {pair!r}.")
        if value[:1] in ("{", "["):
            try:
                arguments[name] = json.loads(value)
                continue
            except json.JSONDecodeError:
                raise CommandError(f"The value of {name} is not valid JSON.") from None
        arguments[name] = value
    return arguments


class Command(BaseCommand):
    help = "Run one assistant tool on a run and print what the model would get."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("tool", nargs="?", help="the name of a tool")
        parser.add_argument("arguments", nargs="*", help="name=value, ...")
        parser.add_argument("--run", help="the run id whose documents the tool sees")
        parser.add_argument("--list", action="store_true", help="list the tools")

    def handle(self, *args: Any, **options: Any) -> None:
        tools: dict[str, FunctionTool] = {
            t.name: t for t in TOOLS if isinstance(t, FunctionTool)
        }
        if options["list"]:
            for name, tool in tools.items():
                self.stdout.write(f"{name}\n  {tool.description}\n")
            return
        name = options["tool"]
        if not name:
            raise CommandError("Name a tool, or use --list.")
        if name not in tools:
            raise CommandError(f"No tool {name!r}. Tools: {', '.join(tools)}.")
        if not options["run"]:
            raise CommandError("Give the run with --run <id>.")
        try:
            run = runs.get_any_run(options["run"])
        except ApiError as error:
            raise CommandError(error.message) from None
        arguments = json.dumps(parse_arguments(options["arguments"]))
        run_view = run_view_of(run)
        self.stdout.write(async_to_sync(self._call)(tools[name], run_view, arguments))

    async def _call(self, tool: FunctionTool, run_view: RunView, arguments: str) -> str:
        state = ReplyContext(run_view=run_view, refs=await run_view.documents())
        context = ToolContext(
            state,
            tool_name=tool.name,
            tool_call_id="by-hand",
            tool_arguments=arguments,
        )
        return str(await tool.on_invoke_tool(context, arguments))
