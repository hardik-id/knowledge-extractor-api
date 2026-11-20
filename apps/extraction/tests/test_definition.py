from typing import Any

import pytest
from pydantic import ValidationError

from apps.extraction.defaults import (
    DEFAULT_OUTPUT,
    DEFAULT_PROMPT,
    DEFAULT_RECORD_TYPES,
)
from apps.extraction.definition import Draft, Field, Output, RecordType


def field(**changes: Any) -> dict[str, Any]:
    return {
        "key": "title",
        "name": "Title",
        "mode": "quote",
        "value_type": "text",
    } | changes


def test_a_field_has_defaults() -> None:
    parsed = Field.model_validate(field())
    assert parsed.description == ""
    assert parsed.choices == []
    assert parsed.multiple is False


def test_a_field_key_is_trimmed() -> None:
    assert Field.model_validate(field(key="  title ")).key == "title"


@pytest.mark.parametrize("mode", ["guessed", "", None, 3])
def test_a_field_mode_is_quote_or_inferred(mode: Any) -> None:
    with pytest.raises(ValidationError):
        Field.model_validate(field(mode=mode))


@pytest.mark.parametrize("value_type", ["text", "date", "number", "choice"])
def test_a_field_takes_each_value_type(value_type: str) -> None:
    assert Field.model_validate(field(value_type=value_type)).value_type == value_type


def test_a_field_value_type_is_one_of_the_four() -> None:
    with pytest.raises(ValidationError):
        Field.model_validate(field(value_type="boolean"))


def test_an_output_format_is_json_markdown_or_csv() -> None:
    for format in ("json", "markdown", "csv"):
        assert Output(format=format, template="").format == format
    with pytest.raises(ValidationError):
        Output.model_validate({"format": "xml", "template": ""})


def test_ids_are_filled_in_when_missing_or_blank() -> None:
    record_type = RecordType.model_validate(
        {"name": "T", "id": " ", "fields": [field(), field(key="b", id="f-b")]}
    )
    assert record_type.id.startswith("rt-")
    assert record_type.fields[0].id.startswith("f-")
    assert record_type.fields[1].id == "f-b"


def test_ids_that_are_given_are_kept() -> None:
    record_type = RecordType.model_validate(
        {"id": "rt-x", "name": "T", "fields": [field(id="f-x")]}
    )
    assert (record_type.id, record_type.fields[0].id) == ("rt-x", "f-x")


def test_a_record_type_needs_a_key_on_each_field() -> None:
    with pytest.raises(ValidationError, match='"T" need a key each'):
        RecordType.model_validate({"name": "T", "fields": [field(key="  ")]})


def test_a_record_type_refuses_two_fields_with_one_key() -> None:
    with pytest.raises(ValidationError, match="no two may share one"):
        RecordType.model_validate(
            {"name": "T", "fields": [field(), field(key=" title", name="Other")]}
        )


def test_a_record_type_may_have_no_fields() -> None:
    assert RecordType.model_validate({"name": "T", "fields": []}).fields == []


def test_the_same_key_in_two_record_types_is_fine() -> None:
    one = {"name": "A", "fields": [field()]}
    draft = Draft.model_validate(
        {
            "prompt": "p",
            "record_types": [one, one | {"name": "B"}],
            "output": {"format": "json", "template": ""},
        }
    )
    assert len(draft.record_types) == 2


def test_a_draft_needs_its_three_parts() -> None:
    whole: dict[str, Any] = {
        "prompt": "p",
        "record_types": [],
        "output": {"format": "json", "template": ""},
    }
    assert Draft.model_validate(whole)
    for part in whole:
        with pytest.raises(ValidationError):
            Draft.model_validate({k: v for k, v in whole.items() if k != part})


def test_a_draft_survives_json_and_back() -> None:
    draft = Draft.model_validate(
        {
            "prompt": "p",
            "record_types": [{"name": "T", "fields": [field(), field(key="b")]}],
            "output": {"format": "csv", "template": "x"},
        }
    )
    assert Draft.model_validate_json(draft.model_dump_json()) == draft


def test_the_seeded_default_parses() -> None:
    draft = Draft.model_validate(
        {
            "prompt": DEFAULT_PROMPT,
            "record_types": DEFAULT_RECORD_TYPES,
            "output": DEFAULT_OUTPUT,
        }
    )
    dumped = draft.model_dump()
    assert dumped["record_types"] == DEFAULT_RECORD_TYPES
    assert dumped["output"]["format"] == DEFAULT_OUTPUT["format"]
