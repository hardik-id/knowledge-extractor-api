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

from apps.core.llm import connect, missing_settings
from apps.extraction import telemetry
from apps.extraction.extractors.base import Definition, ExtractionError, RawRecord
from apps.extraction.extractors.chunks import split
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
TOO_LARGE = "This definition is too large to extract with."


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
        parts = split(text, settings.EXTRACTION_CHUNK_CHARS)
        limit = self._max_chunks or settings.EXTRACTION_MAX_CHUNKS
        if len(parts) > limit:
            raise ExtractionError(TOO_LONG)
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
        except TimeoutError, ModelTimeoutError, ModelBehaviorError, ModelRefusalError:
            raise self._failed(UNUSABLE) from None
        except APIError, AzureError, AgentsException, OSError:
            # The model, the SDK or a sign-in failed.
            raise self._failed(UNREACHABLE) from None
        records: list[RawRecord] = []
        for (start, end), output in zip(parts, answers, strict=True):
            if len(records) >= MAX_RECORDS:
                break
            part = to_raw_records(text, definition, output, start, end)
            records.extend(part[: MAX_RECORDS - len(records)])
        return records

    @staticmethod
    def _failed(message: str) -> ExtractionError:
        # The failure's kind is logged by the job (never its message: it can quote the request).
        log.warning("extraction_model_failed", reason=message)
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
                store=False, max_tokens=settings.EXTRACTION_MAX_OUTPUT_TOKENS
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
