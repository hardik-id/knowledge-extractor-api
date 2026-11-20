"""The built-in extraction templates: complete starting configurations, one JSON file each.

A template is a ``Draft`` (prompt, record types, output) with an id, a name and a
line that says what it is for. The files in ``templates/`` are read and validated
once, when the app starts, so a broken file fails then and in the tests.
"""

import json
from functools import cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from apps.core.errors import ApiError
from apps.extraction.definition import Draft

TEMPLATES_DIR = Path(__file__).parent / "templates"
DEFAULT_TEMPLATE_ID = "adr"


class Template(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    id: str
    name: str
    description: str
    definition: Draft


@cache
def _load() -> dict[str, Template]:
    templates = {}
    for path in sorted(TEMPLATES_DIR.glob("*.json")):
        try:
            template = Template.model_validate(json.loads(path.read_text("utf-8")))
        except ValueError as error:
            raise ValueError(
                f"Template file {path.name} is not valid: {error}"
            ) from error
        if template.id in templates:
            raise ValueError(f"Template file {path.name} repeats the id {template.id}.")
        templates[template.id] = template
    if DEFAULT_TEMPLATE_ID not in templates:
        raise ValueError(f"The default template {DEFAULT_TEMPLATE_ID} is missing.")
    return templates


def list_templates() -> list[Template]:
    """The default first, then the others by name."""
    templates = _load()
    return sorted(
        templates.values(), key=lambda t: (t.id != DEFAULT_TEMPLATE_ID, t.name.lower())
    )


def get_template(template_id: str) -> Template:
    """The template with this id, or 404 ``template_not_found``."""
    try:
        return _load()[template_id]
    except KeyError:
        raise ApiError("template_not_found") from None


def default_template() -> Template:
    return _load()[DEFAULT_TEMPLATE_ID]
