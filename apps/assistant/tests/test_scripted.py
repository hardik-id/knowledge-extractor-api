"""The cases of the UI's mock-assistant.test.ts, in Python, with the same expectations."""

import copy
import itertools
import re
from dataclasses import dataclass
from typing import Any

from apps.assistant.agents.scripted import assistant_reply, key_from_name
from apps.extraction.definition import Draft
from apps.extraction.tests.default_definition import (
    DEFAULT_OUTPUT,
    DEFAULT_PROMPT,
    DEFAULT_RECORD_TYPES,
)

Definition = dict[str, Any]

counter = itertools.count(1)


def ids() -> str:
    return f"id-{next(counter)}"


def bare(prompt: str = "") -> Definition:
    return {
        "prompt": prompt,
        "record_types": [],
        "output": {"format": "markdown", "template": ""},
    }


def adr() -> Definition:
    return copy.deepcopy(
        {
            "prompt": DEFAULT_PROMPT,
            "record_types": DEFAULT_RECORD_TYPES,
            "output": DEFAULT_OUTPUT,
        }
    )


@dataclass
class Proposed:
    """A proposal as the JSON it is stored and sent as."""

    definition: Definition
    reasons: list[dict[str, str]]


@dataclass
class Reply:
    text: str
    proposal: Proposed | None


def validated(definition: Definition) -> Definition:
    """The definition as the models keep it: ids filled, strings trimmed."""
    return Draft.model_validate(definition).model_dump()


def reply(text: str, definition: Definition | None = None) -> Reply:
    given = Draft.model_validate(adr() if definition is None else definition)
    result = assistant_reply(text, given, ids)
    if result.proposal is None:
        return Reply(result.text, None)
    dumped = result.proposal.model_dump()
    return Reply(result.text, Proposed(dumped["definition"], dumped["reasons"]))


def proposed(text: str, definition: Definition | None = None) -> Proposed:
    result = reply(text, definition)
    assert result.proposal, f'expected a proposal for "{text}": {result.text}'
    return result.proposal


def assert_valid(definition: Definition) -> None:
    assert definition["record_types"]
    for record_type in definition["record_types"]:
        keys = [f["key"] for f in record_type["fields"]]
        assert all(keys), "keys are not empty"
        assert len(set(keys)) == len(keys), "keys are unique"
        for field in record_type["fields"]:
            assert field["key"] == key_from_name(field["key"]), "keys are in key form"
            if field["value_type"] == "choice":
                assert field["choices"]
        field_ids = [f["id"] for f in record_type["fields"]]
        assert len(set(field_ids)) == len(field_ids)
    validated(definition)


def fields(definition: Definition) -> list[dict[str, Any]]:
    return definition["record_types"][0]["fields"]  # type: ignore[no-any-return]


def field(definition: Definition, key: str) -> dict[str, Any]:
    return next(f for f in fields(definition) if f["key"] == key)


# a bare prompt


def test_adr_gives_the_adr_record_type_and_its_template_with_fresh_ids() -> None:
    proposal = proposed("Extract all ADRs", bare())
    definition = proposal.definition
    assert definition["record_types"][0]["name"] == "ADR"
    assert definition["output"]["template"] == DEFAULT_OUTPUT["template"].strip()
    assert definition["record_types"][0]["id"] != DEFAULT_RECORD_TYPES[0]["id"]
    assert len(proposal.reasons) > 1
    assert_valid(definition)


def test_the_definitions_own_prompt_is_used_when_the_message_has_no_keyword() -> None:
    definition = proposed(
        "help me start", bare("Find architecture decision records")
    ).definition
    assert definition["record_types"][0]["name"] == "ADR"
    assert definition["prompt"] == "Find architecture decision records"


def test_policy_wording_gives_a_requirement_with_quote_fields_and_says_why() -> None:
    result = reply("Extract the policy requirements, suppliers must comply", bare())
    assert result.proposal
    definition = result.proposal.definition
    record_type = definition["record_types"][0]
    assert record_type["name"] == "Requirement"
    assert [(f["key"], f["mode"]) for f in record_type["fields"]] == [
        ("requirement", "quote"),
        ("applies_to", "quote"),
        ("category", "inferred"),
    ]
    assert record_type["fields"][2]["value_type"] == "choice"
    assert re.search("exact quotes", result.text)
    assert re.search("must not be reworded", result.text)
    assert "{{requirement}}" in definition["output"]["template"]
    assert_valid(definition)


def test_anything_else_gets_a_generic_record_type_named_after_the_main_noun() -> None:
    definition = proposed("Find all invoices in these files", bare()).definition
    record_type = definition["record_types"][0]
    assert record_type["name"] == "Invoice"
    assert [(f["key"], f["mode"]) for f in record_type["fields"]] == [
        ("title", "quote"),
        ("summary", "inferred"),
    ]
    assert "{{title}}" in definition["output"]["template"]
    assert "{{summary}}" in definition["output"]["template"]
    assert_valid(definition)


def test_falls_back_to_item() -> None:
    assert proposed("hello", bare()).definition["record_types"][0]["name"] == "Item"


# refinements


def test_add_a_field_quote_by_default_in_the_template_key_derived() -> None:
    proposal = proposed("Add a field for approval date")
    added = field(proposal.definition, "approval_date")
    assert added["name"] == "Approval date"
    assert added["mode"] == "quote"
    assert added["value_type"] == "date"
    assert "{{approval_date}}" in proposal.definition["output"]["template"]
    assert proposal.reasons[0]["path"] == "ADR / Approval date"
    assert_valid(proposal.definition)


def test_add_as_inferred_and_the_key_stays_unique() -> None:
    definition = proposed("add title 2 as inferred").definition
    assert field(definition, "title_2")["mode"] == "inferred"
    again = proposed("add summary, summarise it")
    assert field(again.definition, "summary")["mode"] == "inferred"


def test_add_a_field_that_exists_is_not_a_proposal() -> None:
    assert reply("add a field for title").proposal is None


def test_add_does_not_touch_the_template_when_the_format_is_not_markdown() -> None:
    definition = adr()
    definition["output"]["format"] = "json"
    next_definition = proposed("add owner", definition).definition
    assert (
        next_definition["output"]["template"]
        == definition["output"]["template"].strip()
    )


def test_remove_and_drop_also_from_the_template() -> None:
    definition = proposed("Drop the context field").definition
    assert not any(f["key"] == "context" for f in fields(definition))
    assert "{{context}}" not in definition["output"]["template"]
    assert "{{decision}}" in definition["output"]["template"]
    assert_valid(definition)


def test_remove_by_key_and_an_unknown_field_is_explained() -> None:
    assert len(fields(proposed("remove decided_on").definition)) == 5
    none = reply("remove colour")
    assert none.proposal is None
    assert re.search("Title", none.text)


def test_make_exact_and_inferred() -> None:
    assert field(proposed("make status exact").definition, "status")["mode"] == "quote"
    assert (
        field(proposed("Make the title inferred").definition, "title")["mode"]
        == "inferred"
    )
    assert (
        field(proposed("make approved by verbatim").definition, "approved_by")["mode"]
        == "quote"
    )


def test_rename_keeps_the_key() -> None:
    definition = proposed("rename decided on to Decision date").definition
    assert field(definition, "decided_on")["name"] == "Decision date"


def test_split_approver_and_approval_date_replaces_approved_by() -> None:
    proposal = proposed("split approver and approval date")
    definition = proposal.definition
    keys = [f["key"] for f in fields(definition)]
    assert "approved_by" not in keys
    assert "approver" in keys
    assert "approval_date" in keys
    assert field(definition, "approver")["multiple"] is True
    assert field(definition, "approval_date")["value_type"] == "date"
    assert "{{approval_date}}" in definition["output"]["template"]
    assert "approved_by" not in definition["output"]["template"]
    assert len(proposal.reasons) == 3
    assert_valid(definition)


def test_split_with_nothing_to_replace_adds_two_fields() -> None:
    definition = proposed("split owner and deadline").definition
    assert len(fields(definition)) == 8


def test_several_values() -> None:
    definition = proposed("Decision can have several values").definition
    assert field(definition, "decision")["multiple"] is True
    assert "{{#decision}}" in definition["output"]["template"]


def test_output_format() -> None:
    assert proposed("output as json").definition["output"]["format"] == "json"
    assert proposed("Export as CSV please").definition["output"]["format"] == "csv"
    as_json = adr()
    as_json["output"] = {"format": "json", "template": ""}
    output = proposed("output as markdown", as_json).definition["output"]
    assert output["format"] == "markdown"
    assert "{{title}}" in output["template"]


def test_use_a_field_in_the_template() -> None:
    definition = adr()
    definition["output"]["template"] = "## {{title}}\n"
    next_definition = proposed("use status in the template", definition).definition
    assert "{{status}}" in next_definition["output"]["template"]
    assert reply("use title in the template", definition).proposal is None


def test_a_named_record_type_is_the_target() -> None:
    definition = adr()
    definition["record_types"].append(
        {"id": "rt-2", "name": "Risk", "description": "", "fields": []}
    )
    next_definition = proposed(
        "add a field for severity to Risk", definition
    ).definition
    assert [f["key"] for f in next_definition["record_types"][1]["fields"]] == [
        "severity"
    ]


def test_the_input_is_not_changed() -> None:
    definition = adr()
    reply("drop context", definition)
    assert definition == adr()


# no match


def test_no_match_says_what_it_can_do_with_two_examples_and_proposes_nothing() -> None:
    result = reply("what is the weather")
    assert result.proposal is None
    assert re.search("add a field for approval date", result.text)
    assert re.search("make approved by exact", result.text)
