"""Unit tests for Phyn Plus device state properties.

Covers the sources/shapes each sensor accepts so push-fed sensors don't sit
at "unknown" when only REST or local data is available. Requires
homeassistant + aiophyn importable (CI installs both); skipped otherwise.
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

pytest.importorskip("homeassistant")
pytest.importorskip("aiophyn")

sys.path.insert(0, str(Path(__file__).parent.parent))

from custom_components.phyn.devices.pp import PhynPlusDevice  # noqa: E402
from custom_components.phyn.entities.pp import PhynFlowState  # noqa: E402


def make_device() -> PhynPlusDevice:
    coordinator = MagicMock()
    coordinator.config_entry.options = {}
    return PhynPlusDevice(coordinator, "home1", "28f537aabbcc", "PP2")


def flow_state_entity(device: PhynPlusDevice) -> PhynFlowState:
    return next(e for e in device.entities if isinstance(e, PhynFlowState))


def test_flow_rate_unknown_without_data():
    device = make_device()
    assert device.current_flow_rate is None


def test_flow_rate_from_push_v():
    device = make_device()
    device._device_state["flow"] = {"v": 1.2345}
    assert device.current_flow_rate == 1.234


def test_flow_rate_from_rest_mean():
    device = make_device()
    device._device_state["flow"] = {"mean": 0.5, "ts": 1}
    assert device.current_flow_rate == 0.5


def test_consumption_unknown_without_data():
    assert make_device().consumption is None


def test_consumption_from_flattened_float():
    device = make_device()
    device._device_state["consumption"] = 123.456
    assert device.consumption == 123.45


def test_consumption_from_raw_dict():
    device = make_device()
    device._device_state["consumption"] = {"v": 9876.543, "ts": 1}
    assert device.consumption == 9876.54


def test_flow_state_ignores_numeric_placeholder():
    device = make_device()
    # __init__ seeds flow_state with a numeric placeholder — not a real state.
    assert flow_state_entity(device).native_value is None


def test_flow_state_prefers_realtime_feed():
    device = make_device()
    device._device_state["flow_state"] = {"v": "off"}
    device._rt_device_state["flow_state"] = {"v": "high"}
    assert flow_state_entity(device).native_value == "high"


def test_flow_state_falls_back_to_device_state():
    device = make_device()
    device._device_state["flow_state"] = {"v": "low"}
    assert flow_state_entity(device).native_value == "low"


def test_last_push_time():
    device = make_device()
    assert device.last_push_time is None
    device._last_push_ts = 1_755_000_000.0
    assert device.last_push_time is not None
    assert device.last_push_time.timestamp() == 1_755_000_000.0


def test_state_throttle_follows_update_interval():
    from datetime import timedelta

    device = make_device()
    device._coordinator.update_interval = timedelta(seconds=30)
    assert device._state_throttle_seconds == 30
    device._coordinator.update_interval = timedelta(seconds=300)
    assert device._state_throttle_seconds == 60
    device._coordinator.update_interval = None
    assert device._state_throttle_seconds == 60


def test_local_poll_interval_from_options():
    from unittest.mock import MagicMock

    from custom_components.phyn.const import CONF_LOCAL_POLL_INTERVAL

    coordinator = MagicMock()
    coordinator.config_entry.options = {CONF_LOCAL_POLL_INTERVAL: 15}
    device = PhynPlusDevice(coordinator, "home1", "28f537aabbcc", "PP2")
    assert device.local_poll_interval == 15
    assert make_device().local_poll_interval == 10
