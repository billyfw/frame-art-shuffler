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
    # Create a copy of the tvs dict.
    # Home Assistant compares the new data object with the old one.
    # If we modify the dictionary in-place without copying, HA might not detect
    # the change and fail to persist the new values to storage.
    tvs = data.get("tvs", {}).copy()
    data["tvs"] = tvs
    
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
    # Create a copy of the tvs dict.
    # Home Assistant compares the new data object with the old one.
    # If we modify the dictionary in-place without copying, HA might not detect
    # the change and fail to persist the new values to storage.
    tvs = data.get("tvs", {}).copy()
    data["tvs"] = tvs
    
    if tv_id not in tvs:
        tvs[tv_id] = {"id": tv_id}
    else:
        # Also copy the specific TV data to ensure the nested dictionary change is detected
        tvs[tv_id] = tvs[tv_id].copy()
    
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
    # Create a copy of the tvs dict.
    # Home Assistant compares the new data object with the old one.
    # If we modify the dictionary in-place without copying, HA might not detect
    # the change and fail to persist the new values to storage.
    tvs = data.get("tvs", {}).copy()
    data["tvs"] = tvs
    
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


def get_effective_tags(tv_config: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Get the effective include/exclude tags for a TV.
    
    Resolves tagsets: uses override_tagset if active, else selected_tagset.
    Returns empty lists if no tagsets are configured.
    
    Args:
        tv_config: TV configuration dict
        
    Returns:
        Tuple of (include_tags, exclude_tags)
    """
    tagsets = tv_config.get("tagsets", {})
    
    if not tagsets:
        return ([], [])
    
    # Use override if active, else selected
    active_name = tv_config.get("override_tagset") or tv_config.get("selected_tagset")
    if not active_name or active_name not in tagsets:
        # Fallback: use first tagset
        active_name = next(iter(tagsets), None)
        if not active_name:
            return ([], [])
    
    tagset = tagsets[active_name]
    return (
        tagset.get("tags", []),
        tagset.get("exclude_tags", [])
    )


def get_active_tagset_name(tv_config: dict[str, Any]) -> str | None:
    """Get the name of the currently active tagset.
    
    Args:
        tv_config: TV configuration dict
        
    Returns:
        Name of active tagset, or None if no tagsets configured
    """
    tagsets = tv_config.get("tagsets", {})
    if not tagsets:
        return None
    
    active_name = tv_config.get("override_tagset") or tv_config.get("selected_tagset")
    if active_name and active_name in tagsets:
        return active_name
    
    # Fallback to first tagset
    return next(iter(tagsets), None)
