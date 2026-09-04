"""Services for the phyn integration"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import (
    config_validation as cv,
)
from homeassistant.helpers import (
    device_registry as dr,
)
from homeassistant.helpers import (
    entity_registry as er,
)
from homeassistant.helpers.target import (
    TargetSelection,
    async_extract_referenced_entity_ids,
)
from homeassistant.util.json import JsonValueType

from .const import DOMAIN, LOGGER

if TYPE_CHECKING:
    from .devices.pp import PhynPlusDevice
    from .update_coordinator import PhynDataUpdateCoordinator

SERVICE_LEAK_TEST = "leak_test"
SERVICE_PAUSE_AUTOSHUTOFF = "pause_autoshutoff"
SERVICE_MARK_ALERT_READ = "mark_alert_read"

#: Durations accepted by the Phyn auto-shutoff pause endpoint, in seconds.
#: ``None`` disables auto shutoff until it is re-enabled manually.
AUTOSHUTOFF_DURATIONS: dict[str, int | None] = {
    "30s": 30,
    "1h": 3600,
    "6h": 21600,
    "24h": 86400,
    "indefinite": None,
}

LEAK_TEST_SCHEMA = vol.Schema(
    {
        **cv.TARGET_SERVICE_FIELDS,
        vol.Optional("extended", default=False): cv.boolean,
    }
)

PAUSE_AUTOSHUTOFF_SCHEMA = vol.Schema(
    {
        **cv.TARGET_SERVICE_FIELDS,
        vol.Optional("duration", default="indefinite"): vol.In(AUTOSHUTOFF_DURATIONS),
    }
)

MARK_ALERT_READ_SCHEMA = vol.Schema(
    {
        vol.Required("alert_id"): cv.string,
    }
)


def _get_client_and_coordinator(
    hass: HomeAssistant,
) -> tuple[Any, PhynDataUpdateCoordinator]:
    """Return the API client and coordinator, or raise if not loaded."""
    client = coordinator = None
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        runtime = getattr(entry, "runtime_data", None)
        if runtime is not None:
            client, coordinator = runtime.client, runtime.coordinator
            break
    if client is None or coordinator is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="not_loaded",
        )
    return client, coordinator


def _extract_phyn_plus_devices(call: ServiceCall) -> list[PhynPlusDevice]:
    """Resolve the service call target to Phyn Plus devices.

    Accepts any combination of entity, device, area, floor, or label targets
    and maps them back to the coordinator's Phyn Plus device objects.
    """
    hass = call.hass
    _, coordinator = _get_client_and_coordinator(hass)

    selected = async_extract_referenced_entity_ids(hass, TargetSelection(call.data))
    entity_ids = selected.referenced | selected.indirectly_referenced
    if not entity_ids:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="no_target",
        )

    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)

    ha_device_ids: set[str] = set()
    for entity_id in entity_ids:
        entry = entity_registry.async_get(entity_id)
        if entry is not None and entry.platform == DOMAIN and entry.device_id:
            ha_device_ids.add(entry.device_id)

    phyn_ids: set[str] = set()
    for ha_device_id in ha_device_ids:
        device_entry = device_registry.async_get(ha_device_id)
        if device_entry is None:
            continue
        for identifier_domain, identifier in device_entry.identifiers:
            if identifier_domain == DOMAIN:
                phyn_ids.add(identifier)

    devices = [
        device
        for device in coordinator.devices
        if device.id in phyn_ids and device.product_code in ("PP1", "PP2")
    ]
    if not devices:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="no_phyn_plus_target",
        )
    return devices  # type: ignore[return-value]


async def _async_leak_test(call: ServiceCall) -> ServiceResponse:
    """Run an on-demand leak (health) test on the targeted Phyn Plus devices."""
    client, _ = _get_client_and_coordinator(call.hass)
    devices = _extract_phyn_plus_devices(call)
    extended = bool(call.data.get("extended", False))

    results: list[JsonValueType] = []
    for device in devices:
        LOGGER.debug(
            "Running %s leak test for device %s",
            "extended" if extended else "standard",
            device.id,
        )
        result = await client.device.run_leak_test(device.id, extended)
        if not isinstance(result, dict) or result.get("code") != "success":
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="leak_test_failed",
                translation_placeholders={"device": device.device_name},
            )
        results.append({"device_id": device.id, "status": "started"})

    if call.return_response:
        return {"results": results}
    return None


async def _async_pause_autoshutoff(call: ServiceCall) -> None:
    """Temporarily disable auto shutoff on the targeted Phyn Plus devices."""
    client, _ = _get_client_and_coordinator(call.hass)
    devices = _extract_phyn_plus_devices(call)
    seconds = AUTOSHUTOFF_DURATIONS[call.data.get("duration", "indefinite")]

    for device in devices:
        LOGGER.debug(
            "Pausing auto shutoff for device %s (duration: %s)",
            device.id,
            "indefinite" if seconds is None else f"{seconds}s",
        )
        await client.device.set_autoshutoff_enabled(device.id, False, seconds)


async def _async_mark_alert_read(call: ServiceCall) -> None:
    """Mark a Phyn alert as read (e.g. after an automation has handled it)."""
    client, _ = _get_client_and_coordinator(call.hass)
    alert_id = call.data["alert_id"]
    LOGGER.debug("Marking alert %s as read", alert_id)
    await client.alert.mark_read(alert_id)


async def async_setup_services(hass: HomeAssistant) -> None:
    """Register the integration's services (idempotent)."""
    if hass.services.has_service(DOMAIN, SERVICE_LEAK_TEST):
        return

    hass.services.async_register(
        DOMAIN,
        SERVICE_LEAK_TEST,
        _async_leak_test,
        schema=LEAK_TEST_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_PAUSE_AUTOSHUTOFF,
        _async_pause_autoshutoff,
        schema=PAUSE_AUTOSHUTOFF_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_MARK_ALERT_READ,
        _async_mark_alert_read,
        schema=MARK_ALERT_READ_SCHEMA,
    )


async def phyn_leak_test_service_setup(hass: HomeAssistant) -> None:
    """Backwards-compatible alias for the old setup entry point."""
    await async_setup_services(hass)
