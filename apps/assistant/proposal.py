"""What the assistant proposes: a complete definition and a reason for each change.

A proposal is stored in ``AssistantMessage.proposal`` and sent on the socket as
``model_dump()``: ``{definition, reasons}``, the same JSON as ever. The definition
is a ``Draft``, so a proposal that exists is a valid one.
"""

from pydantic import BaseModel

from apps.extraction.definition import Draft


class Reason(BaseModel):
    """Why one thing changed. ``path`` names it in plain words: "ADR / Approved by"."""

    path: str
    reason: str


class Proposal(BaseModel):
    """A complete definition (not a patch) and a reason for each change."""

    definition: Draft
    reasons: list[Reason]
