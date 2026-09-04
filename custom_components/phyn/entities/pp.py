"""PP-specific entity classes for Phyn Plus devices."""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.components.valve import (
    ValveDeviceClass,
    ValveEntity,
    ValveEntityFeature,
)
from homeassistant.const import UnitOfVolume, UnitOfVolumeFlowRate
from homeassistant.helpers.entity import EntityCategory

from .base import WATER_ICON, PhynEntity, PhynSwitchEntity

if TYPE_CHECKING:
    from ..devices.pp import PhynPlusDevice

NAME_FLOW_RATE = "Current water flow rate"


class PhynAutoShutoffModeSwitch(PhynSwitchEntity):
    """Switch class for the Phyn Away Mode."""

    _device: PhynPlusDevice

    def __init__(self, device: PhynPlusDevice) -> None:
        """Initialize the Phyn Away Mode switch."""
        super().__init__("autoshutoff_enabled", "Autoshutoff Enabled", device)
        self._preference_name: str | None = "autoshutoff_enabled"

    @property
    def _state(self) -> bool | None:
        return self._device.autoshutoff_enabled

    @property
    def icon(self) -> str:
        """Return the icon reflecting whether automatic shutoff protection is active."""
        if self.is_on:
            return "mdi:shield-check"
        return "mdi:shield-off"

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the preference."""
        await self._device.set_autoshutoff_enabled(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the preference."""
        await self._device.set_autoshutoff_enabled(False)
        self.async_write_ha_state()


class PhynAwayModeSwitch(PhynSwitchEntity):
    """Switch class for the Phyn Away Mode."""

    _device: PhynPlusDevice

    def __init__(self, device: PhynPlusDevice) -> None:
        """Initialize the Phyn Away Mode switch."""
        super().__init__("away_mode", "Away Mode", device)
        self._preference_name: str | None = "leak_sensitivity_away_mode"

    @property
    def _state(self) -> bool | None:
        return self._device.away_mode

    @property
    def icon(self) -> str:
        """Return the icon to use for the away mode."""
        if self.is_on:
            return "mdi:bag-suitcase"
        return "mdi:home-circle"


class PhynFlowState(PhynEntity, SensorEntity):
    """Flow State for Water Sensor"""
    _attr_icon = WATER_ICON
    #_attr_native_unit_of_measurement = UnitOfVolume.GALLONS
    #_attr_state_class: SensorStateClass = SensorStateClass.TOTAL_INCREASING
    #_attr_device_class = SensorDeviceClass.WATER

    _device: PhynPlusDevice

    def __init__(self, device: PhynPlusDevice) -> None:
        """Initialize the water flow state sensor."""
        super().__init__("water_flow_state", "Water Flowing", device)
        self._state: str | None = None

    @property
    def native_value(self) -> str | None:
        """Return the flow state (off/low/med/high).

        Prefers the realtime push feed, falling back to the merged device
        state (fed by local polling and, when present, the REST state) so the
        sensor is not stuck at unknown until the first push arrives. Only
        string values are reported — the initial numeric placeholder is not
        a real state.
        """
        for source in (self._device._rt_device_state, self._device._device_state):
            value = source.get("flow_state", {}).get("v")
            if isinstance(value, str) and value:
                return value
        return None


class PhynLeakTestSensor(PhynEntity, BinarySensorEntity):
    """Leak Test Sensor"""
    _attr_device_class = BinarySensorDeviceClass.RUNNING

    _device: PhynPlusDevice

    def __init__(self, device: PhynPlusDevice) -> None:
        """Initialize the leak test sensor."""
        super().__init__("leak_test_running", "Leak Test Running", device)

    @property
    def is_on(self) -> bool:
        return self._device.leak_test_running


class PhynLeakTestWarning(PhynEntity, BinarySensorEntity):
    """Leak Test Sensor"""
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    _device: PhynPlusDevice

    def __init__(self, device: PhynPlusDevice) -> None:
        """Initialize the leak test warning sensor."""
        super().__init__("leak_test_warning", "Leak Test Warning", device)

    @property
    def is_on(self) -> bool | None:
        if self._device._latest_health_test is None:
            return None
        return self._device._latest_health_test.get('is_warn', False)


class PhynLeakTestLeakDetected(PhynEntity, BinarySensorEntity):
    """Leak Test Sensor"""
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    _device: PhynPlusDevice

    def __init__(self, device: PhynPlusDevice) -> None:
        """Initialize the leak test leak sensor."""
        super().__init__("leak_test_leak", "Leak Detected", device)

    @property
    def is_on(self) -> bool | None:
        if self._device._latest_health_test is None:
            return None
        return self._device._latest_health_test.get('is_leak', False)


class PhynScheduledLeakTestEnabledSwitch(PhynSwitchEntity):
    """Switch class for the Phyn Away Mode."""

    _device: PhynPlusDevice

    def __init__(self, device: PhynPlusDevice) -> None:
        """Initialize the Phyn Away Mode switch."""
        super().__init__("scheduled_leak_test_enabled", "Scheduled Leak Test Enabled", device)
        self._preference_name: str | None = "scheduler_enable"

    @property
    def _state(self) -> bool | None:
        return self._device.scheduled_leak_test_enabled

    @property
    def icon(self) -> str:
        """Return the icon reflecting whether the nightly leak test is scheduled."""
        if self.is_on:
            return "mdi:calendar-check"
        return "mdi:calendar-remove"


class PhynLocalConnectivitySensor(PhynEntity, BinarySensorEntity):
    """Reports whether local (LAN) JNAP polling of the device is healthy.

    Only created when a local host is configured for the device. Always
    available so the local-down state can be observed and alerted on.
    """

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    _device: PhynPlusDevice

    def __init__(self, device: PhynPlusDevice) -> None:
        """Initialize the local connectivity sensor."""
        super().__init__("local_connection", "Local Connection", device)

    @property
    def available(self) -> bool:
        """Always available so the local-down state itself is visible."""
        return True

    @property
    def is_on(self) -> bool:
        """Return True while local polling is delivering data."""
        return self._device.local_active

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the configured host for troubleshooting."""
        return {"host": self._device.local_host}


class PhynLatestLeakTestSensor(PhynEntity, SensorEntity):
    """Timestamp of the most recent leak (health) test, with result details.

    Attributes expose the raw scalar fields of the latest test (result flags,
    pressure-drop figures, initiator, duration, …) so automations can react to
    a failed or warning leak test without scraping the Phyn app.
    """

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    _device: PhynPlusDevice

    def __init__(self, device: PhynPlusDevice) -> None:
        """Initialize the latest leak test sensor."""
        super().__init__("last_leak_test", "Last Leak Test", device)

    @property
    def native_value(self) -> datetime | None:
        """Return when the most recent leak test finished."""
        return self._device.last_leak_test_time

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the scalar details of the latest leak test."""
        test = self._device._latest_health_test
        if not test:
            return None
        return {
            key: value
            for key, value in test.items()
            if isinstance(value, (str, int, float, bool))
        }


class PhynConsumptionSensor(PhynEntity, SensorEntity):
    """Monitors the amount of water usage."""

    _attr_icon = WATER_ICON
    _attr_native_unit_of_measurement = UnitOfVolume.GALLONS
    _attr_state_class: SensorStateClass = SensorStateClass.TOTAL_INCREASING
    _attr_device_class = SensorDeviceClass.WATER

    _device: PhynPlusDevice

    def __init__(self, device: PhynPlusDevice) -> None:
        """Initialize the daily water usage sensor."""
        super().__init__("consumption", "Total Water Usage", device)
        self._state: float | None = None

    @property
    def native_value(self) -> float | None:
        """Return the current daily usage."""
        if self._device.consumption is None:
            return None
        return self._device.consumption


class PhynCurrentFlowRateSensor(PhynEntity, SensorEntity):
    """Monitors the current water flow rate."""

    _attr_state_class: SensorStateClass = SensorStateClass.MEASUREMENT
    _attr_translation_key = "current_flow_rate"
    _attr_device_class = SensorDeviceClass.VOLUME_FLOW_RATE
    _attr_native_unit_of_measurement = UnitOfVolumeFlowRate.GALLONS_PER_MINUTE

    _device: PhynPlusDevice

    def __init__(self, device: PhynPlusDevice) -> None:
        """Initialize the flow rate sensor."""
        super().__init__("current_flow_rate", NAME_FLOW_RATE, device)
        self._state: float | None = None

    @property
    def native_value(self) -> float | None:
        """Return the current flow rate."""
        if self._device.current_flow_rate is None:
            return None
        rate = round(self._device.current_flow_rate, 1)
        return 0 if rate == 0 else rate


class PhynValve(PhynEntity, ValveEntity):
    """ValveEntity for the Phyn valve."""

    _device: PhynPlusDevice

    def __init__(self, device: PhynPlusDevice) -> None:
        """Initialize the Phyn Valve."""
        super().__init__("shutoff_valve", "Shutoff valve", device)
        self._attr_supported_features = ValveEntityFeature(ValveEntityFeature.OPEN | ValveEntityFeature.CLOSE)
        self._attr_device_class = ValveDeviceClass.WATER
        self._attr_reports_position = False

    async def async_open_valve(self) -> None:
        """Open the valve (local-first with cloud fallback)."""
        await self._device.async_open_valve()

    def open_valve(self) -> None:
        """Open the valve."""
        raise NotImplementedError()

    async def async_close_valve(self) -> None:
        """Close the valve (local-first with cloud fallback)."""
        await self._device.async_close_valve()

    def close_valve(self) -> None:
        """Close valve."""
        raise NotImplementedError()

    @property
    def is_closed(self) -> bool | None:
        """Return True if the valve is closed."""
        if self._device.valve_open is None:
            return None
        return not self._device.valve_open

    @property
    def is_opening(self) -> bool:
        """Return True if the valve is transitioning from closed to open."""
        return self._device.valve_changing and self._device._last_known_valve_state is False

    @property
    def is_closing(self) -> bool:
        """Return True if the valve is transitioning from open to closed."""
        return self._device.valve_changing and self._device._last_known_valve_state is True
