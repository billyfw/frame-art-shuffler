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


def get_global_tagsets(entry: ConfigEntry) -> dict[str, Any]:
    """Get the global tagsets from config entry.
    
    Args:
        entry: Config entry
        
    Returns:
        Dict of tagset name -> tagset config
    """
    return entry.data.get("tagsets", {})


def get_effective_tags(entry: ConfigEntry, tv_id: str) -> tuple[list[str], list[str]]:
    """Get the effective include/exclude tags for a TV.
    
    Resolves tagsets from GLOBAL tagsets using TV's selected/override tagset name.
    Returns empty lists if no tagsets are configured.
    
    Args:
        entry: Config entry (contains global tagsets)
        tv_id: TV identifier
        
    Returns:
        Tuple of (include_tags, exclude_tags)
    """
    # Read global tagsets from root of config entry data
    tagsets = entry.data.get("tagsets", {})
    
    if not tagsets:
        return ([], [])
    
    # Get TV's tagset assignment
    tv_config = get_tv_config(entry, tv_id)
    if not tv_config:
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


def get_active_tagset_name(entry: ConfigEntry, tv_id: str) -> str | None:
    """Get the name of the currently active tagset for a TV.
    
    Args:
        entry: Config entry (contains global tagsets)
        tv_id: TV identifier
        
    Returns:
        Name of active tagset, or None if no tagsets configured
    """
    tagsets = entry.data.get("tagsets", {})
    if not tagsets:
        return None
    
    tv_config = get_tv_config(entry, tv_id)
    if not tv_config:
        return None
    
    active_name = tv_config.get("override_tagset") or tv_config.get("selected_tagset")
    if active_name and active_name in tagsets:
        return active_name
    
    # Fallback to first tagset
    return next(iter(tagsets), None)


def update_global_tagsets(
    hass: HomeAssistant,
    entry: ConfigEntry,
    tagsets: dict[str, Any],
) -> None:
    """Update global tagsets in config entry.
    
    Args:
        hass: Home Assistant instance
        entry: Config entry
        tagsets: New tagsets dict
    """
    data = {**entry.data}
    data["tagsets"] = tagsets
    hass.config_entries.async_update_entry(entry, data=data)


def generate_unique_tagset_name(entry: ConfigEntry, base_name: str) -> str:
    """Generate a unique tagset name based on base_name.
    
    If base_name already exists, appends _2, _3, etc.
    
    Args:
        entry: Config entry
        base_name: Desired base name (e.g., "living_room_primary")
        
    Returns:
        Unique tagset name
    """
    tagsets = entry.data.get("tagsets", {})
    
    if base_name not in tagsets:
        return base_name
    
    # Find next available suffix
    suffix = 2
    while f"{base_name}_{suffix}" in tagsets:
        suffix += 1
    
    return f"{base_name}_{suffix}"


def get_tag_weights(entry: ConfigEntry, tv_id: str) -> dict[str, float]:
    """Get tag weights for the active tagset.
    
    Returns dict of tag -> weight. Missing tags default to 1.
    Weights are clamped to 0.1-10 range.
    
    Args:
        entry: Config entry (contains global tagsets)
        tv_id: TV identifier
        
    Returns:
        Dict of tag name -> weight (float)
    """
    tagsets = entry.data.get("tagsets", {})
    if not tagsets:
        return {}
    
    tv_config = get_tv_config(entry, tv_id)
    if not tv_config:
        return {}
    
    active_name = tv_config.get("override_tagset") or tv_config.get("selected_tagset")
    if not active_name or active_name not in tagsets:
        active_name = next(iter(tagsets), None)
    
    if not active_name:
        return {}
    
    tagset = tagsets[active_name]
    raw_weights = tagset.get("tag_weights", {})
    
    # Clamp weights to valid range and ensure they're floats
    weights = {}
    for tag, weight in raw_weights.items():
        try:
            w = float(weight)
            weights[tag] = max(0.1, min(10.0, w))
        except (ValueError, TypeError):
            weights[tag] = 1.0
    
    return weights


def get_tagset_weights(entry: ConfigEntry, tagset_name: str) -> dict[str, float]:
    """Get tag weights for a specific tagset by name.
    
    Args:
        entry: Config entry
        tagset_name: Name of the tagset
        
    Returns:
        Dict of tag name -> weight (float), clamped to 0.1-10
    """
    tagsets = entry.data.get("tagsets", {})
    if not tagsets or tagset_name not in tagsets:
        return {}
    
    tagset = tagsets[tagset_name]
    raw_weights = tagset.get("tag_weights", {})
    
    weights = {}
    for tag, weight in raw_weights.items():
        try:
            w = float(weight)
            weights[tag] = max(0.1, min(10.0, w))
        except (ValueError, TypeError):
            weights[tag] = 1.0
    
    return weights


def calculate_tag_percentages(tags: list[str], weights: dict[str, float]) -> dict[str, int]:
    """Calculate display percentages for each tag based on weights.
    
    Args:
        tags: List of tag names
        weights: Dict of tag -> weight (missing tags default to 1)
        
    Returns:
        Dict of tag -> percentage (integer, rounded)
    """
    if not tags:
        return {}
    
    total = sum(weights.get(tag, 1.0) for tag in tags)
    if total == 0:
        return {tag: 0 for tag in tags}
    
    percentages = {}
    for tag in tags:
        weight = weights.get(tag, 1.0)
        percentages[tag] = round((weight / total) * 100)
    
    return percentages


def format_weight_display(weight: float) -> str:
    """Format a weight value for display.
    
    Decimals show as "0.5", integers show as "4".
    
    Args:
        weight: Weight value
        
    Returns:
        Formatted string
    """
    if weight == int(weight):
        return str(int(weight))
    return f"{weight:.1f}"
