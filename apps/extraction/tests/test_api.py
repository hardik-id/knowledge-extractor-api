"""GET and PUT /api/v1/runs/{id}/stages/extract/definition, through the API."""

import copy
import threading
from typing import Any

import pytest
from django.db import connection
from rest_framework.test import APIClient

from apps.extraction.models import DefinitionVersion
from apps.extraction.tests.factories import DefinitionVersionFactory
from apps.identity.tests.factories import UserFactory
from apps.runs.tests.factories import RunFactory

pytestmark = pytest.mark.django_db


def url(run: Any) -> str:
    return f"/api/v1/runs/{run.pk}/stages/extract/definition"


@pytest.fixture
def run(user: Any) -> Any:
    return RunFactory(owner=user)


@pytest.fixture
def client(api_client: Any, user: Any) -> Any:
    api_client.force_authenticate(user)
    return api_client


def body(current: dict[str, Any], **changes: Any) -> dict[str, Any]:
    draft = {k: copy.deepcopy(v) for k, v in current.items() if k != "version"}
    return {"base_version": current["version"], **draft, **changes}


def test_first_read_is_version_one_with_the_default(client: Any, run: Any) -> None:
    response = client.get(url(run))
    assert response.status_code == 200
    data = response.json()
    assert data["version"] == 1
    [adr] = data["record_types"]
    assert adr["name"] == "ADR"
    assert [f["key"] for f in adr["fields"]] == [
        "title",
        "status",
        "decided_on",
        "approved_by",
        "context",
        "decision",
    ]
    assert data["output"]["format"] == "markdown"
    for field in adr["fields"]:
        assert isinstance(field["multiple"], bool)
        assert isinstance(field["choices"], list)
    assert client.get(url(run)).json() == data
    assert DefinitionVersion.objects.filter(run=run).count() == 1


def test_put_saves_a_new_version_and_keeps_the_old(client: Any, run: Any) -> None:
    current = client.get(url(run)).json()
    response = client.put(url(run), body(current, prompt="Changed."), format="json")
    assert response.status_code == 200
    assert response.json()["version"] == 2
    assert response.json()["prompt"] == "Changed."
    assert client.get(url(run)).json() == response.json()
    assert list(
        DefinitionVersion.objects.filter(run=run)
        .order_by("version")
        .values_list("version", flat=True)
    ) == [1, 2]
    stale = client.put(url(run), body(current), format="json")
    assert stale.status_code == 409
    assert stale.json()["code"] == "definition_conflict"
    assert stale.json()["details"] == {"version": 2}


def test_ids_are_kept_and_missing_ones_made(client: Any, run: Any) -> None:
    current = client.get(url(run)).json()
    new_type = {
        "name": "Risk",
        "fields": [{"key": "k", "name": "K", "mode": "quote", "value_type": "text"}],
    }
    current["record_types"].append(new_type)
    saved = client.put(url(run), body(current), format="json").json()
    assert saved["record_types"][0]["id"] == "rt-adr"
    risk = saved["record_types"][1]
    assert risk["id"]
    assert risk["fields"][0]["id"]
    assert risk["fields"][0]["choices"] == []
    assert risk["fields"][0]["multiple"] is False


def put_changed(client: Any, run: Any, change: Any) -> Any:
    current = client.get(url(run)).json()
    payload = body(current)
    change(payload)
    return client.put(url(run), payload, format="json")


@pytest.mark.parametrize(
    "change",
    [
        lambda p: p["record_types"][0]["fields"][0].update(key=""),
        lambda p: p["record_types"][0]["fields"][0].update(key="  "),
        lambda p: p["record_types"][0]["fields"][1].update(key="title"),
        lambda p: p["record_types"][0]["fields"][0].update(mode="guessed"),
        lambda p: p["record_types"][0]["fields"][0].update(value_type="boolean"),
        lambda p: p["output"].update(format="xml"),
        lambda p: p.pop("prompt"),
        lambda p: p.pop("output"),
        lambda p: p.update(prompt="a\x00b"),
        lambda p: p["record_types"][0]["fields"][0].update(key="a\x00b"),
        lambda p: p["record_types"][0]["fields"][0].update(name="a\x00b"),
    ],
)
def test_invalid_definitions_are_422(client: Any, run: Any, change: Any) -> None:
    response = put_changed(client, run, change)
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_definition"
    assert client.get(url(run)).json()["version"] == 1


def test_the_same_key_in_two_record_types_is_fine(client: Any, run: Any) -> None:
    def change(p: dict[str, Any]) -> None:
        other = copy.deepcopy(p["record_types"][0])
        other["id"] = "rt-other"
        p["record_types"].append(other)

    assert put_changed(client, run, change).status_code == 200


def test_a_missing_base_version_is_422(client: Any, run: Any) -> None:
    current = client.get(url(run)).json()
    payload = body(current)
    del payload["base_version"]
    response = client.put(url(run), payload, format="json")
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_someone_elses_run_is_404(client: Any) -> None:
    other = RunFactory(owner=UserFactory())
    DefinitionVersionFactory(run=other)
    for response in (
        client.get(url(other)),
        client.put(url(other), {"base_version": 1}, format="json"),
    ):
        assert response.status_code == 404
        assert response.json()["code"] == "run_not_found"


def test_without_a_token_is_401(run: Any) -> None:
    response = APIClient().get(url(run))
    assert response.status_code == 401


@pytest.mark.django_db(transaction=True)
def test_two_saves_at_once_one_wins(user: Any) -> None:
    run = RunFactory(owner=user)
    first = APIClient()
    first.force_authenticate(user)
    current = first.get(url(run)).json()
    barrier = threading.Barrier(2)
    statuses: list[int] = []

    def save(prompt: str) -> None:
        try:
            client = APIClient()
            client.force_authenticate(user)
            barrier.wait()
            statuses.append(
                client.put(
                    url(run), body(current, prompt=prompt), format="json"
                ).status_code
            )
        finally:
            connection.close()

    threads = [threading.Thread(target=save, args=(f"p{i}",)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(statuses) == [200, 409]
    assert DefinitionVersion.objects.filter(run=run).count() == 2
