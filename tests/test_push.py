"""Unit tests for realtime push subscription bookkeeping."""
import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from custom_components.phyn.push import (  # noqa: E402
    async_resubscribe,
    async_subscribe,
    unacked_topics,
)


def make_mqtt(connected: bool) -> MagicMock:
    mqtt = MagicMock()
    mqtt.topics = []
    mqtt.pending_acks = {}
    mqtt.is_connected.return_value = connected
    mqtt.subscribe = AsyncMock()
    return mqtt


def test_subscribe_before_connack_keeps_topic_for_reconnect():
    mqtt = make_mqtt(connected=False)
    asyncio.run(async_subscribe(mqtt, "t1"))
    assert mqtt.topics == ["t1"]
    mqtt.subscribe.assert_not_awaited()


def test_subscribe_when_connected_sends_once():
    mqtt = make_mqtt(connected=True)
    mqtt.topics = ["t1"]
    asyncio.run(async_subscribe(mqtt, "t1"))
    assert mqtt.topics == ["t1"]
    mqtt.subscribe.assert_awaited_once_with("t1")


def test_unacked_topics_only_reports_wanted():
    mqtt = make_mqtt(connected=True)
    mqtt.pending_acks = {1: "t1", 2: "other"}
    assert unacked_topics(mqtt, {"t1", "t2"}) == {"t1"}


def test_resubscribe_clears_stale_pending():
    mqtt = make_mqtt(connected=True)
    mqtt.pending_acks = {1: "t1", 2: "t1", 3: "other"}
    asyncio.run(async_resubscribe(mqtt, {"t1"}))
    assert mqtt.pending_acks == {3: "other"}
    mqtt.subscribe.assert_awaited_once_with("t1")
