"""The built-in templates: every file is valid, and the list endpoint."""

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from apps.core.errors import ApiError
from apps.extraction import template_registry
from apps.extraction.definition import Draft
from apps.extraction.template_registry import TEMPLATES_DIR, Template

FILES = sorted(TEMPLATES_DIR.glob("*.json"))
URL = "/api/v1/definition-templates"
TAG = re.compile(r"\{\{[#^/]?\s*([^}\s]+?)\s*\}\}")


def load(path: Path) -> Template:
    try:
        return Template.model_validate(json.loads(path.read_text("utf-8")))
    except ValueError as error:
        pytest.fail(f"{path.name} is not a valid template: {error}")


def test_there_are_four_built_in_templates() -> None:
    assert [t.id for t in template_registry.list_templates()] == [
        "adr",
        "skill",
        "blank",
        "policy-rule",
    ]


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_every_file_parses_and_is_named_after_its_id(path: Path) -> None:
    assert load(path).id == path.stem, f"{path.name}: the id must be the file name"


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_ids_are_unique_inside_a_template(path: Path) -> None:
    template = load(path)
    ids = [rt.id for rt in template.definition.record_types] + [
        f.id for rt in template.definition.record_types for f in rt.fields
    ]
    repeated = [i for i, n in Counter(ids).items() if n > 1]
    assert not repeated, f"{path.name}: ids used twice: {repeated}"
    assert all(ids), f"{path.name}: every record type and field needs an id in the file"
    keys = [f.key for rt in template.definition.record_types for f in rt.fields]
    assert len(keys) == len(set(keys)), f"{path.name}: a field key is used twice"


def test_ids_are_unique_across_templates() -> None:
    ids: list[str] = []
    for path in FILES:
        template = load(path)
        ids += [rt.id for rt in template.definition.record_types]
        ids += [f.id for rt in template.definition.record_types for f in rt.fields]
    repeated = [i for i, n in Counter(ids).items() if n > 1]
    assert not repeated, f"ids used in more than one file: {repeated}"


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_output_template_uses_only_field_keys(path: Path) -> None:
    template = load(path)
    keys = {f.key for rt in template.definition.record_types for f in rt.fields}
    used = {k for k in TAG.findall(template.definition.output.template) if k != "."}
    assert used <= keys, f"{path.name}: the output template uses {sorted(used - keys)}"


def test_get_template_and_unknown_id() -> None:
    assert template_registry.get_template("skill").name
    with pytest.raises(ApiError) as caught:
        template_registry.get_template("nope")
    assert caught.value.code == "template_not_found"


def test_the_default_is_the_adr_as_it_always_was() -> None:
    old: dict[str, Any] = json.loads(
        (Path(__file__).parent / "old_default.json").read_text("utf-8")
    )
    now = template_registry.default_template().definition.model_dump()
    # Draft trims strings, so the template's trailing newline is gone.
    old["output"]["template"] = old["output"]["template"].strip()
    assert now == old
    assert Draft.model_validate(old).model_dump() == now


@pytest.mark.django_db
class TestListEndpoint:
    def test_lists_the_default_first_then_by_name(
        self, api_client: Any, user: Any
    ) -> None:
        api_client.force_authenticate(user)
        response = api_client.get(URL)
        assert response.status_code == 200
        body = response.json()
        assert body["next"] is None
        assert [t["id"] for t in body["items"]] == [
            "adr",
            "skill",
            "blank",
            "policy-rule",
        ]
        skill = body["items"][1]
        assert set(skill) == {"id", "name", "description", "definition"}
        assert set(skill["definition"]) == {"prompt", "record_types", "output"}
        assert skill["definition"]["output"]["format"] == "markdown"

    def test_needs_a_signed_in_person(self, api_client: Any) -> None:
        response = api_client.get(URL)
        assert response.status_code == 401
