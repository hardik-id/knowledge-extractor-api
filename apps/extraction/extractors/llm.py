"""The extractor that calls the language model (``EXTRACTOR=llm``, docs/extraction.md).

One model call per part of the document (a short one is a single part), through the OpenAI Agents SDK: an agent with no tools,
one turn, and ``ModelOutput`` as its output type, which the SDK sends as a strict JSON
schema. The model returns quotes; ``to_raw_records`` finds them in the text. Every
failure becomes an ``ExtractionError`` with a message a person can read.
"""

import asyncio
import time
from collections.abc import Sequence
from typing import Any

import structlog
from agents import (
    Agent,
    AgentsException,
    ModelBehaviorError,
    ModelRefusalError,
    ModelSettings,
    ModelTimeoutError,
    RunConfig,
    Runner,
    set_tracing_disabled,
)
from azure.core.exceptions import AzureError
from django.conf import settings
from openai import APIError

from apps.core.llm import connect, describe_failure, missing_settings, output_limit
from apps.extraction import telemetry
from apps.extraction.extractors.base import Definition, ExtractionError, RawRecord
from apps.extraction.extractors.chunks import split_by
from apps.extraction.extractors.llm_output import (
    MAX_RECORDS,
    ModelOutput,
    to_raw_records,
)
from apps.extraction.extractors.llm_prompt import INSTRUCTIONS, build_input

log = structlog.get_logger(__name__)

# Our own spans come from OpenTelemetry; the SDK never exports traces to OpenAI.
set_tracing_disabled(True)

NOT_CONFIGURED = "No language model is configured for extraction."
UNREACHABLE = "The language model could not be reached."
UNUSABLE = "The language model's answer could not be used."
TOO_LONG = "This document is too long to extract."
TOO_LONG_FOR_SIZE = (
    "This document is too long to extract with this chunk size. "
    "A larger chunk size, or the Automatic strategy, may allow a longer document."
)
UNREADABLE = "This document contains characters that cannot be read."
TOO_LARGE = "This definition is too large to extract with."


def _too_long(definition: Definition) -> str:
    return TOO_LONG if definition.chunking.strategy == "auto" else TOO_LONG_FOR_SIZE


class LlmExtractor:
    """Extracts with the model named by ``LLM_PROVIDER`` and ``LLM_MODEL``.

    ``max_chunks`` and ``timeout`` replace the file limits
    (``EXTRACTION_MAX_CHUNKS``, ``EXTRACTION_FILE_TIMEOUT_SECONDS``), as the
    assistant's preview does.
    """

    def __init__(
        self, max_chunks: int | None = None, timeout: float | None = None
    ) -> None:
        self._max_chunks = max_chunks
        self._timeout = timeout

    def extract(
        self,
        text: str,
        definition: Definition,
        examples: Sequence[RawRecord] = (),
    ) -> list[RawRecord]:
        missing = missing_settings()
        if missing:
            log.warning("extraction_not_configured", missing=missing)
            raise ExtractionError(NOT_CONFIGURED)
        parts = self._parts(text, definition)
        if len(parts) > self._limit():
            raise ExtractionError(_too_long(definition))
        messages = [
            build_input(text[start:end], definition, examples) for start, end in parts
        ]
        if any(len(m) > settings.EXTRACTION_MAX_INPUT_CHARS for m in messages):
            raise ExtractionError(TOO_LARGE)
        telemetry.chunks(len(parts))
        if not parts:
            return []
        try:
            # Called from the worker and from a thread of the assistant's preview:
            # neither has a running loop.
            answers = asyncio.run(self._ask_all(messages))
        except ExtractionError:
            raise
        except (
            TimeoutError,
            ModelTimeoutError,
            ModelBehaviorError,
            ModelRefusalError,
        ) as error:
            raise self._failed(UNUSABLE, error) from None
        except (APIError, AzureError, AgentsException, OSError) as error:
            # The model, the SDK or a sign-in failed.
            raise self._failed(UNREACHABLE, error) from None
        records: list[RawRecord] = []
        for (start, end), output in zip(parts, answers, strict=True):
            if len(records) >= MAX_RECORDS:
                break
            part = to_raw_records(text, definition, output, start, end)
            records.extend(part[: MAX_RECORDS - len(records)])
        return records

    def _limit(self) -> int:
        return self._max_chunks or settings.EXTRACTION_MAX_CHUNKS

    def _parts(self, text: str, definition: Definition) -> list[tuple[int, int]]:
        """The ``(start, end)`` parts of ``text`` for the definition's chunking.

        ``auto`` uses ``EXTRACTION_CHUNK_CHARS``; another strategy uses its size, at
        most ``EXTRACTION_CHUNK_CHARS``. A part is never longer than the size, so a
        text longer than ``limit * size`` cannot fit in ``limit`` parts: it fails
        before the splitter runs (the library strategies are quadratic on a long run
        without whitespace). Parts may be shorter than the size (every strategy), so a
        shorter text can still fail after the split.
        """
        chunking = definition.chunking
        largest = settings.EXTRACTION_CHUNK_CHARS
        size = (
            largest
            if chunking.strategy == "auto" or chunking.size is None
            else min(chunking.size, largest)
        )
        if len(text) > self._limit() * size:
            raise ExtractionError(_too_long(definition))
        try:
            return split_by(text, chunking.strategy, size)
        except UnicodeEncodeError:
            # A lone surrogate (a JSON body can carry one) cannot go to the splitter.
            raise ExtractionError(UNREADABLE) from None

    @staticmethod
    def _failed(message: str, error: BaseException) -> ExtractionError:
        # The error's class, status and provider code, never its message: it can quote
        # the request or the document.
        log.warning(
            "extraction_model_failed", reason=message, **describe_failure(error)
        )
        return ExtractionError(message)

    async def _ask_all(self, messages: list[str]) -> list[ModelOutput]:
        """One call per message, at most ``EXTRACTION_CONCURRENCY`` at a time.

        All or nothing: the first failure cancels the other calls, and all of them
        together get ``EXTRACTION_FILE_TIMEOUT_SECONDS``.
        """
        model, client = connect()
        gate = asyncio.Semaphore(max(settings.EXTRACTION_CONCURRENCY, 1))

        async def one(message: str) -> ModelOutput:
            async with gate:
                return await self._ask(model, message)

        try:
            async with asyncio.timeout(
                self._timeout or settings.EXTRACTION_FILE_TIMEOUT_SECONDS
            ):
                async with asyncio.TaskGroup() as group:
                    tasks = [group.create_task(one(m)) for m in messages]
            return [task.result() for task in tasks]
        except BaseExceptionGroup as group:
            # The first failure, as if the call had been made on its own.
            raise group.exceptions[0] from None
        finally:
            await client.close()

    async def _ask(self, model: Any, message: str) -> ModelOutput:
        started = time.perf_counter()
        agent: Agent[Any] = Agent(
            name="Knowledge Extractor extraction",
            instructions=INSTRUCTIONS,
            model=model,
            model_settings=ModelSettings(
                store=False, **output_limit(settings.EXTRACTION_MAX_OUTPUT_TOKENS)
            ),
            output_type=ModelOutput,
        )
        result = await asyncio.wait_for(
            Runner.run(
                agent,
                message,
                max_turns=1,
                run_config=RunConfig(
                    tracing_disabled=True, trace_include_sensitive_data=False
                ),
            ),
            settings.EXTRACTION_MODEL_TIMEOUT_SECONDS,
        )
        output = result.final_output
        if not isinstance(output, ModelOutput):
            raise ModelBehaviorError("no answer")
        usage = result.context_wrapper.usage
        # At once, so a file that fails later still shows what its finished parts cost.
        telemetry.model_call(
            model=settings.LLM_MODEL,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            records=len(output.records),
            seconds=time.perf_counter() - started,
        )
        return output
