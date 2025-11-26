"""Update coordinator for Frame Art metadata."""

from __future__ import annotations

from datetime import timedelta
import logging
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .metadata import MetadataStore

_LOGGER = logging.getLogger(__name__)


class FrameArtCoordinator(DataUpdateCoordinator[list[dict[str, Any]]]):
    """Coordinator that keeps track of all TVs."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, metadata_path: Path) -> None:
        self._entry = entry
        self._store = MetadataStore(metadata_path)
        super().__init__(
            hass,
            _LOGGER,
            name="Frame Art Shuffler",
            update_interval=timedelta(minutes=5),
        )

    @property
    def store(self) -> MetadataStore:
        return self._store

    async def _async_update_data(self) -> list[dict[str, Any]]:
        # Get TV data from config entry, not metadata.json
        # metadata.json is now only used by the Frame Art Manager add-on for images/tags
        tvs_dict = self._entry.data.get("tvs", {})
        if not tvs_dict:
            return []
        return list(tvs_dict.values())

    async def async_set_active_image(self, tv_id: str, filename: str, is_shuffle: bool = False) -> None:
        """Update the active image state for a TV and refresh sensors.
        
        Args:
            tv_id: The TV identifier.
            filename: The filename of the image being displayed.
            is_shuffle: Whether this update is triggered by a shuffle action.
                       If True, updates last_shuffle_image and last_shuffle_timestamp.
                       If False, only updates current_image.
        """
        from homeassistant.util import dt as dt_util
        from .config_entry import update_tv_config

        updates = {"current_image": filename}
        
        if is_shuffle:
            updates.update({
                "last_shuffle_image": filename,
                "last_shuffle_timestamp": dt_util.now().isoformat(),
            })

        update_tv_config(
            self.hass,
            self._entry,
            tv_id,
            updates,
        )
        await self.async_request_refresh()