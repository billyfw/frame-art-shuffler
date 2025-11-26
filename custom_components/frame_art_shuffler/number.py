"""Number entities for Frame Art Shuffler TV configuration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .config_entry import get_tv_config, update_tv_config
from .const import DOMAIN
from .coordinator import FrameArtCoordinator
from .frame_tv import FrameArtError, set_tv_brightness

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Frame Art number entities for a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: FrameArtCoordinator = data["coordinator"]

    tracked_frequency: dict[str, FrameArtShuffleFrequencyEntity] = {}
    tracked_brightness: dict[str, FrameArtBrightnessEntity] = {}
    tracked_min_lux: dict[str, FrameArtMinLuxEntity] = {}
    tracked_max_lux: dict[str, FrameArtMaxLuxEntity] = {}
    tracked_min_brightness: dict[str, FrameArtMinBrightnessEntity] = {}
    tracked_max_brightness: dict[str, FrameArtMaxBrightnessEntity] = {}
    tracked_motion_off_delay: dict[str, FrameArtMotionOffDelayEntity] = {}

    @callback
    def _process_tvs(tvs: list[dict[str, Any]]) -> None:
        new_entities: list[NumberEntity] = []
        current_tv_ids = {tv.get("id") for tv in tvs if tv.get("id")}

        # Remove entities for TVs that no longer exist
        for tv_id in list(tracked_frequency.keys()):
            if tv_id not in current_tv_ids:
                tracked_frequency.pop(tv_id)
        for tv_id in list(tracked_brightness.keys()):
            if tv_id not in current_tv_ids:
                tracked_brightness.pop(tv_id)
        for tv_id in list(tracked_min_lux.keys()):
            if tv_id not in current_tv_ids:
                tracked_min_lux.pop(tv_id)
        for tv_id in list(tracked_max_lux.keys()):
            if tv_id not in current_tv_ids:
                tracked_max_lux.pop(tv_id)
        for tv_id in list(tracked_min_brightness.keys()):
            if tv_id not in current_tv_ids:
                tracked_min_brightness.pop(tv_id)
        for tv_id in list(tracked_max_brightness.keys()):
            if tv_id not in current_tv_ids:
                tracked_max_brightness.pop(tv_id)
        for tv_id in list(tracked_motion_off_delay.keys()):
            if tv_id not in current_tv_ids:
                tracked_motion_off_delay.pop(tv_id)

        # Add entities for new TVs
        for tv in tvs:
            tv_id = tv.get("id")
            if not tv_id:
                continue

            # Add shuffle frequency entity
            if tv_id not in tracked_frequency:
                entity = FrameArtShuffleFrequencyEntity(
                    coordinator,
                    entry,
                    tv_id,
                )
                tracked_frequency[tv_id] = entity
                new_entities.append(entity)

            # Add brightness entity
            if tv_id not in tracked_brightness:
                entity = FrameArtBrightnessEntity(
                    coordinator,
                    entry,
                    tv_id,
                )
                tracked_brightness[tv_id] = entity
                new_entities.append(entity)

            # Add min lux entity
            if tv_id not in tracked_min_lux:
                entity = FrameArtMinLuxEntity(coordinator, entry, tv_id)
                tracked_min_lux[tv_id] = entity
                new_entities.append(entity)

            # Add max lux entity
            if tv_id not in tracked_max_lux:
                entity = FrameArtMaxLuxEntity(coordinator, entry, tv_id)
                tracked_max_lux[tv_id] = entity
                new_entities.append(entity)

            # Add min brightness entity
            if tv_id not in tracked_min_brightness:
                entity = FrameArtMinBrightnessEntity(coordinator, entry, tv_id)
                tracked_min_brightness[tv_id] = entity
                new_entities.append(entity)

            # Add max brightness entity
            if tv_id not in tracked_max_brightness:
                entity = FrameArtMaxBrightnessEntity(coordinator, entry, tv_id)
                tracked_max_brightness[tv_id] = entity
                new_entities.append(entity)

            # Add motion off delay entity
            if tv_id not in tracked_motion_off_delay:
                entity = FrameArtMotionOffDelayEntity(coordinator, entry, tv_id)
                tracked_motion_off_delay[tv_id] = entity
                new_entities.append(entity)

        if new_entities:
            async_add_entities(new_entities)

    coordinator.async_add_listener(lambda: _process_tvs(coordinator.data or []))
    _process_tvs(coordinator.data or [])


class FrameArtShuffleFrequencyEntity(CoordinatorEntity, NumberEntity):
    """Number entity for TV shuffle frequency in minutes."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:clock-outline"
    _attr_native_min_value = 1
    _attr_native_max_value = 10080  # 7 days
    _attr_native_step = 1.0
    _attr_mode = NumberMode.BOX
    _attr_native_unit_of_measurement = "min"
    _attr_name = "Shuffle Frequency"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: FrameArtCoordinator,
        entry: ConfigEntry,
        tv_id: str,
    ) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator)
        self._tv_id = tv_id
        self._entry = entry

        # Get TV name from config entry
        tv_config = get_tv_config(entry, tv_id)
        tv_name = tv_config.get("name", tv_id) if tv_config else tv_id
        
        # Use tv_id as identifier (no home prefix)
        identifier = tv_id

        self._attr_unique_id = f"{tv_id}_shuffle_frequency"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, identifier)},
            name=tv_name,
            manufacturer="Samsung",
            model="Frame TV",
        )

    @property
    def native_value(self) -> float | None:
        """Return the current value from config entry."""
        tv_config = get_tv_config(self._entry, self._tv_id)
        if not tv_config:
            return None
        return float(tv_config.get("shuffle_frequency_minutes", 60))

    async def async_set_native_value(self, value: float) -> None:
        """Update the shuffle frequency in config entry."""
        # Update HA storage
        update_tv_config(
            self.hass,
            self._entry,
            self._tv_id,
            {"shuffle_frequency_minutes": int(value)},
        )
        
        # Get TV config for logging
        tv_config = get_tv_config(self._entry, self._tv_id)
        tv_name = tv_config.get("name", self._tv_id) if tv_config else self._tv_id
        
        _LOGGER.info(
            "Shuffle frequency changed to %d minutes for %s",
            int(value),
            tv_name,
        )
        
        # TODO: Reschedule shuffle timer when scheduler is implemented
        
        # Refresh coordinator
        await self.coordinator.async_request_refresh()


class FrameArtBrightnessEntity(CoordinatorEntity, NumberEntity):
    """Number entity for TV art mode brightness (1-10)."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:brightness-6"
    _attr_native_min_value = 1
    _attr_native_max_value = 10
    _attr_native_step = 1.0
    _attr_mode = NumberMode.SLIDER
    _attr_name = "Brightness"

    def __init__(
        self,
        coordinator: FrameArtCoordinator,
        entry: ConfigEntry,
        tv_id: str,
    ) -> None:
        """Initialize the brightness number entity."""
        super().__init__(coordinator)
        self._tv_id = tv_id
        self._entry = entry
        self._last_known_value: float | None = None
        self._setting_brightness = False

        # Get TV details from config entry
        tv_config = get_tv_config(entry, tv_id)
        tv_name = tv_config.get("name", tv_id) if tv_config else tv_id
        
        self._attr_unique_id = f"{tv_id}_brightness"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tv_id)},
            name=tv_name,
            manufacturer="Samsung",
            model="Frame TV",
        )

    @property
    def native_value(self) -> float | None:
        """Return the current brightness value from cache, config, or default."""
        # Check hass.data brightness cache first (updated by both auto and manual)
        from .const import DOMAIN
        data = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})
        brightness_cache = data.get("brightness_cache", {})
        cached_brightness = brightness_cache.get(self._tv_id)
        if cached_brightness is not None:
            return float(cached_brightness)
        
        # Fall back to config (persisted by auto-brightness, survives restart)
        tv_config = get_tv_config(self._entry, self._tv_id)
        if tv_config:
            persisted = tv_config.get("current_brightness")
            if persisted is not None:
                # Populate cache so we use it next time
                brightness_cache = data.setdefault("brightness_cache", {})
                brightness_cache[self._tv_id] = persisted
                return float(persisted)
        
        # Default to middle value
        return 5.0

    async def async_set_native_value(self, value: float) -> None:
        """Set the TV brightness with automatic rollback on failure."""
        tv_config = get_tv_config(self._entry, self._tv_id)
        if not tv_config:
            _LOGGER.error("TV config not found for %s", self._tv_id)
            return
        
        tv_ip = tv_config.get("ip")
        tv_name = tv_config.get("name", self._tv_id)
        
        if not tv_ip:
            _LOGGER.error("TV IP not found for %s", tv_name)
            return
        
        # Store the value we're attempting to set
        previous_value = self._last_known_value
        target_value = int(value)
        
        # Set flag to prevent UI jumping during operation
        self._setting_brightness = True
        
        try:
            _LOGGER.debug(
                "Setting brightness to %d for %s (IP: %s)",
                target_value,
                tv_name,
                tv_ip,
            )
            
            # Run the brightness change in executor to avoid blocking
            await self.hass.async_add_executor_job(
                set_tv_brightness,
                tv_ip,
                target_value,
            )
            
            # Success! Update the cache and persist to config
            self._last_known_value = float(target_value)
            
            # Update hass.data cache for immediate entity sync
            from .const import DOMAIN
            data = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})
            brightness_cache = data.setdefault("brightness_cache", {})
            brightness_cache[self._tv_id] = target_value
            
            # Persist to config so it survives restart
            from .config_entry import update_tv_config
            update_tv_config(
                self.hass,
                self._entry,
                self._tv_id,
                {"current_brightness": target_value},
            )
            
            _LOGGER.info(
                "Brightness set to %d for %s",
                target_value,
                tv_name,
            )
            
        except FrameArtError as err:
            # TV communication failed - revert to previous value
            _LOGGER.warning(
                "Failed to set brightness for %s: %s (reverting to %s)",
                tv_name,
                err,
                previous_value,
            )
            # Keep previous value in cache
            if previous_value is not None:
                self._last_known_value = previous_value
        
        except Exception as err:  # pylint: disable=broad-except
            # Unexpected error - revert to previous value
            _LOGGER.error(
                "Unexpected error setting brightness for %s: %s (reverting to %s)",
                tv_name,
                err,
                previous_value,
            )
            if previous_value is not None:
                self._last_known_value = previous_value
        
        finally:
            # Clear the setting flag and force a state update
            self._setting_brightness = False
            self.async_write_ha_state()


class FrameArtMinLuxEntity(CoordinatorEntity, NumberEntity):
    """Number entity for min lux configuration (darkest room value)."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:brightness-5"
    _attr_native_min_value = 0
    _attr_native_max_value = 100000
    _attr_native_step = 1.0
    _attr_mode = NumberMode.BOX
    _attr_native_unit_of_measurement = "lx"
    _attr_name = "Auto-Bright Min Lux"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: FrameArtCoordinator,
        entry: ConfigEntry,
        tv_id: str,
    ) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator)
        self._tv_id = tv_id
        self._entry = entry

        tv_config = get_tv_config(entry, tv_id)
        tv_name = tv_config.get("name", tv_id) if tv_config else tv_id

        self._attr_unique_id = f"{tv_id}_min_lux"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tv_id)},
            name=tv_name,
            manufacturer="Samsung",
            model="Frame TV",
        )

    @property
    def native_value(self) -> float | None:
        """Return the current value from config entry."""
        tv_config = get_tv_config(self._entry, self._tv_id)
        if not tv_config:
            return None
        return float(tv_config.get("min_lux", 0))

    async def async_set_native_value(self, value: float) -> None:
        """Update the min lux in config entry."""
        update_tv_config(
            self.hass,
            self._entry,
            self._tv_id,
            {"min_lux": int(value)},
        )
        await self.coordinator.async_request_refresh()


class FrameArtMaxLuxEntity(CoordinatorEntity, NumberEntity):
    """Number entity for max lux configuration (brightest room value)."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:brightness-7"
    _attr_native_min_value = 0
    _attr_native_max_value = 100000
    _attr_native_step = 1.0
    _attr_mode = NumberMode.BOX
    _attr_native_unit_of_measurement = "lx"
    _attr_name = "Auto-Bright Max Lux"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: FrameArtCoordinator,
        entry: ConfigEntry,
        tv_id: str,
    ) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator)
        self._tv_id = tv_id
        self._entry = entry

        tv_config = get_tv_config(entry, tv_id)
        tv_name = tv_config.get("name", tv_id) if tv_config else tv_id

        self._attr_unique_id = f"{tv_id}_max_lux"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tv_id)},
            name=tv_name,
            manufacturer="Samsung",
            model="Frame TV",
        )

    @property
    def native_value(self) -> float | None:
        """Return the current value from config entry."""
        tv_config = get_tv_config(self._entry, self._tv_id)
        if not tv_config:
            return None
        return float(tv_config.get("max_lux", 1000))

    async def async_set_native_value(self, value: float) -> None:
        """Update the max lux in config entry."""
        update_tv_config(
            self.hass,
            self._entry,
            self._tv_id,
            {"max_lux": int(value)},
        )
        await self.coordinator.async_request_refresh()


class FrameArtMinBrightnessEntity(CoordinatorEntity, NumberEntity):
    """Number entity for min auto brightness (brightness at darkest)."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:brightness-4"
    _attr_native_min_value = 1
    _attr_native_max_value = 10
    _attr_native_step = 1.0
    _attr_mode = NumberMode.SLIDER
    _attr_name = "Auto-Bright Min Level"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: FrameArtCoordinator,
        entry: ConfigEntry,
        tv_id: str,
    ) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator)
        self._tv_id = tv_id
        self._entry = entry

        tv_config = get_tv_config(entry, tv_id)
        tv_name = tv_config.get("name", tv_id) if tv_config else tv_id

        self._attr_unique_id = f"{tv_id}_min_auto_brightness"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tv_id)},
            name=tv_name,
            manufacturer="Samsung",
            model="Frame TV",
        )

    @property
    def native_value(self) -> float | None:
        """Return the current value from config entry."""
        tv_config = get_tv_config(self._entry, self._tv_id)
        if not tv_config:
            return None
        return float(tv_config.get("min_brightness", 1))

    async def async_set_native_value(self, value: float) -> None:
        """Update the min brightness in config entry."""
        update_tv_config(
            self.hass,
            self._entry,
            self._tv_id,
            {"min_brightness": int(value)},
        )
        await self.coordinator.async_request_refresh()


class FrameArtMaxBrightnessEntity(CoordinatorEntity, NumberEntity):
    """Number entity for max auto brightness (brightness at brightest)."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:brightness-7"
    _attr_native_min_value = 1
    _attr_native_max_value = 10
    _attr_native_step = 1.0
    _attr_mode = NumberMode.SLIDER
    _attr_name = "Auto-Bright Max Level"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: FrameArtCoordinator,
        entry: ConfigEntry,
        tv_id: str,
    ) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator)
        self._tv_id = tv_id
        self._entry = entry

        tv_config = get_tv_config(entry, tv_id)
        tv_name = tv_config.get("name", tv_id) if tv_config else tv_id

        self._attr_unique_id = f"{tv_id}_max_auto_brightness"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tv_id)},
            name=tv_name,
            manufacturer="Samsung",
            model="Frame TV",
        )

    @property
    def native_value(self) -> float | None:
        """Return the current value from config entry."""
        tv_config = get_tv_config(self._entry, self._tv_id)
        if not tv_config:
            return None
        return float(tv_config.get("max_brightness", 10))

    async def async_set_native_value(self, value: float) -> None:
        """Update the max brightness in config entry."""
        update_tv_config(
            self.hass,
            self._entry,
            self._tv_id,
            {"max_brightness": int(value)},
        )
        await self.coordinator.async_request_refresh()


class FrameArtMotionOffDelayEntity(CoordinatorEntity, NumberEntity):
    """Number entity for auto-motion off delay in minutes."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:timer-off-outline"
    _attr_native_min_value = 1
    _attr_native_max_value = 120
    _attr_native_step = 1.0
    _attr_mode = NumberMode.BOX
    _attr_native_unit_of_measurement = "min"
    _attr_name = "Auto-Motion Off Delay"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: FrameArtCoordinator,
        entry: ConfigEntry,
        tv_id: str,
    ) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator)
        self._tv_id = tv_id
        self._entry = entry

        tv_config = get_tv_config(entry, tv_id)
        tv_name = tv_config.get("name", tv_id) if tv_config else tv_id

        self._attr_unique_id = f"{tv_id}_motion_off_delay"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tv_id)},
            name=tv_name,
            manufacturer="Samsung",
            model="Frame TV",
        )

    @property
    def native_value(self) -> float | None:
        """Return the current value from config entry."""
        tv_config = get_tv_config(self._entry, self._tv_id)
        if not tv_config:
            return None
        return float(tv_config.get("motion_off_delay", 15))

    async def async_set_native_value(self, value: float) -> None:
        """Update the motion off delay in config entry."""
        update_tv_config(
            self.hass,
            self._entry,
            self._tv_id,
            {"motion_off_delay": int(value)},
        )
        await self.coordinator.async_request_refresh()
