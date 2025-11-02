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