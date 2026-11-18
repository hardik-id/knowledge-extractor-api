import io
import json
import logging
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from django.test import Client, override_settings

from apps.core.logging import make_formatter
from apps.core.middleware import clean_request_id

pytestmark = pytest.mark.django_db

URLS = override_settings(ROOT_URLCONF="apps.core.tests.urls")


@pytest.fixture
def client() -> Client:
    return Client(raise_request_exception=False)


class Lines(list[dict[str, Any]]):
    def __init__(self, stream: io.StringIO) -> None:
        super().__init__()
        self.stream = stream

    def load(self) -> Lines:
        self[:] = [
            json.loads(line) for line in self.stream.getvalue().splitlines() if line
        ]
        return self


@pytest.fixture
def log_lines() -> Iterator[Lines]:
    """JSON lines the root logger writes, as the production format renders them."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(make_formatter("json"))
    root = logging.getLogger()
    old_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    try:
        yield Lines(stream)
    finally:
        root.removeHandler(handler)
        root.setLevel(old_level)


def test_the_callers_id_is_returned(client: Client) -> None:
    response = client.get("/nothing", headers={"X-Request-ID": "abc-123"})
    assert response["X-Request-ID"] == "abc-123"


def test_a_new_id_is_made_without_the_header(client: Client) -> None:
    value = client.get("/nothing")["X-Request-ID"]
    assert uuid.UUID(value)
    assert client.get("/nothing")["X-Request-ID"] != value


@pytest.mark.parametrize("bad", ["x" * 129, "has space", "semi;colon", "aé", ""])
def test_an_odd_id_is_replaced(client: Client, bad: str) -> None:
    value = client.get("/nothing", headers={"X-Request-ID": bad})["X-Request-ID"]
    assert value != bad
    assert clean_request_id(value) == value


@URLS
def test_404_and_500_keep_the_header(client: Client) -> None:
    assert (
        client.get("/nothing", headers={"X-Request-ID": "r-404"})["X-Request-ID"]
        == "r-404"
    )
    response = client.get("/boom", headers={"X-Request-ID": "r-500"})
    assert response.status_code == 500
    assert response["X-Request-ID"] == "r-500"


@URLS
def test_one_json_line_per_request_and_a_view_line_has_the_same_id(
    client: Client, log_lines: Lines
) -> None:
    client.get("/hello", headers={"X-Request-ID": "r-1"})
    log_lines.load()
    request_lines = [line for line in log_lines if line["event"].startswith("request_")]
    assert len(request_lines) == 1
    line = request_lines[0]
    assert line["request_id"] == "r-1"
    assert line["method"] == "GET"
    assert line["path"] == "/hello"
    assert line["status"] == 200
    assert line["duration_ms"] >= 0
    view_line = next(line for line in log_lines if line["event"] == "inside_view")
    assert view_line["request_id"] == "r-1"


@URLS
def test_a_failed_request_is_one_line_with_the_id(
    client: Client, log_lines: Lines
) -> None:
    client.get("/boom", headers={"X-Request-ID": "r-2"})
    log_lines.load()
    failed = [line for line in log_lines if line["event"] == "request_failed"]
    assert len(failed) == 1
    assert failed[0]["request_id"] == "r-2"
    assert failed[0]["status"] == 500


@URLS
def test_no_token_and_no_query_string_is_logged(
    client: Client, log_lines: Lines
) -> None:
    client.get(
        "/hello?ticket=SECRET-TICKET",
        headers={"Authorization": "Bearer SECRET-TOKEN"},
    )
    client.get(
        "/boom?ticket=SECRET-TICKET",
        headers={"Authorization": "Bearer SECRET-TOKEN"},
    )
    client.get("/nothing?ticket=SECRET-TICKET")
    text = json.dumps(log_lines.load())
    assert "request_finished" in text
    for secret in ("SECRET-TOKEN", "SECRET-TICKET", "Bearer", "ticket="):
        assert secret not in text


@pytest.mark.parametrize("name", ["django.server", "uvicorn.access"])
def test_access_loggers_that_print_the_query_string_are_silenced(name: str) -> None:
    from apps.core.logging import build_logging_config

    config = build_logging_config("INFO", "json")["loggers"][name]
    assert config["handlers"] == ["null"]
    assert config["propagate"] is False


def test_the_servers_are_started_without_the_uvicorn_access_log() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    for name in ("Dockerfile", "compose.yaml"):
        assert "--no-access-log" in (root / name).read_text()
