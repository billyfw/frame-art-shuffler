"""Switch entities for Frame Art Shuffler TV configuration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .config_entry import get_tv_config, update_tv_config
from .const import DOMAIN
from .coordinator import FrameArtCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Frame Art switch entities for a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: FrameArtCoordinator = data["coordinator"]

    tracked_dynamic_brightness: dict[str, FrameArtDynamicBrightnessSwitch] = {}
    tracked_motion_control: dict[str, FrameArtMotionControlSwitch] = {}

    @callback
    def _process_tvs(tvs: list[dict[str, Any]]) -> None:
        new_entities: list[SwitchEntity] = []
        current_tv_ids = {tv.get("id") for tv in tvs if tv.get("id")}

        # Remove entities for TVs that no longer exist
        for tv_id in list(tracked_dynamic_brightness.keys()):
            if tv_id not in current_tv_ids:
                tracked_dynamic_brightness.pop(tv_id)
        for tv_id in list(tracked_motion_control.keys()):
            if tv_id not in current_tv_ids:
                tracked_motion_control.pop(tv_id)

        # Add entities for new TVs
        for tv in tvs:
            tv_id = tv.get("id")
            if not tv_id:
                continue

            # Add dynamic brightness switch
            if tv_id not in tracked_dynamic_brightness:
                entity = FrameArtDynamicBrightnessSwitch(coordinator, entry, tv_id)
                tracked_dynamic_brightness[tv_id] = entity
                new_entities.append(entity)

            # Add motion control switch
            if tv_id not in tracked_motion_control:
                entity = FrameArtMotionControlSwitch(hass, coordinator, entry, tv_id)
                tracked_motion_control[tv_id] = entity
                new_entities.append(entity)

        if new_entities:
            async_add_entities(new_entities)

    coordinator.async_add_listener(lambda: _process_tvs(coordinator.data or []))
    _process_tvs(coordinator.data or [])


class FrameArtDynamicBrightnessSwitch(CoordinatorEntity, SwitchEntity):
    """Switch entity to enable/disable auto brightness automation."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:brightness-auto"
    _attr_name = "Auto-Bright Enable"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: FrameArtCoordinator,
        entry: ConfigEntry,
        tv_id: str,
    ) -> None:
        """Initialize the switch entity."""
        super().__init__(coordinator)
        self._tv_id = tv_id
        self._entry = entry

        tv_config = get_tv_config(entry, tv_id)
        tv_name = tv_config.get("name", tv_id) if tv_config else tv_id

        self._attr_unique_id = f"{tv_id}_dynamic_brightness"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tv_id)},
            name=tv_name,
            manufacturer="Samsung",
            model="Frame TV",
        )

    @property
    def is_on(self) -> bool:
        """Return true if dynamic brightness is enabled."""
        tv_config = get_tv_config(self._entry, self._tv_id)
        if not tv_config:
            return False
        return tv_config.get("enable_dynamic_brightness", False)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable auto brightness."""
        update_tv_config(
            self.hass,
            self._entry,
            self._tv_id,
            {"enable_dynamic_brightness": True},
        )
        
        # Start the per-TV timer
        data = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id)
        if data and "start_tv_timer" in data:
            data["start_tv_timer"](self._tv_id)
        
        tv_config = get_tv_config(self._entry, self._tv_id)
        tv_name = tv_config.get("name", self._tv_id) if tv_config else self._tv_id
        _LOGGER.info(f"Enabled auto brightness for {tv_name}")
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable auto brightness."""
        # Cancel the per-TV timer first
        data = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id)
        if data and "cancel_tv_timer" in data:
            data["cancel_tv_timer"](self._tv_id)
        
        update_tv_config(
            self.hass,
            self._entry,
            self._tv_id,
            {"enable_dynamic_brightness": False},
        )
        tv_config = get_tv_config(self._entry, self._tv_id)
        tv_name = tv_config.get("name", self._tv_id) if tv_config else self._tv_id
        _LOGGER.info(f"Disabled auto brightness for {tv_name}")
        await self.coordinator.async_request_refresh()


class FrameArtMotionControlSwitch(CoordinatorEntity, SwitchEntity):
    """Switch entity to enable/disable auto motion TV on/off control."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:motion-sensor"
    _attr_name = "Auto-Motion Enable"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: FrameArtCoordinator,
        entry: ConfigEntry,
        tv_id: str,
    ) -> None:
        """Initialize the switch entity."""
        super().__init__(coordinator)
        self._hass = hass
        self._tv_id = tv_id
        self._entry = entry

        tv_config = get_tv_config(entry, tv_id)
        tv_name = tv_config.get("name", tv_id) if tv_config else tv_id

        self._attr_unique_id = f"{tv_id}_motion_control"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tv_id)},
            name=tv_name,
            manufacturer="Samsung",
            model="Frame TV",
        )

    @property
    def is_on(self) -> bool:
        """Return true if motion control is enabled."""
        tv_config = get_tv_config(self._entry, self._tv_id)
        if not tv_config:
            return False
        return tv_config.get("enable_motion_control", False)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable auto motion control."""
        update_tv_config(
            self.hass,
            self._entry,
            self._tv_id,
            {"enable_motion_control": True},
        )
        
        # Start motion listener for this TV
        data = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id)
        if data and "start_motion_listener" in data:
            data["start_motion_listener"](self._tv_id)
        
        tv_config = get_tv_config(self._entry, self._tv_id)
        tv_name = tv_config.get("name", self._tv_id) if tv_config else self._tv_id
        _LOGGER.info(f"Enabled auto motion control for {tv_name}")
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable auto motion control."""
        # Stop motion listener first
        data = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id)
        if data and "stop_motion_listener" in data:
            data["stop_motion_listener"](self._tv_id)
        
        update_tv_config(
            self.hass,
            self._entry,
            self._tv_id,
            {"enable_motion_control": False},
        )
        tv_config = get_tv_config(self._entry, self._tv_id)
        tv_name = tv_config.get("name", self._tv_id) if tv_config else self._tv_id
        _LOGGER.info(f"Disabled auto motion control for {tv_name}")
        await self.coordinator.async_request_refresh()
