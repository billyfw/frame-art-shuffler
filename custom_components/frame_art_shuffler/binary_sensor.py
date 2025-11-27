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
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .config_entry import get_tv_config
from .const import DOMAIN
from .coordinator import FrameArtCoordinator
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

ART_MODE_DESCRIPTION = BinarySensorEntityDescription(
    key="art_mode",
    icon="mdi:palette",
    translation_key="art_mode",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities,
) -> None:
    """Set up Frame Art TV binary sensors for a config entry."""

    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: FrameArtCoordinator = data["coordinator"]

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
                "art_mode": None,
            }

            # Create binary sensors per TV
            screen_on_entity = FrameArtScreenOnEntity(hass, coordinator, entry, tv_id)
            art_mode_entity = FrameArtArtModeEntity(hass, coordinator, entry, tv_id)

            tracked[tv_id] = (screen_on_entity, art_mode_entity)
            new_entities.extend([screen_on_entity, art_mode_entity])

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

            # Check screen status (read-only REST call)
            try:
                screen_on = await hass.async_add_executor_job(
                    frame_tv.is_screen_on, ip, TV_STATUS_CHECK_TIMEOUT
                )
                tv_status_cache[tv_id]["screen_on"] = screen_on
            except Exception as err:
                _LOGGER.debug(f"Failed to check screen status for {tv_name}: {err}")
                # Don't clear the cache - keep last known value
                # Only set to None if we've never had a value
                if tv_status_cache[tv_id]["screen_on"] is None:
                    tv_status_cache[tv_id]["screen_on"] = None

            # Check art mode status (read-only WebSocket call)
            # Only check if screen appears to be on, to avoid unnecessary connections
            if tv_status_cache[tv_id]["screen_on"]:
                try:
                    art_mode = await hass.async_add_executor_job(
                        frame_tv.is_art_mode_enabled, ip
                    )
                    tv_status_cache[tv_id]["art_mode"] = art_mode
                except Exception as err:
                    _LOGGER.debug(f"Failed to check art mode for {tv_name}: {err}")
                
                # Fallback: Start motion off timer if TV is on but no timer exists
                # This catches external power-on (remote, app, etc.)
                if tv_config.get("enable_motion_control", False):
                    motion_off_times = data.get("motion_off_times", {})
                    if tv_id not in motion_off_times:
                        start_motion_off_timer = data.get("start_motion_off_timer")
                        if start_motion_off_timer:
                            start_motion_off_timer(tv_id)
                            _LOGGER.info(f"Auto motion: Started off timer for {tv_name} (external power-on detected)")
            else:
                # If screen is off, art mode check would fail anyway
                # Keep the last known art mode value or set to None
                pass

        # Trigger sensor updates
        for tv_id, entities in tracked.items():
            for entity in entities:
                entity.async_write_ha_state()

    # Start polling
    cancel_poll = async_track_time_interval(
        hass,
        async_poll_tv_status,
        TV_STATUS_POLL_INTERVAL,
    )
    entry.async_on_unload(cancel_poll)

    # Do an initial poll
    hass.async_create_task(async_poll_tv_status(None))


class FrameArtScreenOnEntity(CoordinatorEntity[FrameArtCoordinator], BinarySensorEntity):
    """Binary sensor for TV screen power state."""

    entity_description = SCREEN_ON_DESCRIPTION
    _attr_has_entity_name = True
    _attr_name = "Screen On"

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: FrameArtCoordinator,
        entry: ConfigEntry,
        tv_id: str,
    ) -> None:
        super().__init__(coordinator)
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


class FrameArtArtModeEntity(CoordinatorEntity[FrameArtCoordinator], BinarySensorEntity):
    """Binary sensor for TV art mode state."""

    entity_description = ART_MODE_DESCRIPTION
    _attr_has_entity_name = True
    _attr_name = "Art Mode"

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: FrameArtCoordinator,
        entry: ConfigEntry,
        tv_id: str,
    ) -> None:
        super().__init__(coordinator)
        self._hass = hass
        self._tv_id = tv_id
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{tv_id}_art_mode"

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
        """Return True if art mode is active."""
        data = self._hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})
        status_cache = data.get("tv_status_cache", {})
        tv_status = status_cache.get(self._tv_id, {})
        return tv_status.get("art_mode")

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        # Available if we have a TV config
        return get_tv_config(self._entry, self._tv_id) is not None
