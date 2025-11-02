"""Config entry data management helpers."""

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant


def get_tv_config(entry: ConfigEntry, tv_id: str) -> dict[str, Any] | None:
    """Get TV configuration from config entry.
    
    Args:
        entry: Config entry
        tv_id: TV identifier (UUID)
    
    Returns:
        TV config dict or None if not found
    """
    tvs = entry.data.get("tvs", {})
    return tvs.get(tv_id)


def add_tv_config(
    hass: HomeAssistant,
    entry: ConfigEntry,
    tv_id: str,
    tv_data: dict[str, Any],
) -> None:
    """Add a new TV to config entry.
    
    Args:
        hass: Home Assistant instance
        entry: Config entry
        tv_id: TV identifier (UUID)
        tv_data: TV configuration dict
    """
    data = {**entry.data}
    tvs = data.setdefault("tvs", {})
    
    tvs[tv_id] = {"id": tv_id, **tv_data}
    
    hass.config_entries.async_update_entry(entry, data=data)


def update_tv_config(
    hass: HomeAssistant,
    entry: ConfigEntry,
    tv_id: str,
    updates: dict[str, Any],
) -> None:
    """Update TV configuration in config entry.
    
    Args:
        hass: Home Assistant instance
        entry: Config entry
        tv_id: TV identifier (UUID)
        updates: Dict of fields to update
    """
    data = {**entry.data}
    tvs = data.setdefault("tvs", {})
    
    if tv_id not in tvs:
        tvs[tv_id] = {"id": tv_id}
    
    tvs[tv_id].update(updates)
    
    hass.config_entries.async_update_entry(entry, data=data)


def remove_tv_config(
    hass: HomeAssistant,
    entry: ConfigEntry,
    tv_id: str,
) -> None:
    """Remove TV from config entry.
    
    Args:
        hass: Home Assistant instance
        entry: Config entry
        tv_id: TV identifier (UUID)
    """
    data = {**entry.data}
    tvs = data.get("tvs", {})
    
    if tv_id in tvs:
        del tvs[tv_id]
        hass.config_entries.async_update_entry(entry, data=data)


def list_tv_configs(entry: ConfigEntry) -> dict[str, dict[str, Any]]:
    """Get all TV configurations from config entry.
    
    Args:
        entry: Config entry
    
    Returns:
        Dict mapping TV IDs to TV config dicts
    """
    return entry.data.get("tvs", {})
