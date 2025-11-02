"""Button entities for Frame Art Shuffler TV management."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.button import ButtonEntity, ButtonDeviceClass
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

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Frame Art button entities for a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: FrameArtCoordinator = data["coordinator"]

    tracked: dict[str, FrameArtRemoveTVButton] = {}

    @callback
    def _process_tvs(tvs: list[dict[str, Any]]) -> None:
        new_entities: list[ButtonEntity] = []
        current_tv_ids = {tv.get("id") for tv in tvs if tv.get("id")}

        # Remove entities for TVs that no longer exist
        for tv_id in list(tracked.keys()):
            if tv_id not in current_tv_ids:
                tracked.pop(tv_id)

        # Add entities for new TVs
        for tv in tvs:
            tv_id = tv.get("id")
            if not tv_id or tv_id in tracked:
                continue

            entity = FrameArtRemoveTVButton(coordinator, entry, tv_id)
            tracked[tv_id] = entity
            new_entities.append(entity)

        if new_entities:
            async_add_entities(new_entities)

    coordinator.async_add_listener(lambda: _process_tvs(coordinator.data or []))
    _process_tvs(coordinator.data or [])


class FrameArtRemoveTVButton(CoordinatorEntity, ButtonEntity):
    """Button entity to remove a TV."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:delete"
    _attr_device_class = ButtonDeviceClass.RESTART
    _attr_entity_category = EntityCategory.CONFIG
    _attr_name = "Remove TV"

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
