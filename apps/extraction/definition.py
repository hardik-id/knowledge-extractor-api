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
    StrictInt,
    StringConstraints,
    field_validator,
    model_validator,
)

Mode = Literal["quote", "inferred"]
ValueType = Literal["text", "date", "number", "choice"]
Format = Literal["json", "markdown", "csv"]

MODES: tuple[str, ...] = get_args(Mode)
VALUE_TYPES: tuple[str, ...] = get_args(ValueType)
FORMATS: tuple[str, ...] = get_args(Format)
ChunkStrategy = Literal["auto", "heading", "paragraph", "fixed", "custom"]
CHUNK_STRATEGIES: tuple[str, ...] = get_args(ChunkStrategy)
CHUNK_MIN_SIZE = 1000
CHUNK_DEFAULT_SIZE = 4000
CUSTOM_INSTRUCTION_MAX = 2000
CUSTOM_URL_MAX = 2000
CUSTOM_CODE_MAX = 20000
CUSTOM_SUMMARY_MAX = 1000
CUSTOM_CODE_MISSING = "Generate and apply the splitting code first."


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


def chunk_size_range() -> tuple[int, int]:
    """The smallest and largest allowed chunk size under today's setting."""
    largest = int(settings.EXTRACTION_CHUNK_CHARS)
    return min(CHUNK_MIN_SIZE, largest), largest


class CustomChunking(BaseModel):
    """Splitting code written by a sandbox agent for the ``custom`` strategy (prototype).

    ``instruction`` is the person's words, ``source_url`` an optional page the agent
    read, ``code`` the Python source (``def split(text, size)``, see
    ``apps.extraction.custom_chunking``) and ``summary`` what the code does.
    """

    instruction: Annotated[
        Text,
        StringConstraints(
            strip_whitespace=True, min_length=1, max_length=CUSTOM_INSTRUCTION_MAX
        ),
    ]
    source_url: Annotated[
        Text | None, StringConstraints(strip_whitespace=True, max_length=CUSTOM_URL_MAX)
    ] = None
    code: Annotated[Text, StringConstraints(max_length=CUSTOM_CODE_MAX)] = ""
    summary: Annotated[
        Text, StringConstraints(strip_whitespace=True, max_length=CUSTOM_SUMMARY_MAX)
    ] = ""

    @field_validator("source_url")
    @classmethod
    def _blank_url_is_none(cls, value: str | None) -> str | None:
        return value or None


class Chunking(BaseModel):
    """How a long document is cut into parts: a strategy and a part size in characters.

    ``auto`` is the built-in behaviour and has no size: whatever was sent is dropped and
    ``size`` is None. The other strategies take a whole-number size from
    ``min(1000, EXTRACTION_CHUNK_CHARS)`` up to ``settings.EXTRACTION_CHUNK_CHARS``; a
    missing size is 4000 (or the largest allowed size when that is smaller).

    ``custom`` is the splitting code of the ``custom`` strategy (sized like ``fixed``):
    an object only for that strategy and without it the strategy is refused; for every
    other strategy it is None, whatever was sent.
    """

    strategy: ChunkStrategy = "auto"
    size: StrictInt | None = None
    custom: CustomChunking | None = None

    @model_validator(mode="before")
    @classmethod
    def _drop_what_the_strategy_has_no_use_for(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        strategy = data.get("strategy", "auto")
        if strategy == "auto":
            data = {**data, "size": None}
        if strategy != "custom":
            data = {**data, "custom": None}
        return data

    @model_validator(mode="after")
    def _custom_needs_code(self) -> Self:
        if self.strategy == "custom" and (
            self.custom is None or not self.custom.code.strip()
        ):
            raise ValueError(CUSTOM_CODE_MISSING)
        return self

    @model_validator(mode="after")
    def _size_in_range(self) -> Self:
        if self.strategy == "auto":
            return self
        smallest, largest = chunk_size_range()
        if self.size is None:
            self.size = min(CHUNK_DEFAULT_SIZE, largest)
        elif not smallest <= self.size <= largest:
            raise ValueError(
                f"The chunk size must be between {smallest} and {largest} characters."
            )
        return self


def stored_chunking(value: Any) -> Chunking:
    """The chunking of a saved version: ``auto`` when it has none or it is unusable.

    A saved size outside today's range (the setting was changed since) is moved into
    it, so an old version stays readable. This never raises.
    """
    data = value if isinstance(value, dict) else {}
    strategy = data.get("strategy")
    if not isinstance(strategy, str) or strategy not in CHUNK_STRATEGIES:
        return Chunking()
    if strategy == "auto":
        return Chunking()
    size = data.get("size")
    if not isinstance(size, int) or isinstance(size, bool):
        size = None
    else:
        smallest, largest = chunk_size_range()
        size = min(largest, max(smallest, size))
    try:
        return Chunking(
            strategy=strategy,  # type: ignore[arg-type]
            size=size,
            custom=data.get("custom"),
        )
    except pydantic.ValidationError:
        return Chunking()


class Draft(BaseModel):
    """A definition without ``version`` and ``base_version``."""

    model_config = ConfigDict(str_strip_whitespace=True)

    prompt: Text
    record_types: list[RecordType]
    output: Output
    chunking: Chunking = pydantic.Field(default_factory=Chunking)


class GeneratedPart(BaseModel):
    """A part the generated code makes: its range and the line it begins with."""

    start: int
    end: int
    starts_with: str


class GeneratedDocument(BaseModel):
    file_id: str
    name: str
    characters: int
    parts: list[GeneratedPart]


class GeneratedChunking(BaseModel):
    """The answer of the generate call: the code, what it does and what it makes."""

    code: str
    summary: str
    documents: list[GeneratedDocument]
