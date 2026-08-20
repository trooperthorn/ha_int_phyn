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
