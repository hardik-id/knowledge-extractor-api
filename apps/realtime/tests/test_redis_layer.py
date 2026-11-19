"""The Redis channel layer of the real settings: an idle socket stays open."""

import asyncio
from typing import Any

import pytest
import redis
from channels_redis.core import RedisChannelLayer
from django.conf import settings
from django.test import override_settings

from apps.realtime.tests.test_run_socket import a_cell, open_socket, set_running
from config.settings import base

REDIS_LAYERS: dict[str, Any] = base.CHANNEL_LAYERS


def redis_is_up() -> bool:
    try:
        client = redis.Redis.from_url(settings.REDIS_URL, socket_connect_timeout=0.5)
        return bool(client.ping())
    except redis.RedisError:
        return False


def test_a_read_outlasts_the_wait_of_an_idle_receive() -> None:
    layer = RedisChannelLayer(**REDIS_LAYERS["default"]["CONFIG"])
    pool = layer.create_pool(0)
    assert pool.connection_kwargs["socket_timeout"] > layer.brpop_timeout
    assert pool.connection_kwargs["socket_connect_timeout"] <= 5


@pytest.mark.skipif(not redis_is_up(), reason="needs the compose Redis")
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_an_idle_socket_on_real_redis_stays_open_and_gets_the_event() -> None:
    with override_settings(CHANNEL_LAYERS=REDIS_LAYERS):
        cell = await a_cell()
        socket = await open_socket(cell.file.run.owner, cell.file.run_id)

        # Longer than one wait on Redis, so the socket has been idle through it.
        await asyncio.sleep(RedisChannelLayer.brpop_timeout + 1.5)
        await set_running(cell, progress=42)

        event = await socket.receive_json_from(timeout=5)
        assert event["type"] == "cell"
        assert event["cell"]["progress"] == 42
        await socket.disconnect()
