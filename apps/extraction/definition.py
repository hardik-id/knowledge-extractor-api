"""The shape of an extraction definition, and the rules that belong to the shape.

A draft has a prompt, record types and an output; a record type has fields.
Each model here owns its own part and nothing else. This module knows nothing
about the database, HTTP or Django: ``apps.extraction.validation`` turns a failure
into an API error, and the serializers that describe the wire are in
``apps.extraction.api``.

Strings are trimmed, as they always were on the wire. An id that is missing or
blank is filled in.
"""

import uuid
from typing import Literal, Self, get_args

import pydantic
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

Mode = Literal["quote", "inferred"]
ValueType = Literal["text", "date", "number", "choice"]
Format = Literal["json", "markdown", "csv"]

MODES: tuple[str, ...] = get_args(Mode)
VALUE_TYPES: tuple[str, ...] = get_args(ValueType)
FORMATS: tuple[str, ...] = get_args(Format)


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class Field(BaseModel):
    """What is read from a record: its key, how it is found and what it holds."""

    model_config = ConfigDict(str_strip_whitespace=True)

    id: str = pydantic.Field(default="", validate_default=True)
    key: str
    name: str
    description: str = ""
    mode: Mode
    value_type: ValueType
    choices: list[str] = []
    multiple: bool = False

    @field_validator("id")
    @classmethod
    def _fill_id(cls, value: str) -> str:
        return value or _new_id("f")


class RecordType(BaseModel):
    """A kind of record and the fields it has. Each field has a key, no two the same."""

    model_config = ConfigDict(str_strip_whitespace=True)

    id: str = pydantic.Field(default="", validate_default=True)
    name: str
    description: str = ""
    fields: list[Field]

    @field_validator("id")
    @classmethod
    def _fill_id(cls, value: str) -> str:
        return value or _new_id("rt")

    @model_validator(mode="after")
    def _keys_are_set_and_unique(self) -> Self:
        keys = [field.key for field in self.fields]
        if not all(keys) or len(set(keys)) != len(keys):
            raise ValueError(
                f'The fields of "{self.name}" need a key each, and no two may share one.'
            )
        return self


class Output(BaseModel):
    """How the records are written out."""

    model_config = ConfigDict(str_strip_whitespace=True)

    format: Format
    template: str


class Draft(BaseModel):
    """A definition without ``version`` and ``base_version``."""

    model_config = ConfigDict(str_strip_whitespace=True)

    prompt: str
    record_types: list[RecordType]
    output: Output
