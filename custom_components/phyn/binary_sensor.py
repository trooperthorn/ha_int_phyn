"""Binary sensor platform for the Phyn integration."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Phyn binary sensors from config entry."""
    coordinator = config_entry.runtime_data.coordinator
    entities = []
    for device in coordinator.devices:
        entities.extend([
            entity
            for entity in device.entities
            if isinstance(entity, BinarySensorEntity)
        ])
    async_add_entities(entities)