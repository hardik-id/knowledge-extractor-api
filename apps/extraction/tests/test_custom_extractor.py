"""The model extractor with the ``custom`` chunking: the saved code cuts the parts."""

import json
from typing import Any

import pytest
from agents.testing import ModelStep, ScriptedModel, assistant_message

from apps.extraction import selectors
from apps.extraction.definition import Draft
from apps.extraction.extractors.base import Definition, ExtractionError
from apps.extraction.extractors.llm import LlmExtractor
from apps.extraction.tests import custom_code as code
from apps.extraction.tests.default_definition import (
    DEFAULT_OUTPUT,
    DEFAULT_PROMPT,
    DEFAULT_RECORD_TYPES,
)
from apps.extraction.tests.test_llm import FakeClient
from apps.extraction.validation import parse_draft
from apps.runs.tests.factories import RunFactory

pytestmark = pytest.mark.django_db

LLM = "apps.extraction.extractors.llm"


def draft(source: str = code.SECTIONS, size: int = 1000) -> Draft:
    return parse_draft(
        {
            "prompt": DEFAULT_PROMPT,
            "record_types": DEFAULT_RECORD_TYPES,
            "output": DEFAULT_OUTPUT,
            "chunking": {
                "strategy": "custom",
                "size": size,
                "custom": {
                    "instruction": "by heading",
                    "code": source,
                    "summary": "",
                },
            },
        }
    )


def definition(**kwargs: Any) -> Definition:
    d = draft(**kwargs)
    return Definition(1, d.prompt, d.record_types, d.chunking)


@pytest.fixture
def model(settings: Any, monkeypatch: pytest.MonkeyPatch) -> ScriptedModel:
    settings.EXTRACTOR = "llm"
    settings.CUSTOM_CHUNKING = "local"
    settings.LLM_PROVIDER = "openai"
    settings.LLM_MODEL = "test-model"
    settings.OPENAI_API_KEY = "sk-test"
    scripted = ScriptedModel()
    monkeypatch.setattr(f"{LLM}.connect", lambda: (scripted, FakeClient()))
    return scripted


def empty() -> ModelStep:
    return ModelStep(output=[assistant_message(json.dumps({"records": []}))])


def sent(model: ScriptedModel) -> list[str]:
    return [
        c.input if isinstance(c.input, str) else c.input[0]["content"]
        for c in model.calls
    ]


def test_each_part_the_code_makes_is_one_model_call(model: ScriptedModel) -> None:
    for _ in range(6):
        model.enqueue(empty())
    LlmExtractor().extract(code.DOCUMENT, definition(), [])
    messages = sent(model)
    assert len(messages) == 6  # the intro and five decisions
    for number in range(1, 6):
        assert sum(f"## Decision {number}\n" in m for m in messages) == 1


def test_the_size_still_limits_the_parts(model: ScriptedModel) -> None:
    for _ in range(40):
        model.enqueue(empty())
    LlmExtractor(max_chunks=40).extract(code.DOCUMENT, definition(size=1000), [])
    assert 1 <= len(model.calls) <= 40


def test_the_too_long_guard_still_applies(model: ScriptedModel, settings: Any) -> None:
    settings.EXTRACTION_MAX_CHUNKS = 1
    with pytest.raises(ExtractionError, match="too long"):
        LlmExtractor().extract("x" * 1001, definition(size=1000), [])
    assert not model.calls


def test_more_parts_than_the_limit_fail(model: ScriptedModel, settings: Any) -> None:
    settings.EXTRACTION_MAX_CHUNKS = 3
    with pytest.raises(ExtractionError, match="too long"):
        LlmExtractor().extract(code.DOCUMENT, definition(), [])
    assert not model.calls


@pytest.mark.parametrize("source", [code.WRONG_RANGE, code.RAISES, code.NO_SPLIT])
def test_code_that_fails_fails_the_document(model: ScriptedModel, source: str) -> None:
    with pytest.raises(ExtractionError) as error:
        LlmExtractor().extract(code.DOCUMENT, definition(source=source), [])
    assert error.value.message == "The custom splitting code failed on this document."
    assert not model.calls


def test_code_that_is_too_slow_fails_the_document(
    model: ScriptedModel, settings: Any
) -> None:
    settings.CUSTOM_CHUNKING_RUN_TIMEOUT_SECONDS = 1
    with pytest.raises(ExtractionError) as error:
        LlmExtractor().extract(code.DOCUMENT, definition(source=code.FOREVER), [])
    assert error.value.message == (
        "The custom splitting code took too long on this document."
    )


def test_it_is_refused_when_the_server_has_it_off(
    model: ScriptedModel, settings: Any
) -> None:
    settings.CUSTOM_CHUNKING = "off"
    with pytest.raises(ExtractionError) as error:
        LlmExtractor().extract(code.DOCUMENT, definition(), [])
    assert error.value.message == "Custom chunking is turned off on this server."
    assert not model.calls


def test_a_text_with_a_lone_surrogate_is_unreadable(model: ScriptedModel) -> None:
    with pytest.raises(ExtractionError, match="cannot be read"):
        LlmExtractor().extract("a\ud800b", definition(), [])


def test_the_assistant_preview_works_with_custom(
    model: ScriptedModel, user: Any, settings: Any
) -> None:
    settings.EXTRACTION_PREVIEW_MAX_CHUNKS = 10
    run = RunFactory(owner=user)
    for _ in range(6):
        model.enqueue(empty())
    selectors.preview_records(run, code.DOCUMENT, draft())
    assert len(model.calls) == 6


def test_an_empty_text_makes_no_parts_and_starts_no_sandbox(
    model: ScriptedModel, monkeypatch: pytest.MonkeyPatch
) -> None:
    started: list[object] = []

    async def no_process(*args: Any, **kwargs: Any) -> Any:
        started.append(args)
        raise AssertionError("a process was started")

    monkeypatch.setattr(
        "apps.extraction.custom_chunking.process.asyncio.create_subprocess_exec",
        no_process,
    )
    assert LlmExtractor().extract("", definition(), []) == []
    assert started == []
