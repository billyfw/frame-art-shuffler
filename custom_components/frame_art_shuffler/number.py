"""Number entities for Frame Art Shuffler TV configuration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .config_entry import get_tv_config, update_tv_config
from .const import DOMAIN
from .frame_tv import FrameArtError, set_tv_brightness
from .activity import log_activity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Frame Art number entities for a config entry."""
    # Read TV configs directly from entry (stored as dict with tv_id as key)
    tvs_dict = entry.data.get("tvs", {})
    
    entities: list[NumberEntity] = []
    for tv_id, tv in tvs_dict.items():
        if not tv_id:
            continue

        entities.extend([
            FrameArtShuffleFrequencyEntity(hass, entry, tv_id),
            FrameArtBrightnessEntity(hass, entry, tv_id),
            FrameArtMinLuxEntity(hass, entry, tv_id),
            FrameArtMaxLuxEntity(hass, entry, tv_id),
            FrameArtMinBrightnessEntity(hass, entry, tv_id),
            FrameArtMaxBrightnessEntity(hass, entry, tv_id),
            FrameArtMotionOffDelayEntity(hass, entry, tv_id),
        ])

    if entities:
        async_add_entities(entities)


class FrameArtShuffleFrequencyEntity(NumberEntity):
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
        hass: HomeAssistant,
        entry: ConfigEntry,
        tv_id: str,
    ) -> None:
        """Initialize the number entity."""
        self._hass = hass
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
        
        # Update UI to reflect new value
        self.async_write_ha_state()


class FrameArtBrightnessEntity(NumberEntity):
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
        hass: HomeAssistant,
        entry: ConfigEntry,
        tv_id: str,
    ) -> None:
        """Initialize the brightness number entity."""
        self._hass = hass
        self._tv_id = tv_id
        self._entry = entry
        self._last_known_value: float | None = None
        self._setting_brightness = False
        self._unsubscribe_brightness: Callable[[], None] | None = None

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

    async def async_added_to_hass(self) -> None:
        """Subscribe to brightness adjusted signals for real-time updates."""
        @callback
        def _brightness_adjusted() -> None:
            """Handle brightness adjusted signal from auto-brightness."""
            self.async_write_ha_state()
        
        signal = f"{DOMAIN}_brightness_adjusted_{self._entry.entry_id}_{self._tv_id}"
        self._unsubscribe_brightness = async_dispatcher_connect(
            self.hass,
            signal,
            _brightness_adjusted,
        )

    async def async_will_remove_from_hass(self) -> None:
        """Unsubscribe from brightness adjusted signals."""
        if self._unsubscribe_brightness:
            self._unsubscribe_brightness()
            self._unsubscribe_brightness = None

    @property
    def native_value(self) -> float | None:
        """Return the current brightness value from cache, config, or default."""
        # Check hass.data brightness cache first (updated by both auto and manual)
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
            
            # Log activity
            log_activity(
                self.hass, self._entry.entry_id, self._tv_id,
                "brightness_adjusted",
                f"Brightness → {target_value} (manual)",
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


class FrameArtMinLuxEntity(NumberEntity):
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
        hass: HomeAssistant,
        entry: ConfigEntry,
        tv_id: str,
    ) -> None:
        """Initialize the number entity."""
        self._hass = hass
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
        self.async_write_ha_state()


class FrameArtMaxLuxEntity(NumberEntity):
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
        hass: HomeAssistant,
        entry: ConfigEntry,
        tv_id: str,
    ) -> None:
        """Initialize the number entity."""
        self._hass = hass
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
        self.async_write_ha_state()


class FrameArtMinBrightnessEntity(NumberEntity):
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
        hass: HomeAssistant,
        entry: ConfigEntry,
        tv_id: str,
    ) -> None:
        """Initialize the number entity."""
        self._hass = hass
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
        self.async_write_ha_state()


class FrameArtMaxBrightnessEntity(NumberEntity):
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
        hass: HomeAssistant,
        entry: ConfigEntry,
        tv_id: str,
    ) -> None:
        """Initialize the number entity."""
        self._hass = hass
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
        self.async_write_ha_state()


class FrameArtMotionOffDelayEntity(NumberEntity):
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
        hass: HomeAssistant,
        entry: ConfigEntry,
        tv_id: str,
    ) -> None:
        """Initialize the number entity."""
        self._hass = hass
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
        self.async_write_ha_state()
