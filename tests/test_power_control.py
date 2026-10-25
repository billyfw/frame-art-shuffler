"""Power control per TV (0.5.0): the remote-keys path unchanged, the IP Control path, the token on disk.

Pure tests: the TV's REST state, its art channel, the WebSocket remote and the IP Control client are fakes,
and a fake clock stands in for the waits.
"""

from __future__ import annotations

import logging
import stat
from pathlib import Path

import pytest

from custom_components.frame_art_shuffler import frame_tv
from custom_components.frame_art_shuffler.const import POWER_CONTROL_IP_CONTROL, POWER_CONTROL_REMOTE_KEYS
from custom_components.frame_art_shuffler.ip_control import (
    IPControlAuthError,
    IPControlTransportError,
)
from custom_components.frame_art_shuffler.targets import power_control

IP = "192.0.2.40"
MAC = "aa:bb:cc:dd:ee:ff"
TOKEN = "tok-0c4f8e21aa"


class Clock:
    """time.monotonic and time.sleep for frame_tv: sleeping advances the clock."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class FakeIPClient:
    """Stands in for ip_control.IPControlClient; class attributes script the TV."""

    made: list["FakeIPClient"] = []
    power_on_errors: list[Exception] = []
    power_off_error: Exception | None = None
    pair_token: str | None = TOKEN

    def __init__(self, host, token=None, **_kwargs) -> None:
        self.host, self.token = host, token
        self.calls: list[str] = []
        FakeIPClient.made.append(self)

    def power_on(self) -> None:
        self.calls.append("power_on")
        if FakeIPClient.power_on_errors:
            raise FakeIPClient.power_on_errors.pop(0)

    def power_off(self) -> None:
        self.calls.append("power_off")
        if FakeIPClient.power_off_error:
            raise FakeIPClient.power_off_error

    def power_state(self) -> str:
        self.calls.append("power_state")
        return "powerOff"

    def pair(self, timeout=None) -> str:
        self.calls.append("pair")
        return FakeIPClient.pair_token


class NoIPClient:
    def __init__(self, *args, **kwargs) -> None:
        raise AssertionError("IP Control used on a remote-keys TV")


@pytest.fixture
def clock(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(frame_tv.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(frame_tv.time, "sleep", clock.sleep)
    return clock


@pytest.fixture
def tokens(monkeypatch, tmp_path) -> Path:
    monkeypatch.setattr(frame_tv, "TOKEN_DIR", tmp_path)
    return tmp_path


@pytest.fixture
def ip_client(monkeypatch):
    FakeIPClient.made = []
    FakeIPClient.power_on_errors = []
    FakeIPClient.power_off_error = None
    FakeIPClient.pair_token = TOKEN
    monkeypatch.setattr(frame_tv, "IPControlClient", FakeIPClient)
    return FakeIPClient


def _screen(monkeypatch, states):
    """is_screen_on answers from ``states`` in turn, then repeats the last one."""
    answers = list(states)

    def is_screen_on(ip, timeout=None):
        return answers.pop(0) if len(answers) > 1 else answers[0]

    monkeypatch.setattr(frame_tv, "is_screen_on", is_screen_on)


# --- the setting -----------------------------------------------------------------------------------


def test_power_control_is_explicit_with_a_default():
    assert power_control({}) == POWER_CONTROL_REMOTE_KEYS  # every TV set up before 0.5.0
    assert power_control(None) == POWER_CONTROL_REMOTE_KEYS
    assert power_control({"power_control": "ip_control"}) == POWER_CONTROL_IP_CONTROL
    assert power_control({"power_control": "remote_keys"}) == POWER_CONTROL_REMOTE_KEYS
    assert power_control({"power_control": "something-newer"}) == POWER_CONTROL_REMOTE_KEYS
    assert power_control({"kind": "tablet", "power_control": "ip_control"}) is None  # never contacted


# --- the token on disk ---------------------------------------------------------------------------------


def test_the_ip_control_token_sits_beside_the_websocket_token(tokens):
    frame_tv.save_ip_control_token(IP, TOKEN)
    path = tokens / "192_0_2_40.ipcontrol.token"
    assert path.read_text() == TOKEN
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not (tokens / "192_0_2_40.ipcontrol.token.tmp").exists()
    assert frame_tv.read_ip_control_token(IP) == TOKEN and frame_tv.has_ip_control_token(IP)
    frame_tv.save_ip_control_token(IP, "tok-second")  # a re-pair replaces it
    assert frame_tv.read_ip_control_token(IP) == "tok-second"


def test_deleting_a_tv_removes_both_tokens(tokens):
    (tokens / "192_0_2_40.token").write_text("12345678")
    frame_tv.save_ip_control_token(IP, TOKEN)
    frame_tv.delete_token(IP)
    assert list(tokens.iterdir()) == []


def test_no_token_reads_as_none(tokens):
    assert frame_tv.read_ip_control_token(IP) is None
    with pytest.raises(IPControlAuthError):
        frame_tv.check_ip_control(IP)


def test_pairing_stores_the_token(tokens, ip_client):
    frame_tv.pair_ip_control(IP)
    assert ip_client.made[0].calls == ["pair"]
    assert frame_tv.read_ip_control_token(IP) == TOKEN


# --- remote keys: unchanged --------------------------------------------------------------------------


def test_remote_keys_off_still_holds_the_power_key(monkeypatch, tokens, clock):
    held = []

    class FakeRemote:
        def open(self):
            pass

        def hold_key(self, key, seconds):
            held.append((key, seconds))

        def close(self):
            pass

    monkeypatch.setattr(frame_tv, "IPControlClient", NoIPClient)
    monkeypatch.setattr(frame_tv, "_build_client", lambda ip, path, timeout=None: FakeRemote())
    _screen(monkeypatch, [True])
    frame_tv.tv_off(IP)
    frame_tv.tv_off(IP, POWER_CONTROL_REMOTE_KEYS)
    assert held == [("KEY_POWER", 3), ("KEY_POWER", 3)]


def test_remote_keys_on_still_sends_two_wake_packets(monkeypatch, tokens, clock):
    sent = []
    monkeypatch.setattr(frame_tv, "IPControlClient", NoIPClient)
    monkeypatch.setattr(frame_tv, "_send_wake_on_lan", lambda mac: sent.append(mac))
    monkeypatch.setattr(frame_tv, "is_art_mode_enabled", lambda ip: True)
    _screen(monkeypatch, [True])
    assert frame_tv.tv_on(IP, MAC) is True
    assert sent == [MAC, MAC]
    assert clock.sleeps == [12, 3]


# --- IP Control -----------------------------------------------------------------------------------------


def test_ip_off_leaves_a_dark_tv_alone(monkeypatch, tokens, clock, ip_client):
    frame_tv.save_ip_control_token(IP, TOKEN)
    _screen(monkeypatch, [False])
    frame_tv.tv_off(IP, POWER_CONTROL_IP_CONTROL)
    assert ip_client.made == []


def test_ip_off_sends_power_off_and_waits_for_standby(monkeypatch, tokens, clock, ip_client, caplog):
    caplog.set_level(logging.INFO)
    frame_tv.save_ip_control_token(IP, TOKEN)
    _screen(monkeypatch, [True, True, True, False])
    frame_tv.tv_off(IP, POWER_CONTROL_IP_CONTROL)
    assert ip_client.made[0].token == TOKEN
    assert ip_client.made[0].calls == ["power_off"]
    assert "standby" in caplog.text and TOKEN not in caplog.text


def test_ip_off_warns_when_the_screen_stays_on(monkeypatch, tokens, clock, ip_client, caplog):
    frame_tv.save_ip_control_token(IP, TOKEN)
    _screen(monkeypatch, [True])
    frame_tv.tv_off(IP, POWER_CONTROL_IP_CONTROL)
    assert "still reports its screen on" in caplog.text


def test_ip_off_without_a_pairing_says_so(monkeypatch, tokens, clock, ip_client):
    _screen(monkeypatch, [True])
    with pytest.raises(frame_tv.FrameArtConnectionError, match="not paired"):
        frame_tv.tv_off(IP, POWER_CONTROL_IP_CONTROL)
    assert ip_client.made == []


def test_ip_off_with_a_rejected_key_asks_for_a_new_pairing(monkeypatch, tokens, clock, ip_client):
    frame_tv.save_ip_control_token(IP, TOKEN)
    ip_client.power_off_error = IPControlAuthError("rejected")
    _screen(monkeypatch, [True])
    with pytest.raises(frame_tv.FrameArtConnectionError, match="pair it again") as caught:
        frame_tv.tv_off(IP, POWER_CONTROL_IP_CONTROL)
    assert TOKEN not in str(caught.value)


def test_ip_on_keeps_trying_while_the_tv_settles_after_an_off(monkeypatch, tokens, clock, ip_client):
    """Right after a real off the TV once refused every port for 25 s to 2 min."""
    frame_tv.save_ip_control_token(IP, TOKEN)
    ip_client.power_on_errors = [IPControlTransportError("refused"), IPControlTransportError("refused")]
    _screen(monkeypatch, [False, False, True])
    art = iter([None, None, True])
    monkeypatch.setattr(frame_tv, "is_art_mode_enabled", lambda ip: next(art))
    assert frame_tv.tv_on(IP, None, POWER_CONTROL_IP_CONTROL) is True
    assert ip_client.made[0].calls == ["power_on", "power_on", "power_on"]
    assert clock.sleeps.count(frame_tv._IP_ON_RETRY_DELAY) == 2


def test_ip_on_gives_up_after_the_reach_window(monkeypatch, tokens, clock, ip_client):
    frame_tv.save_ip_control_token(IP, TOKEN)
    ip_client.power_on_errors = [IPControlTransportError("refused")] * 100
    _screen(monkeypatch, [False])
    with pytest.raises(frame_tv.FrameArtConnectionError, match="IP Remote"):
        frame_tv.tv_on(IP, None, POWER_CONTROL_IP_CONTROL)
    assert sum(clock.sleeps) >= frame_tv._IP_ON_REACH_SECONDS


def test_ip_on_with_a_rejected_key_stops_at_once(monkeypatch, tokens, clock, ip_client):
    frame_tv.save_ip_control_token(IP, TOKEN)
    ip_client.power_on_errors = [IPControlAuthError("rejected")]
    _screen(monkeypatch, [False])
    with pytest.raises(frame_tv.FrameArtConnectionError, match="pair it again"):
        frame_tv.tv_on(IP, None, POWER_CONTROL_IP_CONTROL)
    assert ip_client.made[0].calls == ["power_on"]


def test_ip_on_leaves_a_lit_tv_alone(monkeypatch, tokens, clock, ip_client):
    _screen(monkeypatch, [True])
    assert frame_tv.tv_on(IP, None, POWER_CONTROL_IP_CONTROL) is True
    assert ip_client.made == []


def test_ip_on_raises_when_the_screen_never_comes_on(monkeypatch, tokens, clock, ip_client):
    frame_tv.save_ip_control_token(IP, TOKEN)
    _screen(monkeypatch, [False])
    with pytest.raises(frame_tv.FrameArtConnectionError, match="did not come on"):
        frame_tv.tv_on(IP, None, POWER_CONTROL_IP_CONTROL)


def test_ip_on_warns_when_the_art_channel_stays_silent(monkeypatch, tokens, clock, ip_client, caplog):
    frame_tv.save_ip_control_token(IP, TOKEN)
    _screen(monkeypatch, [False, True])
    monkeypatch.setattr(frame_tv, "is_art_mode_enabled", lambda ip: None)
    assert frame_tv.tv_on(IP, None, POWER_CONTROL_IP_CONTROL) is True
    assert "art channel did not answer" in caplog.text
