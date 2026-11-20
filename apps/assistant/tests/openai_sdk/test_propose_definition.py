"""The propose_definition tool: validation, corrections, one proposal per reply."""

import copy

import pytest
from agents.testing import (
    ScriptedModel,
    assistant_message,
)

from apps.assistant.agents.openai_sdk import OpenAIAgent
from apps.assistant.agents.openai_sdk.tools import propose_definition
from apps.assistant.tests.fakes import FakeWorkspace
from apps.assistant.tests.openai_sdk.helpers import *  # noqa: F403
from apps.assistant.tests.openai_sdk.helpers import (
    collect,
    duplicate_keys,
    proposal_args,
    propose,
    split,
    tool_outputs,
)
from apps.assistant.tests.test_scripted import adr, bare
from apps.extraction import validation
from apps.extraction.definition import Draft


@pytest.mark.asyncio
async def test_new_things_get_ids_and_the_definition_is_not_changed() -> None:
    draft = adr()
    for record_type in draft["record_types"]:
        record_type["id"] = ""
        for field in record_type["fields"]:
            field["id"] = ""
    model = ScriptedModel(
        [[propose(proposal_args(draft))], [assistant_message("Done.")]]
    )
    given = Draft.model_validate(bare())
    before = copy.deepcopy(given)
    events = [
        e async for e in OpenAIAgent(model).reply("hi", given, [], FakeWorkspace())
    ]
    _, [proposal] = split(events)
    assert all(rt.id for rt in proposal.definition.record_types)
    assert all(f.id for rt in proposal.definition.record_types for f in rt.fields)
    assert given == before


@pytest.mark.asyncio
async def test_an_invalid_first_proposal_goes_back_and_is_corrected_in_a_second_turn() -> (
    None
):
    model = ScriptedModel(
        [
            [
                assistant_message("Here is a first try."),
                propose(proposal_args(duplicate_keys()), "p1"),
            ],
            [propose(proposal_args(), "p2")],
            [assistant_message("Fixed the keys.")],
        ]
    )
    events = await collect(OpenAIAgent(model))
    model.assert_complete()
    [error] = tool_outputs(model.calls[1])
    assert error.startswith("Error: ")
    assert "the definition is not valid" in error
    assert "no two may share one" in error
    text, [proposal] = split(events)
    assert proposal.definition.model_dump() == Draft.model_validate(adr()).model_dump()
    assert text == "Here is a first try.\n\nFixed the keys."


@pytest.mark.asyncio
async def test_arguments_that_do_not_fit_the_schema_go_back_as_a_tool_error() -> None:
    wrong = proposal_args()
    wrong["definition"]["record_types"][0]["fields"][0]["mode"] = "exact"
    del wrong["definition"]["output"]
    model = ScriptedModel(
        [
            [propose(wrong, "p1")],
            [propose("not json", "p2")],
            [propose({**proposal_args(), "reasons": []}, "p3")],
            [assistant_message("I could not get it right.")],
        ]
    )
    events = await collect(OpenAIAgent(model))
    outputs = tool_outputs(model.calls[-1])
    assert len(outputs) == 3
    assert all(o.startswith("Error: ") for o in outputs)
    assert "definition.record_types.0.fields.0.mode" in outputs[0]
    assert "definition.output" in outputs[0]
    assert "exact" not in outputs[0], "the values are not echoed"
    assert "reason" in outputs[2]
    _, proposals = split(events)
    assert proposals == []


@pytest.mark.asyncio
async def test_only_the_first_valid_proposal_reaches_the_person() -> None:
    other = adr()
    other["prompt"] = "Something else."
    model = ScriptedModel(
        [
            [propose(proposal_args(), "p1"), propose(proposal_args(other), "p2")],
            [propose(proposal_args(other), "p3")],
            [assistant_message("Done.")],
        ]
    )
    events = await collect(OpenAIAgent(model))
    _, [proposal] = split(events)
    assert proposal.definition.prompt == adr()["prompt"]
    assert "already accepted" in tool_outputs(model.calls[-1])[-1]


def test_the_tool_schema_matches_the_definition_rules() -> None:
    schema = propose_definition.TOOL.params_json_schema
    field = schema["$defs"]["FieldArgs"]["properties"]
    assert tuple(field["mode"]["enum"]) == validation.MODES
    assert tuple(field["value_type"]["enum"]) == validation.VALUE_TYPES
    output = schema["$defs"]["OutputArgs"]["properties"]
    assert set(output["format"]["enum"]) == set(validation.FORMATS)
    assert propose_definition.TOOL.strict_json_schema
