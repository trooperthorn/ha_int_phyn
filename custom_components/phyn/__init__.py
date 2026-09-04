"""The phyn integration."""
import asyncio
import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from aiophyn import async_get_api
from aiophyn.errors import AuthenticationError, RequestError
from botocore.exceptions import ClientError

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.typing import ConfigType
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv

from .const import (
    DOMAIN,
    CONF_HOME_ID,
    CONF_DEVICE_IDS,
    CONF_LOCAL_HOSTS,
    CONF_LOCAL_POLL_INTERVAL,
    CONF_UPDATE_INTERVAL,
    DEFAULT_LOCAL_POLL_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
)
from .update_coordinator import PhynDataUpdateCoordinator
from .exceptions import HaAuthError, HaCannotConnect
from .services import async_setup_services


@dataclass
class PhynRuntimeData:
    """Objects one loaded entry owns."""

    client: Any
    coordinator: PhynDataUpdateCoordinator


type PhynConfigEntry = ConfigEntry[PhynRuntimeData]

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS = [Platform.BINARY_SENSOR, Platform.EVENT, Platform.SENSOR, Platform.SWITCH, Platform.UPDATE, Platform.VALVE]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Phyn domain: register services once, independent of entries."""
    await async_setup_services(hass)
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Apply option changes.

    Excluded alert types are read live on every update cycle and the polling
    interval is pushed into the running coordinator directly; a change to the
    local (LAN) host mapping needs a reload so per-device local pollers and
    entities are rebuilt.
    """
    runtime = getattr(entry, "runtime_data", None)
    if runtime is None:
        return
    coordinator: PhynDataUpdateCoordinator = runtime.coordinator

    new_hosts: dict = entry.options.get(CONF_LOCAL_HOSTS, {})
    new_local_interval = int(
        entry.options.get(CONF_LOCAL_POLL_INTERVAL, DEFAULT_LOCAL_POLL_INTERVAL)
    )
    for device in coordinator.devices:
        if not hasattr(device, "local_host") or not hasattr(
            device, "local_poll_interval"
        ):
            continue
        if (new_hosts.get(device.id) or None) != device.local_host or (
            device.local_host and new_local_interval != device.local_poll_interval
        ):
            _LOGGER.info(
                "Local access configuration changed for %s; reloading Phyn", device.id
            )
            hass.config_entries.async_schedule_reload(entry.entry_id)
            return

    new_interval = timedelta(
        seconds=entry.options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
    )
    if coordinator.update_interval != new_interval:
        coordinator.update_interval = new_interval
        _LOGGER.debug("Phyn polling interval changed to %s", new_interval)
        await coordinator.async_request_refresh()


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate old entry to the current schema version."""
    _LOGGER.debug("Migrating from version %s.%s", config_entry.version, config_entry.minor_version)

    if config_entry.version > 1:
        # Downgraded from a future version.
        return False

    if config_entry.version == 1:
        new_data = {**config_entry.data}

        if config_entry.minor_version < 3:
            # Remove the now-obsolete Brand field.
            new_data.pop("Brand", None)

        if config_entry.minor_version < 4:
            # Migrate to account-scoped entry (one entry per account, no CONF_HOME_ID).
            username = new_data.get(CONF_USERNAME, "")
            all_entries = [
                e for e in hass.config_entries.async_entries(DOMAIN)
                if e.data.get(CONF_USERNAME) == username
            ]
            primary = min(all_entries, key=lambda e: e.entry_id) if all_entries else config_entry
            is_primary = primary.entry_id == config_entry.entry_id

            if is_primary:
                all_device_ids: list[str] = []
                seen: set[str] = set()
                for sibling in all_entries:
                    for did in sibling.data.get(CONF_DEVICE_IDS, []):
                        if did not in seen:
                            seen.add(did)
                            all_device_ids.append(did)

                new_data.pop(CONF_HOME_ID, None)
                new_data[CONF_DEVICE_IDS] = all_device_ids

                hass.config_entries.async_update_entry(
                    config_entry,
                    title=username,
                    data=new_data,
                    unique_id=username,
                    version=1,
                    minor_version=4,
                )
            else:
                new_data.pop(CONF_HOME_ID, None)
                hass.config_entries.async_update_entry(
                    config_entry,
                    data=new_data,
                    version=1,
                    minor_version=4,
                )

            _LOGGER.debug(
                "Migration to version 1.4 complete for entry %s (is_primary=%s)",
                config_entry.entry_id,
                is_primary,
            )
            return True

        hass.config_entries.async_update_entry(
            config_entry, data=new_data, version=1, minor_version=4
        )

    _LOGGER.debug("Migration to version %s.%s successful", config_entry.version, config_entry.minor_version)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: PhynConfigEntry) -> bool:
    """Set up Phyn from a config entry."""

    username = entry.data.get(CONF_USERNAME, "")
    same_account = [
        e for e in hass.config_entries.async_entries(DOMAIN)
        if e.data.get(CONF_USERNAME) == username
    ]
    primary = min(same_account, key=lambda e: e.entry_id) if same_account else entry
    if entry.entry_id != primary.entry_id:
        _LOGGER.debug(
            "Removing redundant Phyn entry %s; primary is %s",
            entry.entry_id, primary.entry_id,
        )
        hass.async_create_task(hass.config_entries.async_remove(entry.entry_id))
        return True

    session = async_get_clientsession(hass)
    client_id = f"homeassistant-{hass.data['core.uuid']}-{entry.entry_id}"
    try:
        client = await async_get_api(
            entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD],
            phyn_brand="phyn", session=session,
            client_id=client_id
        )
    except AuthenticationError as error:
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN,
            translation_key="auth_failed",
        ) from error
    except RequestError as error:
        raise ConfigEntryNotReady from error
    except ClientError as error:
        if error.response['Error']['Code'] == "NotAuthorizedException":
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key="auth_failed"
            )
        else:
            raise error

    homes = await client.home.get_homes(entry.data[CONF_USERNAME])

    _LOGGER.debug("Phyn homes: %s", homes)

    device_ids: list[str] = entry.data.get(CONF_DEVICE_IDS, [])

    if not device_ids:
        # Primary entry has no selected devices.
        _LOGGER.debug("Entry %s has no devices; skipping setup", entry.entry_id)
        return True

    all_account_devices: dict[str, dict] = {}
    for home in homes:
        for device in home.get("devices", []):
            all_account_devices[device["device_id"]] = {
                "home_id": home["id"],
                "home_name": home.get("name", home["id"]),
                "product_code": device["product_code"],
            }

    selected_home_ids = {
        all_account_devices[d]["home_id"]
        for d in device_ids
        if d in all_account_devices
    }
    multi_home = len(selected_home_ids) > 1

    device_registry = dr.async_get(hass)
    for dev_entry in dr.async_entries_for_config_entry(device_registry, entry.entry_id):
        phyn_ids = {identifier[1] for identifier in dev_entry.identifiers if identifier[0] == DOMAIN}
        if phyn_ids and not phyn_ids.intersection(device_ids):
            device_registry.async_remove_device(dev_entry.id)
            _LOGGER.debug("Removed stale device %s", phyn_ids)

    try:
        await client.mqtt.connect()

        coordinator = PhynDataUpdateCoordinator(hass, client, entry)
        for device_id in device_ids:
            if device_id in all_account_devices:
                info = all_account_devices[device_id]
                home_name = info["home_name"] if multi_home else ""
                coordinator.add_device(info["home_id"], device_id, info["product_code"], home_name)
            else:
                _LOGGER.warning(
                    "Selected device %s not found in account; skipping", device_id
                )
        entry.runtime_data = PhynRuntimeData(client=client, coordinator=coordinator)

        await coordinator.async_refresh()
        await coordinator.async_setup()

        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

        entry.async_on_unload(entry.add_update_listener(_async_options_updated))

        return True
    except Exception:
        # Ensure MQTT is disconnected on any setup failure to avoid leaking
        # open connections across repeated failed setups.
        try:
            await asyncio.wait_for(client.mqtt.disconnect_and_wait(), timeout=15)
        except Exception as err:
            _LOGGER.debug("Error disconnecting MQTT after setup failure: %s", err)
        raise


async def async_unload_entry(hass: HomeAssistant, entry: PhynConfigEntry) -> bool:
    """Unload a config entry."""
    runtime = getattr(entry, "runtime_data", None)
    if runtime is None:
        return True
    client = runtime.client
    try:
        await asyncio.wait_for(client.mqtt.disconnect_and_wait(), timeout=15)
    except TimeoutError:
        _LOGGER.warning(
            "Timed out waiting for MQTT disconnect during unload; proceeding anyway"
        )
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
