"""Power control in Home Assistant (0.5.0): the options flow's choice and IP Control pairing, and the
services passing each TV's method. Runs inside Home Assistant 2026.9; no TV is contacted."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.frame_art_shuffler import frame_tv
from custom_components.frame_art_shuffler.const import DOMAIN
from custom_components.frame_art_shuffler.ip_control import IPControlTransportError

PKG = "custom_components.frame_art_shuffler"
TV_ID = "tv0001"
IP = "192.0.2.10"
MAC = "aa:bb:cc:dd:ee:ff"
TOKEN = "tok-9a7b3c11de"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


class FakeIPClient:
    """ip_control.IPControlClient as the flow sees it; class attributes script the TV."""

    made: list["FakeIPClient"] = []
    state_error: Exception | None = None
    pair_error: Exception | None = None
    accepted = threading.Event()  # set: someone accepted the prompt on the TV

    def __init__(self, host, token=None, **_kwargs) -> None:
        self.host, self.token = host, token
        self.calls: list[str] = []
        FakeIPClient.made.append(self)

    def power_state(self) -> str:
        self.calls.append("power_state")
        if FakeIPClient.state_error:
            raise FakeIPClient.state_error
        return "powerOn"

    def pair(self, timeout=None) -> str:
        self.calls.append("pair")
        assert FakeIPClient.accepted.wait(10), "nobody accepted the prompt in the test"
        if FakeIPClient.pair_error:
            raise FakeIPClient.pair_error
        return TOKEN

    @classmethod
    def all_calls(cls) -> list[str]:
        return [call for client in cls.made for call in client.calls]


@pytest.fixture
def tv_net():
    """Every TV network entry point the entry or the flow could reach, faked."""
    FakeIPClient.made = []
    FakeIPClient.state_error = None
    FakeIPClient.pair_error = None
    FakeIPClient.accepted = threading.Event()
    mocks = {
        "tv_on": MagicMock(return_value=True),
        "tv_off": MagicMock(return_value=None),
        "set_art_mode": MagicMock(return_value=None),
    }
    with patch(f"{PKG}.frame_tv.is_screen_on", MagicMock(return_value=False)), \
            patch(f"{PKG}.frame_tv.set_art_on_tv_deleteothers", MagicMock(side_effect=AssertionError("upload"))), \
            patch(f"{PKG}.shuffle.set_art_on_tv_deleteothers", MagicMock(side_effect=AssertionError("upload"))), \
            patch(f"{PKG}.frame_tv.IPControlClient", FakeIPClient), \
            patch(f"{PKG}.tv_on", mocks["tv_on"]), \
            patch(f"{PKG}.tv_off", mocks["tv_off"]), \
            patch(f"{PKG}.set_art_mode", mocks["set_art_mode"]), \
            patch(f"{PKG}.async_generate_dashboard", AsyncMock(return_value=False)):
        yield mocks


def _tv(**overrides) -> dict:
    tv = {
        "id": TV_ID, "name": "Office Frame", "short_name": "Office", "ip": IP, "mac": MAC,
        "selected_tagset": None, "shuffle_frequency_minutes": 60, "enable_auto_shuffle": False,
    }
    tv.update(overrides)
    return tv


async def _setup(hass: HomeAssistant, tmp_path: Path, tvs: dict) -> MockConfigEntry:
    root = tmp_path / "media" / "frame_art"
    (root / "library").mkdir(parents=True)
    metadata = root / "metadata.json"
    metadata.write_text(json.dumps({"version": "1.0", "images": {}, "tvs": [], "tags": []}))
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Frame Art Shuffler",
        data={"metadata_path": str(metadata), "token_dir": str(tmp_path / "tokens"), "tvs": tvs, "tagsets": {}},
        options={"library_sync_token": "kept"},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _edit_tv(hass: HomeAssistant, entry: MockConfigEntry, fields: dict) -> dict:
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"action": "edit_tv"})
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"tv_id": TV_ID})
    assert result["step_id"] == "edit_tv"
    return await hass.config_entries.options.async_configure(result["flow_id"], fields)


async def test_a_stored_key_switches_the_tv_to_ip_control_without_a_prompt(hass, tmp_path, tv_net):
    """The TV has no light sensor: the edit form saves without one (it raised 'Entity None' before 0.5.0)."""
    entry = await _setup(hass, tmp_path, {TV_ID: _tv()})
    frame_tv.save_ip_control_token(IP, TOKEN)
    result = await _edit_tv(hass, entry, {"power_control": "ip_control"})
    assert result["type"] == "create_entry"
    tv = entry.data["tvs"][TV_ID]
    assert tv["power_control"] == "ip_control"
    assert tv["ip"] == IP and tv["mac"] == MAC and tv["name"] == "Office Frame"
    assert FakeIPClient.all_calls() == ["power_state"]  # verified, never paired
    assert entry.options["library_sync_token"] == "kept"


async def test_without_a_key_the_flow_pairs_while_someone_accepts_the_prompt(hass, tmp_path, tv_net):
    entry = await _setup(hass, tmp_path, {TV_ID: _tv()})
    result = await _edit_tv(hass, entry, {"power_control": "ip_control"})
    assert result["type"] == "form" and result["step_id"] == "ip_control"
    assert not result["errors"]
    assert entry.data["tvs"][TV_ID].get("power_control") is None  # nothing saved before the pairing

    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert result["type"] == "progress" and result["step_id"] == "ip_control_pair"
    assert result["description_placeholders"] == {"tv_name": "Office Frame"}
    FakeIPClient.accepted.set()  # the prompt is accepted on the TV
    await hass.async_block_till_done()
    result = await hass.config_entries.options.async_configure(result["flow_id"])
    assert result["type"] == "create_entry"
    assert entry.data["tvs"][TV_ID]["power_control"] == "ip_control"
    assert frame_tv.read_ip_control_token(IP) == TOKEN
    assert "pair" in FakeIPClient.all_calls()


async def test_a_pairing_nobody_accepts_comes_back_with_the_reason(hass, tmp_path, tv_net):
    entry = await _setup(hass, tmp_path, {TV_ID: _tv()})
    FakeIPClient.pair_error = IPControlTransportError("timed out")
    result = await _edit_tv(hass, entry, {"power_control": "ip_control"})
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert result["type"] == "progress"
    FakeIPClient.accepted.set()  # the wait ends (here: with the timeout error)
    await hass.async_block_till_done()
    result = await hass.config_entries.options.async_configure(result["flow_id"])
    assert result["type"] == "form" and result["step_id"] == "ip_control"
    assert result["errors"] == {"base": "ip_control_timeout"}
    assert entry.data["tvs"][TV_ID].get("power_control") is None
    assert frame_tv.read_ip_control_token(IP) is None


async def test_an_unreachable_tv_shows_what_to_check(hass, tmp_path, tv_net):
    entry = await _setup(hass, tmp_path, {TV_ID: _tv()})
    frame_tv.save_ip_control_token(IP, TOKEN)
    FakeIPClient.state_error = IPControlTransportError("refused")
    result = await _edit_tv(hass, entry, {"power_control": "ip_control"})
    assert result["type"] == "form" and result["step_id"] == "ip_control"
    assert result["errors"] == {"base": "ip_control_unreachable"}
    assert entry.data["tvs"][TV_ID].get("power_control") is None


async def test_back_to_remote_keys_saves_at_once(hass, tmp_path, tv_net):
    entry = await _setup(hass, tmp_path, {TV_ID: _tv(power_control="ip_control")})
    frame_tv.save_ip_control_token(IP, TOKEN)
    result = await _edit_tv(hass, entry, {"power_control": "remote_keys"})
    assert result["type"] == "create_entry"
    assert entry.data["tvs"][TV_ID]["power_control"] == "remote_keys"
    assert FakeIPClient.made == []


async def test_an_ip_control_tv_edited_for_something_else_is_not_paired_again(hass, tmp_path, tv_net):
    entry = await _setup(hass, tmp_path, {TV_ID: _tv(power_control="ip_control")})
    frame_tv.save_ip_control_token(IP, TOKEN)
    result = await _edit_tv(hass, entry, {"shuffle_frequency_minutes": 20})
    assert result["type"] == "create_entry"
    tv = entry.data["tvs"][TV_ID]
    assert tv["power_control"] == "ip_control" and tv["shuffle_frequency_minutes"] == 20
    assert FakeIPClient.made == []


async def test_a_new_tv_with_ip_control_is_added_once_paired(hass, tmp_path, tv_net):
    entry = await _setup(hass, tmp_path, {})
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"action": "add_tv"})
    assert result["step_id"] == "add_tv"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"name": "Den Frame", "host": "192.0.2.41", "mac": "aa:bb:cc:dd:ee:01", "power_control": "ip_control",
         "skip_pairing": True, "shuffle_frequency_minutes": 30},
    )
    assert result["type"] == "form" and result["step_id"] == "ip_control"
    assert entry.data["tvs"] == {}
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert result["type"] == "progress"
    FakeIPClient.accepted.set()
    await hass.async_block_till_done()
    result = await hass.config_entries.options.async_configure(result["flow_id"])
    assert result["type"] == "create_entry"
    tv = next(iter(entry.data["tvs"].values()))
    assert tv["power_control"] == "ip_control" and tv["ip"] == "192.0.2.41"
    assert frame_tv.read_ip_control_token("192.0.2.41") == TOKEN
    await hass.async_block_till_done()  # the entry reloads for its new TV


async def test_a_new_tv_defaults_to_remote_keys(hass, tmp_path, tv_net):
    entry = await _setup(hass, tmp_path, {})
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"action": "add_tv"})
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"name": "Den Frame", "host": "192.0.2.41", "mac": "aa:bb:cc:dd:ee:01", "skip_pairing": True},
    )
    assert result["type"] == "create_entry"
    assert next(iter(entry.data["tvs"].values()))["power_control"] == "remote_keys"
    assert FakeIPClient.made == []
    await hass.async_block_till_done()  # the entry reloads for its new TV


@pytest.mark.parametrize("method", ["ip_control", "remote_keys"])
async def test_the_power_services_use_the_tvs_method(hass, tmp_path, tv_net, method):
    entry = await _setup(hass, tmp_path, {TV_ID: _tv(power_control=method)})
    sensor = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{TV_ID}")
    await hass.services.async_call(DOMAIN, "turn_off_tv", {"entity_id": sensor}, blocking=True)
    tv_net["tv_off"].assert_called_once_with(IP, method)
    await hass.services.async_call(DOMAIN, "turn_on_tv", {"entity_id": sensor}, blocking=True)
    tv_net["tv_on"].assert_called_once_with(IP, MAC, method)
    tv_net["set_art_mode"].assert_called_once_with(IP)
