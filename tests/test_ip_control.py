"""Samsung IP Control client (ip_control.py): the JSON-RPC envelopes, the error mapping, and the token kept
out of exceptions, reprs and logs. No network: http.client.HTTPSConnection is replaced."""

from __future__ import annotations

import json
import logging
import ssl

import pytest

from custom_components.frame_art_shuffler import ip_control
from custom_components.frame_art_shuffler.ip_control import (
    PAIR_TIMEOUT,
    IPControlAuthError,
    IPControlClient,
    IPControlProtocolError,
    IPControlTransportError,
    IPControlUnavailableError,
)

TOKEN = "tok-5f1d2c9e77"
HOST = "192.0.2.30"


class FakeResponse:
    def __init__(self, body: bytes | dict, status: int = 200) -> None:
        self.status = status
        self.body = json.dumps(body).encode() if isinstance(body, dict) else body

    def read(self, amount: int = -1) -> bytes:
        return self.body if amount < 0 else self.body[:amount]


class FakeConnection:
    """One HTTPS connection to the TV; the test sets the reply (or the error) before the call."""

    made: list["FakeConnection"] = []
    reply: FakeResponse | None = None
    error: Exception | None = None

    def __init__(self, host, port, timeout=None, context=None) -> None:
        self.host, self.port, self.timeout, self.context = host, port, timeout, context
        self.sent: list[tuple[str, str, dict, dict]] = []
        self.closed = False
        FakeConnection.made.append(self)

    def request(self, method, path, body=None, headers=None) -> None:
        if FakeConnection.error is not None:
            raise FakeConnection.error
        self.sent.append((method, path, json.loads(body), headers))

    def getresponse(self) -> FakeResponse:
        assert FakeConnection.reply is not None
        return FakeConnection.reply

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def tv(monkeypatch):
    FakeConnection.made = []
    FakeConnection.reply = FakeResponse({"jsonrpc": "2.0", "id": "1", "result": {"power": "powerOn"}})
    FakeConnection.error = None
    monkeypatch.setattr(ip_control.http.client, "HTTPSConnection", FakeConnection)
    return FakeConnection


def _only_request(tv) -> tuple[str, str, dict, dict]:
    assert len(tv.made) == 1 and len(tv.made[0].sent) == 1
    return tv.made[0].sent[0]


def test_pair_asks_for_a_token_without_params_and_waits_long(tv):
    tv.reply = FakeResponse({"jsonrpc": "2.0", "id": "1", "result": {"AccessToken": TOKEN}})
    client = IPControlClient(HOST)
    assert client.pair() == TOKEN
    method, path, body, headers = _only_request(tv)
    assert (method, path) == ("POST", "/")
    assert body == {"jsonrpc": "2.0", "id": 1, "method": "createAccessToken"}
    assert headers["Content-Type"] == "application/json" and headers["Accept"] == "application/json"
    conn = tv.made[0]
    assert (conn.host, conn.port, conn.timeout) == (HOST, 1516, PAIR_TIMEOUT)
    assert conn.context.verify_mode == ssl.CERT_NONE and conn.context.check_hostname is False
    assert conn.closed
    assert "paired=True" in repr(client) and TOKEN not in repr(client)


def test_power_read_and_commands_carry_the_token(tv):
    client = IPControlClient(HOST, TOKEN)
    assert client.power_state() == "powerOn"
    assert _only_request(tv)[2] == {
        "jsonrpc": "2.0", "id": 1, "method": "powerControl", "params": {"AccessToken": TOKEN},
    }
    tv.made.clear()
    tv.reply = FakeResponse({"jsonrpc": "2.0", "id": "1", "result": {"power": "powerOff"}})
    client.power_off()
    assert _only_request(tv)[2]["params"] == {"AccessToken": TOKEN, "power": "powerOff"}
    tv.made.clear()
    client.power_on()
    assert _only_request(tv)[2]["params"] == {"AccessToken": TOKEN, "power": "powerOn"}
    assert tv.made[0].timeout == ip_control.COMMAND_TIMEOUT


def test_an_unpaired_client_never_calls_the_tv(tv):
    with pytest.raises(IPControlAuthError):
        IPControlClient(HOST).power_off()
    assert tv.made == []


@pytest.mark.parametrize(
    "reply",
    [
        {"code": -32700, "message": "Parse error"},  # the flat envelope a 2026 Frame answers a stale token with
        {"jsonrpc": "2.0", "id": "1", "error": {"code": -32700, "message": "Parse error"}},
        {"jsonrpc": "2.0", "id": "1", "error": {"code": -32010, "message": "Unauthorized"}},
    ],
)
def test_a_rejected_token_is_an_auth_error(tv, reply):
    tv.reply = FakeResponse(reply)
    with pytest.raises(IPControlAuthError) as caught:
        IPControlClient(HOST, TOKEN).power_state()
    assert TOKEN not in str(caught.value)


@pytest.mark.parametrize("code", [-32601, -32002])
def test_refused_in_the_current_state_is_unavailable(tv, code):
    tv.reply = FakeResponse({"jsonrpc": "2.0", "id": "1", "error": {"code": code, "message": "x"}})
    with pytest.raises(IPControlUnavailableError):
        IPControlClient(HOST, TOKEN).power_off()


def test_a_parse_error_while_pairing_is_a_protocol_error(tv):
    """No token was sent, so -32700 cannot mean a stale token."""
    tv.reply = FakeResponse({"code": -32700, "message": "Parse error"})
    with pytest.raises(IPControlProtocolError):
        IPControlClient(HOST).pair()


@pytest.mark.parametrize(
    "error",
    [ConnectionRefusedError(111, "refused"), TimeoutError("timed out"), ssl.SSLError("handshake"), OSError(113, "no route")],
)
def test_no_answer_is_a_transport_error(tv, error, caplog):
    tv.error = error
    caplog.set_level(logging.DEBUG)
    with pytest.raises(IPControlTransportError) as caught:
        IPControlClient(HOST, TOKEN).power_on()
    assert TOKEN not in str(caught.value) and TOKEN not in caplog.text
    assert tv.made[0].closed


@pytest.mark.parametrize(
    "reply",
    [
        FakeResponse(b"<html>busy</html>"),
        FakeResponse(b"[1, 2]"),
        FakeResponse({"jsonrpc": "2.0", "id": "1"}),
        FakeResponse({"jsonrpc": "2.0", "id": "1", "result": {"power": "sleeping"}}),
        FakeResponse({"jsonrpc": "2.0"}, status=500),
        FakeResponse(b"x" * (ip_control.MAX_RESPONSE_BYTES + 10)),
    ],
)
def test_an_unexpected_reply_is_a_protocol_error(tv, reply):
    tv.reply = reply
    with pytest.raises(IPControlProtocolError) as caught:
        IPControlClient(HOST, TOKEN).power_state()
    assert TOKEN not in str(caught.value)


def test_pairing_without_a_token_in_the_reply_fails(tv):
    tv.reply = FakeResponse({"jsonrpc": "2.0", "id": "1", "result": {}})
    with pytest.raises(IPControlProtocolError):
        IPControlClient(HOST).pair()
