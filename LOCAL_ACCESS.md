# Local (LAN) Access to Phyn Devices: Research & Architecture

_Last updated: 2026-08-20_

This document records what is and is not possible for **direct, local-network
communication** with Phyn devices, the sources behind each finding, and the
architecture this integration uses as a result: **local-first for the Phyn
Plus, cloud fallback for everything, cloud-only where the hardware allows
nothing else.**

## TL;DR

| Device | Local access | What this integration does |
|---|---|---|
| Phyn Plus (PP2, fw 4.9.x) | **Yes, JNAP HTTP API on TCP port 80** (unofficial) | Local telemetry polling every 10 s + local valve control, with automatic cloud fallback |
| Phyn Plus (PP1) | Unknown (likely, unverified) | Same code path, configure a local IP and the integration verifies before using it |
| Phyn Classic (PC1) | Unknown | Cloud only |
| Phyn Smart Water Sensor (PW1) | **No**, battery WiFi device, sleeps, exposes nothing | Cloud only, with MQTT push subscribed so leak events arrive within seconds |

## 1. The Phyn Plus local API: JNAP

The Phyn Plus runs a lighttpd web server on **TCP port 80** speaking **JNAP**
(JSON Network Access Protocol), the same protocol family Belkin/Linksys
routers and Uponor Smatrix modules use (Phyn was originally a Belkin/Uponor
joint venture, and Phyn built Uponor's communication modules; JNAP actions on
both use the `http://phyn.com/jnap/...` action namespace).

Protocol summary (verified on PP2 firmware 4.9.x):

- Every call is `POST http://<device-ip>/JNAP/`; the operation is selected by
  the `X-JNAP-Action` header, not the path.
- Authorization: `X-JNAP-Authorization: Basic <base64("admin:admin")>` -
  static firmware credentials.
- Response envelope: `{"result": "OK", "output": {...}}`.
- Known-good actions:
  - `http://phyn.com/jnap/core/GetDeviceInfo` → `deviceID` (MAC),
    `serialNumber`, `productCode`, `firmwareVersion`
  - `http://phyn.com/jnap/attribute/get` (body must be `{}`) → full telemetry
    dump: `product.sensor_pressure_1` (PSI), `product.sensor_temperature_1`
    (°F), `product.sensor_flow` (GPM), `product.sensor_flow_state`,
    `product.sov_state_str`, `product.consumption_total` (cumulative gal),
    leak/freeze/pressure ML state flags, `stats.wifi_sta_rssi`, uptime, …
  - `http://phyn.com/jnap/shutoff/GetShutoffValveState` → `{"state": "Open"}`
  - `http://phyn.com/jnap/shutoff/SetShutoffValveState` with
    `{"state": "Open"|"Close"}` → **actuates the physical valve**
- The local interface runs in parallel with the cloud connection. It is
  polling-only, there is no local push/subscribe mechanism.

**Firmware quirk:** on fw `4.9.0.23`, the `attribute/get` response is
malformed HTTP, a debug line leaks into the headers and a pipelined second
response follows the declared `Content-Length` body. Strict clients (aiohttp)
reject it. This integration's client (`custom_components/phyn/jnap.py`)
therefore speaks raw TCP and parses tolerantly: it skips non-header lines and
reads exactly `Content-Length` bytes.

Sources:

- https://github.com/rplankenhorn/ha-phyn-local, LAN-only HA integration for
  the PP2 (July 2026), incl. `PROTOCOL.md` documenting the actions above.
- https://github.com/rplankenhorn/ha-phyn-local/issues/1, independent user
  confirming the endpoint on real PP2 hardware (fw
  `Phyn_WaterDevice_release_4_9_0_23_locked`, `lighttpd/1.4.49`) and
  documenting the malformed-HTTP quirk.
- Uponor JNAP ecosystem using the same `phyn.com/jnap` namespace and WASP
  attribute daemon: https://github.com/asev/py-uponor-jnap,
  https://github.com/dave-code-ruiz/uhomeuponor/issues/21, and others.

### Risks and caveats

- **Unofficial.** Static `admin:admin` credentials on an unauthenticated LAN
  port could be hardened or removed by any future firmware. The cloud path is
  always kept as fallback, and losing local access degrades gracefully (a
  warning is logged, the "Local Connection" diagnostic sensor turns off).
- Verified on PP2 / firmware 4.9.x only. PP1 is untested; the integration
  verifies device identity (`GetDeviceInfo` deviceID vs. the cloud device id)
  before ever using a configured host, so misconfiguration fails safe.
- The Phyn Plus MAC OUI `28:F5:37` is an IEEE **shared** registry block, so
  DHCP discovery can over-match other vendors' hardware. Every discovered
  candidate is probed with `GetDeviceInfo` before anything is stored.

## 2. What does NOT exist (negative findings)

All verified as of August 2026:

- **No official/public Phyn API**: no developer portal, no documented REST
  API, no OpenAPI/Swagger for `api.phyn.com`. Official integrations are
  Alexa, Google Assistant, and IFTTT (cloud-to-cloud).
- **No HomeKit and no Matter support** on any Phyn device (HomeKit was
  promised historically and never shipped), so HA's local HomeKit Controller
  path is unavailable.
- **No mDNS/zeroconf or SSDP advertisement**: DHCP is the only usable
  discovery signal.
- **No local API on the PW1** water sensor pucks. They are battery devices
  that sleep and wake only to report to the cloud.
- **No published MQTT interception or firmware analysis**: the devices
  authenticate to AWS IoT with device certificates; nobody has published
  redirecting them to a local broker.
- **No BLE data path**: Bluetooth is used only for initial WiFi
  provisioning; no GATT maps or BLE advertisements have been documented.
- **No `phyn` integration in Home Assistant core**: everything is
  custom/HACS.

## 3. The cloud protocol (fallback and PW1 path)

Via the `aiophyn` library (https://github.com/jordanruthe/aiophyn):

- **Auth:** AWS Cognito SRP (`us-east-1`), refresh-token renewal.
- **REST:** `https://api.phyn.com`, state, consumption, water statistics
  (PW1), valve open/close, preferences (away mode, leak-test scheduler),
  auto-shutoff enable/disable (with timed disable), health tests (leak
  tests), firmware info, alerts (latest / active summary / mark-read).
- **Real-time push:** `POST /users/{email}/iot_policy` returns a presigned
  AWS IoT websocket URL; MQTT over websockets, subscribing to
  `prd/app_subscriptions/{device_id}`. Payloads carry `flow`, `flow_state`,
  `sov_state`, `consumption`, and `sensor_data.pressure/temperature`.

This integration subscribes **all** devices (including PW1) to that topic.
For PW1 pucks a push triggers an immediate full refresh, so water-detected
alerts land in seconds instead of at the next poll.

## 4. Architecture implemented here

```
                    ┌────────────────────────────┐
                    │   Phyn cloud (api.phyn.com │
                    │      + AWS IoT MQTT)       │
                    └──────┬──────────┬──────────┘
              REST polling │          │ MQTT push (realtime)
     (alerts, consumption, │          │ flow/pressure/temp/valve
      preferences, tests)  │          │ + PW1 wake events
                    ┌──────┴──────────┴──────────┐
                    │   Phyn integration (HA)    │
                    └──────┬─────────────────────┘
        local JNAP polling │  every 10 s, + valve control
        (when configured)  │  cloud fallback on failure
                    ┌──────┴──────────┐
                    │  Phyn Plus (LAN)│   PW1 pucks: cloud only
                    └─────────────────┘
```

- **Local telemetry:** when a local IP is configured for a Phyn Plus, the
  integration polls `attribute/get` every 10 seconds and maps pressure,
  temperature, flow, flow state, valve state, cumulative consumption, and
  WiFi RSSI onto the same state the cloud feeds, entities update from
  whichever source spoke last. While local polling is healthy the cloud
  state endpoint is skipped, reducing cloud API load.
- **Local valve control:** `valve.open`/`valve.close` go to the device
  directly when local is healthy, falling back to the cloud API, so leak
  response automations still work during an internet outage.
- **Fallback:** after 3 consecutive local failures the integration logs a
  warning, marks local down (see the "Local Connection" diagnostic sensor),
  and relies on cloud; local recovers automatically when polls succeed again.
- **Configuration:** per-device local IPs live in the integration options.
  DHCP discovery (`28:F5:37*`) auto-fills and auto-updates them after a
  successful identity check, a DHCP reservation for the Phyn Plus is still
  recommended.
- **Availability:** a device counts as available while local polling is
  healthy, even if the Phyn cloud says it is offline.

## 5. Future paths

- **PP1:** confirm JNAP works on PP1 hardware (expected but unverified) -
  reports welcome in the issue tracker.
- **Additional JNAP attributes:** the `attribute/get` dump contains more than
  is currently mapped (leak-detector state flags, plumbing-check progress,
  valve close counts, uptime). These can become entities once field meanings
  are confirmed on real hardware.
- **Cloud independence:** should the Phyn cloud ever degrade (Phyn changed
  owners in 2025, Belkin sold it to an investor group), the local path
  already covers the safety-critical functions for the Phyn Plus: telemetry
  and valve control.
