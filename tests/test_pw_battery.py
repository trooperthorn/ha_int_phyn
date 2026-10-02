"""Unit tests for the PW1 low-battery alert.

The Phyn cloud keeps a battery alert "ongoing" after the puck recovers, so
the binary sensor must also respect the measured battery level.
"""
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

pytest.importorskip("homeassistant")
pytest.importorskip("aiophyn")

sys.path.insert(0, str(Path(__file__).parent.parent))

from custom_components.phyn.devices.pw import PhynWaterSensorDevice  # noqa: E402

ONGOING = [{"id": "a1", "device_id": "pw1", "alert_type": "battery", "ongoing": True}]


def make_device(
    level: int | None, alerts: list[dict], options: dict | None = None
) -> PhynWaterSensorDevice:
    coordinator = MagicMock()
    coordinator.config_entry.options = options or {}
    device = PhynWaterSensorDevice(coordinator, "home1", "pw1", "PW1")
    if level is not None:
        device._water_statistics["battery_level"] = level
    device._latest_device_alerts = alerts
    device._device_state["online_status"] = {"v": "online"}
    device._last_statistics_ts = int(time.time())
    return device


def test_no_alert_is_off():
    assert make_device(75, []).alert_battery is False


def test_ongoing_alert_with_healthy_level_is_off():
    assert make_device(75, ONGOING).alert_battery is False


def test_ongoing_alert_with_low_level_is_on():
    assert make_device(8, ONGOING).alert_battery is True


def test_ongoing_alert_without_level_is_on():
    assert make_device(None, ONGOING).alert_battery is True


@pytest.mark.parametrize("level", [5, 10])
def test_low_level_without_alert_is_on(level):
    assert make_device(level, []).alert_battery is True


def test_battery_alert_uses_battery_device_class():
    from homeassistant.components.binary_sensor import BinarySensorDeviceClass

    from custom_components.phyn.entities.base import PhynAlertSensor

    device = make_device(75, [])
    sensor = next(
        e for e in device.entities
        if isinstance(e, PhynAlertSensor) and e._device_property == "alert_battery"
    )
    assert sensor.device_class == BinarySensorDeviceClass.BATTERY


def test_level_just_above_threshold_is_off():
    assert make_device(11, ONGOING).alert_battery is False


def test_configured_threshold_is_used():
    options = {"low_battery_threshold": 30}
    assert make_device(30, [], options).alert_battery is True
    assert make_device(31, ONGOING, options).alert_battery is False


def test_offline_sensor_is_battery_dead():
    device = make_device(75, [])
    device._device_state["online_status"] = {"v": "offline"}
    assert device.battery_state == "dead"
    assert device.alert_battery is True


def test_silent_sensor_is_battery_dead():
    device = make_device(75, [])
    device._last_statistics_ts = int(time.time()) - 73 * 3600
    assert device.battery_state == "dead"


def test_configured_dead_after_hours():
    device = make_device(75, [], {"dead_after_hours": 24})
    device._last_statistics_ts = int(time.time()) - 25 * 3600
    assert device.battery_state == "dead"


def test_battery_states():
    assert make_device(75, []).battery_state == "normal"
    assert make_device(5, []).battery_state == "low"


def test_battery_alert_stays_available_when_offline():
    from custom_components.phyn.entities.base import PhynAlertSensor

    device = make_device(75, [])
    device._device_state["online_status"] = {"v": "offline"}
    sensor = next(
        e for e in device.entities
        if isinstance(e, PhynAlertSensor) and e._device_property == "alert_battery"
    )
    assert sensor.available is True
    assert sensor.is_on is True
    assert sensor.extra_state_attributes == {"battery_state": "dead"}


def test_water_sensor_mac_is_device_id():
    coordinator = MagicMock()
    coordinator.config_entry.options = {}
    device = PhynWaterSensorDevice(coordinator, "home1", "28F53742135F", "PW1")
    assert device.mac_addresses == {"28:f5:37:42:13:5f"}
