"""Motion control with presence sensors (0.6.0): a sensor that stays on (occupancy, presence) keeps the screen
on, and the off delay counts from the moment every sensor reads clear. Runs inside Home Assistant 2026.9; no TV
is contacted."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.frame_art_shuffler.const import DOMAIN

PKG = "custom_components.frame_art_shuffler"
TV_ID = "tv0001"
IP = "192.0.2.10"
MAC = "aa:bb:cc:dd:ee:ff"
PRESENCE = "binary_sensor.room_presence"  # an mmWave sensor: on while someone is in the room, still or not
PIR = "binary_sensor.hall_motion"  # a motion sensor: on for a moment after each movement
DELAY = 15  # minutes


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def tv():
    """The TV as motion control sees it: lit at the start, dark after an off and lit after an on (the power
    calls recorded), no upload allowed."""
    screen = {"on": True}

    def power(on: bool):
        def call(*_args, **_kwargs):
            screen["on"] = on
            return True if on else None
        return call

    calls = {"tv_off": MagicMock(side_effect=power(False)), "tv_on": MagicMock(side_effect=power(True))}
    lit = MagicMock(side_effect=lambda *_args, **_kwargs: screen["on"])
    with patch(f"{PKG}.frame_tv.is_screen_on", lit), \
            patch(f"{PKG}.frame_tv.verify_screen_on", lit), \
            patch(f"{PKG}.frame_tv.tv_off", calls["tv_off"]), \
            patch(f"{PKG}.frame_tv.tv_on", calls["tv_on"]), \
            patch(f"{PKG}.tv_off", calls["tv_off"]), \
            patch(f"{PKG}.tv_on", calls["tv_on"]), \
            patch(f"{PKG}.set_art_mode", MagicMock(return_value=None)), \
            patch(f"{PKG}.frame_tv.set_art_on_tv_deleteothers", MagicMock(side_effect=AssertionError("upload"))), \
            patch(f"{PKG}.shuffle.set_art_on_tv_deleteothers", MagicMock(side_effect=AssertionError("upload"))), \
            patch(f"{PKG}.async_generate_dashboard", AsyncMock(return_value=False)):
        yield calls


async def _setup(hass: HomeAssistant, tmp_path: Path, sensors: list[str]) -> MockConfigEntry:
    for sensor in sensors:
        hass.states.async_set(sensor, "off")
    root = tmp_path / "media" / "frame_art"
    (root / "library").mkdir(parents=True)
    metadata = root / "metadata.json"
    metadata.write_text(json.dumps({"version": "1.0", "images": {}, "tvs": [], "tags": []}))
    tv = {
        "id": TV_ID, "name": "Living Frame", "short_name": "Living", "ip": IP, "mac": MAC,
        "selected_tagset": None, "shuffle_frequency_minutes": 60, "enable_auto_shuffle": False,
        "enable_motion_control": True, "motion_sensors": sensors, "motion_off_delay": DELAY,
        "power_control": "ip_control",
    }
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Frame Art Shuffler",
        data={"metadata_path": str(metadata), "token_dir": str(tmp_path / "tokens"), "tvs": {TV_ID: tv}, "tagsets": {}},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


@pytest.fixture(autouse=True)
async def unload_after(hass):
    yield
    for entry in hass.config_entries.async_entries(DOMAIN):
        await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def _set(hass: HomeAssistant, sensor: str, state: str) -> None:
    hass.states.async_set(sensor, state)
    await hass.async_block_till_done()


async def _wait(hass: HomeAssistant, freezer, minutes: float) -> None:
    """Let time pass a minute at a time, so every timer due on the way fires."""
    whole, rest = int(minutes), minutes - int(minutes)
    for step in [1.0] * whole + ([rest] if rest else []):
        freezer.tick(timedelta(minutes=step))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()


async def test_a_presence_sensor_holding_on_keeps_the_screen_on(hass, tmp_path, tv, freezer):
    await _setup(hass, tmp_path, [PRESENCE])
    await _set(hass, PRESENCE, "on")  # someone walks in and sits down
    await _wait(hass, freezer, 3 * DELAY)  # still there, still: the sensor holds on
    tv["tv_off"].assert_not_called()

    await _set(hass, PRESENCE, "off")  # they leave
    await _wait(hass, freezer, DELAY - 1)
    tv["tv_off"].assert_not_called()
    await _wait(hass, freezer, 2)
    tv["tv_off"].assert_called_once_with(IP, "ip_control")


async def test_a_motion_pulse_turns_the_screen_off_one_delay_after_it_clears(hass, tmp_path, tv, freezer):
    await _setup(hass, tmp_path, [PIR])
    await _set(hass, PIR, "on")
    await _wait(hass, freezer, 0.5)
    await _set(hass, PIR, "off")
    await _wait(hass, freezer, DELAY - 1)
    tv["tv_off"].assert_not_called()
    await _wait(hass, freezer, 2)
    tv["tv_off"].assert_called_once_with(IP, "ip_control")


async def test_any_sensor_reading_on_holds_the_screen(hass, tmp_path, tv, freezer):
    await _setup(hass, tmp_path, [PRESENCE, PIR])
    await _set(hass, PRESENCE, "on")
    await _set(hass, PIR, "on")
    await _wait(hass, freezer, 0.5)
    await _set(hass, PIR, "off")  # the hall sensor clears; the room sensor still sees someone
    await _wait(hass, freezer, 2 * DELAY)
    tv["tv_off"].assert_not_called()

    await _set(hass, PRESENCE, "off")
    await _wait(hass, freezer, DELAY + 1)
    tv["tv_off"].assert_called_once()


async def test_a_sensor_clearing_in_tv_mode_starts_no_countdown(hass, tmp_path, tv, freezer):
    """TV mode (the auto shuffle switched off to watch TV) cancels the countdown; a clear must not start one."""
    await _setup(hass, tmp_path, [PRESENCE])
    shuffle = er.async_get(hass).async_get_entity_id("switch", DOMAIN, f"{TV_ID}_auto_shuffle")
    await hass.services.async_call("switch", "turn_on", {"entity_id": shuffle}, blocking=True)
    await _set(hass, PRESENCE, "on")
    await hass.services.async_call("switch", "turn_off", {"entity_id": shuffle}, blocking=True)
    await _set(hass, PRESENCE, "off")
    await _wait(hass, freezer, DELAY + 2)
    tv["tv_off"].assert_not_called()


async def test_the_tv_forms_offer_occupancy_and_presence_sensors(hass, tmp_path, tv):
    entry = await _setup(hass, tmp_path, [PRESENCE])
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"action": "edit_tv"})
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"tv_id": TV_ID})
    assert result["step_id"] == "edit_tv"
    selector = next(v for k, v in result["data_schema"].schema.items() if k == "motion_sensors")
    assert selector.config["device_class"] == ["motion", "occupancy", "presence"]
    assert selector.config["multiple"] is True
