"""Realtime push subscription bookkeeping on top of aiophyn's MQTT client.

aiophyn records a topic in ``mqtt.topics`` only after the broker acknowledges
it, and re-subscribes only those topics on reconnect. A subscribe sent before
the CONNACK is dropped by paho and never acknowledged, so the topic is lost
for the life of the client. These helpers keep the wanted topics registered
and resend any that stay unacknowledged.
"""

from __future__ import annotations

from typing import Any


async def async_subscribe(mqtt: Any, topic: str) -> None:
    """Register *topic* for every reconnect and subscribe now if connected."""
    if topic not in mqtt.topics:
        mqtt.topics.append(topic)
    if mqtt.is_connected():
        await mqtt.subscribe(topic)


def unacked_topics(mqtt: Any, wanted: set[str]) -> set[str]:
    """Return wanted topics that only appear as pending acknowledgements."""
    return {topic for topic in mqtt.pending_acks.values() if topic in wanted}


async def async_resubscribe(mqtt: Any, topics: set[str]) -> None:
    """Drop stale pending entries for *topics* and subscribe again."""
    for mid in [mid for mid, topic in mqtt.pending_acks.items() if topic in topics]:
        del mqtt.pending_acks[mid]
    for topic in topics:
        await mqtt.subscribe(topic)
