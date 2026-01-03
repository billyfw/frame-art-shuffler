"""Binary sensor platform for Frame Art Shuffler TVs."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Callable, Iterable

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_track_time_interval

from .config_entry import get_active_tagset_name, get_tv_config
from .const import DOMAIN
from . import frame_tv

_LOGGER = logging.getLogger(__name__)

# Polling interval for TV status checks
TV_STATUS_POLL_INTERVAL = timedelta(seconds=10)
# Timeout for status checks (short to avoid blocking)
TV_STATUS_CHECK_TIMEOUT = 5


SCREEN_ON_DESCRIPTION = BinarySensorEntityDescription(
    key="screen_on",
    device_class=BinarySensorDeviceClass.POWER,
    icon="mdi:television",
    translation_key="screen_on",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities,
) -> None:
    """Set up Frame Art TV binary sensors for a config entry."""

    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]

    # Initialize the status cache in hass.data
    tv_status_cache: dict[str, dict[str, bool | None]] = {}
    data["tv_status_cache"] = tv_status_cache

    tracked: dict[str, tuple] = {}

    @callback
    def _process_tvs(tvs: Iterable[dict[str, Any]]) -> None:
        new_entities: list[BinarySensorEntity] = []
        for tv in tvs:
            tv_id = tv.get("id")
            if not tv_id or tv_id in tracked:
                continue

            # Initialize status cache for this TV
            tv_status_cache[tv_id] = {
                "screen_on": None,
            }

            # Create binary sensors per TV
            screen_on_entity = FrameArtScreenOnEntity(hass, entry, tv_id)

            tracked[tv_id] = screen_on_entity
            new_entities.append(screen_on_entity)

        if new_entities:
            async_add_entities(new_entities)

    _process_tvs(coordinator.data or [])

    @callback
    def _handle_coordinator_update() -> None:
        _process_tvs(coordinator.data or [])

    unsubscribe = coordinator.async_add_listener(_handle_coordinator_update)
    entry.async_on_unload(unsubscribe)

    # Set up polling for TV status
    async def async_poll_tv_status(_now: Any) -> None:
        """Poll all TVs for their current status."""
        for tv in coordinator.data or []:
            tv_id = tv.get("id")
            if not tv_id:
                continue

            tv_config = get_tv_config(entry, tv_id)
            if not tv_config:
                continue

            ip = tv_config.get("ip")
            if not ip:
                continue

            tv_name = tv_config.get("name", tv_id)
            
            # Capture old value to detect changes
            old_screen_on = tv_status_cache[tv_id].get("screen_on")

            # Check screen status (read-only REST call)
            try:
                screen_on = await hass.async_add_executor_job(
                    frame_tv.is_screen_on, ip, TV_STATUS_CHECK_TIMEOUT
                )
                tv_status_cache[tv_id]["screen_on"] = screen_on
            except Exception as err:
                _LOGGER.debug(f"Failed to check screen status for {tv_name}: {err}")

            # Handle motion control based on screen state
            if tv_status_cache[tv_id]["screen_on"]:
                # Fallback: Start motion off timer if TV is on but no timer exists
                # This catches external power-on (remote, app, etc.)
                if tv_config.get("enable_motion_control", False):
                    motion_off_times = data.get("motion_off_times", {})
                    if tv_id not in motion_off_times:
                        start_motion_off_timer = data.get("start_motion_off_timer")
                        if start_motion_off_timer:
                            start_motion_off_timer(tv_id)
                            _LOGGER.debug(f"Auto motion: Started off timer for {tv_name} (external power-on)")
            else:
                # Screen is off - cancel motion off timer if one exists
                if tv_config.get("enable_motion_control", False):
                    motion_off_times = data.get("motion_off_times", {})
                    if tv_id in motion_off_times:
                        cancel_motion_off_timer = data.get("cancel_motion_off_timer")
                        if cancel_motion_off_timer:
                            cancel_motion_off_timer(tv_id)
                            _LOGGER.info(f"Auto motion: Cancelled off timer for {tv_name} (screen is off)")

            # Only notify HA if state actually changed
            new_screen_on = tv_status_cache[tv_id].get("screen_on")
            
            if tv_id in tracked:
                screen_entity = tracked[tv_id]
                if new_screen_on != old_screen_on:
                    screen_entity.async_write_ha_state()
                    
                    # Update display log when screen state changes
                    display_log = data.get("display_log")
                    if display_log and old_screen_on is not None:
                        if old_screen_on and not new_screen_on:
                            # Screen turned off - close the current display session
                            display_log.note_screen_off(tv_id=tv_id, tv_name=tv_name)
                            _LOGGER.debug(f"Display log: Closed session for {tv_name} (screen off detected by poll)")
                        elif not old_screen_on and new_screen_on:
                            # Screen turned on - start a new session if we know the current image
                            # Get current image from shuffle_cache or config
                            shuffle_cache = data.get("shuffle_cache", {}).get(tv_id, {})
                            current_image = shuffle_cache.get("current_image")
                            if not current_image:
                                current_image = tv_config.get("current_image")
                            
                            if current_image:
                                # Try to get image tags from metadata
                                metadata_path = data.get("metadata_path")
                                image_tags: list[str] = []
                                if metadata_path:
                                    try:
                                        from .metadata import MetadataStore
                                        store = MetadataStore(metadata_path)
                                        image_meta = store.get_image(current_image)
                                        if image_meta:
                                            image_tags = list(image_meta.get("tags", []))
                                    except Exception:
                                        pass
                                
                                # Get TV's configured tags for matched_tags computation
                                tv_tags = tv_config.get("include_tags") if tv_config else None
                                
                                # Get matte and filter from shuffle_cache (may be None if not available)
                                current_matte = shuffle_cache.get("current_matte")
                                current_filter = shuffle_cache.get("current_filter")
                                
                                # Get active tagset name
                                tagset_name = get_active_tagset_name(entry, tv_id)
                                
                                display_log.note_screen_on(
                                    tv_id=tv_id,
                                    tv_name=tv_name,
                                    filename=current_image,
                                    tags=image_tags,
                                    tv_tags=tv_tags,
                                    matte=current_matte,
                                    photo_filter=current_filter,
                                    tagset_name=tagset_name,
                                )
                                _LOGGER.debug(f"Display log: Started session for {tv_name} (screen on detected by poll)")

    # Start polling
    cancel_poll = async_track_time_interval(
        hass,
        async_poll_tv_status,
        TV_STATUS_POLL_INTERVAL,
    )
    entry.async_on_unload(cancel_poll)

    # Do an initial poll
    hass.async_create_task(async_poll_tv_status(None))


class FrameArtScreenOnEntity(BinarySensorEntity):
    """Binary sensor for TV screen power state."""

    entity_description = SCREEN_ON_DESCRIPTION
    _attr_has_entity_name = True
    _attr_name = "Screen On"

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        tv_id: str,
    ) -> None:
        self._hass = hass
        self._tv_id = tv_id
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{tv_id}_screen_on"

        tv_config = get_tv_config(entry, tv_id)
        tv_name = tv_config.get("name", tv_id) if tv_config else tv_id

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tv_id)},
            name=tv_name,
            manufacturer="Samsung",
            model="Frame TV",
        )

    @property
    def is_on(self) -> bool | None:
        """Return True if the screen is on."""
        data = self._hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})
        status_cache = data.get("tv_status_cache", {})
        tv_status = status_cache.get(self._tv_id, {})
        return tv_status.get("screen_on")

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        # Available if we have a TV config
        return get_tv_config(self._entry, self._tv_id) is not None
