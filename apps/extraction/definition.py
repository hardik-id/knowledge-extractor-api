"""The shape of an extraction definition, and the rules that belong to the shape.

A draft has a prompt, record types, an output and a chunking; a record type has fields.
Each model here owns its own part and nothing else. This module knows nothing
about the database, HTTP or Django: ``apps.extraction.validation`` turns a failure
into an API error, and the serializers that describe the wire are in
``apps.extraction.api``.

Strings are trimmed, as they always were on the wire. An id that is missing or
blank is filled in.
"""

import uuid
from typing import Annotated, Any, Literal, Self, get_args

import pydantic
from django.conf import settings
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    field_validator,
    model_validator,
)

Mode = Literal["quote", "inferred"]
ValueType = Literal["text", "date", "number", "choice"]
Format = Literal["json", "markdown", "csv"]

MODES: tuple[str, ...] = get_args(Mode)
VALUE_TYPES: tuple[str, ...] = get_args(ValueType)
FORMATS: tuple[str, ...] = get_args(Format)
ChunkStrategy = Literal["auto", "heading", "paragraph", "fixed"]
CHUNK_STRATEGIES: tuple[str, ...] = get_args(ChunkStrategy)
CHUNK_MIN_SIZE = 1000
CHUNK_DEFAULT_SIZE = 4000


def _without_nul(value: str) -> str:
    if "\x00" in value:
        raise ValueError("Null characters are not allowed.")
    return value


# Every string of a definition. A NUL cannot be stored in PostgreSQL text, so it is
# refused here, as it always was on the wire.
Text = Annotated[str, AfterValidator(_without_nul)]


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class Field(BaseModel):
    """What is read from a record: its key, how it is found and what it holds."""

    model_config = ConfigDict(str_strip_whitespace=True)

    id: Text = pydantic.Field(default="", validate_default=True)
    key: Text
    name: Text
    description: Text = ""
    mode: Mode
    value_type: ValueType
    choices: list[Text] = []
    multiple: bool = False

    @field_validator("id")
    @classmethod
    def _fill_id(cls, value: str) -> str:
        return value or _new_id("f")


class RecordType(BaseModel):
    """A kind of record and the fields it has. Each field has a key, no two the same."""

    model_config = ConfigDict(str_strip_whitespace=True)

    id: Text = pydantic.Field(default="", validate_default=True)
    name: Text
    description: Text = ""
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
    template: Text


class Chunking(BaseModel):
    """How a long document is cut into parts: a strategy and a part size in characters.

    ``auto`` is the built-in behaviour and has no size: whatever was sent is dropped and
    ``size`` is None. The other strategies take a size from 1000 up to
    ``settings.EXTRACTION_CHUNK_CHARS``; a missing size is 4000 (or the largest allowed
    size when that is smaller).
    """

    strategy: ChunkStrategy = "auto"
    size: int | None = None

    @model_validator(mode="before")
    @classmethod
    def _auto_has_no_size(cls, data: Any) -> Any:
        if isinstance(data, dict) and data.get("strategy", "auto") == "auto":
            return {**data, "size": None}
        return data

    @model_validator(mode="after")
    def _size_in_range(self) -> Self:
        if self.strategy == "auto":
            return self
        largest = int(settings.EXTRACTION_CHUNK_CHARS)
        if self.size is None:
            self.size = min(CHUNK_DEFAULT_SIZE, largest)
        elif not CHUNK_MIN_SIZE <= self.size <= largest:
            raise ValueError(
                f"The chunk size must be between {CHUNK_MIN_SIZE} and {largest} characters."
            )
        return self


def stored_chunking(value: Any) -> Chunking:
    """The chunking of a saved version: ``auto`` when it has none.

    A saved size outside today's range (the setting was lowered since) is moved into
    it, so an old version stays readable.
    """
    data = value if isinstance(value, dict) else {}
    strategy = data.get("strategy")
    if strategy not in CHUNK_STRATEGIES or strategy == "auto":
        return Chunking()
    size = data.get("size")
    largest = int(settings.EXTRACTION_CHUNK_CHARS)
    if not isinstance(size, int) or isinstance(size, bool):
        return Chunking(strategy=strategy, size=None)
    return Chunking(strategy=strategy, size=min(largest, max(CHUNK_MIN_SIZE, size)))


class Draft(BaseModel):
    """A definition without ``version`` and ``base_version``."""

    model_config = ConfigDict(str_strip_whitespace=True)

    prompt: Text
    record_types: list[RecordType]
    output: Output
    chunking: Chunking = pydantic.Field(default_factory=Chunking)
