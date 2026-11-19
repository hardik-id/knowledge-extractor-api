"""The schema of a definition. It mirrors apps.extraction.validation; the model's
arguments are checked against it before validate_draft sees them. A tool that
takes a definition as an argument uses ``DefinitionArgs``."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FieldArgs(Strict):
    id: str
    key: str
    name: str
    description: str
    mode: Literal["quote", "inferred"]
    value_type: Literal["text", "date", "number", "choice"]
    choices: list[str]
    multiple: bool


class RecordTypeArgs(Strict):
    id: str
    name: str
    description: str
    fields: list[FieldArgs]


class OutputArgs(Strict):
    format: Literal["json", "markdown", "csv"]
    template: str


class DefinitionArgs(Strict):
    prompt: str
    record_types: list[RecordTypeArgs]
    output: OutputArgs
