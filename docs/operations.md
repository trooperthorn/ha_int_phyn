# Operations

Runtime behavior of the coordinator and troubleshooting notes.

## Alert polling and initial-fetch seeding

`PhynDataUpdateCoordinator._async_update_data` fetches the latest alerts per
home on every poll (`custom_components/phyn/update_coordinator.py`). The
fetch limit differs between the first poll and subsequent polls:

- First poll: limit 50. This seeds `_seen_alert_ids` with existing alert
  history so that alerts that already existed before Home Assistant started
  are never replayed as new events on the Alert event entity.
- Subsequent polls: limit 20. Any alert created in the last poll interval
  (60 seconds) will be at the top of the most-recent list, so a small limit
  is sufficient once the seed is in place.

## MQTT reconnect fallback

The Phyn Plus's realtime state arrives over the cloud MQTT feed. If MQTT
stays disconnected while the REST API remains reachable, the coordinator
counts consecutive down cycles and reloads the config entry once
`MQTT_DOWN_RELOAD_THRESHOLD` is reached, to rebuild the MQTT client from
scratch as a last resort.

The threshold is intentionally high (about 10 minutes at 60-second poll
intervals) because aiophyn's own reconnect loop is expected to recover the
connection on its own well before the threshold fires. A full config entry
reload is disruptive (it tears down and rebuilds all entities), so it is
reserved for the case where the automatic reconnect has actually stalled.

When this path triggers, the coordinator logs the aiophyn MQTT client's
private reconnect state-machine attributes (`connect_task`, `reconnect_evt`,
`disconnect_evt`) for diagnostics, read with `getattr` because they are not
part of aiophyn's public API and may not exist in every version.

## Push subscriptions

aiophyn's `connect()` returns when the socket opens, before the broker's
CONNACK, and paho drops a subscribe sent in that window without an error.
aiophyn records a topic in `mqtt.topics` only when its SUBACK arrives and
re-subscribes only those topics on reconnect, so an early subscribe was lost
for the life of the client: diagnostics showed `subscribed_topics: 0` and one
pending ack per device, and every push-only sensor (Water Flowing, Total
Water Usage, Last Realtime Update) stayed `unknown`.

`push.py` fixes this without patching aiophyn. Setup waits up to 10 seconds
for the CONNACK, every device topic goes into `mqtt.topics` up front so each
reconnect carries it, and the coordinator resends any wanted topic that is
still only a pending ack after two polls. The MQTT down watchdog now keys on
the wanted topics instead of `mqtt.topics`, which was empty in this failure.

## Offline grace and availability

The Phyn cloud flips a device offline on every Wi-Fi drop. On a weak signal
(the field case was -85 dBm) that is about ten 12-minute outages a day, and
each one took every entity unavailable. `PhynDevice.available` now stays true
until the device has been offline for `OFFLINE_GRACE` (20 minutes), measured
from the `online_status` timestamp. The Online sensor reports the raw state
(`PhynDevice.online`) and the valve goes unavailable immediately, because a
stale valve state is misleading.

## Current flow rate fallback

Without push data, the flow rate falls back to the REST `flow.mean`, which
summarizes a past window. A mean older than `FLOW_MEAN_MAX_AGE` (10 minutes)
reads as 0 so the sensor does not report hour-old flow as current. The
assumption that no fresh window means no flow is unverified against Phyn
documentation.

## Water sensor battery state

`PhynWaterSensorDevice.battery_state` is `dead`, `low` or `normal`. A PW1 that
is offline or silent longer than the `dead_after_hours` option (default 72)
is dead, since it stops reporting when the battery is too weak to run.
Otherwise the measured level is compared with the `low_battery_threshold`
option (default 10%). The Phyn cloud battery alert is used only when no level
is known, because it stays ongoing after a battery is replaced. The Low
Battery Alert entity never goes unavailable and exposes `battery_state` as
an attribute for the battery blueprints.

## Network MAC connections

Since core 2026.8 a device belongs to one config entry, so a Phyn device and
the UniFi client for the same hardware stay separate devices. Core lists
them as linked devices (`config/device_registry/list_linked_devices`) when
they share a connection, so each Phyn device presents its MAC as a
`CONNECTION_NETWORK_MAC` connection via `PhynDevice.mac_addresses`.

The Phyn device id is the MAC without separators. On a PW1 water sensor it
is the Wi-Fi MAC UniFi sees. On a Phyn Plus the Wi-Fi radio is the device id
plus one (field case: id `28F53743DF84`, UniFi client `28:f5:37:43:df:85`),
so both addresses are presented. Core merges new connections into the
existing device on the next setup.
