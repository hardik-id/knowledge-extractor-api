"""Structured logging: the structlog setup and the formatter the LOGGING setting uses.

Settings call `configure_structlog()` and name `make_formatter` in LOGGING; app
code only does `structlog.get_logger(__name__)`. See docs/logging.md.
"""

from typing import Any

import structlog
from structlog.typing import EventDict, Processor, WrappedLogger


def drop_request_started(
    logger: WrappedLogger, method_name: str, event_dict: EventDict
) -> EventDict:
    """One line per request: keep request_finished and request_failed only."""
    if event_dict.get("event") == "request_started":
        raise structlog.DropEvent
    return event_dict


def _shared_processors() -> list[Processor]:
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
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
        "handlers": {
            "console": {"class": "logging.StreamHandler", "formatter": "structlog"},
            "null": {"class": "logging.NullHandler"},
        },
        "root": {"handlers": ["console"], "level": log_level},
        "loggers": {
            # runserver logs the full path with the query string; our request
            # line replaces it.
            "django.server": {"handlers": ["null"], "propagate": False},
        },
    }
