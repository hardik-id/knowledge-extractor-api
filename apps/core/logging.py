"""Structured logging: the structlog setup and the formatter the LOGGING setting uses.

Settings call `configure_structlog()` and name `make_formatter` in LOGGING; app
code only does `structlog.get_logger(__name__)`. See docs/logging.md.
"""

import logging
import re
from typing import Any

import structlog
from opentelemetry import trace
from structlog.typing import EventDict, Processor, WrappedLogger


def drop_request_started(
    logger: WrappedLogger, method_name: str, event_dict: EventDict
) -> EventDict:
    """One line per request: keep request_finished and request_failed only."""
    if event_dict.get("event") == "request_started":
        raise structlog.DropEvent
    return event_dict


_TICKET = re.compile(r"(ticket=)[^&\s\"']*")


class RedactTicket(logging.Filter):
    """Blanks the value of ``ticket=``: a WebSocket ticket is a secret in a URL.

    uvicorn logs the socket's path with its query string; this keeps the ticket
    out of that line and out of any other that quotes the URL.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if "ticket=" in message:
            record.msg = _TICKET.sub(r"\1[redacted]", message)
            record.args = None
        return True


def add_trace_context(
    logger: WrappedLogger, method_name: str, event_dict: EventDict
) -> EventDict:
    """trace_id, span_id and trace_flags (lower-case hex) of the span the line is written in.

    trace_flags is "01" for a sampled trace, "00" otherwise."""
    span_context = trace.get_current_span().get_span_context()
    if span_context.is_valid:
        event_dict["trace_id"] = f"{span_context.trace_id:032x}"
        event_dict["span_id"] = f"{span_context.span_id:016x}"
        event_dict["trace_flags"] = f"{int(span_context.trace_flags) & 1:02x}"
    return event_dict


def _shared_processors() -> list[Processor]:
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        add_trace_context,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]


def configure_structlog() -> None:
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            *_shared_processors(),
            structlog.processors.StackInfoRenderer(),
            drop_request_started,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


def make_formatter(log_format: str = "console", **kwargs: Any) -> Any:
    """Formatter for both structlog events and plain stdlib records."""
    renderer: Processor
    if log_format == "json":
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=False)
    return structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.format_exc_info,
            renderer,
        ],
        foreign_pre_chain=_shared_processors(),
    )


def build_logging_config(log_level: str, log_format: str) -> dict[str, Any]:
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "structlog": {
                "()": "apps.core.logging.make_formatter",
                "log_format": log_format,
            },
        },
        "filters": {"redact_ticket": {"()": "apps.core.logging.RedactTicket"}},
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "structlog",
                "filters": ["redact_ticket"],
            },
            "null": {"class": "logging.NullHandler"},
        },
        "root": {"handlers": ["console"], "level": log_level},
        "loggers": {
            # runserver logs the full path with the query string; our request
            # line replaces it.
            "django.server": {"handlers": ["null"], "propagate": False},
            # uvicorn's access log is `GET /path?query`; same reason. The server
            # is also started with --no-access-log; this covers other launchers.
            "uvicorn.access": {"handlers": ["null"], "propagate": False},
            # uvicorn logs `WebSocket /path?ticket=...` here, to its own handler
            # (the one on the parent logger), so the handler filter above does
            # not see it: filter the logger itself.
            "uvicorn.error": {"filters": ["redact_ticket"]},
        },
    }
