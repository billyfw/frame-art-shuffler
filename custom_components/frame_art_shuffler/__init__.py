"""Frame Art Shuffler integration base setup.

This integration provides art-focused control for Samsung Frame TVs:
- Upload and display artwork
- Manage art gallery (delete others, select images)
- Control art mode brightness
- Basic power control (screen on/off while staying in art mode)

It can work standalone or alongside Home Assistant's Samsung Smart TV integration.
See README.md for details on standalone vs. hybrid deployment modes.
"""
from __future__ import annotations

from pathlib import Path

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import CONF_HOME, CONF_METADATA_PATH, CONF_TOKEN_DIR, DOMAIN
from .coordinator import FrameArtCoordinator
from .frame_tv import TOKEN_DIR as DEFAULT_TOKEN_DIR, set_token_directory

PLATFORMS = [Platform.SENSOR]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Frame Art Shuffler integration."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a config entry for Frame Art Shuffler."""

    metadata_path = Path(entry.data[CONF_METADATA_PATH])
    token_dir = Path(entry.data[CONF_TOKEN_DIR])
    home = entry.data[CONF_HOME]

    token_dir.mkdir(parents=True, exist_ok=True)
    set_token_directory(token_dir)

    coordinator = FrameArtCoordinator(hass, metadata_path, home)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
        "metadata_path": metadata_path,
        "token_dir": token_dir,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a Frame Art Shuffler config entry."""

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False

    data = hass.data.get(DOMAIN)
    if data and entry.entry_id in data:
        data.pop(entry.entry_id)

    if not hass.config_entries.async_entries(DOMAIN):
        set_token_directory(DEFAULT_TOKEN_DIR)

    return True


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
