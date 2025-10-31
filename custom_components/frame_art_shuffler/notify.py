"""Add-on notification stubs for Frame Art Shuffler."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


async def async_notify_addon_tv_change(
    hass: HomeAssistant,
    *,
    event: str,
    home: str,
    tv: dict[str, Any],
) -> None:
    """Stub: notify the Frame Art Manager add-on about TV changes.

    This will be replaced in a later phase once the add-on exposes an HTTP
    endpoint the integration can call. For now the hook logs at debug level so
    we can ensure the plumbing is exercised during tests.
    """

    _LOGGER.debug(
        "Add-on notification stub invoked: event=%s home=%s tv=%s",
        event,
        home,
        tv,
    )