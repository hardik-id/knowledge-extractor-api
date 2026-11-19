"""Metrics of the run sockets (docs/observability.md).

Counts only: no run id, no user and no event content ever becomes an attribute.
"""

from dataclasses import dataclass
from functools import lru_cache

from opentelemetry import metrics

from apps.core import telemetry

SCOPE = "apps.realtime"


@dataclass(frozen=True)
class _Instruments:
    connections: metrics.UpDownCounter
    events: metrics.Counter


@lru_cache
def _instruments(provider: metrics.MeterProvider) -> _Instruments:
    meter = provider.get_meter(SCOPE)
    return _Instruments(
        connections=meter.create_up_down_counter(
            "realtime.connections",
            unit="{connection}",
            description="Run sockets that are open now.",
        ),
        events=meter.create_counter(
            "realtime.events.published",
            unit="{event}",
            description="Events handed to the channel layer, by event type.",
        ),
    )


def connection_opened() -> None:
    _instruments(telemetry.meter_provider()).connections.add(1)


def connection_closed() -> None:
    _instruments(telemetry.meter_provider()).connections.add(-1)


def event_published(event_type: str) -> None:
    _instruments(telemetry.meter_provider()).events.add(1, {"type": event_type})
