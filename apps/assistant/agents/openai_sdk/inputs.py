"""The conversation as the model gets it."""

import json

from agents import TResponseInputItem

from apps.assistant.agents.base import Definition, DocumentRef, Message
from apps.assistant.agents.openai_sdk.tools._shared import NAME_CHARS, as_data

LISTED_DOCUMENTS = 50  # documents named in the request
HISTORY_MESSAGES = 20  # the most recent turns of the conversation
HISTORY_CHARS = 2000  # of each earlier turn


def build_input(
    text: str,
    definition: Definition,
    history: list[Message],
    refs: list[DocumentRef],
) -> list[TResponseInputItem]:
    """The conversation for the model: earlier turns, then the request with its context."""
    items: list[TResponseInputItem] = [
        {"role": turn.role, "content": turn.text[:HISTORY_CHARS]}
        for turn in history[-HISTORY_MESSAGES:]
        if turn.text
    ]
    listed = refs[:LISTED_DOCUMENTS]
    if listed:
        names = "\n".join(
            f"- {ref.id}: {as_data(ref.name[:NAME_CHARS])}" for ref in listed
        )
        more = len(refs) - len(listed)
        if more:
            names += f"\n- and {more} more"
        documents = f"The documents of this run (id: name):\n{names}"
    else:
        documents = "This run has no documents to read."
    context = (
        "The definition on my screen:\n"
        f"```json\n{json.dumps(definition, ensure_ascii=False, indent=2)}\n```\n\n"
        f"{documents}\n\n"
        f"My request:\n{text}"
    )
    items.append({"role": "user", "content": context})
    return items
