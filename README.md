# homeassistant-phyn

Home Assistant custom component for interfacing with [Phyn](https://www.phyn.com) Smart Water Assistant and Kohler H2Wise+ by Phyn.

The integration's IoT class is **Cloud Push**: state changes for the Phyn Plus arrive in realtime over the Phyn cloud's MQTT feed, with periodic cloud polling for alerts, consumption, and preferences. In addition, **optional local (LAN) access** is supported for the Phyn Plus — telemetry polling and valve control that keep working during an internet outage. See [LOCAL_ACCESS.md](LOCAL_ACCESS.md) for the research and architecture.

See [docs/README.md](docs/README.md) for operational and troubleshooting notes.

This integration currently provides the following capabilities:

- **Local device access for the Phyn Plus** (optional): direct LAN telemetry every 10 seconds and local valve control with automatic cloud fallback
- Realtime water flow, pressure, temperature, and valve state (cloud MQTT push and/or local polling)
- Daily and total water usage (compatible with the Energy/Water dashboard)
- Shutoff valve control (`valve` entity; local-first when configured)
- Leak testing: on-demand leak test action, leak test running/warning/leak-detected sensors, last-leak-test timestamp with full result details, scheduled leak test control
- Alert binary sensors (leak, pinhole leak, recurring flow, freeze warning, high pressure, battery, temperature, humidity, water detected) and an **Alert event entity** for automations
- Phyn Smart Water Sensor (PW1) support: water detected, humidity, air temperature, battery, last-reading timestamp — with realtime push so leak events arrive in seconds
- Away mode and auto-shutoff control, including a timed **pause auto shutoff** action
- Diagnostics: per-device connectivity (cloud + local), WiFi signal strength, downloadable diagnostics report
- Automation **blueprints** for leak response, freeze protection, prolonged water running, and livestock water supply watch

# Installation via HACS

This custom component can be integrated into [HACS](https://github.com/hacs/integration), so you can track future updates. If you have do not have have HACS installed, please see [their installation guide](https://hacs.xyz/docs/installation/manual).

1. Select HACS from the left-hand navigation menu.

2. Click _Integrations_.

3. Click the three dots in the upper right-hand corner and select _Custom Repositories_.

4. Paste "https://github.com/trooperthorn/ha_int_phyn" into _Repository_, select "Integration" as _Category_, and click Add.

5. Close the Custom repositories dialog after it updates with the new integration.

6. "Phyn Smart Water Assistant" will appear in your list of repositories. Click to open, click the following Download buttons.

# Configuration

Configuration is done via the UI. Add the "Phyn" integration via the Integration settings and provide existing Phyn username and password.

* In the Home Assistant UI, go to Settings > Devices & services, go to the Devices tab, and click "+ Add Device" on the bottom right.

* Search for and select "Phyn".

* A prompt will appear for you to enter your Phyn Account username and password. (This could sometimes take 2-3 minutes, or longer).

## Options

Open **Settings → Devices & services → Phyn → Configure** to set:

- **Suppress these alert types** — alert types that should never fire the Alert event entity.
- **Cloud polling interval** — how often the Phyn cloud is polled (30–600 s, default 60 s). Realtime state arrives over push regardless; polling covers alerts, consumption, and preferences.
- **Local polling interval** — how often a locally-connected Phyn Plus is polled over the LAN (5–60 s, default 10 s).
- **Local IP per Phyn Plus** — enables direct LAN access for that device (see below).

# Local device access (Phyn Plus)

The Phyn Plus exposes an (unofficial) local HTTP API on your LAN. When a local IP is configured, this integration:

- polls telemetry (flow, pressure, temperature, valve state, total consumption, WiFi signal) directly from the device every 10 seconds,
- sends **valve open/close commands locally first**, falling back to the cloud — so leak-response automations keep working during an internet outage,
- reduces cloud API load while local polling is healthy,
- exposes a **Local Connection** diagnostic sensor so you can alert if local access drops.

To enable it, either:

1. **Automatic:** when Home Assistant sees the Phyn Plus request a DHCP lease (MAC prefix `28:F5:37`), the integration verifies the device's identity over the local API and stores its IP automatically — including after the device's IP changes.
2. **Manual:** enter the device's IP in **Configure → Local IP for …**. The integration verifies the address answers as *that* Phyn device before saving.

A DHCP reservation for the Phyn Plus in your router is recommended. Local access is verified on PP2 hardware (firmware 4.9.x); PP1 owners are welcome to try it and report results. PW1 water sensor pucks have no local interface (battery devices — cloud only), but their cloud push subscription delivers leak events within seconds. Full research notes: [LOCAL_ACCESS.md](LOCAL_ACCESS.md).

To check which of your devices answer locally, run the bundled probe from any machine on the same network (requires only Python 3.11+):

```bash
python3 scripts/jnap_probe.py 192.168.1.24 192.168.1.25 <other-ips...>
```

It reports device identity, valve state, and live telemetry for every IP that speaks Phyn's local protocol, without changing any device state.

# Actions (services)

| Action | Description |
|---|---|
| `phyn.leak_test` | Start an on-demand leak (health) test on the targeted Phyn Plus. Field `extended: true` runs the longer test. Supports response data. |
| `phyn.pause_autoshutoff` | Temporarily disable automatic shutoff (30 s / 1 h / 6 h / 24 h / until re-enabled) — e.g. while filling a pool or running irrigation. |
| `phyn.mark_alert_read` | Mark a Phyn alert as read in the Phyn app after an automation has handled it. The alert ID comes with each Alert event. |

All actions accept normal Home Assistant targets (entity, device, or area) where applicable.

# Automation blueprints

Ready-made blueprints live in [`blueprints/automation/phyn/`](blueprints/automation/phyn/). Import them via **Settings → Automations & scenes → Blueprints → Import blueprint** using the buttons below:

| Blueprint | Import |
|---|---|
| **Water leak response** — close the valve and notify when any leak/moisture sensor trips | [![Open your Home Assistant instance and show the blueprint import dialog with a specific blueprint pre-filled.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Ftrooperthorn%2Fha_int_phyn%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fphyn%2Fwater_leak_response.yaml) |
| **Freeze protection** — act on low temperature from any sensor (e.g. a Davis WeatherLink outdoor sensor) or Phyn freeze alerts | [![Open your Home Assistant instance and show the blueprint import dialog with a specific blueprint pre-filled.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Ftrooperthorn%2Fha_int_phyn%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fphyn%2Ffreeze_protection.yaml) |
| **Prolonged water running** — alert when water has been flowing continuously too long | [![Open your Home Assistant instance and show the blueprint import dialog with a specific blueprint pre-filled.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Ftrooperthorn%2Fha_int_phyn%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fphyn%2Fprolonged_water_running.yaml) |
| **Livestock water supply watch** — alert when a supply line animals depend on has had no flow for too long (optionally gated to freezing weather) | [![Open your Home Assistant instance and show the blueprint import dialog with a specific blueprint pre-filled.](https://my.home-assistant.io/badges/blueprint_import.svg)](https://my.home-assistant.io/redirect/blueprint_import/?blueprint_url=https%3A%2F%2Fgithub.com%2Ftrooperthorn%2Fha_int_phyn%2Fblob%2Fmain%2Fblueprints%2Fautomation%2Fphyn%2Flivestock_water_watch.yaml) |

# Sensor states after a restart

A few Phyn Plus entities are fed by the **realtime feed** (cloud push or local polling), not the periodic cloud poll:

- **Total Water Usage**, **Current water flow rate**, and **Water Flowing** show `unknown` after a Home Assistant restart until the first realtime update arrives — Phyn typically pushes one as soon as water actually moves. Configuring a **local IP** for the device (see above) removes this gap entirely: local polling fills them within ~10 seconds of startup and keeps them fresh even with no water running.
- The **Alert** event entity showing `unknown` is normal Home Assistant behavior: an event entity's state is the timestamp of the last event it fired, so it stays `unknown` until the first alert after a restart. Automations triggering on it work regardless.

# Diagnostics

Every Phyn device exposes diagnostic entities (Online, Local Connection when configured, Signal Strength, Last Leak Test / Last Reading timestamps), and the integration supports Home Assistant's **Download diagnostics** (Settings → Devices & services → Phyn → ⋮ → Download diagnostics) with credentials and location data redacted.

# Translations

[![Translation status](https://hosted.weblate.org/widget/homeassistant-phyn/homeassistant-phyn/svg-badge.svg)](https://hosted.weblate.org/engage/homeassistant-phyn/)

Translations for this integration are managed with [Weblate](https://weblate.org/), a
libre web-based continuous localization platform. Weblate generously provides free
hosting for this project under its [Libre plan](https://weblate.org/hosting/).

Want to help translate Phyn into your language? No GitHub account or coding required —
just head to the [Phyn project on Hosted Weblate](https://hosted.weblate.org/engage/homeassistant-phyn/)
and start translating. Contributions are batched into pull requests automatically.

[![Translation status](https://hosted.weblate.org/widget/homeassistant-phyn/homeassistant-phyn/multi-auto.svg)](https://hosted.weblate.org/engage/homeassistant-phyn/)

For contributors: `strings.json` is the source of truth for the integration's English
strings (config flow, entity names, service names) and may reference Home Assistant's
shared strings via `[%key:...%]`. `translations/en.json` is the literal-English template
Weblate translates from — it's generated, not hand-edited. After changing `strings.json`,
regenerate it with:

```
python3 scripts/sync_translations.py
```

CI runs `scripts/sync_translations.py --check` to make sure the two never drift. The
other `translations/*.json` files are owned by Weblate; hand edits to them get
overwritten on the next Weblate sync.

# Tracking usage since a date (e.g. cistern fills)

If you draw water from a cistern (or any fixed-capacity tank) and need to know how much has been used since the last fill — so you can trigger a "refill needed" notification — you can do this entirely with built-in Home Assistant helpers. No extra integration code is required.

## Which sensor to use

**Phyn Plus (PP1/PP2) devices** expose a **"Total Water Usage"** sensor
(`sensor.<device>_total_water_usage`) that is a cumulative, ever-increasing meter sourced
from the device's real-time MQTT feed. This is the best source for this use-case.

**Phyn Classic (PC1) devices** do not have a cumulative meter; use the **"Daily water usage"**
sensor (`sensor.<device>_daily_consumption`) instead. The `utility_meter` will accumulate
daily totals across days without resetting automatically.

## Step 1 — Create a utility_meter helper

Add the following to your `configuration.yaml` (adjust the `source` entity ID to match
your actual device):

```yaml
utility_meter:
  cistern_usage_since_fill:
    source: sensor.phyn_total_water_usage   # adjust to your entity id
    # No "cycle:" key → meter accumulates indefinitely until manually reset
```

Restart Home Assistant. A new sensor `sensor.cistern_usage_since_fill` will appear,
showing gallons used since the meter was last reset.

> **Tip:** Find your exact entity ID in **Settings → Devices & services → Phyn → entities**.

## Step 2 — Record the fill date (optional)

Create an **Input Datetime** helper to log when each fill happened
(**Settings → Devices & services → Helpers → + Create helper → Date and/or time**),
e.g. named `Cistern fill date` → entity `input_datetime.cistern_fill_date`.

## Step 3 — Reset the meter on each fill

When you refill the cistern, reset the `utility_meter` via **Developer Tools → Actions**:

| Field | Value |
|-------|-------|
| Action | `utility_meter.reset` |
| Targets (entity) | `sensor.cistern_usage_since_fill` |

Or, in an automation triggered by a dashboard button, a physical button helper, etc.:

```yaml
action:
  - service: utility_meter.reset
    target:
      entity_id: sensor.cistern_usage_since_fill
  - service: input_datetime.set_datetime
    target:
      entity_id: input_datetime.cistern_fill_date
    data:
      datetime: "{{ now().isoformat() }}"
```

## Step 4 — Automate the refill alert

```yaml
automation:
  - alias: "Cistern refill needed"
    trigger:
      - platform: numeric_state
        entity_id: sensor.cistern_usage_since_fill
        above: 900        # gallons used since fill; adjust to your cistern capacity
    action:
      - service: notify.notify
        data:
          title: "Cistern refill needed"
          message: >
            {{ states('sensor.cistern_usage_since_fill') }} gal used since the
            last fill on {{ states('input_datetime.cistern_fill_date') }}.
```

For longer-term trends, the **"Daily water usage"** sensor is already compatible with the
Home Assistant **Energy / Water** dashboard.

**Further reading:**
- [utility_meter integration](https://www.home-assistant.io/integrations/utility_meter/)
- [input_datetime integration](https://www.home-assistant.io/integrations/input_datetime/)

# Viewing PW1 environmental history (temperature / humidity / battery)

The PW1 water sensor imports authoritative hourly statistics (mean, min, max) for
its Air Temperature, Humidity, and Battery sensors directly from the Phyn cloud API.
These statistics are stored under external `phyn:` statistic IDs, separate from the
sensors' own recorder-compiled statistics, so the two never conflict.

The standard more-info popup graph for each sensor shows the recorder's short-term
history. To view the richer Phyn-imported hourly history, use a **Statistics Graph
card** and point it at the `phyn:` statistic IDs. You can find the exact IDs for your
device in **Developer Tools → Statistics**; they follow the pattern
`phyn:<device_id>_<metric>` (e.g. `phyn:deviceid_humidity`).

```yaml
type: statistics-graph
title: PW1 Environmental History (Phyn API)
entities:
  - phyn:<your_device_id>_air_temperature
  - phyn:<your_device_id>_humidity
  - phyn:<your_device_id>_battery
stat_types:
  - mean
  - min
  - max
period: hour
```

Replace `<your_device_id>` with your device's ID slug from **Developer Tools →
Statistics**.

# Known Issues

* Phyn home name (in the Phyn App > Settings > Home > Address > Home Name) cannot be set to "Home" or integration configuration and setup will fail.

* If get an (API) error when trying to first initialize saying "User Not Found" then take note that Phyn username e-mail address is case sensitive.

## Developer note

The base entity classes have been consolidated into a single canonical location: `custom_components/phyn/entities/base.py`. The legacy `custom_components/phyn/entity.py` file has been completely removed to eliminate duplicate class definitions. If you maintain local forks or external code that imports from the old path, please update imports to use `..entities.base` (for internal package imports) or `custom_components.phyn.entities.base` as appropriate.

## Development and Testing

This integration includes automated tests to ensure quality and reliability.

### Running Tests Locally

```bash
# Install test dependencies
pip install -r requirements_test.txt

# Run all tests
pytest tests/

# Run with coverage report
pytest tests/ --cov=custom_components.phyn --cov-report=term-missing -v

# Run specific test file
pytest tests/test_config_flow_helpers.py -v
```

### Continuous Integration

Tests run automatically on every pull request via GitHub Actions. The test suite validates:
- Config flow (user setup, authentication, error handling)
- Integration setup and teardown
- Configuration migration
- Reauth and reconfigure flows

This ensures compatibility with Home Assistant 2026.6.4+ and helps maintain Bronze tier quality standards.
