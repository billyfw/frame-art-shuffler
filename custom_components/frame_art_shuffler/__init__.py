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
from typing import Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback, ServiceCall
from homeassistant.helpers import device_registry as dr

from .const import CONF_METADATA_PATH, CONF_TOKEN_DIR, DOMAIN
from .coordinator import FrameArtCoordinator
from .config_entry import remove_tv_config
from .frame_tv import TOKEN_DIR as DEFAULT_TOKEN_DIR, set_token_directory
from .metadata import MetadataStore

PLATFORMS = [Platform.TEXT, Platform.NUMBER, Platform.BUTTON]


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Frame Art Shuffler integration."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a config entry for Frame Art Shuffler."""

    metadata_path = Path(entry.data[CONF_METADATA_PATH])
    token_dir = Path(entry.data[CONF_TOKEN_DIR])

    token_dir.mkdir(parents=True, exist_ok=True)
    set_token_directory(token_dir)

    # Migrate TV data from metadata.json to config entry (one-time)
    if "tvs" not in entry.data or not entry.data["tvs"]:
        await _async_migrate_from_metadata(hass, entry, metadata_path)

    coordinator = FrameArtCoordinator(hass, entry, metadata_path)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
        "metadata_path": metadata_path,
        "token_dir": token_dir,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    
    # Register device removal handler
    entry.async_on_unload(
        _register_device_removal_listener(hass, entry, metadata_path)
    )
    
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


async def _async_migrate_from_metadata(
    hass: HomeAssistant,
    entry: ConfigEntry,
    metadata_path: Path,
) -> None:
    """One-time migration: import TV data from metadata.json into config entry."""
    store = MetadataStore(metadata_path)
    
    try:
        metadata_tvs = await hass.async_add_executor_job(store.list_tvs)
    except Exception:
        # metadata.json might not exist yet or be empty
        return
    
    if not metadata_tvs:
        return
    
    tvs = {}
    for tv in metadata_tvs:
        tv_id = tv.get("id")
        if not tv_id:
            continue
        
        shuffle_data = tv.get("shuffle", {})
        tvs[tv_id] = {
            "id": tv_id,
            "name": tv.get("name"),
            "ip": tv.get("ip"),
            "mac": tv.get("mac"),
            "shuffle_frequency_minutes": shuffle_data.get("frequencyMinutes", 60) if isinstance(shuffle_data, dict) else 60,
            "tags": tv.get("tags", []),
            "exclude_tags": tv.get("notTags", []),
        }
    
    if tvs:
        data = {**entry.data, "tvs": tvs}
        hass.config_entries.async_update_entry(entry, data=data)


@callback
def _register_device_removal_listener(
    hass: HomeAssistant,
    entry: ConfigEntry,
    metadata_path: Path,
) -> Callable[[], None]:
    """Register a listener for device removal to clean up metadata."""
    
    @callback
    def device_removed(event):
        """Handle device removal."""
        device_id = event.data["device_id"]
        device_registry = dr.async_get(hass)
        device = device_registry.async_get(device_id)
        
        if not device:
            return
        
        # Check if this device belongs to our integration
        if not any(entry.entry_id in entry_id for entry_id in device.config_entries):
            return
        
        # Extract TV ID from device identifiers
        # Format is now just tv_id (no home prefix)
        tv_id = None
        for identifier in device.identifiers:
            if identifier[0] == DOMAIN:
                tv_id = identifier[1]
                break
        
        if not tv_id:
            return
        
        # Remove from metadata
        async def _remove_tv():
            store = MetadataStore(metadata_path)
            token_dir = hass.data.get(DOMAIN, {}).get(entry.entry_id, {}).get("token_dir")
            try:
                # Get TV data before removing to find token file
                tv_data = await hass.async_add_executor_job(store.get_tv, tv_id)
                tv_ip = tv_data.get("ip") if tv_data else None
                
                # Remove from config entry
                remove_tv_config(hass, entry, tv_id)
                
                # Delete token file if it exists
                if token_dir and tv_ip:
                    from .flow_utils import safe_token_filename
                    token_path = Path(token_dir) / f"{safe_token_filename(tv_ip)}.token"
                    if token_path.exists():
                        await hass.async_add_executor_job(token_path.unlink)
                
                # Refresh coordinator
                data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
                if data:
                    coordinator = data.get("coordinator")
                    if coordinator:
                        await coordinator.async_request_refresh()
            except Exception:
                # TV might already be deleted, ignore
                pass
        
        hass.async_create_task(_remove_tv())
    
    return hass.bus.async_listen("device_registry_updated", device_removed)
