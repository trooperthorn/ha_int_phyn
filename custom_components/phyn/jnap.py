"""Minimal local JNAP client for Phyn Plus devices.

The Phyn Plus (verified on PP2 firmware 4.9.x) runs a lighttpd server on TCP
port 80 speaking JNAP — the JSON-over-HTTP protocol Belkin/Linksys and Uponor
devices share. Every call is ``POST /JNAP/`` with the operation selected by
the ``X-JNAP-Action`` header, authorized with the device's static
``admin:admin`` credentials. See LOCAL_ACCESS.md for the protocol research.

The firmware's HTTP layer is buggy: on fw 4.9.0.23 and 4.9.5.4 the
``attribute/get`` response contains a stray debug line inside the headers
(``GetDataFromDaemon: Thread N calling WASP_Init``) and a pipelined second
``200 OK`` response with body ``{}`` after the declared ``Content-Length``
body. Strict HTTP clients (aiohttp) reject this, so this module speaks raw
TCP: it accumulates the response until ``Content-Length`` bytes of body have
arrived (``attribute/get`` is ~11 KB and spans several TCP segments), parses
headers tolerantly, and ignores any trailing garbage.

This module is deliberately dependency-free and does no Home Assistant
imports beyond logging, so it can be unit tested standalone.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
from typing import Any

_LOGGER = logging.getLogger(__name__)

JNAP_PORT = 80
JNAP_PATH = "/JNAP/"
#: Static credentials baked into the firmware.
JNAP_AUTH = base64.b64encode(b"admin:admin").decode()

ACTION_GET_DEVICE_INFO = "http://phyn.com/jnap/core/GetDeviceInfo"
ACTION_GET_ATTRIBUTES = "http://phyn.com/jnap/attribute/get"
ACTION_GET_VALVE_STATE = "http://phyn.com/jnap/shutoff/GetShutoffValveState"
ACTION_SET_VALVE_STATE = "http://phyn.com/jnap/shutoff/SetShutoffValveState"
ACTION_REBOOT = "http://phyn.com/jnap/core/Reboot"

DEFAULT_TIMEOUT = 10
#: Upper bound on a single response; attribute/get is ~11 KB.
MAX_RESPONSE_BYTES = 1024 * 1024
#: Per-read chunk size.
READ_CHUNK = 65536


class JnapError(Exception):
    """Base error for JNAP communication problems."""


class JnapConnectionError(JnapError):
    """The device could not be reached or the connection failed."""


class JnapProtocolError(JnapError):
    """The device answered, but not with a valid/successful JNAP response."""


def build_request(host: str, action: str, payload: dict | None = None) -> bytes:
    """Build the raw HTTP request bytes for a JNAP call."""
    body = json.dumps(payload or {}).encode()
    headers = (
        f"POST {JNAP_PATH} HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        f"X-JNAP-Authorization: Basic {JNAP_AUTH}\r\n"
        f"X-JNAP-Action: {action}\r\n"
        "Content-Type: application/json\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Connection: close\r\n"
        "\r\n"
    )
    return headers.encode() + body


def _parse_content_length(header_block: bytes) -> int | None:
    """Return the Content-Length from a raw header block, tolerating junk lines.

    The firmware's debug line is LF-terminated, so after splitting on CRLF it
    may be glued to the following header; Content-Length is always on its own
    CRLF line, so a plain ``name: value`` partition per line is sufficient.
    """
    for line in header_block.decode(errors="replace").split("\r\n"):
        name, sep, value = line.partition(":")
        if sep and name.strip().lower() == "content-length":
            with contextlib.suppress(ValueError):
                return int(value.strip())
    return None


async def _read_response(
    reader: asyncio.StreamReader, limit: int = MAX_RESPONSE_BYTES
) -> bytes:
    """Read exactly one HTTP response: headers plus ``Content-Length`` of body.

    ``StreamReader.read(n)`` returns as soon as *any* data is available, not at
    EOF, so a single call only ever yielded the first TCP segment of the ~11 KB
    ``attribute/get`` body — the root cause of the intermittent
    "Could not parse JNAP JSON body" failures. Accumulate until the declared
    body is complete; fall back to EOF (or *limit*) when Content-Length is
    missing. Stopping at Content-Length also means we never wait on the
    firmware's pipelined second response or on a connection it forgets to
    close.
    """
    raw = b""
    body_start = -1
    content_length: int | None = None
    while len(raw) < limit:
        chunk = await reader.read(READ_CHUNK)
        if not chunk:
            break
        raw += chunk
        if body_start == -1:
            header_end = raw.find(b"\r\n\r\n")
            if header_end == -1:
                continue
            body_start = header_end + 4
            content_length = _parse_content_length(raw[:header_end])
        if content_length is not None and len(raw) >= body_start + content_length:
            break
    return raw


def parse_response(raw: bytes) -> dict[str, Any]:
    """Parse a (possibly malformed) JNAP HTTP response into the result dict.

    Tolerates the firmware quirks: non-header debug lines mixed into the
    header block and pipelined trailing data after the declared body length.

    Returns the call's payload: the ``output`` object when the action wraps
    its result in one (``core/GetDeviceInfo``, ``shutoff/*``), otherwise every
    top-level key except ``result`` (``attribute/get`` returns ``system``,
    ``product`` and ``stats`` at the top level).

    Raises JnapProtocolError when no usable JSON body can be extracted or the
    JNAP ``result`` is not ``OK``.
    """
    header_end = raw.find(b"\r\n\r\n")
    if header_end == -1:
        raise JnapProtocolError("No HTTP header terminator in response")

    header_block = raw[:header_end]
    status_line = header_block.decode(errors="replace").split("\r\n", 1)[0]
    if " 200 " not in f"{status_line} " and not status_line.endswith(" 200"):
        raise JnapProtocolError(f"Unexpected HTTP status: {status_line!r}")

    content_length = _parse_content_length(header_block)

    body_start = header_end + 4
    if content_length is not None:
        body = raw[body_start : body_start + content_length]
    else:
        body = raw[body_start:]

    try:
        data = json.loads(body.decode(errors="replace"))
    except (json.JSONDecodeError, UnicodeDecodeError) as err:
        # Last resort: extract the first balanced JSON object from the body
        # region (guards against a pipelined second response or trailing junk
        # when Content-Length was missing or wrong).
        data = _extract_first_json_object(raw[body_start:])
        if data is None:
            raise JnapProtocolError("Could not parse JNAP JSON body") from err

    if not isinstance(data, dict):
        raise JnapProtocolError(f"Unexpected JNAP body type: {type(data).__name__}")
    result = data.get("result")
    if result != "OK":
        raise JnapProtocolError(f"JNAP call failed: {result}")

    output = data.get("output")
    if isinstance(output, dict):
        return output
    # attribute/get puts its sections at the top level alongside "result".
    return {key: value for key, value in data.items() if key != "result"}


def _extract_first_json_object(buf: bytes) -> dict | None:
    """Extract the first balanced top-level JSON object from *buf*."""
    text = buf.decode(errors="replace")
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    parsed = json.loads(text[start : index + 1])
                except json.JSONDecodeError:
                    return None
                return parsed if isinstance(parsed, dict) else None
    return None


class JnapClient:
    """Raw-TCP JNAP client for one Phyn Plus device."""

    def __init__(self, host: str, timeout: float = DEFAULT_TIMEOUT) -> None:
        """Initialize the client for *host*."""
        self._host = host
        self._timeout = timeout

    @property
    def host(self) -> str:
        """Return the configured host."""
        return self._host

    async def _request(self, action: str, payload: dict | None = None) -> dict[str, Any]:
        """Perform one JNAP call and return its payload dict."""
        try:
            async with asyncio.timeout(self._timeout):
                reader, writer = await asyncio.open_connection(self._host, JNAP_PORT)
                try:
                    writer.write(build_request(self._host, action, payload))
                    await writer.drain()
                    raw = await _read_response(reader)
                finally:
                    writer.close()
                    with contextlib.suppress(OSError):
                        await writer.wait_closed()
        except (OSError, TimeoutError) as err:
            raise JnapConnectionError(f"Cannot reach {self._host}: {err}") from err

        return parse_response(raw)

    async def get_device_info(self) -> dict[str, Any]:
        """Return the device identity (deviceID, serialNumber, firmwareVersion...)."""
        return await self._request(ACTION_GET_DEVICE_INFO)

    async def get_attributes(self) -> dict[str, Any]:
        """Return the full telemetry dump ({system, product, stats}).

        The body MUST be empty ``{}`` — the firmware rejects any filter.
        """
        return await self._request(ACTION_GET_ATTRIBUTES)

    async def get_valve_state(self) -> str | None:
        """Return the raw valve state string (e.g. ``Open``)."""
        output = await self._request(ACTION_GET_VALVE_STATE)
        return output.get("state")

    async def set_valve_state(self, open_valve: bool) -> None:
        """Actuate the shutoff valve."""
        await self._request(
            ACTION_SET_VALVE_STATE, {"state": "Open" if open_valve else "Close"}
        )

    async def reboot(self) -> None:
        """Reboot the device (``device_reboot_reason`` becomes ``jnap_reboot``).

        The device drops off the network for 1–2 minutes; kinesisd returns to
        ``uploading`` within ~5–7 minutes.
        """
        await self._request(ACTION_REBOOT)


def normalize_mac(value: str) -> str:
    """Normalize a MAC/device id to lowercase hex without separators."""
    return "".join(ch for ch in value.lower() if ch in "0123456789abcdef")


async def async_verify_device(host: str, expected_device_id: str | None = None) -> dict[str, Any]:
    """Probe *host* for a Phyn JNAP endpoint and optionally match identity.

    Returns the GetDeviceInfo output on success. Raises JnapConnectionError /
    JnapProtocolError on failure, or JnapProtocolError when the responding
    device is not the expected one (guards against the shared 28:F5:37 OUI
    block matching non-Phyn hardware).
    """
    client = JnapClient(host)
    info = await client.get_device_info()
    if expected_device_id:
        reported = normalize_mac(str(info.get("deviceID", "")))
        expected = normalize_mac(expected_device_id)
        if not reported or reported != expected:
            raise JnapProtocolError(
                f"Device at {host} reports id {info.get('deviceID')!r}, "
                f"expected {expected_device_id!r}"
            )
    return info
