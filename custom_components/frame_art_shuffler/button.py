"""Button entities for Frame Art Shuffler TV management."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers import device_registry as dr

from .config_entry import get_tv_config
from .const import DOMAIN
from .coordinator import FrameArtCoordinator
from .frame_tv import tv_on, tv_off, FrameArtError

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Frame Art button entities for a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: FrameArtCoordinator = data["coordinator"]

    tracked_remove: dict[str, FrameArtRemoveTVButton] = {}
    tracked_on: dict[str, FrameArtTVOnButton] = {}
    tracked_off: dict[str, FrameArtTVOffButton] = {}

    @callback
    def _process_tvs(tvs: list[dict[str, Any]]) -> None:
        new_entities: list[ButtonEntity] = []
        current_tv_ids = {tv.get("id") for tv in tvs if tv.get("id")}

        # Remove entities for TVs that no longer exist
        for tv_id in list(tracked_remove.keys()):
            if tv_id not in current_tv_ids:
                tracked_remove.pop(tv_id)
        for tv_id in list(tracked_on.keys()):
            if tv_id not in current_tv_ids:
                tracked_on.pop(tv_id)
        for tv_id in list(tracked_off.keys()):
            if tv_id not in current_tv_ids:
                tracked_off.pop(tv_id)

        # Add entities for new TVs
        for tv in tvs:
            tv_id = tv.get("id")
            if not tv_id:
                continue
            
            # Add remove button
            if tv_id not in tracked_remove:
                entity = FrameArtRemoveTVButton(coordinator, entry, tv_id)
                tracked_remove[tv_id] = entity
                new_entities.append(entity)
            
            # Add TV On button
            if tv_id not in tracked_on:
                entity = FrameArtTVOnButton(coordinator, entry, tv_id)
                tracked_on[tv_id] = entity
                new_entities.append(entity)
            
            # Add TV Off button
            if tv_id not in tracked_off:
                entity = FrameArtTVOffButton(coordinator, entry, tv_id)
                tracked_off[tv_id] = entity
                new_entities.append(entity)

        if new_entities:
            async_add_entities(new_entities)

    coordinator.async_add_listener(lambda: _process_tvs(coordinator.data or []))
    _process_tvs(coordinator.data or [])


class FrameArtRemoveTVButton(CoordinatorEntity[FrameArtCoordinator], ButtonEntity):  # type: ignore[misc]
    """Button entity to remove a TV."""

    _attr_has_entity_name = True
    _attr_name = "zzDANGER-DEL THIS TV"
    _attr_icon = "mdi:delete-alert"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: FrameArtCoordinator,
        entry: ConfigEntry,
        tv_id: str,
    ) -> None:
        """Initialize the button entity."""
        super().__init__(coordinator)
        self._tv_id = tv_id
        self._entry = entry

        # Get TV name from config entry
        tv_config = get_tv_config(entry, tv_id)
        tv_name = tv_config.get("name", tv_id) if tv_config else tv_id
        self._tv_name = tv_name
        
        # Use tv_id as identifier (no home prefix)
        identifier = tv_id

        self._attr_unique_id = f"{tv_id}_remove"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, identifier)},
            name=tv_name,
            manufacturer="Samsung",
            model="Frame TV",
        )

    async def async_press(self) -> None:
        """Handle the button press - remove this TV."""
        device_registry = dr.async_get(self.hass)
        
        # Find the device for this TV
        identifier = self._tv_id
        device = device_registry.async_get_device(identifiers={(DOMAIN, identifier)})
        
        if device:
            # Remove the device (this will trigger our device_removed listener)
            device_registry.async_remove_device(device.id)
            _LOGGER.info(f"Removed TV device: {self._tv_name}")
        
        # Also remove from config entry so it doesn't reappear on reload
        from .config_entry import remove_tv_config
        remove_tv_config(self.hass, self._entry, self._tv_id)
        _LOGGER.info(f"Removed TV {self._tv_name} from config entry")


class FrameArtTVOnButton(CoordinatorEntity[FrameArtCoordinator], ButtonEntity):  # type: ignore[misc]
    """Button entity to turn TV screen on (Wake-on-LAN)."""

    _attr_has_entity_name = True
    _attr_name = "TV On (~12s)"
    _attr_icon = "mdi:television"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: FrameArtCoordinator,
        entry: ConfigEntry,
        tv_id: str,
    ) -> None:
        """Initialize the button entity."""
        super().__init__(coordinator)
        self._tv_id = tv_id
        self._entry = entry

        # Get TV config
        tv_config = get_tv_config(entry, tv_id)
        if tv_config:
            self._tv_name = tv_config.get("name", tv_id)
            self._tv_ip = tv_config.get("ip")
            self._tv_mac = tv_config.get("mac")
        else:
            self._tv_name = tv_id
            self._tv_ip = None
            self._tv_mac = None

        self._attr_unique_id = f"{tv_id}_tv_on"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tv_id)},
            name=self._tv_name,
            manufacturer="Samsung",
            model="Frame TV",
        )

    async def async_press(self) -> None:
        """Handle the button press - turn TV screen on via Wake-on-LAN."""
        if not self._tv_ip or not self._tv_mac:
            _LOGGER.error(f"Cannot turn on {self._tv_name}: missing IP or MAC address in config")
            return

        try:
            await self.hass.async_add_executor_job(tv_on, self._tv_ip, self._tv_mac)
            _LOGGER.info(f"Sent Wake-on-LAN to {self._tv_name}")
        except FrameArtError as err:
            _LOGGER.error(f"Failed to turn on {self._tv_name}: {err}")


class FrameArtTVOffButton(CoordinatorEntity[FrameArtCoordinator], ButtonEntity):  # type: ignore[misc]
    """Button entity to turn TV screen off (stays in art mode)."""

    _attr_has_entity_name = True
    _attr_name = "TV Off (~3s)"
    _attr_icon = "mdi:television-off"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: FrameArtCoordinator,
        entry: ConfigEntry,
        tv_id: str,
    ) -> None:
        """Initialize the button entity."""
        super().__init__(coordinator)
        self._tv_id = tv_id
        self._entry = entry

        # Get TV config
        tv_config = get_tv_config(entry, tv_id)
        if tv_config:
            self._tv_name = tv_config.get("name", tv_id)
            self._tv_ip = tv_config.get("ip")
        else:
            self._tv_name = tv_id
            self._tv_ip = None

        self._attr_unique_id = f"{tv_id}_tv_off"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tv_id)},
            name=self._tv_name,
            manufacturer="Samsung",
            model="Frame TV",
        )

    async def async_press(self) -> None:
        """Handle the button press - turn TV screen off."""
        if not self._tv_ip:
            _LOGGER.error(f"Cannot turn off {self._tv_name}: missing IP address in config")
            return

        try:
            await self.hass.async_add_executor_job(tv_off, self._tv_ip)
            _LOGGER.info(f"Sent screen off command to {self._tv_name}")
        except FrameArtError as err:
            _LOGGER.error(f"Failed to turn off {self._tv_name}: {err}")
