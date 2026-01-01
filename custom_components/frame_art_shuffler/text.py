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

from .config_entry import get_effective_tags, get_tv_config, update_tv_config
from .const import CONF_TAGSETS, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Frame Art text entities for a config entry."""
    # Read TV configs directly from entry (stored as dict with tv_id as key)
    tvs_dict = entry.data.get("tvs", {})
    
    entities: list[TextEntity] = []
    for tv_id, tv in tvs_dict.items():
        if not tv_id:
            continue

        entities.extend([
            FrameArtTagsEntity(hass, entry, tv_id),
            FrameArtExcludeTagsEntity(hass, entry, tv_id),
        ])

    if entities:
        async_add_entities(entities)


class FrameArtTextEntityBase(TextEntity):
    """Base class for Frame Art text entities."""

    _attr_has_entity_name = True

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        tv_id: str,
        key: str,
        name: str,
        icon: str,
        pattern: str | None = None,
    ) -> None:
        """Initialize the text entity."""
        self._hass = hass
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
        """Return the effective tags from the active tagset."""
        tv_config = get_tv_config(self._entry, self._tv_id)
        if not tv_config:
            return None
        
        include_tags, exclude_tags = get_effective_tags(self._entry, self._tv_id)
        if self._key == "tags":
            return ",".join(include_tags) if include_tags else None
        elif self._key == "exclude_tags":
            return ",".join(exclude_tags) if exclude_tags else None
        return None

    async def async_set_value(self, value: str) -> None:
        """Update tags - redirects to tagset modification.
        
        Tags are now managed via tagsets. This logs a warning directing users
        to use the tagset services instead.
        """
        tv_config = get_tv_config(self._entry, self._tv_id)
        tv_name = tv_config.get("name", self._tv_id) if tv_config else self._tv_id
        
        _LOGGER.warning(
            "Cannot set %s directly for %s. "
            "Use the tagset services (upsert_tagset, select_tagset, etc.) or the add-on UI instead.",
            self._key,
            tv_name,
        )


class FrameArtTagsEntity(FrameArtTextEntityBase):
    """Text entity for TV tags (comma-separated)."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        tv_id: str,
    ) -> None:
        """Initialize the tags entity."""
        super().__init__(
            hass,
            entry,
            tv_id,
            "tags",
            "Tags - Include",
            "mdi:tag-multiple",
        )
class FrameArtExcludeTagsEntity(FrameArtTextEntityBase):
    """Text entity for TV exclude tags (comma-separated)."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        tv_id: str,
    ) -> None:
        """Initialize the exclude tags entity."""
        super().__init__(
            hass,
            entry,
            tv_id,
            "exclude_tags",
            "Tags - Exclude",
            "mdi:tag-off",
        )
