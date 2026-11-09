"""Unit tests for the local JNAP client's request building and parsing.

These are pure unit tests — no Home Assistant harness required.
"""
import importlib.util
import json
from pathlib import Path

import pytest

# Load jnap.py directly by path: importing it through the package would pull
# in Home Assistant, which pure unit tests must not require.
_JNAP_PATH = (
    Path(__file__).parent.parent / "custom_components" / "phyn" / "jnap.py"
)
_spec = importlib.util.spec_from_file_location("phyn_jnap", _JNAP_PATH)
jnap = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(jnap)

JnapProtocolError = jnap.JnapProtocolError
build_request = jnap.build_request
normalize_mac = jnap.normalize_mac
parse_response = jnap.parse_response


def _http(body: bytes, *, extra_headers: str = "", content_length: int | None = None) -> bytes:
    length = len(body) if content_length is None else content_length
    return (
        f"HTTP/1.1 200 OK\r\n"
        f"Content-Type: application/json\r\n"
        f"{extra_headers}"
        f"Content-Length: {length}\r\n"
        f"\r\n"
    ).encode() + body


def test_build_request_contains_action_and_auth():
    raw = build_request("192.168.1.50", "http://phyn.com/jnap/core/GetDeviceInfo")
    text = raw.decode()
    assert text.startswith("POST /JNAP/ HTTP/1.1\r\n")
    assert "X-JNAP-Action: http://phyn.com/jnap/core/GetDeviceInfo\r\n" in text
    assert "X-JNAP-Authorization: Basic YWRtaW46YWRtaW4=\r\n" in text
    assert text.endswith("\r\n\r\n{}")


def test_build_request_payload_length():
    payload = {"state": "Open"}
    raw = build_request("h", "a", payload)
    body = raw.split(b"\r\n\r\n", 1)[1]
    assert json.loads(body) == payload
    assert f"Content-Length: {len(body)}".encode() in raw


def test_parse_clean_response():
    body = json.dumps({"result": "OK", "output": {"state": "Open"}}).encode()
    assert parse_response(_http(body)) == {"state": "Open"}


def test_parse_malformed_firmware_response():
    """fw 4.9.0.23: debug line in headers + pipelined second response."""
    body = json.dumps({"result": "OK", "output": {"product": {"sensor_flow": 0.0}}}).encode()
    raw = _http(
        body,
        extra_headers="GetDataFromDaemon: Thread 25736 calling WASP_Init\r\n",
    )
    # Pipelined trailing junk after the declared Content-Length body.
    raw += b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}"
    assert parse_response(raw) == {"product": {"sensor_flow": 0.0}}


def test_parse_response_without_content_length_and_trailing_junk():
    body = json.dumps({"result": "OK", "output": {"a": 1}}).encode()
    raw = b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n" + body + b"\r\ngarbage"
    assert parse_response(raw) == {"a": 1}


def test_parse_error_result_raises():
    body = json.dumps({"result": "_ErrorInvalidInput"}).encode()
    with pytest.raises(JnapProtocolError):
        parse_response(_http(body))


def test_parse_non_200_raises():
    raw = b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n"
    with pytest.raises(JnapProtocolError):
        parse_response(raw)


def test_parse_garbage_raises():
    with pytest.raises(JnapProtocolError):
        parse_response(_http(b"not json at all"))


def test_normalize_mac():
    assert normalize_mac("28:F5:37:AB:CD:EF") == "28f537abcdef"
    assert normalize_mac("28f537abcdef") == "28f537abcdef"
    assert normalize_mac("28-F5-37-ab-cd-ef") == "28f537abcdef"


# --- fw 4.9.5.4: multi-segment responses and top-level attribute sections ---

_read_response = jnap._read_response
JnapClient = jnap.JnapClient


class _ChunkedReader:
    """Minimal StreamReader stand-in that yields *size*-byte chunks."""

    def __init__(self, data: bytes, size: int) -> None:
        self._data = data
        self._size = size
        self.reads = 0

    async def read(self, _n: int) -> bytes:
        self.reads += 1
        chunk, self._data = self._data[: self._size], self._data[self._size :]
        return chunk


def _attribute_dump_response() -> tuple[bytes, dict]:
    """A realistic attribute/get reply: debug line, large body, pipelined trailer."""
    sections = {
        "result": "OK",
        "system": {"fw_version": 40905004, "hw_product": "PP2"},
        "product": {"sov_state_str": "opened", "consumption_total": 1997.19, "pad": "x" * 6000},
        "stats": {"wifi_sta_rssi": -66},
    }
    body = json.dumps(sections).encode()
    raw = (
        b"HTTP/1.1 200 OK\r\n"
        b"GetDataFromDaemon: Thread 18188 calling WASP_Init\n"  # LF-terminated debug line
        b"Content-Type: application/json; charset=utf-8\r\n"
        b"Connection: close\r\n"
        + f"Content-Length: {len(body)}\r\n".encode()
        + b"Server: lighttpd/1.4.49\r\n\r\n"
        + body
        + b"\n\n\nHTTP/1.1 200 OK\r\nContent-Type: application/json; charset=utf-8\r\n"
        b"Connection: close\r\nContent-Length: 2\r\n\r\n{}"
    )
    expected = {k: v for k, v in sections.items() if k != "result"}
    return raw, expected


@pytest.mark.parametrize("chunk", [7, 100, 1460, 1 << 20])
async def test_read_response_accumulates_across_segments(chunk):
    """A single read() only returns the first TCP segment; we must keep reading."""
    raw, expected = _attribute_dump_response()
    reader = _ChunkedReader(raw, chunk)
    got = await _read_response(reader)
    assert parse_response(got) == expected


async def test_read_response_stops_at_content_length():
    """Do not wait for EOF / the pipelined trailer once the body is complete."""
    raw, _ = _attribute_dump_response()
    header_end = raw.find(b"\r\n\r\n") + 4
    body_len = int(raw.split(b"Content-Length: ")[1].split(b"\r\n")[0])
    reader = _ChunkedReader(raw, header_end + body_len)  # exactly headers+body
    got = await _read_response(reader)
    assert reader.reads == 1
    assert len(got) == header_end + body_len


async def test_read_response_without_content_length_reads_to_eof():
    body = json.dumps({"result": "OK", "output": {"a": 1}}).encode()
    raw = b"HTTP/1.1 200 OK\r\n\r\n" + body + b"\r\ngarbage"
    got = await _read_response(_ChunkedReader(raw, 5))
    assert got == raw
    assert parse_response(got) == {"a": 1}


def test_single_read_of_first_segment_fails_to_parse():
    """Regression guard: the pre-fix behaviour (first 1460 bytes) cannot parse."""
    raw, _ = _attribute_dump_response()
    with pytest.raises(JnapProtocolError):
        parse_response(raw[:1460])


def test_parse_returns_top_level_sections_without_output_wrapper():
    body = json.dumps({"result": "OK", "system": {"a": 1}, "product": {"b": 2}}).encode()
    assert parse_response(_http(body)) == {"system": {"a": 1}, "product": {"b": 2}}


def test_parse_prefers_output_wrapper_when_present():
    body = json.dumps({"result": "OK", "output": {"state": "Open"}, "noise": 1}).encode()
    assert parse_response(_http(body)) == {"state": "Open"}


def test_reboot_action_constant():
    assert jnap.ACTION_REBOOT == "http://phyn.com/jnap/core/Reboot"
    assert hasattr(JnapClient, "reboot")
