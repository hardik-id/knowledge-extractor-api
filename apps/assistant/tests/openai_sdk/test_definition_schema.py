"""The schema of a definition for a tool is derived from the core models."""

from typing import Any

import pytest
from pydantic import ValidationError

from apps.assistant.agents.openai_sdk.tools._definition_schema import DefinitionArgs
from apps.assistant.proposal import Proposal, Reason
from apps.assistant.tests.test_scripted import adr, validated
from apps.extraction.definition import Draft


def test_a_definition_fits_and_unknown_keys_are_refused() -> None:
    assert DefinitionArgs.model_validate(validated(adr())).model_dump() == validated(
        adr()
    )
    with pytest.raises(ValidationError):
        DefinitionArgs.model_validate({**validated(adr()), "extra": 1})


def _shapes(schema: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any]:
    """Property names (each required) of a schema and of what it holds, by path."""
    schema = defs[schema["$ref"].split("/")[-1]] if "$ref" in schema else schema
    if schema.get("type") == "array":
        return _shapes(schema["items"], defs)
    if "properties" not in schema:
        return {}
    return {
        name: _shapes(prop, defs) for name, prop in schema["properties"].items()
    } | {"__required__": sorted(schema.get("required", []))}


def test_the_strict_schema_names_every_property_of_the_core_models() -> None:
    core = Draft.model_json_schema()
    strict = DefinitionArgs.model_json_schema()
    ours = _shapes(strict, strict.get("$defs", {}))
    theirs = _shapes(core, core.get("$defs", {}))

    def check(a: dict[str, Any], b: dict[str, Any]) -> None:
        names = sorted(k for k in b if k != "__required__")
        assert sorted(k for k in a if k != "__required__") == names
        assert a["__required__"] == names, "every property is required"
        for name in names:
            check(a[name], b[name]) if b[name] else None

    check(ours, theirs)
    assert strict["additionalProperties"] is False


def test_a_proposal_is_a_definition_and_reasons_and_dumps_to_plain_json() -> None:
    proposal = Proposal(
        definition=Draft.model_validate(adr()),
        reasons=[Reason(path="ADR", reason="Looks for decision records.")],
    )
    dumped = proposal.model_dump()
    assert list(dumped) == ["definition", "reasons"]
    assert dumped["definition"] == validated(adr())
    assert dumped["reasons"] == [
        {"path": "ADR", "reason": "Looks for decision records."}
    ]
    with pytest.raises(ValidationError):
        Proposal.model_validate({"definition": {"prompt": "x"}, "reasons": []})
