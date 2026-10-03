"""Wall tablet targets (0.4.0), run inside Home Assistant 2026.9 (pytest-homeassistant-custom-component).

A tablet is never contacted: these tests fail if any Frame TV network call happens for one.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.frame_art_shuffler.const import DOMAIN

PKG = "custom_components.frame_art_shuffler"
TABLET_ID = "tablet0001"
TV_ID = "tv0001"
SHOWING = "input_boolean.wall_showing"

LIBRARY = {
    "beach-1.jpg": ((4000, 2250), ["landscape"]),
    "beach-2.jpg": ((4000, 2250), ["landscape"]),
    "ridge-3.png": ((3000, 2000), ["landscape"]),
    "kids-4.jpg": ((2000, 1500), ["family", "private"]),
    "office-5.jpg": ((1600, 900), ["billy-only"]),
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def tv_calls():
    """Every Frame TV network entry point, failing loudly if a tablet path reaches one."""
    mocks = {
        "set_art_on_tv_deleteothers": MagicMock(side_effect=AssertionError("upload to a TV")),
        "is_screen_on": MagicMock(return_value=False),
        "tv_on": MagicMock(side_effect=AssertionError("wake a TV")),
        "tv_off": MagicMock(side_effect=AssertionError("turn off a TV")),
    }
    with patch(f"{PKG}.frame_tv.set_art_on_tv_deleteothers", mocks["set_art_on_tv_deleteothers"]), \
            patch(f"{PKG}.shuffle.set_art_on_tv_deleteothers", mocks["set_art_on_tv_deleteothers"]), \
            patch(f"{PKG}.frame_tv.is_screen_on", mocks["is_screen_on"]), \
            patch(f"{PKG}.tv_on", mocks["tv_on"]), \
            patch(f"{PKG}.tv_off", mocks["tv_off"]), \
            patch(f"{PKG}.async_generate_dashboard", AsyncMock(return_value=False)):
        yield mocks


def _make_library(root: Path) -> Path:
    lib = root / "library"
    lib.mkdir(parents=True)
    images = {}
    for name, (size, tags) in LIBRARY.items():
        if name.endswith(".png"):
            Image.new("RGBA", size, (10, 120, 200, 128)).save(lib / name, "PNG")
        else:
            Image.new("RGB", size, (200, 30, 30)).save(lib / name, "JPEG")
        images[name] = {"tags": tags, "matte": "none", "filter": "None"}
    metadata = root / "metadata.json"
    metadata.write_text(json.dumps({"version": "1.0", "images": images, "tvs": [], "tags": []}))
    return metadata


def _tablet(**overrides):
    tablet = {
        "id": TABLET_ID,
        "kind": "tablet",
        "name": "Wall Test",
        "short_name": "Wall",
        "showing_entity": SHOWING,
        "selected_tagset": "wall",
        "shuffle_frequency_minutes": 5,
        "enable_auto_shuffle": True,
    }
    tablet.update(overrides)
    return tablet


async def _setup(hass: HomeAssistant, tmp_path: Path, tvs: dict, *, tagsets=None, options=None) -> MockConfigEntry:
    assert await async_setup_component(hass, "input_boolean", {"input_boolean": {"wall_showing": {"name": "Wall showing"}}})
    metadata = _make_library(tmp_path / "media" / "frame_art")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Frame Art Shuffler",
        data={
            "metadata_path": str(metadata),
            "token_dir": str(tmp_path / "tokens"),
            "tvs": tvs,
            "tagsets": tagsets if tagsets is not None else {
                "wall": {"tags": ["landscape", "family"], "exclude_tags": ["private", "billy-only"]},
            },
        },
        options=options or {},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _entity(hass: HomeAssistant, domain: str, unique_id: str) -> str | None:
    return er.async_get(hass).async_get_entity_id(domain, DOMAIN, unique_id)


async def _show_art(hass: HomeAssistant, on: bool = True) -> None:
    await hass.services.async_call("input_boolean", "turn_on" if on else "turn_off", {"entity_id": SHOWING}, blocking=True)
    await hass.async_block_till_done()


async def test_tablet_gets_only_its_entities(hass, tmp_path, tv_calls):
    entry = await _setup(hass, tmp_path, {TABLET_ID: _tablet()})
    eid = entry.entry_id
    assert _entity(hass, "image", f"{eid}_{TABLET_ID}_artwork_image")
    assert _entity(hass, "sensor", f"{eid}_{TABLET_ID}")
    assert _entity(hass, "binary_sensor", f"{eid}_{TABLET_ID}_screen_on")
    assert _entity(hass, "switch", f"{TABLET_ID}_auto_shuffle")
    assert _entity(hass, "number", f"{TABLET_ID}_shuffle_frequency")
    assert _entity(hass, "button", f"{TABLET_ID}_shuffle")
    for domain, unique_id in (
        ("switch", f"{TABLET_ID}_power"),
        ("number", f"{TABLET_ID}_brightness"),
        ("button", f"{TABLET_ID}_art_mode"),
        ("sensor", f"{eid}_{TABLET_ID}_ip"),
        ("sensor", f"{eid}_{TABLET_ID}_current_matte"),
    ):
        assert _entity(hass, domain, unique_id) is None, unique_id
    screen = _entity(hass, "binary_sensor", f"{eid}_{TABLET_ID}_screen_on")
    assert hass.states.get(screen).state == "off"
    device = dr.async_get(hass).async_get_device_by_identifier((DOMAIN, TABLET_ID), entry.entry_id)
    assert device.model == "Wall tablet"
    for mock in tv_calls.values():
        assert not mock.called


async def test_showing_art_picks_an_allowed_picture_and_serves_it_resized(hass, tmp_path, tv_calls, hass_client):
    entry = await _setup(hass, tmp_path, {TABLET_ID: _tablet()})
    eid = entry.entry_id
    sensor = _entity(hass, "sensor", f"{eid}_{TABLET_ID}")
    image = _entity(hass, "image", f"{eid}_{TABLET_ID}_artwork_image")
    screen = _entity(hass, "binary_sensor", f"{eid}_{TABLET_ID}_screen_on")

    await _show_art(hass)
    assert hass.states.get(screen).state == "on"
    pick = hass.states.get(sensor).state
    assert pick in ("beach-1.jpg", "beach-2.jpg", "ridge-3.png")  # never private or billy-only
    assert hass.states.get(image).attributes["filename"] == pick
    assert hass.states.get(sensor).attributes["image_entity"] == image
    assert hass.states.get(sensor).attributes["entity_picture"] is None  # the library is not public

    client = await hass_client()
    response = await client.get(f"/api/image_proxy/{image}")
    assert response.status == 200
    assert response.headers["Content-Type"] == "image/jpeg"
    served = Image.open(io.BytesIO(await response.read()))
    assert served.width <= 1920 and served.height <= 1200
    assert not tv_calls["set_art_on_tv_deleteothers"].called


async def test_image_proxy_needs_login_or_token(hass, tmp_path, tv_calls, hass_client_no_auth):
    entry = await _setup(hass, tmp_path, {TABLET_ID: _tablet()})
    image = _entity(hass, "image", f"{entry.entry_id}_{TABLET_ID}_artwork_image")
    await _show_art(hass)
    anonymous = await hass_client_no_auth()
    assert (await anonymous.get(f"/api/image_proxy/{image}")).status in (401, 403)
    token = hass.states.get(image).attributes["access_token"]
    assert (await anonymous.get(f"/api/image_proxy/{image}?token={token}")).status == 200
    # and the library is not under www, so nothing is published at /local
    assert (await anonymous.get("/local/frame_art/metadata.json")).status == 404


async def test_tablet_without_tags_shows_nothing(hass, tmp_path, tv_calls):
    entry = await _setup(hass, tmp_path, {TABLET_ID: _tablet(selected_tagset=None)}, tagsets={})
    sensor = _entity(hass, "sensor", f"{entry.entry_id}_{TABLET_ID}")
    await _show_art(hass)
    assert hass.states.get(sensor).state == "Unknown"


async def test_turning_off_closes_and_repicks_only_after_a_minute(hass, tmp_path, tv_calls):
    entry = await _setup(hass, tmp_path, {TABLET_ID: _tablet()})
    sensor = _entity(hass, "sensor", f"{entry.entry_id}_{TABLET_ID}")
    await _show_art(hass)
    first = hass.states.get(sensor).state
    await _show_art(hass, False)
    await _show_art(hass)
    assert hass.states.get(sensor).state == first  # a quick off and on keeps the picture


async def test_display_image_on_a_tablet(hass, tmp_path, tv_calls):
    entry = await _setup(hass, tmp_path, {TABLET_ID: _tablet()})
    sensor = _entity(hass, "sensor", f"{entry.entry_id}_{TABLET_ID}")
    await hass.services.async_call(DOMAIN, "display_image", {"entity_id": sensor, "filename": "ridge-3.png"}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get(sensor).state == "ridge-3.png"
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "display_image", {"entity_id": sensor, "filename": "../metadata.json"}, blocking=True)
    assert not tv_calls["set_art_on_tv_deleteothers"].called


async def test_tv_power_services_refuse_a_tablet(hass, tmp_path, tv_calls):
    entry = await _setup(hass, tmp_path, {TABLET_ID: _tablet()})
    sensor = _entity(hass, "sensor", f"{entry.entry_id}_{TABLET_ID}")
    for service in ("turn_on_tv", "turn_off_tv"):
        if hass.services.has_service(DOMAIN, service):
            with pytest.raises(ServiceValidationError):
                await hass.services.async_call(DOMAIN, service, {"entity_id": sensor}, blocking=True)


async def test_a_tv_target_keeps_its_entities(hass, tmp_path, tv_calls):
    tv = {
        "id": TV_ID, "name": "Office Frame", "ip": "192.0.2.10", "mac": "aa:bb:cc:dd:ee:ff",
        "selected_tagset": "wall", "shuffle_frequency_minutes": 60, "enable_auto_shuffle": False,
    }
    entry = await _setup(hass, tmp_path, {TV_ID: tv})
    eid = entry.entry_id
    assert _entity(hass, "switch", f"{TV_ID}_power")
    assert _entity(hass, "number", f"{TV_ID}_brightness")
    assert _entity(hass, "sensor", f"{eid}_{TV_ID}_ip")
    assert _entity(hass, "image", f"{eid}_{TV_ID}_artwork_image")
    assert tv_calls["is_screen_on"].called  # the TV is still polled
    sensor = _entity(hass, "sensor", f"{eid}_{TV_ID}")
    assert hass.states.get(sensor).attributes["kind"] == "tv"


async def test_add_tablet_keeps_the_options(hass, tmp_path, tv_calls):
    entry = await _setup(hass, tmp_path, {}, options={"library_sync_token": "secret", "library_sync_interval_minutes": 15})
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"action": "add_tablet"})
    assert result["step_id"] == "add_tablet"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"name": "Wall kitchenhall", "short_name": "Wall", "tags": "landscape, family",
         "exclude_tags": "private, billy-only", "showing_entity": SHOWING,
         "shuffle_frequency_minutes": 3, "enable_auto_shuffle": True},
    )
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()
    assert entry.options["library_sync_token"] == "secret"
    tablet = next(iter(entry.data["tvs"].values()))
    assert tablet["kind"] == "tablet" and tablet["showing_entity"] == SHOWING and "ip" not in tablet
    tagset = entry.data["tagsets"][tablet["selected_tagset"]]
    assert tagset == {"tags": ["landscape", "family"], "exclude_tags": ["private", "billy-only"]}


async def test_new_entry_chooses_its_library_folder(hass, tmp_path):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["step_id"] == "user"
    bad = await hass.config_entries.flow.async_configure(result["flow_id"], {"library_dir": "relative/path"})
    assert bad["errors"] == {"library_dir": "invalid_library_dir"}
    folder = tmp_path / "media" / "frame_art"
    with patch(f"{PKG}.async_setup_entry", AsyncMock(return_value=True)):
        done = await hass.config_entries.flow.async_configure(result["flow_id"], {"library_dir": str(folder)})
    assert done["type"] == "create_entry"
    assert done["data"]["metadata_path"] == str(folder / "metadata.json")
    assert folder.is_dir()


async def test_display_image_on_a_tv_uses_the_library_file(hass, tmp_path, tv_calls):
    """The manager sends image_url and filename; with the library outside www only the file exists."""
    tv = {
        "id": TV_ID, "name": "Lau Frame", "ip": "192.0.2.11", "mac": "aa:bb:cc:dd:ee:01",
        "selected_tagset": "wall", "shuffle_frequency_minutes": 60, "enable_auto_shuffle": False,
    }
    entry = await _setup(hass, tmp_path, {TV_ID: tv})
    sensor = _entity(hass, "sensor", f"{entry.entry_id}_{TV_ID}")
    upload = MagicMock(return_value=True)
    with patch(f"{PKG}.frame_tv.set_art_on_tv_deleteothers", upload):
        await hass.services.async_call(
            DOMAIN,
            "display_image",
            {"entity_id": sensor, "filename": "beach-1.jpg", "image_url": "/local/frame_art/library/beach-1.jpg"},
            blocking=True,
        )
    sent_path = upload.call_args.args[1]
    assert sent_path == str(tmp_path / "media" / "frame_art" / "library" / "beach-1.jpg")
