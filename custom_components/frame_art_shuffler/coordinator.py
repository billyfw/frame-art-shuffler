"""Update coordinator for Frame Art metadata."""

from __future__ import annotations

from datetime import timedelta
import logging
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .metadata import MetadataStore

_LOGGER = logging.getLogger(__name__)


class FrameArtCoordinator(DataUpdateCoordinator[list[dict[str, Any]]]):
    """Coordinator that keeps track of TVs for a specific home."""

    def __init__(self, hass: HomeAssistant, metadata_path: Path, home: str) -> None:
        self._store = MetadataStore(metadata_path)
        self._home = home
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
        return await self.hass.async_add_executor_job(self._store.list_tvs, self._home)