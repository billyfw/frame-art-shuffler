"""Image platform: each display target's current pick as a Home Assistant image entity.

HA serves an image entity at ``/api/image_proxy/<entity_id>`` to logged-in users, or to a request
carrying the entity's current access token (rotated every five minutes and visible only to
logged-in users in the entity's state). A wall tablet's dashboard shows its ambient picture through
this, so the library itself never has to be published at /local. The picture is a JPEG fitted to
the tablet's screen (artwork.py), cached beside the library and warmed right after each pick.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.image import ImageEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import artwork
from .config_entry import get_tv_config
from .const import DERIVATIVE_DIR_NAME, DOMAIN, SIGNAL_SHUFFLE
from .targets import library_root, resolve_library_file, target_device_info

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """One artwork image entity per target (TVs and tablets alike)."""
    entities = [
        FrameArtArtworkImage(hass, entry, tv_id)
        for tv_id in (entry.data.get("tvs") or {})
        if tv_id
    ]
    if entities:
        async_add_entities(entities)


class FrameArtArtworkImage(ImageEntity):
    """The picture a target shows now (its last pick)."""

    _attr_has_entity_name = True
    _attr_name = "Artwork"
    _attr_icon = "mdi:image-frame"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, tv_id: str) -> None:
        super().__init__(hass)
        self._entry = entry
        self._tv_id = tv_id
        tv_config = get_tv_config(entry, tv_id) or {}
        self._attr_unique_id = f"{entry.entry_id}_{tv_id}_artwork_image"
        self._attr_device_info = target_device_info(entry, tv_id, tv_config.get("name", tv_id))
        self._filename: str | None = None

    def _entry_data(self) -> dict[str, Any]:
        return self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})

    def _current_filename(self) -> str | None:
        cached = self._entry_data().get("shuffle_cache", {}).get(self._tv_id, {}).get("current_image")
        if cached:
            return str(cached)
        current = (get_tv_config(self._entry, self._tv_id) or {}).get("current_image")
        return str(current) if current else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"filename": self._filename}

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._filename = self._current_filename()
        if self._filename:
            self._attr_image_last_updated = dt_util.utcnow()
            self._warm_cache()
        signal = f"{SIGNAL_SHUFFLE}_{self._entry.entry_id}_{self._tv_id}"
        self.async_on_remove(async_dispatcher_connect(self.hass, signal, self._handle_pick))

    @callback
    def _handle_pick(self) -> None:
        filename = self._current_filename()
        if not filename or filename == self._filename:
            return
        self._filename = filename
        self._cached_image = None
        self._attr_image_last_updated = dt_util.utcnow()
        self._warm_cache()
        self.async_write_ha_state()

    def _paths(self) -> tuple[Any, Any] | None:
        metadata_path = self._entry_data().get("metadata_path")
        if not metadata_path or not self._filename:
            return None
        return metadata_path, library_root(metadata_path) / DERIVATIVE_DIR_NAME

    def _render(self) -> tuple[bytes, str] | None:
        paths = self._paths()
        if paths is None:
            return None
        metadata_path, cache_dir = paths
        src = resolve_library_file(metadata_path, self._filename)
        if src is None:
            return None
        return artwork.render(src, cache_dir)

    @callback
    def _warm_cache(self) -> None:
        """Render the derivative now, so the tablet's request finds it ready."""

        async def _warm() -> None:
            try:
                await self.hass.async_add_executor_job(self._render)
            except Exception as err:  # pylint: disable=broad-except
                _LOGGER.debug("Artwork cache warm failed for %s: %s", self._tv_id, err)

        self.hass.async_create_background_task(_warm(), f"{DOMAIN} artwork warm {self._tv_id}")

    async def async_image(self) -> bytes | None:
        """The current pick, fitted to a wall tablet's screen."""
        result = await self.hass.async_add_executor_job(self._render)
        if result is None:
            return None
        content, content_type = result
        self._attr_content_type = content_type
        return content

