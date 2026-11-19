"""The tools of the agent, one per module, each exporting ``TOOL``.

The rules of a tool:

- It reads through the ``ReplyContext``, never the database or the network itself.
- It returns text. A failure is text that starts with ``Error:`` (``_shared.error``).
- Its output is bounded.
- Document text is always wrapped as untrusted data (``_shared.as_data``).
- Only ``propose_definition`` has an effect, and that effect is on the context.

To add a tool: write a module here that exports ``TOOL``, import it below and add
it to ``TOOLS``. Nothing else changes.
"""

from agents import Tool

from apps.assistant.agents.openai_sdk.tools import (
    find_in_documents,
    propose_definition,
    read_document,
)

TOOLS: list[Tool] = [
    read_document.TOOL,
    find_in_documents.TOOL,
    propose_definition.TOOL,
]
