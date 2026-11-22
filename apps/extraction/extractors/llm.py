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
from apps.extraction.extractors.llm_output import ModelOutput, to_raw_records
from apps.extraction.extractors.llm_prompt import INSTRUCTIONS, build_input

log = structlog.get_logger(__name__)

# Our own spans come from OpenTelemetry; the SDK never exports traces to OpenAI.
set_tracing_disabled(True)

NOT_CONFIGURED = "No language model is configured for extraction."
UNREACHABLE = "The language model could not be reached."
UNUSABLE = "The language model's answer could not be used."
TOO_LONG = "This document is too long to extract."
TOO_LARGE = "This definition is too large to extract with."


# One part's answer: the output, (input tokens, output tokens) and the seconds it took.
_Answer = tuple[ModelOutput, tuple[int, int], float]


class LlmExtractor:
    """Extracts with the model named by ``LLM_PROVIDER`` and ``LLM_MODEL``."""

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
        if len(parts) > settings.EXTRACTION_MAX_CHUNKS:
            raise ExtractionError(TOO_LONG)
        messages = [
            build_input(text[start:end], definition, examples) for start, end in parts
        ]
        if any(len(m) > settings.EXTRACTION_MAX_INPUT_CHARS for m in messages):
            raise ExtractionError(TOO_LARGE)
        telemetry.chunks(len(parts))
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
        for (start, end), (output, usage, seconds) in zip(parts, answers, strict=True):
            part = to_raw_records(text, definition, output, start, end)
            telemetry.model_call(
                model=settings.LLM_MODEL,
                input_tokens=usage[0],
                output_tokens=usage[1],
                records=len(part),
                seconds=seconds,
            )
            records.extend(part)
        return records

    @staticmethod
    def _failed(message: str) -> ExtractionError:
        # The failure's kind is logged by the job (never its message: it can quote the request).
        log.warning("extraction_model_failed", reason=message)
        return ExtractionError(message)

    async def _ask_all(self, messages: list[str]) -> list[_Answer]:
        """One call per message, at most ``EXTRACTION_CONCURRENCY`` at a time.

        All or nothing: the first failure cancels the other calls, and all of them
        together get ``EXTRACTION_FILE_TIMEOUT_SECONDS``.
        """
        model, client = connect()
        gate = asyncio.Semaphore(max(settings.EXTRACTION_CONCURRENCY, 1))

        async def one(message: str) -> _Answer:
            async with gate:
                return await self._ask(model, message)

        try:
            async with asyncio.timeout(settings.EXTRACTION_FILE_TIMEOUT_SECONDS):
                async with asyncio.TaskGroup() as group:
                    tasks = [group.create_task(one(m)) for m in messages]
            return [task.result() for task in tasks]
        except BaseExceptionGroup as group:
            # The first failure, as if the call had been made on its own.
            raise group.exceptions[0] from None
        finally:
            await client.close()

    async def _ask(self, model: Any, message: str) -> _Answer:
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
        return (
            output,
            (usage.input_tokens, usage.output_tokens),
            (time.perf_counter() - started),
        )
