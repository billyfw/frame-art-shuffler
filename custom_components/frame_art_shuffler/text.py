"""Text entities for Frame Art Shuffler TV configuration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.text import TextEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .config_entry import get_tv_config, update_tv_config
from .const import DOMAIN
from .coordinator import FrameArtCoordinator
from .flow_utils import validate_host
from .metadata import normalize_mac

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Frame Art text entities for a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: FrameArtCoordinator = data["coordinator"]

    tracked: dict[str, list[TextEntity]] = {}

    @callback
    def _process_tvs(tvs: list[dict[str, Any]]) -> None:
        new_entities: list[TextEntity] = []
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

            entities = [
                FrameArtTagsEntity(coordinator, entry, tv_id),
                FrameArtExcludeTagsEntity(coordinator, entry, tv_id),
                FrameArtIPEntity(coordinator, entry, tv_id),
                FrameArtMACEntity(coordinator, entry, tv_id),
            ]
            tracked[tv_id] = entities
            new_entities.extend(entities)

        if new_entities:
            async_add_entities(new_entities)

    coordinator.async_add_listener(lambda: _process_tvs(coordinator.data or []))
    _process_tvs(coordinator.data or [])


class FrameArtTextEntityBase(CoordinatorEntity, TextEntity):
    """Base class for Frame Art text entities."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: FrameArtCoordinator,
        entry: ConfigEntry,
        tv_id: str,
        key: str,
        name: str,
        icon: str,
        pattern: str | None = None,
    ) -> None:
        """Initialize the text entity."""
        super().__init__(coordinator)
        self._tv_id = tv_id
        self._entry = entry
        self._key = key
        self._attr_icon = icon
        self._attr_native_value = None
        self._attr_name = name
        if pattern:
            self._attr_pattern = pattern

        # Get TV name from config entry
        tv_config = get_tv_config(entry, tv_id)
        tv_name = tv_config.get("name", tv_id) if tv_config else tv_id
        
        # Use tv_id as identifier (no home prefix)
        identifier = tv_id

        self._attr_unique_id = f"{tv_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, identifier)},
            name=tv_name,
            manufacturer="Samsung",
            model="Frame TV",
        )

    @property
    def native_value(self) -> str | None:
        """Return the current value from config entry."""
        tv_config = get_tv_config(self._entry, self._tv_id)
        if not tv_config:
            return None
        
        value = tv_config.get(self._key)
        if isinstance(value, list):
            return ",".join(value)
        return str(value) if value else None

    async def async_set_value(self, value: str) -> None:
        """Update the value in config entry (no add-on sync for most fields)."""
        _LOGGER.info("Setting %s for TV %s to: %s", self._key, self._tv_id, value)
        
        # Parse value based on entity type
        if self._key in ("tags", "exclude_tags"):
            parsed_value = [tag.strip() for tag in value.split(",") if tag.strip()]
        else:
            parsed_value = value.strip()

        # Update HA storage
        update_tv_config(
            self.hass,
            self._entry,
            self._tv_id,
            {self._key: parsed_value},
        )
        
        # Get TV config for logging
        tv_config = get_tv_config(self._entry, self._tv_id)
        tv_name = tv_config.get("name", self._tv_id) if tv_config else self._tv_id
        
        _LOGGER.info(
            "%s changed to '%s' for %s",
            self._attr_name,
            value,
            tv_name,
        )
        
        # Refresh coordinator
        await self.coordinator.async_request_refresh()


class FrameArtIPEntity(FrameArtTextEntityBase):
    """Text entity for TV IP address."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: FrameArtCoordinator,
        entry: ConfigEntry,
        tv_id: str,
    ) -> None:
        """Initialize the IP entity."""
        super().__init__(
            coordinator,
            entry,
            tv_id,
            "ip",
            "IP Address",
            "mdi:ip-network",
        )
    
    async def async_set_value(self, value: str) -> None:
        """Update the IP address with validation."""
        # Validate IP address
        try:
            validated_ip = validate_host(value.strip())
        except ValueError as err:
            raise ServiceValidationError(
                f"Invalid IP address: {value}. Please enter a valid IP address (e.g., 192.168.1.100)"
            ) from err
        
        # Call parent with validated value
        self._validated_value = validated_ip
        await super().async_set_value(validated_ip)


class FrameArtMACEntity(FrameArtTextEntityBase):
    """Text entity for TV MAC address."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: FrameArtCoordinator,
        entry: ConfigEntry,
        tv_id: str,
    ) -> None:
        """Initialize the MAC entity."""
        super().__init__(
            coordinator,
            entry,
            tv_id,
            "mac",
            "MAC Address",
            "mdi:ethernet",
            r"^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$",
        )
    
    async def async_set_value(self, value: str) -> None:
        """Update the MAC address with validation."""
        # Validate and normalize MAC address
        normalized = normalize_mac(value.strip())
        if not normalized:
            raise ServiceValidationError(
                f"Invalid MAC address: {value}. Please enter a valid MAC address (e.g., aa:bb:cc:dd:ee:ff or AA-BB-CC-DD-EE-FF)"
            )
        
        # Call parent with normalized value
        await super().async_set_value(normalized)


class FrameArtTagsEntity(FrameArtTextEntityBase):
    """Text entity for TV tags (comma-separated)."""

    def __init__(
        self,
        coordinator: FrameArtCoordinator,
        entry: ConfigEntry,
        tv_id: str,
    ) -> None:
        """Initialize the tags entity."""
        super().__init__(
            coordinator,
            entry,
            tv_id,
            "tags",
            "Tags - Include",
            "mdi:tag-multiple",
        )


class FrameArtExcludeTagsEntity(FrameArtTextEntityBase):
    """Text entity for TV exclude tags (comma-separated)."""

    def __init__(
        self,
        coordinator: FrameArtCoordinator,
        entry: ConfigEntry,
        tv_id: str,
    ) -> None:
        """Initialize the exclude tags entity."""
        super().__init__(
            coordinator,
            entry,
            tv_id,
            "exclude_tags",
            "Tags - Exclude",
            "mdi:tag-off",
        )
