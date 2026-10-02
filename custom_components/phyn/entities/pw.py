"""PW-specific entity classes for Phyn Water Sensors."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfRatio

from .base import PhynAlertSensor, PhynEntity

if TYPE_CHECKING:
    from ..devices.pw import PhynWaterSensorDevice


class PhynBatterySensor(PhynEntity, SensorEntity):
    """Monitors the battery level."""

    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = UnitOfRatio.PERCENTAGE
    _attr_state_class: SensorStateClass = SensorStateClass.MEASUREMENT

    _device: PhynWaterSensorDevice

    def __init__(self, device: PhynWaterSensorDevice, name: str, readable_name: str) -> None:
        """Initialize the battery sensor."""
        super().__init__(name, readable_name, device)
        self._state: float | None = None
        self._device_property: str = "battery"

    @property
    def native_value(self) -> float | None:
        """Return the current battery."""
        if not hasattr(self._device, self._device_property) or self._device.battery is None:
            return None
        return round(self._device.battery, 1)


class PhynBatteryAlertSensor(PhynAlertSensor):
    """Low battery alert that stays available so a dead sensor shows as Low."""

    _device: PhynWaterSensorDevice

    def __init__(self, device: PhynWaterSensorDevice) -> None:
        """Initialize the battery alert."""
        super().__init__(
            device,
            "battery_alert",
            "Low Battery Alert",
            "alert_battery",
            BinarySensorDeviceClass.BATTERY,
        )

    @property
    def available(self) -> bool:
        """An offline PW1 is the dead-battery case, so never go unavailable."""
        return True

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose why the alert is on: dead, low or normal."""
        return {"battery_state": self._device.battery_state}
