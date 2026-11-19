from typing import Any

import pytest

from apps.core.errors import ApiError
from apps.extraction import selectors
from apps.extraction.defaults import (
    DEFAULT_OUTPUT,
    DEFAULT_PROMPT,
    DEFAULT_RECORD_TYPES,
)
from apps.extraction.services import save_definition
from apps.extraction.validation import validate_draft
from apps.runs.tests.factories import RunFactory

pytestmark = pytest.mark.django_db


def draft() -> dict[str, Any]:
    return {
        "prompt": DEFAULT_PROMPT,
        "record_types": DEFAULT_RECORD_TYPES,
        "output": DEFAULT_OUTPUT,
    }


def test_validate_draft_fills_ids_and_defaults() -> None:
    data = validate_draft(
        {
            "prompt": "p",
            "record_types": [
                {
                    "name": "T",
                    "fields": [
                        {
                            "key": " a ",
                            "name": "A",
                            "mode": "quote",
                            "value_type": "text",
                        }
                    ],
                }
            ],
            "output": {"format": "json", "template": ""},
        }
    )
    [record_type] = data["record_types"]
    assert record_type["id"]
    assert record_type["fields"][0]["key"] == "a"
    assert record_type["fields"][0]["id"]
    assert record_type["fields"][0]["choices"] == []


def test_validate_draft_rejects_non_objects() -> None:
    with pytest.raises(ApiError) as error:
        validate_draft([])
    assert error.value.code == "invalid_definition"


def test_get_definition_version_returns_an_old_version(user: Any) -> None:
    run = RunFactory(owner=user)
    first = selectors.get_definition(user, run.pk)
    save_definition(user, run.pk, base_version=1, data=draft() | {"prompt": "two"})
    assert selectors.get_definition_version(run.pk, 1).prompt == first.prompt
    assert selectors.get_definition_version(run.pk, 2).prompt == "two"
    with pytest.raises(ApiError):
        selectors.get_definition_version(run.pk, 3)
