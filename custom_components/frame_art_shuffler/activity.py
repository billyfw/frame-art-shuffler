"""Activity history tracking for Frame Art Shuffler TVs.

This module provides:
1. ActivityHistorySensor - A sensor entity that displays recent activity
2. log_activity() - Helper function to record events from throughout the integration
3. Persistence across HA restarts via RestoreEntity
4. Automatic retention: keeps events for 7 days
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone, timedelta
from typing import Any, Callable

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send
from homeassistant.helpers.restore_state import RestoreEntity

from .config_entry import get_tv_config
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Maximum age of events to keep (in days)
MAX_HISTORY_AGE_DAYS = 7

# Dispatcher signal prefix for activity updates
ACTIVITY_SIGNAL_PREFIX = f"{DOMAIN}_activity_update"


@dataclass
class ActivityEvent:
    """Represents a single activity event."""
    
    timestamp: str  # ISO format timestamp
    event_type: str  # Short event type (e.g., "motion", "brightness", "shuffle")
    message: str  # Human-readable message
    icon: str = "mdi:information"  # Icon for the event
    
    def to_dict(self) -> dict[str, str]:
        """Convert to dictionary for storage."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ActivityEvent":
        """Create from dictionary."""
        return cls(
            timestamp=data.get("timestamp", ""),
            event_type=data.get("event_type", "unknown"),
            message=data.get("message", ""),
            icon=data.get("icon", "mdi:information"),
        )


# Event type definitions with icons
EVENT_TYPES = {
    "motion_detected": ("mdi:motion-sensor", "Motion detected"),
    "motion_wake": ("mdi:power", "Screen on (woken by motion)"),
    "motion_off": ("mdi:power-off", "TV turned off (no motion)"),
    "motion_timer_reset": ("mdi:timer-refresh", "Motion timer reset"),
    "brightness_adjusted": ("mdi:brightness-6", "Brightness adjusted"),
    "brightness_skipped": ("mdi:brightness-auto", "Brightness unchanged"),
    "shuffle": ("mdi:shuffle-variant", "Image shuffled"),
    "shuffle_initiated": ("mdi:shuffle", "Shuffle started"),
    "shuffle_skipped": ("mdi:shuffle-disabled", "Shuffle skipped"),
    "screen_on": ("mdi:television", "Screen turned on"),
    "screen_off": ("mdi:television-off", "Screen turned off"),
    "auto_motion_enabled": ("mdi:motion-sensor", "Auto-motion enabled"),
    "auto_motion_disabled": ("mdi:motion-sensor-off", "Auto-motion disabled"),
    "verbose_motion_enabled": ("mdi:text-box-search", "Verbose motion logging enabled"),
    "verbose_motion_disabled": ("mdi:text-box-remove", "Verbose motion logging disabled"),
    "auto_brightness_enabled": ("mdi:brightness-auto", "Auto-brightness enabled"),
    "auto_brightness_disabled": ("mdi:brightness-5", "Auto-brightness disabled"),
    "auto_shuffle_enabled": ("mdi:shuffle-variant", "Auto-shuffle enabled"),
    "auto_shuffle_disabled": ("mdi:shuffle-disabled", "Auto-shuffle disabled"),
    "auto_shuffle_error": ("mdi:alert", "Auto-shuffle error"),
    "display_image": ("mdi:image", "Image displayed"),
    "integration_start": ("mdi:play-circle", "Integration started"),
    "error": ("mdi:alert-circle", "Error occurred"),
}


ACTIVITY_DESCRIPTION = SensorEntityDescription(
    key="recent_activity",
    icon="mdi:history",
    entity_category=EntityCategory.DIAGNOSTIC,
    translation_key="recent_activity",
)


def _trim_old_events(tv_history: list[dict[str, str]]) -> None:
    """Remove events older than MAX_HISTORY_AGE_DAYS.
    
    Modifies the list in-place, removing events from the end (oldest).
    """
    if not tv_history:
        return
    
    cutoff_time = datetime.now(timezone.utc) - timedelta(days=MAX_HISTORY_AGE_DAYS)
    
    # Events are stored most recent first, so iterate from the end
    while tv_history:
        try:
            # Parse timestamp from the last (oldest) event
            last_event = tv_history[-1]
            timestamp_str = last_event.get("timestamp", "")
            event_time = datetime.fromisoformat(timestamp_str)
            
            # If event is too old, remove it
            if event_time < cutoff_time:
                tv_history.pop()
            else:
                # Events are in order, so if this one is recent enough, we're done
                break
        except (ValueError, TypeError, KeyError):
            # If we can't parse the timestamp, keep the event
            break


def log_activity(
    hass: HomeAssistant,
    entry_id: str,
    tv_id: str,
    event_type: str,
    message: str | None = None,
    icon: str | None = None,
) -> None:
    """Log an activity event for a TV.
    
    This function should be called from throughout the integration
    to record notable events.
    
    Args:
        hass: Home Assistant instance
        entry_id: Config entry ID
        tv_id: TV identifier
        event_type: Event type key (see EVENT_TYPES)
        message: Optional custom message (overrides default)
        icon: Optional custom icon (overrides default)
    """
    # Get default icon and message from event type
    default_icon, default_message = EVENT_TYPES.get(
        event_type, ("mdi:information", event_type.replace("_", " ").title())
    )
    
    event = ActivityEvent(
        timestamp=datetime.now(timezone.utc).isoformat(),
        event_type=event_type,
        message=message or default_message,
        icon=icon or default_icon,
    )
    
    # Store in hass.data
    data = hass.data.get(DOMAIN, {}).get(entry_id, {})
    activity_history = data.setdefault("activity_history", {})
    tv_history = activity_history.setdefault(tv_id, [])
    
    # Prepend new event (most recent first)
    tv_history.insert(0, event.to_dict())
    
    # Trim events older than MAX_HISTORY_AGE_DAYS
    _trim_old_events(tv_history)
    
    # Signal sensors to update
    signal = f"{ACTIVITY_SIGNAL_PREFIX}_{entry_id}_{tv_id}"
    async_dispatcher_send(hass, signal)


def get_activity_history(
    hass: HomeAssistant,
    entry_id: str,
    tv_id: str,
) -> list[dict[str, str]]:
    """Get the activity history for a TV.
    
    Returns:
        List of activity event dicts, most recent first
    """
    data = hass.data.get(DOMAIN, {}).get(entry_id, {})
    activity_history = data.get("activity_history", {})
    return activity_history.get(tv_id, [])


class FrameArtActivitySensor(RestoreEntity, SensorEntity):
    """Sensor showing recent activity for a Frame TV."""

    entity_description = ACTIVITY_DESCRIPTION
    _attr_has_entity_name = True
    _attr_name = "Recent Activity"

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        tv_id: str,
    ) -> None:
        """Initialize the activity sensor."""
        self._hass = hass
        self._entry = entry
        self._tv_id = tv_id
        self._attr_unique_id = f"{entry.entry_id}_{tv_id}_recent_activity"
        self._unsubscribe: Callable[[], None] | None = None

        tv_config = get_tv_config(entry, tv_id)
        tv_name = tv_config.get("name", tv_id) if tv_config else tv_id

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tv_id)},
            name=tv_name,
            manufacturer="Samsung",
            model="Frame TV",
        )

    async def async_added_to_hass(self) -> None:
        """Restore state and subscribe to updates."""
        await super().async_added_to_hass()
        
        # Restore previous history from saved state
        last_state = await self.async_get_last_state()
        if last_state and last_state.attributes.get("history"):
            # Restore history to hass.data
            data = self._hass.data.setdefault(DOMAIN, {}).setdefault(self._entry.entry_id, {})
            activity_history = data.setdefault("activity_history", {})
            
            # Only restore if we don't already have history (e.g., from other sensors)
            if self._tv_id not in activity_history:
                restored = last_state.attributes.get("history", [])
                activity_history[self._tv_id] = restored
                # Trim old events after restore
                _trim_old_events(activity_history[self._tv_id])
                _LOGGER.debug(f"Restored {len(activity_history[self._tv_id])} activity events for {self._tv_id}")
        
        # Subscribe to activity updates
        @callback
        def _activity_updated() -> None:
            """Handle activity update signal."""
            self.async_write_ha_state()
        
        signal = f"{ACTIVITY_SIGNAL_PREFIX}_{self._entry.entry_id}_{self._tv_id}"
        self._unsubscribe = async_dispatcher_connect(
            self._hass,
            signal,
            _activity_updated,
        )

    async def async_will_remove_from_hass(self) -> None:
        """Unsubscribe from updates."""
        if self._unsubscribe:
            self._unsubscribe()
            self._unsubscribe = None
        await super().async_will_remove_from_hass()

    @property
    def native_value(self) -> str | None:
        """Return the most recent event message."""
        history = get_activity_history(
            self._hass, self._entry.entry_id, self._tv_id
        )
        if history:
            return history[0].get("message", "No activity")
        return "No activity"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the activity history as attributes."""
        history = get_activity_history(
            self._hass, self._entry.entry_id, self._tv_id
        )
        
        # Format timestamps for display
        formatted_history = []
        for event in history:
            try:
                ts = datetime.fromisoformat(event.get("timestamp", ""))
                # Convert to local time for display
                local_ts = ts.astimezone()
                # Format: "Tue 11/28 5:08PM"
                day_abbrev = local_ts.strftime("%a")  # Mon, Tue, Wed, etc.
                full_day = local_ts.strftime("%A")    # Monday, Tuesday, etc.
                date_part = local_ts.strftime("%-m/%d")  # 11/28 (no leading zero on month)
                time_part = local_ts.strftime("%-I:%M%p").replace("AM", "am").replace("PM", "pm")  # 5:08pm
                
                # Old format for backward compatibility if needed
                formatted_time = f"{day_abbrev} {date_part} {time_part}"
                
                # New fields for grouped display
                day_header = f"{full_day} {date_part}"
                
                formatted_history.append({
                    "time": formatted_time,
                    "day_header": day_header,
                    "time_display": time_part,
                    "timestamp": event.get("timestamp"),
                    "event_type": event.get("event_type"),
                    "message": event.get("message"),
                    "icon": event.get("icon"),
                })
            except (ValueError, TypeError):
                formatted_history.append(event)
        
        return {
            "history": history,  # Raw history for persistence
            "formatted_history": formatted_history,  # For display
            "event_count": len(history),
        }

    @property
    def icon(self) -> str:
        """Return icon based on most recent event."""
        history = get_activity_history(
            self._hass, self._entry.entry_id, self._tv_id
        )
        if history:
            return history[0].get("icon", "mdi:history")
        return "mdi:history"
