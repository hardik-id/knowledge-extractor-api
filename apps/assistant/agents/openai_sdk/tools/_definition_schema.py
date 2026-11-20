"""The definition as a tool's arguments, derived from the core models.

The Agents SDK wants a strict schema: every property required, no extras. A
variant of each model in ``apps.extraction.definition`` is made from its fields,
so a field added to the definition shows up here without being written twice.
Rules (trimming, unique keys, filling ids) stay with the core models: the
arguments are parsed with ``parse_draft`` after they fit the schema.
"""

from typing import Any, get_args, get_origin

from pydantic import BaseModel, create_model

from apps.assistant.agents.openai_sdk.tools._shared import Strict
from apps.assistant.proposal import Reason
from apps.extraction.definition import Draft


def strict_variant(model: type[BaseModel], name: str) -> type[Strict]:
    """``model`` with every property required, no extras, nested models likewise."""
    fields: dict[str, Any] = {
        field: (_strict(info.annotation), ...)
        for field, info in model.model_fields.items()
    }
    return create_model(name, __base__=Strict, **fields)


def _strict(annotation: Any) -> Any:
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return strict_variant(annotation, f"{annotation.__name__}Args")
    origin = get_origin(annotation)
    if origin is list:
        return list[_strict(get_args(annotation)[0])]  # type: ignore[misc]
    return annotation


DefinitionArgs = strict_variant(Draft, "DefinitionArgs")
ReasonArgs = strict_variant(Reason, "ReasonArgs")
