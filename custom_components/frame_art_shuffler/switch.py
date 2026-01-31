"""Switch entities for Frame Art Shuffler TV configuration."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .config_entry import get_tv_config, update_tv_config
from .const import DOMAIN, CONF_ENABLE_AUTO_SHUFFLE
from .frame_tv import tv_on, tv_off, set_art_mode, is_screen_on, FrameArtError
from .activity import log_activity

_LOGGER = logging.getLogger(__name__)

# Delay before polling TV state after power commands
# tv_off: hold_key takes 3s, then TV needs time to transition and REST API to stabilize
# tv_on: already has ~18s of delays built-in, just need a small buffer
_POWER_OFF_POLL_DELAY = 4  # seconds after tv_off completes
_POWER_ON_POLL_DELAY = 3   # seconds after set_art_mode completes
_STATUS_CHECK_TIMEOUT = 6  # timeout for status check (matches _SCREEN_CHECK_TIMEOUT)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Frame Art switch entities for a config entry."""
    # Read TV configs directly from entry (stored as dict with tv_id as key)
    tvs_dict = entry.data.get("tvs", {})
    
    entities: list[SwitchEntity] = []
    for tv_id, tv in tvs_dict.items():
        if not tv_id:
            continue

        entities.extend([
            FrameArtPowerSwitch(hass, entry, tv_id),
            FrameArtDynamicBrightnessSwitch(hass, entry, tv_id),
            FrameArtMotionControlSwitch(hass, entry, tv_id),
            FrameArtAutoShuffleSwitch(hass, entry, tv_id),
            FrameArtVerboseMotionLoggingSwitch(hass, entry, tv_id),
        ])

    if entities:
        async_add_entities(entities)


class FrameArtPowerSwitch(SwitchEntity):
    """Switch entity to control TV power with art mode.
    
    This combines the TV On button (Wake-on-LAN + art mode) and TV Off button
    (screen off while staying in art mode) into a single toggle switch that
    also reflects the current screen state.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:television"
    _attr_name = "Power"
    _attr_device_class = SwitchDeviceClass.SWITCH  # Standard toggle switch

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        tv_id: str,
    ) -> None:
        """Initialize the power switch entity."""
        self._hass = hass
        self._tv_id = tv_id
        self._entry = entry

        tv_config = get_tv_config(entry, tv_id)
        if tv_config:
            self._tv_name = tv_config.get("name", tv_id)
            self._tv_ip = tv_config.get("ip")
            self._tv_mac = tv_config.get("mac")
        else:
            self._tv_name = tv_id
            self._tv_ip = None
            self._tv_mac = None

        self._attr_unique_id = f"{tv_id}_power"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tv_id)},
            name=self._tv_name,
            manufacturer="Samsung",
            model="Frame TV",
        )

    @property
    def is_on(self) -> bool:
        """Return true if the TV screen is on."""
        data = self._hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})
        status_cache = data.get("tv_status_cache", {})
        tv_status = status_cache.get(self._tv_id, {})
        # Return False if unknown - prevents "unknown" state lightning bolt icon
        return tv_status.get("screen_on") or False

    async def _async_poll_and_update_state(self, delay: float) -> None:
        """Poll TV state after a delay and update the cache.
        
        This confirms the actual TV state after a power command, updating both
        the status cache and any binary sensors that depend on it.
        """
        await asyncio.sleep(delay)
        
        try:
            # Poll screen status
            screen_on = await self._hass.async_add_executor_job(
                is_screen_on, self._tv_ip, _STATUS_CHECK_TIMEOUT
            )
            
            # Update the cache with confirmed state
            data = self._hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})
            status_cache = data.get("tv_status_cache", {})
            if self._tv_id in status_cache:
                status_cache[self._tv_id]["screen_on"] = screen_on
            
            _LOGGER.debug(
                f"Power switch poll for {self._tv_name}: screen_on={screen_on}"
            )
            
            # Trigger state update for this switch and binary sensors
            self.async_write_ha_state()
            
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.debug(f"Power switch poll failed for {self._tv_name}: {err}")
            # Keep optimistic state on failure - next regular poll will correct if needed

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the TV and switch to art mode."""
        if not self._tv_ip or not self._tv_mac:
            _LOGGER.error(f"Cannot turn on {self._tv_name}: missing IP or MAC address in config")
            return

        try:
            # First turn on the TV via Wake-on-LAN
            await self._hass.async_add_executor_job(tv_on, self._tv_ip, self._tv_mac)
            _LOGGER.info(f"Sent Wake-on-LAN to {self._tv_name}, waiting for TV to be ready...")
            
            # tv_on already includes the ~12 second wait for the TV to be ready
            # Now switch to art mode
            await self._hass.async_add_executor_job(set_art_mode, self._tv_ip)
            _LOGGER.info(f"Switched {self._tv_name} to art mode")
            
            # Optimistically update the status cache so UI doesn't flip back
            data = self._hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})
            status_cache = data.get("tv_status_cache", {})
            if self._tv_id in status_cache:
                status_cache[self._tv_id]["screen_on"] = True
            self.async_write_ha_state()
            
            # Schedule a delayed poll to confirm actual state and sync binary sensors
            # tv_on + set_art_mode already waited ~18s, just need small buffer for REST API
            self._hass.async_create_task(
                self._async_poll_and_update_state(_POWER_ON_POLL_DELAY)
            )
            
            # Log activity
            log_activity(
                self._hass, self._entry.entry_id, self._tv_id,
                "screen_on",
                "Screen turned on (power switch)",
            )
            
            # Start motion off timer if auto-motion is enabled
            tv_config = get_tv_config(self._entry, self._tv_id)
            if tv_config and tv_config.get("enable_motion_control", False):
                data = self._hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})
                start_motion_off_timer = data.get("start_motion_off_timer")
                if start_motion_off_timer:
                    start_motion_off_timer(self._tv_id)
                    _LOGGER.debug(f"Started motion off timer for {self._tv_name} after power on")
        except FrameArtError as err:
            _LOGGER.error(f"Failed to turn on {self._tv_name}: {err}")

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the TV screen (stays in art mode)."""
        if not self._tv_ip:
            _LOGGER.error(f"Cannot turn off {self._tv_name}: missing IP address in config")
            return

        try:
            await self._hass.async_add_executor_job(tv_off, self._tv_ip)
            _LOGGER.info(f"Turned off {self._tv_name} screen")
            
            # Optimistically update the status cache so UI doesn't flip back
            data = self._hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})
            status_cache = data.get("tv_status_cache", {})
            if self._tv_id in status_cache:
                status_cache[self._tv_id]["screen_on"] = False
            self.async_write_ha_state()
            
            # Schedule a delayed poll to confirm actual state and sync binary sensors
            # tv_off hold_key takes 3s, then TV needs time to transition and REST API to stabilize
            self._hass.async_create_task(
                self._async_poll_and_update_state(_POWER_OFF_POLL_DELAY)
            )
            
            # Log activity
            log_activity(
                self._hass, self._entry.entry_id, self._tv_id,
                "screen_off",
                "Screen turned off (power switch)",
            )
            
            # Cancel motion off timer since TV is now off
            tv_config = get_tv_config(self._entry, self._tv_id)
            if tv_config and tv_config.get("enable_motion_control", False):
                data = self._hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})
                cancel_motion_off_timer = data.get("cancel_motion_off_timer")
                if cancel_motion_off_timer:
                    cancel_motion_off_timer(self._tv_id)
                    _LOGGER.debug(f"Cancelled motion off timer for {self._tv_name} after power off")
        except FrameArtError as err:
            _LOGGER.error(f"Failed to turn off {self._tv_name}: {err}")


class FrameArtDynamicBrightnessSwitch(SwitchEntity):
    """Switch entity to enable/disable auto brightness automation."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:brightness-auto"
    _attr_name = "Auto-Bright Enable"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        tv_id: str,
    ) -> None:
        """Initialize the switch entity."""
        self._hass = hass
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
        
        log_activity(
            self.hass, self._entry.entry_id, self._tv_id,
            "auto_brightness_enabled",
            "Auto-brightness enabled",
        )
        self.async_write_ha_state()

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
        
        log_activity(
            self.hass, self._entry.entry_id, self._tv_id,
            "auto_brightness_disabled",
            "Auto-brightness disabled",
        )
        self.async_write_ha_state()


class FrameArtMotionControlSwitch(SwitchEntity):
    """Switch entity to enable/disable auto motion TV on/off control."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:motion-sensor"
    _attr_name = "Auto-Motion Enable"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        tv_id: str,
    ) -> None:
        """Initialize the switch entity."""
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
        
        log_activity(
            self.hass, self._entry.entry_id, self._tv_id,
            "auto_motion_enabled",
            "Auto-motion enabled",
        )
        self.async_write_ha_state()

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
        
        log_activity(
            self.hass, self._entry.entry_id, self._tv_id,
            "auto_motion_disabled",
            "Auto-motion disabled",
        )
        self.async_write_ha_state()


class FrameArtAutoShuffleSwitch(SwitchEntity):
    """Switch entity to enable/disable automatic shuffling."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:shuffle-variant"
    _attr_name = "Auto-Shuffle Enable"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        tv_id: str,
    ) -> None:
        self._hass = hass
        self._entry = entry
        self._tv_id = tv_id

        tv_config = get_tv_config(entry, tv_id)
        tv_name = tv_config.get("name", tv_id) if tv_config else tv_id

        self._attr_unique_id = f"{tv_id}_auto_shuffle"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tv_id)},
            name=tv_name,
            manufacturer="Samsung",
            model="Frame TV",
        )

    @property
    def is_on(self) -> bool:
        tv_config = get_tv_config(self._entry, self._tv_id)
        if not tv_config:
            return False
        return tv_config.get(CONF_ENABLE_AUTO_SHUFFLE, False)

    async def async_turn_on(self, **kwargs: Any) -> None:
        update_tv_config(
            self.hass,
            self._entry,
            self._tv_id,
            {CONF_ENABLE_AUTO_SHUFFLE: True},
        )

        data = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id)
        if data:
            starter = data.get("start_auto_shuffle_timer")
            if starter:
                starter(self._tv_id)

            # Trigger immediate shuffle to start fresh session
            # (respects skip_if_screen_off - won't shuffle if TV is off)
            runner = data.get("async_run_auto_shuffle")
            if runner:
                await runner(self._tv_id)

        log_activity(
            self.hass,
            self._entry.entry_id,
            self._tv_id,
            "auto_shuffle_enabled",
            "Auto-shuffle enabled",
        )
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        data = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id)
        if data:
            # End the current display session before canceling the timer
            # This prevents inflated display times when TV is used for other purposes
            display_log = data.get("display_log")
            if display_log:
                tv_config = get_tv_config(self._entry, self._tv_id)
                tv_name = tv_config.get("name", self._tv_id) if tv_config else self._tv_id
                display_log.note_auto_shuffle_disabled(tv_id=self._tv_id, tv_name=tv_name)

            canceller = data.get("cancel_auto_shuffle_timer")
            if canceller:
                canceller(self._tv_id)

        update_tv_config(
            self.hass,
            self._entry,
            self._tv_id,
            {CONF_ENABLE_AUTO_SHUFFLE: False},
        )
        log_activity(
            self.hass,
            self._entry.entry_id,
            self._tv_id,
            "auto_shuffle_disabled",
            "Auto-shuffle disabled",
        )
        self.async_write_ha_state()


class FrameArtVerboseMotionLoggingSwitch(SwitchEntity):
    """Switch entity to enable/disable verbose motion detection logging.
    
    When enabled, logs every motion detection event (including timer resets)
    to the activity history. Useful for debugging multi-sensor setups.
    """

    _attr_has_entity_name = True
    _attr_icon = "mdi:motion-sensor"
    _attr_name = "Verbose Motion Logging"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        tv_id: str,
    ) -> None:
        """Initialize the switch entity."""
        self._hass = hass
        self._tv_id = tv_id
        self._entry = entry

        tv_config = get_tv_config(entry, tv_id)
        tv_name = tv_config.get("name", tv_id) if tv_config else tv_id

        self._attr_unique_id = f"{tv_id}_verbose_motion_logging"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tv_id)},
            name=tv_name,
            manufacturer="Samsung",
            model="Frame TV",
        )

    @property
    def is_on(self) -> bool:
        """Return true if verbose motion logging is enabled."""
        tv_config = get_tv_config(self._entry, self._tv_id)
        if not tv_config:
            return False
        return tv_config.get("verbose_motion_logging", False)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable verbose motion logging."""
        update_tv_config(
            self.hass,
            self._entry,
            self._tv_id,
            {"verbose_motion_logging": True},
        )
        tv_config = get_tv_config(self._entry, self._tv_id)
        tv_name = tv_config.get("name", self._tv_id) if tv_config else self._tv_id
        _LOGGER.info(f"Enabled verbose motion logging for {tv_name}")
        log_activity(
            self.hass, self._entry.entry_id, self._tv_id,
            "verbose_motion_enabled",
            "Verbose motion logging enabled",
        )
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable verbose motion logging."""
        update_tv_config(
            self.hass,
            self._entry,
            self._tv_id,
            {"verbose_motion_logging": False},
        )
        tv_config = get_tv_config(self._entry, self._tv_id)
        tv_name = tv_config.get("name", self._tv_id) if tv_config else self._tv_id
        _LOGGER.info(f"Disabled verbose motion logging for {tv_name}")
        log_activity(
            self.hass, self._entry.entry_id, self._tv_id,
            "verbose_motion_disabled",
            "Verbose motion logging disabled",
        )
        self.async_write_ha_state()
