"""ReplyContext: what the tools of one reply share."""

from dataclasses import dataclass, field

from apps.assistant.agents.base import DocumentRef, RunView, ToolUsed
from apps.assistant.proposal import Proposal
from apps.extraction.definition import Chunking


@dataclass
class ReplyContext:
    """The run's view and what the tools have done so far in one reply."""

    run_view: RunView
    refs: list[DocumentRef]
    chunking: Chunking = field(
        default_factory=Chunking
    )  # of the definition asked about
    proposal: Proposal | None = None
    reads: int = 0
    previews: int = 0  # previews run so far
    rejected: int = 0  # proposals sent back as errors
    tool_calls: int = 0  # every tool call of the reply, refused ones too
    used: list[ToolUsed] = field(default_factory=list)  # calls and how they ended
    announced: int = 0  # how many of ``used`` the runner has sent on
