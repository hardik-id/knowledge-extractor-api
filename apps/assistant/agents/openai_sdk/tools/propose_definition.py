"""propose_definition: the one tool with an effect, and the effect is on the context."""

import json

from pydantic import ValidationError

from apps.assistant.agents.base import Proposal
from apps.assistant.agents.openai_sdk.context import ReplyContext
from apps.assistant.agents.openai_sdk.tools._definition_schema import (
    DefinitionArgs,
    Strict,
)
from apps.assistant.agents.openai_sdk.tools._shared import declare, error
from apps.core.errors import ApiError
from apps.extraction.validation import validate_draft


class ReasonArgs(Strict):
    path: str
    reason: str


class ProposeArgs(Strict):
    definition: DefinitionArgs
    reasons: list[ReasonArgs]


def _schema_errors(err: ValidationError) -> str:
    """Where and why the arguments do not fit the schema, without echoing the values."""
    lines = []
    for item in err.errors(include_input=False, include_url=False)[:10]:
        where = ".".join(str(part) for part in item["loc"]) or "arguments"
        lines.append(f"{where}: {item['msg']}")
    return "; ".join(lines)


def _definition_errors(err: ApiError) -> str:
    details = (err.details or {}).get("errors")
    if not details:
        return err.message
    return f"{err.message} {json.dumps(details, ensure_ascii=False)}"


async def _propose(state: ReplyContext, arguments: str) -> str:
    if state.proposal is not None:
        return error(
            "a proposal was already accepted in this reply, and only one reaches "
            "the person. Do not call propose_definition again."
        )
    try:
        args = ProposeArgs.model_validate_json(arguments or "{}")
    except ValidationError as err:
        state.rejected += 1
        return error(
            "the arguments do not match the schema of propose_definition: "
            f"{_schema_errors(err)}. Correct them and call propose_definition again."
        )
    try:
        definition = validate_draft(args.definition.model_dump())
    except ApiError as err:
        state.rejected += 1
        return error(
            f"the definition is not valid: {_definition_errors(err)} "
            "Correct it and call propose_definition again."
        )
    if not args.reasons:
        state.rejected += 1
        return error(
            "give one reason for each change. Call propose_definition again with reasons."
        )
    state.proposal = Proposal(
        definition,
        [{"path": r.path, "reason": r.reason} for r in args.reasons],
    )
    return (
        "Accepted. The proposal will be shown to the person, who decides whether to "
        "apply it. Do not call propose_definition again; end with a short sentence."
    )


TOOL = declare(
    name="propose_definition",
    description=(
        "Propose a complete definition to the person, with one reason for each change. "
        "The person decides whether to apply it. Call it at most once per reply, unless "
        "it answers with an error."
    ),
    params_json_schema=ProposeArgs.model_json_schema(),
    handler=_propose,
)
