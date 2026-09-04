"""Event platform for Phyn alerts."""
from __future__ import annotations

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Phyn event entities from a config entry."""
    coordinator = config_entry.runtime_data.coordinator
    entities = []
    for device in coordinator.devices:
        entities.extend([
            entity
            for entity in device.entities
            if isinstance(entity, EventEntity)
        ])
    async_add_entities(entities)
