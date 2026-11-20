"""The default template's definition as plain JSON, for tests that need a valid one."""

from typing import Any

from apps.extraction.template_registry import default_template

_DEFINITION = default_template().definition.model_dump()

DEFAULT_PROMPT: str = _DEFINITION["prompt"]
DEFAULT_RECORD_TYPES: list[dict[str, Any]] = _DEFINITION["record_types"]
DEFAULT_OUTPUT: dict[str, Any] = _DEFINITION["output"]
