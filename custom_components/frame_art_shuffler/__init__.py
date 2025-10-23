"""Frame Art Shuffler integration base setup.

This integration provides art-focused control for Samsung Frame TVs:
- Upload and display artwork
- Manage art gallery (delete others, select images)
- Control art mode brightness
- Basic power control (screen on/off while staying in art mode)

It can work standalone or alongside Home Assistant's Samsung Smart TV integration.
See README.md for details on standalone vs. hybrid deployment modes.
"""
from __future__ import annotations

from typing import Any

from .const import DOMAIN


async def async_setup(hass: Any, config: dict) -> bool:
    """Set up the Frame Art Shuffler integration."""
    hass.data.setdefault(DOMAIN, {})
    return True
