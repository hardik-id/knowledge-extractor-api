"""The chunking of a configuration: saved per version, read back, kept by every copy."""

from typing import Any

import pytest

from apps.extraction import selectors, template_registry
from apps.extraction.definition import Draft, stored_chunking
from apps.extraction.extractors.base import Definition
from apps.extraction.models import DefinitionVersion
from apps.extraction.tests.factories import DefinitionVersionFactory
from apps.runs.tests.factories import RunFactory

pytestmark = pytest.mark.django_db

AUTO = {"strategy": "auto", "size": None}


def url(run: Any, tail: str = "") -> str:
    return f"/api/v1/runs/{run.pk}/stages/extract/definition{tail}"


@pytest.fixture
def run(user: Any) -> Any:
    return RunFactory(owner=user)


@pytest.fixture
def client(api_client: Any, user: Any) -> Any:
    api_client.force_authenticate(user)
    return api_client


def put(client: Any, run: Any, **changes: Any) -> Any:
    """Save the current definition with ``changes``; a value of None leaves the key out."""
    current = client.get(url(run)).json()
    body = {k: current[k] for k in ("prompt", "record_types", "output", "chunking")}
    body = {k: v for k, v in {**body, **changes}.items() if v is not None}
    return client.put(
        url(run), {"base_version": current["version"], **body}, format="json"
    )


def test_a_new_definition_answers_auto(client: Any, run: Any) -> None:
    assert client.get(url(run)).json()["chunking"] == AUTO


@pytest.mark.parametrize("strategy", ["heading", "paragraph", "fixed"])
def test_save_and_read_back(client: Any, run: Any, strategy: str) -> None:
    saved = put(client, run, chunking={"strategy": strategy, "size": 2500})
    assert saved.status_code == 200, saved.json()
    expected = {"strategy": strategy, "size": 2500}
    assert saved.json()["chunking"] == expected
    assert client.get(url(run)).json()["chunking"] == expected
    assert client.get(url(run, "/versions/2")).json()["chunking"] == expected


def test_auto_drops_whatever_size_was_sent(client: Any, run: Any) -> None:
    for size in (2500, 5, 99999, "abc"):
        saved = put(client, run, chunking={"strategy": "auto", "size": size})
        assert saved.status_code == 200, saved.json()
        assert saved.json()["chunking"] == AUTO


@pytest.mark.parametrize("strategy", ["heading", "paragraph", "fixed"])
def test_a_missing_size_is_4000(client: Any, run: Any, strategy: str) -> None:
    for chunking in ({"strategy": strategy}, {"strategy": strategy, "size": None}):
        saved = put(client, run, chunking=chunking)
        assert saved.json()["chunking"] == {"strategy": strategy, "size": 4000}


def test_a_request_without_chunking_means_auto(client: Any, run: Any) -> None:
    put(client, run, chunking={"strategy": "fixed", "size": 3000})
    older_client = put(
        client, run, chunking=None
    )  # a client that does not know the key
    assert older_client.status_code == 200
    assert older_client.json()["chunking"] == AUTO


def test_an_empty_chunking_object_means_auto(client: Any, run: Any) -> None:
    assert put(client, run, chunking={}).json()["chunking"] == AUTO


@pytest.mark.parametrize(
    "chunking",
    [
        {"strategy": "fixed", "size": 999},
        {"strategy": "heading", "size": 8001},
        {"strategy": "paragraph", "size": 0},
        {"strategy": "paragraph", "size": -5},
        {"strategy": "fixed", "size": "big"},
        {"strategy": "sentence", "size": 4000},
        {"strategy": 3},
        "fixed",
    ],
)
def test_a_bad_chunking_is_422(client: Any, run: Any, chunking: Any) -> None:
    response = put(client, run, chunking=chunking)
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_definition"
    assert client.get(url(run)).json()["version"] == 1, "nothing was saved"


def test_the_size_message_names_the_allowed_range(client: Any, run: Any) -> None:
    response = put(client, run, chunking={"strategy": "fixed", "size": 10})
    [problem] = response.json()["details"]["errors"]
    assert problem["path"] == "chunking"
    assert (
        problem["message"] == "The chunk size must be between 1000 and 8000 characters."
    )


def test_the_largest_size_follows_the_setting(
    client: Any, run: Any, settings: Any
) -> None:
    settings.EXTRACTION_CHUNK_CHARS = 3000
    ok = put(client, run, chunking={"strategy": "fixed", "size": 3000})
    assert ok.status_code == 200
    refused = put(client, run, chunking={"strategy": "fixed", "size": 3001})
    assert refused.status_code == 422
    assert "between 1000 and 3000" in str(refused.json())


def test_the_history_reads_the_chunking_of_each_version(client: Any, run: Any) -> None:
    put(client, run, chunking={"strategy": "paragraph", "size": 1500})
    put(client, run, chunking={"strategy": "fixed", "size": 7000})
    chunkings = [
        client.get(url(run, f"/versions/{n}")).json()["chunking"] for n in (1, 2, 3)
    ]
    assert chunkings == [
        AUTO,
        {"strategy": "paragraph", "size": 1500},
        {"strategy": "fixed", "size": 7000},
    ]


def test_restore_keeps_the_restored_versions_chunking(client: Any, run: Any) -> None:
    put(client, run, chunking={"strategy": "heading", "size": 2000})  # version 2
    put(client, run, chunking={"strategy": "fixed", "size": 6000})  # version 3
    restored = client.post(url(run, "/versions/2/restore"))
    assert restored.status_code == 200
    assert restored.json()["version"] == 4
    heading = {"strategy": "heading", "size": 2000}
    assert restored.json()["chunking"] == heading
    assert client.get(url(run)).json()["chunking"] == heading
    assert client.post(url(run, "/versions/1/restore")).json()["chunking"] == AUTO


def test_a_version_from_before_the_column_reads_as_auto(client: Any, run: Any) -> None:
    # What the migration gives an old row is the column's default; an empty
    # value must read as auto too.
    version = DefinitionVersionFactory(run=run, version=1)
    assert version.chunking == AUTO
    assert client.get(url(run)).json()["chunking"] == AUTO
    DefinitionVersion.objects.filter(pk=version.pk).update(chunking={})
    assert client.get(url(run)).json()["chunking"] == AUTO
    assert client.get(url(run, "/versions/1")).json()["chunking"] == AUTO
    found = DefinitionVersion.objects.get(pk=version.pk)
    assert Definition.from_version(found).chunking.strategy == "auto"


def test_a_saved_size_outside_todays_range_stays_readable(settings: Any) -> None:
    settings.EXTRACTION_CHUNK_CHARS = 2000
    assert stored_chunking({"strategy": "fixed", "size": 8000}).size == 2000
    assert stored_chunking({"strategy": "fixed", "size": 10}).size == 1000
    assert stored_chunking({"strategy": "bogus", "size": 10}).strategy == "auto"
    assert stored_chunking({"strategy": "heading"}).size == 2000


def test_the_extractors_definition_carries_the_chunking(run: Any) -> None:
    version = DefinitionVersionFactory(
        run=run, chunking={"strategy": "paragraph", "size": 1200}
    )
    chunking = Definition.from_version(version).chunking
    assert (chunking.strategy, chunking.size) == ("paragraph", 1200)
    assert Definition(1, "p", []).chunking.strategy == "auto"


def test_the_built_in_templates_start_auto(client: Any) -> None:
    response = client.get("/api/v1/definition-templates")
    assert response.status_code == 200
    for item in response.json()["items"]:
        assert item["definition"]["chunking"] == AUTO


def test_a_template_with_chunking_starts_a_project_with_it(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    template = template_registry.get_template("skill").model_copy(deep=True)
    template.definition = Draft.model_validate(
        {**template.definition.model_dump(), "chunking": {"strategy": "heading"}}
    )
    real = template_registry.get_template
    monkeypatch.setattr(
        template_registry,
        "get_template",
        lambda template_id: template if template_id == "skill" else real(template_id),
    )
    created = client.post(
        "/api/v1/projects", {"name": "P", "template_id": "skill"}, format="json"
    )
    assert created.status_code == 201, created.content
    path = f"/api/v1/runs/{created.json()['run_id']}/stages/extract/definition"
    assert client.get(path).json()["chunking"] == {"strategy": "heading", "size": 4000}


def test_preview_hands_the_drafts_chunking_to_the_extractor(
    run: Any, user: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[Definition] = []

    class Spy:
        def extract(
            self, text: str, definition: Definition, examples: Any
        ) -> list[Any]:
            seen.append(definition)
            return []

    monkeypatch.setattr(selectors, "get_preview_extractor", lambda: Spy())
    draft = Draft.model_validate(
        {
            "prompt": "p",
            "record_types": [],
            "output": {"format": "json", "template": ""},
            "chunking": {"strategy": "fixed", "size": 1500},
        }
    )
    selectors.preview_records(user, run.pk, "text", draft)
    assert seen[0].chunking.model_dump() == {"strategy": "fixed", "size": 1500}
