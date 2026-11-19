"""ReplyContext: what the tools of one reply share."""

from dataclasses import dataclass

from apps.assistant.agents.base import DocumentRef, Proposal, RunDocuments


@dataclass
class ReplyContext:
    """The run's documents and what the tools have done so far in one reply."""

    documents: RunDocuments
    refs: list[DocumentRef]
    proposal: Proposal | None = None
    reads: int = 0
    rejected: int = 0  # proposals sent back as errors
