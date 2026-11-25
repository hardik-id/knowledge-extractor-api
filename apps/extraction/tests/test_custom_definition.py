"""The ``custom`` chunking strategy in a definition: saved, read back, copied."""

from typing import Any

import pytest

from apps.extraction.definition import Chunking, stored_chunking
from apps.extraction.extractors.base import Definition
from apps.extraction.tests.custom_code import SECTIONS
from apps.extraction.tests.factories import DefinitionVersionFactory
from apps.runs.tests.factories import RunFactory

pytestmark = pytest.mark.django_db

CUSTOM = {
    "instruction": "Split at every level-2 heading",
    "source_url": None,
    "code": SECTIONS,
    "summary": "Splits at each level-2 heading.",
}


def url(run: Any, tail: str = "") -> str:
    return f"/api/v1/runs/{run.pk}/stages/extract/definition{tail}"


@pytest.fixture
def run(user: Any) -> Any:
    return RunFactory(owner=user)


@pytest.fixture
def client(api_client: Any, user: Any) -> Any:
    api_client.force_authenticate(user)
    return api_client


def put(client: Any, run: Any, chunking: Any) -> Any:
    current = client.get(url(run)).json()
    body = {k: current[k] for k in ("prompt", "record_types", "output")}
    return client.put(
        url(run),
        {"base_version": current["version"], **body, "chunking": chunking},
        format="json",
    )


def test_a_custom_chunking_is_saved_and_read_back(client: Any, run: Any) -> None:
    saved = put(client, run, {"strategy": "custom", "size": 2500, "custom": CUSTOM})
    assert saved.status_code == 200, saved.json()
    expected = {"strategy": "custom", "size": 2500, "custom": CUSTOM}
    assert saved.json()["chunking"] == expected
    assert client.get(url(run)).json()["chunking"] == expected
    assert client.get(url(run, "/versions/2")).json()["chunking"] == expected


def test_the_size_of_a_custom_chunking_is_4000_when_missing(
    client: Any, run: Any
) -> None:
    saved = put(client, run, {"strategy": "custom", "custom": CUSTOM})
    assert saved.json()["chunking"]["size"] == 4000


def test_a_custom_chunking_keeps_its_size_range(client: Any, run: Any) -> None:
    refused = put(client, run, {"strategy": "custom", "size": 5, "custom": CUSTOM})
    assert refused.status_code == 422


@pytest.mark.parametrize(
    "custom",
    [None, {}, {**CUSTOM, "code": ""}, {**CUSTOM, "code": "   \n"}],
)
def test_custom_without_code_is_refused(client: Any, run: Any, custom: Any) -> None:
    refused = put(client, run, {"strategy": "custom", "custom": custom})
    assert refused.status_code == 422
    if custom != {}:
        assert "Generate and apply the splitting code first." in str(refused.json())


@pytest.mark.parametrize(
    "bad",
    [
        {**CUSTOM, "instruction": ""},
        {**CUSTOM, "instruction": "x" * 2001},
        {**CUSTOM, "source_url": "u" * 2001},
        {**CUSTOM, "code": "x" * 20001},
        {**CUSTOM, "summary": "s" * 1001},
        {**CUSTOM, "code": "a\x00b"},
    ],
)
def test_the_limits_of_the_custom_block(client: Any, run: Any, bad: Any) -> None:
    assert put(client, run, {"strategy": "custom", "custom": bad}).status_code == 422


@pytest.mark.parametrize("strategy", ["auto", "heading", "paragraph", "fixed"])
def test_other_strategies_drop_the_custom_block(
    client: Any, run: Any, strategy: str
) -> None:
    saved = put(client, run, {"strategy": strategy, "size": 2000, "custom": CUSTOM})
    assert saved.status_code == 200, saved.json()
    assert saved.json()["chunking"]["custom"] is None


def test_a_blank_link_is_none(client: Any, run: Any) -> None:
    saved = put(
        client, run, {"strategy": "custom", "custom": {**CUSTOM, "source_url": " "}}
    )
    assert saved.json()["chunking"]["custom"]["source_url"] is None


def test_a_save_without_chunking_and_a_restore_keep_the_custom_block(
    client: Any, run: Any
) -> None:
    put(client, run, {"strategy": "custom", "size": 2000, "custom": CUSTOM})
    current = client.get(url(run)).json()
    body = {k: current[k] for k in ("prompt", "record_types", "output")}
    saved = client.put(
        url(run), {"base_version": 2, **body, "note": "no chunking key"}, format="json"
    )
    assert saved.json()["chunking"]["custom"] == CUSTOM
    put(client, run, {"strategy": "auto"})
    restored = client.post(url(run, "/versions/2/restore"))
    assert restored.json()["chunking"] == {
        "strategy": "custom",
        "size": 2000,
        "custom": CUSTOM,
    }


def test_an_unusable_stored_custom_block_reads_as_auto() -> None:
    auto = Chunking()
    for value in (
        {"strategy": "custom", "size": 2000},
        {"strategy": "custom", "size": 2000, "custom": "x"},
        {"strategy": "custom", "size": 2000, "custom": {**CUSTOM, "code": ""}},
    ):
        assert stored_chunking(value) == auto
    good = stored_chunking({"strategy": "custom", "size": 2000, "custom": CUSTOM})
    assert good.strategy == "custom" and good.custom is not None
    assert good.custom.code == SECTIONS


def test_a_definition_version_carries_the_custom_block(run: Any) -> None:
    version = DefinitionVersionFactory(
        run=run,
        chunking={"strategy": "custom", "size": 2000, "custom": CUSTOM},
    )
    chunking = Definition.from_version(version).chunking
    assert chunking.custom is not None
    assert chunking.custom.instruction == CUSTOM["instruction"]


def test_a_custom_object_without_code_gives_the_contract_message(
    client: Any, run: Any
) -> None:
    body = {"instruction": "x", "source_url": None, "summary": ""}
    refused = put(client, run, {"strategy": "custom", "custom": body})
    assert refused.status_code == 422
    assert "Generate and apply the splitting code first." in str(refused.json())
    assert "Field required" not in str(refused.json())
