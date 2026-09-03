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
