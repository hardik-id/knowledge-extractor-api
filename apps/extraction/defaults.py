"""The definition a run starts with, copied from the UI's mock (src/mocks/extraction.ts)."""

from typing import Any

DEFAULT_PROMPT = "Extract every architecture decision record (ADR) in the document."


def _field(
    key: str,
    name: str,
    description: str,
    mode: str,
    value_type: str,
    choices: list[str] | None = None,
    multiple: bool = False,
) -> dict[str, Any]:
    return {
        "id": f"f-adr-{key.replace('_', '-')}",
        "key": key,
        "name": name,
        "description": description,
        "mode": mode,
        "value_type": value_type,
        "choices": choices or [],
        "multiple": multiple,
    }


DEFAULT_RECORD_TYPES: list[dict[str, Any]] = [
    {
        "id": "rt-adr",
        "name": "ADR",
        "description": "One architecture decision record: a titled decision with its context.",
        "fields": [
            _field("title", "Title", "The title of the decision.", "quote", "text"),
            _field(
                "status",
                "Status",
                "Where the decision stands.",
                "inferred",
                "choice",
                ["proposed", "accepted", "superseded", "rejected"],
            ),
            _field(
                "decided_on",
                "Decided on",
                "The date the decision was made.",
                "inferred",
                "date",
            ),
            _field(
                "approved_by",
                "Approved by",
                "The people who approved the decision.",
                "quote",
                "text",
                multiple=True,
            ),
            _field(
                "context", "Context", "Why the decision was needed.", "quote", "text"
            ),
            _field("decision", "Decision", "What was decided.", "quote", "text"),
        ],
    }
]

DEFAULT_OUTPUT: dict[str, Any] = {
    "format": "markdown",
    "template": """## {{title}}

**Status:** {{status}}
**Decided on:** {{decided_on}}
**Approved by:**
{{#approved_by}}- {{.}}
{{/approved_by}}
### Context

{{context}}

### Decision

{{decision}}
""",
}
