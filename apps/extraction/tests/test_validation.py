import copy
from typing import Any

import pytest

from apps.core.errors import ApiError
from apps.extraction.defaults import (
    DEFAULT_OUTPUT,
    DEFAULT_PROMPT,
    DEFAULT_RECORD_TYPES,
)
from apps.extraction.validation import DraftSerializer, parse_draft, validate_draft


def draft() -> dict[str, Any]:
    return copy.deepcopy(
        {
            "prompt": DEFAULT_PROMPT,
            "record_types": DEFAULT_RECORD_TYPES,
            "output": DEFAULT_OUTPUT,
        }
    )


def changed(change: Any) -> dict[str, Any]:
    data = draft()
    change(data)
    return data


def first_field(data: dict[str, Any]) -> dict[str, Any]:
    field: dict[str, Any] = data["record_types"][0]["fields"][0]
    return field


# Valid and invalid samples. The serializers describe the wire for the schema, the
# models decide: both must give the same verdict on each.
VALID = [
    draft(),
    changed(lambda d: first_field(d).pop("id")),
    changed(lambda d: d["record_types"][0].pop("id")),
    changed(lambda d: d["record_types"][0].update(fields=[])),
    changed(lambda d: d.update(record_types=[])),
    changed(lambda d: first_field(d).update(key="  padded ")),
    changed(lambda d: first_field(d).update(multiple=True, choices=["a"])),
    changed(lambda d: d["output"].update(format="csv", template="")),
    changed(lambda d: d.update(extra="ignored")),
]
INVALID: list[Any] = [
    [],
    None,
    {},
    changed(lambda d: d.pop("prompt")),
    changed(lambda d: d.pop("output")),
    changed(lambda d: d.pop("record_types")),
    changed(lambda d: d.update(record_types={})),
    changed(lambda d: first_field(d).update(mode="guessed")),
    changed(lambda d: first_field(d).update(value_type="boolean")),
    changed(lambda d: first_field(d).pop("name")),
    changed(lambda d: first_field(d).update(choices="a")),
    changed(lambda d: d["output"].update(format="xml")),
    changed(lambda d: d["output"].pop("template")),
    changed(lambda d: d.update(prompt=None)),
]
# The serializer cannot see these: they are rules of the record type.
RULES = [
    changed(lambda d: first_field(d).update(key="")),
    changed(lambda d: first_field(d).update(key="   ")),
    changed(lambda d: d["record_types"][0]["fields"][1].update(key="title")),
    changed(lambda d: d["record_types"][0]["fields"][1].update(key=" title ")),
]


def errors_of(error: ApiError) -> list[dict[str, str]]:
    assert error.details is not None
    errors: list[dict[str, str]] = error.details["errors"]
    return errors


def accepted_by_serializer(data: Any) -> bool:
    return DraftSerializer(data=data).is_valid()


def accepted_by_models(data: Any) -> bool:
    try:
        parse_draft(data)
    except ApiError:
        return False
    return True


@pytest.mark.parametrize("data", VALID)
def test_a_valid_draft_is_accepted_by_both(data: Any) -> None:
    assert accepted_by_serializer(data)
    assert accepted_by_models(data)


@pytest.mark.parametrize("data", INVALID)
def test_an_invalid_draft_is_refused_by_both(data: Any) -> None:
    assert not accepted_by_serializer(data)
    assert not accepted_by_models(data)


@pytest.mark.parametrize("data", RULES)
def test_the_rules_of_a_record_type_are_refused_by_the_models(data: Any) -> None:
    assert not accepted_by_models(data)


def test_the_result_is_what_the_serializer_gave_apart_from_ids() -> None:
    data = changed(lambda d: first_field(d).update(key=" title ", description=" d "))
    serializer = DraftSerializer(data=data)
    assert serializer.is_valid()
    expected = serializer.validated_data
    result = validate_draft(data)
    assert result["prompt"] == expected["prompt"]
    assert result["output"] == dict(expected["output"])
    assert result["record_types"] == [
        {**rt, "fields": [dict(f) for f in rt["fields"]]}
        for rt in expected["record_types"]
    ]


def test_validate_draft_fills_ids_and_returns_plain_data() -> None:
    data = changed(lambda d: first_field(d).pop("id"))
    result = validate_draft(data)
    assert result["record_types"][0]["fields"][0]["id"].startswith("f-")
    assert type(result) is dict
    assert type(result["record_types"][0]["fields"][0]) is dict


def test_a_refusal_names_the_path_to_the_value() -> None:
    data = changed(lambda d: d["record_types"][0]["fields"][2].update(mode="guessed"))
    with pytest.raises(ApiError) as error:
        parse_draft(data)
    assert error.value.code == "invalid_definition"
    [problem] = errors_of(error.value)
    assert problem["path"] == "record_types.0.fields.2.mode"


def test_a_refusal_names_the_record_type() -> None:
    data = changed(lambda d: d["record_types"][0]["fields"][1].update(key="title"))
    with pytest.raises(ApiError) as error:
        parse_draft(data)
    [problem] = errors_of(error.value)
    assert problem["path"] == "record_types.0"
    assert '"ADR"' in problem["message"]
    assert "no two may share one" in problem["message"]


def test_a_missing_value_is_named_by_its_path() -> None:
    with pytest.raises(ApiError) as error:
        parse_draft({"prompt": "p", "record_types": []})
    [problem] = errors_of(error.value)
    assert problem["path"] == "output"


def test_not_an_object_is_refused() -> None:
    with pytest.raises(ApiError) as error:
        parse_draft([])
    assert error.value.code == "invalid_definition"
    assert errors_of(error.value)[0]["path"] == ""
