"""Number entities for Frame Art Shuffler TV configuration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
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
    """Set up Frame Art number entities for a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: FrameArtCoordinator = data["coordinator"]

    tracked: dict[str, FrameArtShuffleFrequencyEntity] = {}

    @callback
    def _process_tvs(tvs: list[dict[str, Any]]) -> None:
        new_entities: list[NumberEntity] = []
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

            entity = FrameArtShuffleFrequencyEntity(
                coordinator,
                entry,
                tv_id,
            )
            tracked[tv_id] = entity
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
