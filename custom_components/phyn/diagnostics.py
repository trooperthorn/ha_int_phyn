"""Diagnostics support for the Phyn integration."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .const import CLIENT, DOMAIN

# Keys removed from state/preference dumps. Device IDs are kept (shortened)
# because they are required to correlate diagnostics with debug logs.
TO_REDACT = {
    CONF_PASSWORD,
    CONF_USERNAME,
    "address",
    "alert_recipients",
    "city",
    "device_id",
    "country",
    "email",
    "latitude",
    "longitude",
    "phone",
    "postal_code",
    "serial_number",
    "ssid",
    "state",
    "street",
    "user_id",
    "wifi_ssid",
    "zip_code",
}


def _short_id(device_id: str) -> str:
    """Shorten a device id (MAC-derived) to its last four characters."""
    return f"…{device_id[-4:]}" if len(device_id) > 4 else device_id


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    data = hass.data.get(DOMAIN, {})
    client = data.get(CLIENT)
    coordinator = data.get("coordinator")

    diagnostics: dict[str, Any] = {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": async_redact_data(dict(entry.options), {"local_hosts"}),
            "version": entry.version,
            "minor_version": entry.minor_version,
        },
    }

    if client is not None:
        mqtt = client.mqtt
        diagnostics["mqtt"] = {
            "connected": mqtt.is_connected(),
            "subscribed_topics": len(getattr(mqtt, "topics", [])),
            "pending_acks": len(getattr(mqtt, "pending_acks", {})),
        }

    if coordinator is not None:
        diagnostics["coordinator"] = {
            "last_update_success": coordinator.last_update_success,
            "update_interval": str(coordinator.update_interval),
        }
        diagnostics["devices"] = [
            {
                "device_id": _short_id(device.id),
                "product_code": device.product_code,
                "model": device.model,
                "firmware_version": device.firmware_version,
                "available": device.available,
                "rssi": device.rssi,
                "local_configured": getattr(device, "local_host", None) is not None,
                "local_active": getattr(device, "local_active", False),
                "last_push_time": str(getattr(device, "last_push_time", None)),
                "state": async_redact_data(device._device_state, TO_REDACT),
                "preferences": async_redact_data(
                    device._device_preferences, TO_REDACT
                ),
                "firmware_info": async_redact_data(device._firmware_info, TO_REDACT),
                "active_alerts": device._active_alerts,
                "latest_alert_count": len(device._latest_device_alerts),
            }
            for device in coordinator.devices
        ]

    return diagnostics
