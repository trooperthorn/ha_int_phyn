#!/usr/bin/env python3
"""Probe LAN IPs for the Phyn JNAP local API.

Run this from any machine on the SAME network as your Phyn devices:

    python3 scripts/jnap_probe.py 192.168.1.24 192.168.1.25
    python3 scripts/jnap_probe.py --full 192.168.1.30   # dump all attributes

For each address it reports whether a Phyn JNAP endpoint answers on TCP port
80, the device identity (model, firmware, MAC), the shutoff valve state, and
a summary of live telemetry. It never changes any device state.

Expected results by device type (see LOCAL_ACCESS.md):
  - Phyn Plus (PP2, fw 4.9.x): answers with full telemetry.
  - Phyn Plus (PP1): unknown — please report your result!
  - Phyn Smart Water Sensor (PW1) pucks: NO local API — these are battery
    devices that only talk to the Phyn cloud, even while awake. A probe of a
    PW1's IP is expected to time out or refuse the connection.

Requires only Python 3.11+ (stdlib). No Home Assistant needed.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import sys
from pathlib import Path

_JNAP_PATH = (
    Path(__file__).resolve().parent.parent
    / "custom_components"
    / "phyn"
    / "jnap.py"
)
_spec = importlib.util.spec_from_file_location("phyn_jnap", _JNAP_PATH)
jnap = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(jnap)

TELEMETRY_FIELDS = [
    ("product", "sensor_pressure_1", "Water pressure (PSI)"),
    ("product", "sensor_temperature_1", "Water temperature (F)"),
    ("product", "sensor_flow", "Flow rate (GPM)"),
    ("product", "sensor_flow_state", "Flow state"),
    ("product", "sov_state_str", "Valve state"),
    ("product", "consumption_total", "Total consumption (gal)"),
    ("product", "alert_notifier_fp_state_str", "Leak notifier state"),
    ("stats", "wifi_sta_rssi", "WiFi RSSI (dBm)"),
    ("stats", "device_up_time_sec", "Uptime (s)"),
]


async def probe(host: str, timeout: float, full: bool) -> bool:
    """Probe one host; return True when a Phyn JNAP endpoint answered."""
    print(f"\n=== {host} ===")
    client = jnap.JnapClient(host, timeout=timeout)

    try:
        info = await client.get_device_info()
    except jnap.JnapConnectionError as err:
        print(f"  No JNAP endpoint: {err}")
        print(
            "  (Expected for PW1 water sensor pucks — they have no local API. "
            "For a Phyn Plus, check the IP and that you are on the same VLAN.)"
        )
        return False
    except jnap.JnapProtocolError as err:
        print(f"  Something answered on port 80, but not Phyn JNAP: {err}")
        return False

    print("  Phyn JNAP endpoint FOUND:")
    for key in ("deviceName", "productCode", "deviceID", "serialNumber", "firmwareVersion"):
        if key in info:
            print(f"    {key}: {info[key]}")

    try:
        valve = await client.get_valve_state()
        print(f"    Shutoff valve: {valve}")
    except jnap.JnapError as err:
        print(f"    Shutoff valve: query failed ({err})")

    try:
        attrs = await client.get_attributes()
    except jnap.JnapError as err:
        print(f"    Telemetry: query failed ({err})")
        return True

    if full:
        print(json.dumps(attrs, indent=2, sort_keys=True))
        return True

    print("  Telemetry:")
    for section, key, label in TELEMETRY_FIELDS:
        value = attrs.get(section, {}).get(key)
        if value is not None:
            print(f"    {label}: {value}")
    return True


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("hosts", nargs="+", help="IP addresses to probe")
    parser.add_argument("--timeout", type=float, default=5.0, help="per-call timeout (s)")
    parser.add_argument("--full", action="store_true", help="dump the full attribute JSON")
    args = parser.parse_args()

    results = {}
    for host in args.hosts:
        results[host] = await probe(host, args.timeout, args.full)

    print("\n=== Summary ===")
    for host, found in results.items():
        print(f"  {host}: {'Phyn JNAP local API available' if found else 'no local API'}")
    return 0 if any(results.values()) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
