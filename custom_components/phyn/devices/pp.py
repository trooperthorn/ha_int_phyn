"""Support for Phyn Plus Water Monitor sensors."""
from __future__ import annotations
from typing import TYPE_CHECKING, Any

from aiophyn.errors import RequestError
from asyncio import Lock, timeout

from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import UpdateFailed
import homeassistant.util.dt as dt_util

from ..const import (
    CONF_LOCAL_HOSTS,
    LOCAL_FAILURE_THRESHOLD,
    LOCAL_POLL_INTERVAL_SECONDS,
    LOGGER,
)
from ..jnap import JnapClient, JnapError
from ..entities.base import (
    PhynAlertEvent,
    PhynAlertSensor,
    PhynConnectivitySensor,
    PhynDailyUsageSensor,
    PhynFirmwareUpdateAvailableSensor,
    PhynFirwmwareUpdateEntity,
    PhynPressureSensor,
    PhynSignalStrengthSensor,
    PhynTemperatureSensor,
)
from ..entities.pp import (
    PhynAutoShutoffModeSwitch,
    PhynAwayModeSwitch,
    PhynConsumptionSensor,
    PhynCurrentFlowRateSensor,
    PhynFlowState,
    PhynLatestLeakTestSensor,
    PhynLeakTestLeakDetected,
    PhynLeakTestSensor,
    PhynLeakTestWarning,
    PhynLocalConnectivitySensor,
    PhynScheduledLeakTestEnabledSwitch,
    PhynValve,
)
from .base import PhynDevice

from datetime import datetime, timedelta, timezone
import math
import time

if TYPE_CHECKING:
    from ..update_coordinator import PhynDataUpdateCoordinator

NAME_WATER_TEMPERATURE = "Current water temperature"
NAME_WATER_PRESSURE = "Current water pressure"

class PhynPlusDevice(PhynDevice):
    """Phyn device object."""

    ALERT_EVENT_TYPES: list[str] = [
        "battery",
        "freeze_warn",
        "high_pressure",
        "leak",
        "offline_leak",
        "periodic_leak",
        "pinhole_leak",
        "temperature",
    ]

    def __init__(
        self,
        coordinator: PhynDataUpdateCoordinator,
        home_id: str,
        device_id: str,
        product_code: str,
        home_name: str = "",
    ) -> None:
        """Initialize the device."""
        super().__init__(coordinator, home_id, device_id, product_code, home_name)
        self._device_state: dict[str, Any] = {
            "flow_state": {
                "v": 0.0,
                "ts": 0,
            }
        }
        self._auto_shutoff: dict[str, Any] = {}
        self._away_mode: dict[str, Any] = {}
        self._water_usage: dict[str, Any] = {}
        self._last_known_valve_state: bool = True
        self._latest_health_test: dict[str, Any] | None = None
        self._rt_device_state: dict[str, Any] = {}
        self._state_lock: Lock = Lock()

        # Local (LAN) JNAP access — see LOCAL_ACCESS.md. Configured per device
        # via the integration options (or auto-configured by DHCP discovery).
        local_hosts: dict[str, str] = coordinator.config_entry.options.get(
            CONF_LOCAL_HOSTS, {}
        )
        self._local_host: str | None = local_hosts.get(device_id) or None
        self._local_client: JnapClient | None = (
            JnapClient(self._local_host) if self._local_host else None
        )
        self._local_active: bool = False
        self._local_failures: int = 0

        self.entities = [
            PhynAlertEvent(self),
            PhynAlertSensor(self, "alert_battery", "Battery Alert", "alert_battery"),
            PhynAlertSensor(self, "alert_freeze_warn", "Freeze Warning Alert", "alert_freeze_warn"),
            PhynAlertSensor(self, "alert_high_pressure", "High Pressure Alert", "alert_high_pressure"),
            PhynAlertSensor(self, "alert_leak", "Leak Alert", "alert_leak"),
            PhynAlertSensor(self, "alert_offline_leak", "Offline Leak Shutoff Alert", "alert_offline_leak"),
            PhynAlertSensor(self, "alert_periodic_leak", "Recurring Flow Alert", "alert_periodic_leak"),
            PhynAlertSensor(self, "alert_pinhole_leak", "Pinhole Leak Alert", "alert_pinhole_leak"),
            PhynAlertSensor(self, "alert_temperature", "Temperature Alert", "alert_temperature"),
            PhynAutoShutoffModeSwitch(self),
            PhynAwayModeSwitch(self),
            PhynConnectivitySensor(self),
            PhynFlowState(self),
            PhynDailyUsageSensor(self),
            PhynCurrentFlowRateSensor(self),
            PhynConsumptionSensor(self),
            PhynFirmwareUpdateAvailableSensor(self),
            PhynFirwmwareUpdateEntity(self),
            PhynLatestLeakTestSensor(self),
            PhynLeakTestLeakDetected(self),
            PhynLeakTestSensor(self),
            PhynLeakTestWarning(self),
            PhynScheduledLeakTestEnabledSwitch(self),
            PhynSignalStrengthSensor(self),
            PhynTemperatureSensor(self, "temperature", NAME_WATER_TEMPERATURE),
            PhynPressureSensor(self, "pressure", NAME_WATER_PRESSURE),
            PhynValve(self),
        ]
        if self._local_host:
            self.entities.append(PhynLocalConnectivitySensor(self))

    async def async_update_data(self):
        """Update data via library."""
        try:
            async with timeout(20):
                await self._update_device_state()
                await self._update_alerts()
                await self._update_alert_events()
                await self._update_autoshutoff()
                await self._update_device_preferences()
                await self._update_consumption_data()

                #Update every 10 minutes
                if self._update_count % 10 == 0:
                    await self._update_device_health_tests()

                #Update every hour
                if (self._update_count % 60 == 0):
                    await self._update_firmware_information()
                
                self._update_count += 1
        except (RequestError) as error:
            raise UpdateFailed(error) from error

    @property
    def consumption(self) -> float | None:
        """Return the current consumption for today in gallons."""
        if "consumption" not in self._rt_device_state:
            return None
        return self._device_state.get("consumption")

    @property
    def consumption_today(self) -> float | None:
        """Return the current consumption for today in gallons."""
        return self._water_usage.get("water_consumption")

    @property
    def current_flow_rate(self) -> float | None:
        """Return current flow rate in gpm."""
        flow = self._device_state.get("flow", {})
        if "v" not in flow:
            return None
        return round(flow["v"], 3)

    @property
    def current_psi(self) -> float:
        """Return the current pressure in psi."""
        pressure = self._device_state.get("pressure", {})
        if "v" in pressure:
            return round(pressure["v"], 2)
        return round(pressure.get("mean", 0), 2)

    @property
    def leak_test_running(self) -> bool:
        """Check if a leak test is running"""
        sov_status = self._device_state.get("sov_status", {})
        return sov_status.get("v") == "LeakExp"

    @property
    def last_leak_test_time(self) -> datetime | None:
        """Return when the most recent leak (health) test finished, as UTC.

        The API reports ``end_time`` as an epoch timestamp; the scale
        (seconds vs milliseconds) is normalized defensively.
        """
        if not self._latest_health_test:
            return None
        end_time = self._latest_health_test.get("end_time")
        if not isinstance(end_time, (int, float)) or end_time <= 0:
            return None
        if end_time > 1e12:  # milliseconds epoch
            end_time /= 1000
        return datetime.fromtimestamp(end_time, tz=timezone.utc)

    @property
    def temperature(self) -> float:
        """Return the current temperature in degrees F."""
        temp = self._device_state.get("temperature", {})
        if "v" in temp:
            return round(temp["v"], 2)
        return round(temp.get("mean", 0), 2)

    @property
    def scheduled_leak_test_enabled(self) -> bool | None:
        """Return if the scheduled leak test is enabled"""
        if "scheduler_enable" not in self._device_preferences:
            return None
        scheduler = self._device_preferences.get("scheduler_enable", {})
        return scheduler.get("value") == "true"


    @property
    def alert_battery(self) -> bool:
        return self.has_active_alert("battery")

    @property
    def alert_freeze_warn(self) -> bool:
        return self.has_active_alert("freeze_warn")

    @property
    def alert_high_pressure(self) -> bool:
        return self.has_active_alert("high_pressure")

    @property
    def alert_leak(self) -> bool:
        return self.has_active_alert("leak")

    @property
    def alert_offline_leak(self) -> bool:
        return self.has_active_alert("offline_leak")

    @property
    def alert_periodic_leak(self) -> bool:
        return self.has_active_alert("periodic_leak")

    @property
    def alert_pinhole_leak(self) -> bool:
        return self.has_active_alert("pinhole_leak")

    @property
    def alert_temperature(self) -> bool:
        return self.has_active_alert("temperature")

    @property
    def valve_open(self) -> bool:
        """Return the valve state for the device."""
        if self.valve_changing:
            return self._last_known_valve_state
        sov_status = self._device_state.get("sov_status", {})
        return sov_status.get("v") == "Open"

    @property
    def valve_changing(self) -> bool:
        """Return the valve changing status"""
        sov_status = self._device_state.get("sov_status", {})
        return sov_status.get("v") == "Partial"

    @property
    def available(self) -> bool:
        """Available when locally reachable, else when the cloud says online."""
        if self._local_active:
            return True
        return super().available

    @property
    def local_host(self) -> str | None:
        """Return the configured local (LAN) host, if any."""
        return self._local_host

    @property
    def local_active(self) -> bool:
        """Return True while local (LAN) polling is healthy."""
        return self._local_active

    async def async_setup(self) -> str | None:  # type: ignore[override]
        """Setup a new device coordinator"""
        LOGGER.debug("Setting up coordinator")

        await self._coordinator.api_client.mqtt.add_event_handler("update", self.on_device_update)
        await self._coordinator.api_client.mqtt.subscribe(f"prd/app_subscriptions/{self._phyn_device_id}")

        if self._local_client is not None:
            LOGGER.debug(
                "Starting local JNAP polling for %s at %s every %ss",
                self._phyn_device_id,
                self._local_host,
                LOCAL_POLL_INTERVAL_SECONDS,
            )
            self._coordinator.config_entry.async_on_unload(
                async_track_time_interval(
                    self._coordinator.hass,
                    self._async_local_poll,
                    timedelta(seconds=LOCAL_POLL_INTERVAL_SECONDS),
                )
            )
            # Prime immediately rather than waiting a full interval.
            self._coordinator.hass.async_create_task(self._async_local_poll())

        return self._device_state.get("sov_status", {}).get("v")

    async def async_open_valve(self) -> None:
        """Open the shutoff valve, preferring the local path."""
        await self._async_set_valve(True)

    async def async_close_valve(self) -> None:
        """Close the shutoff valve, preferring the local path."""
        await self._async_set_valve(False)

    async def _async_set_valve(self, open_valve: bool) -> None:
        """Actuate the valve locally when possible, falling back to cloud."""
        if self._local_client is not None and self._local_active:
            try:
                await self._local_client.set_valve_state(open_valve)
                LOGGER.debug(
                    "Valve %s command sent locally to %s",
                    "open" if open_valve else "close",
                    self._local_host,
                )
                return
            except JnapError as err:
                LOGGER.warning(
                    "Local valve command to %s failed (%s); falling back to cloud",
                    self._local_host,
                    err,
                )
        if open_valve:
            await self._coordinator.api_client.device.open_valve(self._phyn_device_id)
        else:
            await self._coordinator.api_client.device.close_valve(self._phyn_device_id)

    @staticmethod
    def _local_number(value: Any) -> float | None:
        """Coerce a JNAP/WASP attribute value into a float if possible."""
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                return None
        return None

    async def _async_local_poll(self, now: Any = None) -> None:
        """Poll the device's local JNAP API and merge telemetry into state."""
        if self._local_client is None:
            return
        try:
            output = await self._local_client.get_attributes()
        except JnapError as err:
            self._local_failures += 1
            if self._local_failures == LOCAL_FAILURE_THRESHOLD:
                LOGGER.warning(
                    "Local polling for %s at %s is failing (%s); "
                    "relying on cloud until it recovers",
                    self._phyn_device_id,
                    self._local_host,
                    err,
                )
                self._local_active = False
                self._write_entity_states()
            return

        was_active = self._local_active
        self._local_failures = 0
        self._local_active = True
        if not was_active:
            LOGGER.info(
                "Local JNAP polling active for %s at %s",
                self._phyn_device_id,
                self._local_host,
            )

        await self._apply_local_attributes(output)

    async def _apply_local_attributes(self, output: dict[str, Any]) -> None:
        """Map a JNAP ``attribute/get`` dump onto the cloud state schema."""
        product = output.get("product", {})
        stats = output.get("stats", {})
        if not isinstance(product, dict):
            product = {}
        if not isinstance(stats, dict):
            stats = {}

        update_data: dict[str, Any] = {}

        pressure = self._local_number(product.get("sensor_pressure_1"))
        if pressure is not None:
            update_data["pressure"] = {"v": pressure}

        temperature = self._local_number(product.get("sensor_temperature_1"))
        if temperature is not None:
            update_data["temperature"] = {"v": temperature}

        flow = self._local_number(product.get("sensor_flow"))
        if flow is not None:
            update_data["flow"] = {"v": flow}

        flow_state = product.get("sensor_flow_state")
        if isinstance(flow_state, str) and flow_state:
            update_data["flow_state"] = {"v": flow_state}

        sov_state = product.get("sov_state_str")
        if isinstance(sov_state, str) and sov_state:
            update_data["sov_status"] = {"v": sov_state}

        consumption = self._local_number(product.get("consumption_total"))
        if consumption is not None:
            update_data["consumption"] = math.floor(consumption * 100) / 100

        rssi = self._local_number(stats.get("wifi_sta_rssi"))
        if rssi is not None:
            update_data["signal_strength"] = rssi

        if not update_data:
            LOGGER.debug(
                "Local attribute dump for %s had no mappable fields", self._phyn_device_id
            )
            return

        async with self._state_lock:
            self._device_state.update(update_data)
            # Mirror what the MQTT push handler maintains so entities that
            # read the realtime dict (flow state, consumption) stay in sync.
            if "flow_state" in update_data:
                self._rt_device_state["flow_state"] = update_data["flow_state"]
            if "consumption" in update_data:
                self._rt_device_state["consumption"] = {"v": update_data["consumption"]}
            # Refresh the throttle stamp: while local polling is healthy the
            # cloud state endpoint does not need to be hit every cycle.
            self._device_state["last_updated"] = math.floor(time.time())
            self._update_last_known_valve_state()

        self._write_entity_states()

    def _write_entity_states(self) -> None:
        """Push current state to all initialized entities."""
        for entity in self.entities:
            if getattr(entity, "hass", None) is None:
                continue
            entity.async_write_ha_state()
    
    @property
    def autoshutoff_enabled(self) -> bool | None:
        """Return True if auto shutoff enabled"""
        if "auto_shutoff_enable" not in self._auto_shutoff:
            return None
        return self._auto_shutoff["auto_shutoff_enable"] == True
    
    async def set_autoshutoff_enabled(self, state: bool) -> None:
        LOGGER.debug("Setting auto shutoff state: %s" % state)
        await self._coordinator.api_client.device.set_autoshutoff_enabled(self._phyn_device_id, state)
        self._auto_shutoff["auto_shutoff_enable"] = state

    @property
    def away_mode(self) -> bool | None:
        """Return True if device is in away mode."""
        if "leak_sensitivity_away_mode" not in self._device_preferences:
            return None
        return self._device_preferences["leak_sensitivity_away_mode"]["value"] == "true"

    async def set_device_preference(self, name: str, val: bool) -> None:
        """Set Device Preference"""
        if name not in ["leak_sensitivity_away_mode", "scheduler_enable"]:
            LOGGER.debug("Tried setting preference for %s but not avialable", name)
            return None
        if val not in ["true", "false"]:
            return None
        params = [{
            "device_id": self._phyn_device_id,
            "name": name,
            "value": val
        }]
        LOGGER.debug("Setting preference '%s' to '%s'", name, val)
        await self._coordinator.api_client.device.set_device_preferences(self._phyn_device_id, params)
        if name not in self._device_preferences:
            self._device_preferences[name] = {}
        self._device_preferences[name]["value"] = val
    
    async def set_away_mode(self, state: bool) -> None:
        """Manually set away mode value"""
        key = "leak_sensitivity_away_mode"
        val = "true" if state else "false"
        params = [{
            "device_id": self._phyn_device_id,
            "name": key,
            "value": val
        }]
        await self._coordinator.api_client.device.set_device_preferences(self._phyn_device_id, params)
        self._device_preferences[key]["value"] = val

    async def set_scheduler_enabled(self, state: bool) -> None:
        """Manually set the scheduler enabled mode"""
        key = "scheduler_enable"
        val = "true" if state else "false"
        params = [{
            "device_id": self._phyn_device_id,
            "name": key,
            "value": val
        }]
        await self._coordinator.api_client.device.set_device_preferences(self._phyn_device_id, params)
        self._device_preferences[key]["value"] = val
    
    async def _update_autoshutoff(self, *_) -> None:
        """Update auto shutoff status"""
        data = await self._coordinator.api_client.device.get_autoshuftoff_status(self._phyn_device_id)
        LOGGER.debug("Autoshutoff info: %s" % data)
        self._auto_shutoff.update(data)
    
    async def _update_away_mode(self, *_) -> None:
        """Update the away mode data from the API"""
        self._away_mode = await self._coordinator.api_client.device.get_away_mode(
            self._phyn_device_id
        )

    async def _update_device_preferences(self, *_) -> None:
        """Update the device preferences from the API"""
        data = await self._coordinator.api_client.device.get_device_preferences(self._phyn_device_id)
        for item in data:
            self._device_preferences.update({item['name']: item})
        #LOGGER.debug("Device Preferences: %s", self._device_preferences)

    async def _update_consumption_data(self, *_) -> None:
        """Update water consumption data from the API."""
        today = dt_util.now().date()
        duration = today.strftime("%Y/%m/%d")
        self._water_usage = await self._coordinator.api_client.device.get_consumption(
            self._phyn_device_id, duration
        )
        LOGGER.debug("Updated Phyn consumption data: %s", self._water_usage)
    
    async def _update_device_health_tests(self, *_) -> None:
        """Update the latest health test"""
        try: 
            data = await self._coordinator.api_client.device.get_health_tests(self._phyn_device_id)
        except Exception as error:
            LOGGER.error("Error getting health tests: %s" % error)
            self._latest_health_test = None
            return
        latest_test = None
        LOGGER.debug("Health data: %s" % data)
        for test in data['data']:
            if latest_test is None or latest_test['end_time'] < test['end_time']:
                latest_test = test
        
        self._latest_health_test = latest_test        

    def _update_last_known_valve_state(self) -> None:
        """Update last known valve state from device state. Must be called within _state_lock."""
        sov_status = self._device_state.get("sov_status", {})
        if sov_status.get("v") != "Partial":
            self._last_known_valve_state = sov_status.get("v") == "Open"

    async def _update_device_state(self, *_) -> None:
        """Update the device state from the API."""
        async with self._state_lock:
            if 'last_updated' not in self._device_state or self._device_state['last_updated'] <= (math.floor(time.time()) - 60):
                state_data = await self._coordinator.api_client.device.get_state(
                    self._phyn_device_id
                )
                self._device_state.update(state_data)
                self._device_state['last_updated'] = math.floor(time.time())
                self._update_last_known_valve_state()

    async def on_device_update(self, device_id, data):
        if device_id == self._phyn_device_id:
            async with self._state_lock:
                self._rt_device_state = data

                update_data = {}
                if "consumption" in data:
                    # Round consumption down to 2 decimal points.
                    update_data.update({"consumption": math.floor(data["consumption"]["v"] * 100) / 100})
                if "flow" in data:
                    update_data.update({"flow": data["flow"]})
                if "flow_state" in data:
                    update_data.update({"flow_state": data["flow_state"]})
                if "sov_state" in data:
                    update_data.update({"sov_status":{"v": data["sov_state"]}})
                if "sensor_data" in data:
                    if "pressure" in data["sensor_data"]:
                        update_data.update({"pressure": data["sensor_data"]["pressure"]})
                    if "temperature" in data["sensor_data"]:
                        update_data.update({"temperature": data["sensor_data"]["temperature"]})
                self._device_state.update(update_data)
                self._device_state['last_updated'] = math.floor(time.time())
                self._update_last_known_valve_state()
                LOGGER.debug("Updating device %s Device State: %s", self._phyn_device_id, self._device_state)

            self._write_entity_states()
