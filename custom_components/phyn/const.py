"""Constants for the phyn integration."""
import logging

LOGGER = logging.getLogger(__package__)

DOMAIN = "phyn"

# All known alert types across all Phyn device models.
# Used as the event_types list for the HA event entity and in the
# options-flow multi-select for suppressing specific alert types.
ALL_ALERT_TYPES: dict[str, str] = {
    "battery": "Battery",
    "freeze_warn": "Freeze Warning",
    "high_humidity": "High Humidity",
    "high_pressure": "High Pressure",
    "leak": "Leak",
    "low_humidity": "Low Humidity",
    "low_temperature": "Low Temperature",
    "offline_leak": "Offline Leak Shutoff",
    "periodic_leak": "Recurring Flow",
    "pinhole_leak": "Pinhole Leak",
    "temperature": "Temperature",
    "water_detected": "Water Detected",
}

CONF_EXCLUDED_ALERT_TYPES = "excluded_alert_types"
CONF_HOME_ID = "home_id"
CONF_DEVICE_IDS = "device_ids"

# Cloud polling cadence (seconds). Real-time state arrives over MQTT push;
# polling covers alerts, preferences and consumption, so it can be relaxed
# on metered/slow connections or tightened for faster alert pickup.
CONF_UPDATE_INTERVAL = "update_interval"
DEFAULT_UPDATE_INTERVAL = 60
MIN_UPDATE_INTERVAL = 30
MAX_UPDATE_INTERVAL = 600

# Local (LAN) access to Phyn Plus devices over the JNAP protocol.
# Maps phyn device_id -> IP/host on the local network. See LOCAL_ACCESS.md.
CONF_LOCAL_HOSTS = "local_hosts"
# Local polling cadence (seconds), configurable in the options flow.
CONF_LOCAL_POLL_INTERVAL = "local_poll_interval"
DEFAULT_LOCAL_POLL_INTERVAL = 10
MIN_LOCAL_POLL_INTERVAL = 5
MAX_LOCAL_POLL_INTERVAL = 60
# Consecutive local poll failures before falling back to cloud-only and
# surfacing a warning (transient WiFi hiccups shouldn't flap the source).
LOCAL_FAILURE_THRESHOLD = 3
