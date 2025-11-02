"""Sensor platform for Frame Art Shuffler TVs."""

from __future__ import annotations

from typing import Any, Iterable

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_HOME,
    CONF_SHUFFLE_FREQUENCY,
    DOMAIN,
)
from .coordinator import FrameArtCoordinator


TV_DESCRIPTION = SensorEntityDescription(
    key="current_artwork",
    icon="mdi:image-frame",
    translation_key="current_artwork",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities,
) -> None:
    """Set up Frame Art TV sensors for a config entry."""

    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: FrameArtCoordinator = data["coordinator"]

    tracked: dict[str, FrameArtTVEntity] = {}

    @callback
    def _process_tvs(tvs: Iterable[dict[str, Any]]) -> None:
        new_entities: list[FrameArtTVEntity] = []
        for tv in tvs:
            tv_id = tv.get("id")
            if not tv_id or tv_id in tracked:
                continue
            entity = FrameArtTVEntity(coordinator, entry, tv_id)
            tracked[tv_id] = entity
            new_entities.append(entity)
        if new_entities:
            async_add_entities(new_entities)

    _process_tvs(coordinator.data or [])

    @callback
    def _handle_coordinator_update() -> None:
        _process_tvs(coordinator.data or [])

    unsubscribe = coordinator.async_add_listener(_handle_coordinator_update)
    entry.async_on_unload(unsubscribe)


class FrameArtTVEntity(CoordinatorEntity[FrameArtCoordinator], SensorEntity):
    """Representation of a Frame TV from metadata."""

    entity_description = TV_DESCRIPTION
    _attr_has_entity_name = True

    def __init__(self, coordinator: FrameArtCoordinator, entry: ConfigEntry, tv_id: str) -> None:
        super().__init__(coordinator)
        self._tv_id = tv_id
        self._home_identifier = entry.data.get(CONF_HOME)
        identifier = f"{self._home_identifier}_{tv_id}" if self._home_identifier else tv_id
        self._attr_unique_id = f"{entry.entry_id}_{tv_id}"

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, identifier)},
            name=self._derive_name(),
            manufacturer="Samsung",
            model="Frame TV",
        )

    def _derive_name(self) -> str:
        tv = self._current_tv
        if not tv:
            return "Frame TV"
        return tv.get(CONF_NAME) or tv.get("name") or "Frame TV"

    @property
    def _current_tv(self) -> dict[str, Any] | None:
        tvs = self.coordinator.data or []
        for tv in tvs:
            if tv.get("id") == self._tv_id:
                return tv
        return None

    @property
    def native_value(self) -> str | None:
        tv = self._current_tv
        if not tv:
            return None
        # Try to get current artwork from shuffle data or return "No artwork"
        shuffle = tv.get("shuffle", {})
        if isinstance(shuffle, dict):
            current = shuffle.get("currentImage") or shuffle.get("current")
            if current:
                # Extract filename from path if it's a full path
                if isinstance(current, str) and "/" in current:
                    return current.split("/")[-1]
                return str(current)
        return "Unknown"

    @property
    def name(self) -> str | None:
        return self._derive_name()

    @property
    def available(self) -> bool:
        return self._current_tv is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        tv = self._current_tv
        if not tv:
            return None
        data = {
            "ip": tv.get("ip"),
            "mac": tv.get("mac"),
            "tags": tv.get("tags", []),
            "exclude_tags": tv.get("notTags", []),
        }
        shuffle = tv.get("shuffle") or {}
        if isinstance(shuffle, dict):
            data["shuffle_frequency"] = shuffle.get(CONF_SHUFFLE_FREQUENCY)
        return data