"""A WebSocket ticket never reaches a log line, whichever logger writes the URL."""

import io
import logging
from collections.abc import Iterator

import pytest
from django.conf import settings

from apps.core.logging import make_formatter


@pytest.fixture
def uvicorn_output() -> Iterator[io.StringIO]:
    """What uvicorn's error logger writes after Django's LOGGING is applied."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger = logging.getLogger("uvicorn.error")
    old_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        yield stream
    finally:
        logger.removeHandler(handler)
        logger.setLevel(old_level)


def test_uvicorns_websocket_line_is_redacted(uvicorn_output: io.StringIO) -> None:
    # uvicorn's own format: '%s - "WebSocket %s" [accepted]'
    logging.getLogger("uvicorn.error").info(
        '%s - "WebSocket %s" [accepted]',
        "127.0.0.1:5000",
        "/ws/runs/1/?ticket=SECRET-123&x=1",
    )
    line = uvicorn_output.getvalue()
    assert "SECRET-123" not in line
    assert "/ws/runs/1/?ticket=[redacted]&x=1" in line


def test_the_console_handler_redacts_too() -> None:
    handler_config = settings.LOGGING["handlers"]["console"]
    assert "redact_ticket" in handler_config["filters"]
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(make_formatter("json"))
    from apps.core.logging import RedactTicket

    handler.addFilter(RedactTicket())
    record = logging.LogRecord(
        "x", logging.INFO, __file__, 1, "GET /ws?ticket=%s", ("SECRET-456",), None
    )
    handler.handle(record)
    assert "SECRET-456" not in stream.getvalue()


def test_other_lines_are_left_alone(uvicorn_output: io.StringIO) -> None:
    logging.getLogger("uvicorn.error").info("started %s", "fine")
    assert uvicorn_output.getvalue() == "started fine\n"
