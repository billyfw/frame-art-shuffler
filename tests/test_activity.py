"""Tests for activity history functionality."""

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, AsyncMock
import pytest

from custom_components.frame_art_shuffler.activity import (
    ActivityEvent,
    FrameArtActivitySensor,
    log_activity,
    get_activity_history,
    MAX_HISTORY_AGE_DAYS,
    EVENT_TYPES,
    _trim_old_events,
)
from custom_components.frame_art_shuffler.const import DOMAIN


class TestActivityEvent:
    """Tests for ActivityEvent dataclass."""

    def test_to_dict(self):
        """Test converting event to dictionary."""
        event = ActivityEvent(
            timestamp="2025-11-27T10:30:00+00:00",
            event_type="motion_detected",
            message="Motion detected",
            icon="mdi:motion-sensor",
        )
        result = event.to_dict()
        
        assert result == {
            "timestamp": "2025-11-27T10:30:00+00:00",
            "event_type": "motion_detected",
            "message": "Motion detected",
            "icon": "mdi:motion-sensor",
        }

    def test_from_dict(self):
        """Test creating event from dictionary."""
        data = {
            "timestamp": "2025-11-27T10:30:00+00:00",
            "event_type": "shuffle",
            "message": "Shuffled to image.jpg",
            "icon": "mdi:shuffle-variant",
        }
        event = ActivityEvent.from_dict(data)
        
        assert event.timestamp == "2025-11-27T10:30:00+00:00"
        assert event.event_type == "shuffle"
        assert event.message == "Shuffled to image.jpg"
        assert event.icon == "mdi:shuffle-variant"

    def test_from_dict_missing_fields(self):
        """Test creating event from dict with missing fields uses defaults."""
        data = {"timestamp": "2025-11-27T10:30:00+00:00"}
        event = ActivityEvent.from_dict(data)
        
        assert event.timestamp == "2025-11-27T10:30:00+00:00"
        assert event.event_type == "unknown"
        assert event.message == ""
        assert event.icon == "mdi:information"


class TestLogActivity:
    """Tests for log_activity function."""

    def test_log_activity_creates_entry(self):
        """Test that log_activity creates an entry in hass.data."""
        hass = MagicMock()
        hass.data = {DOMAIN: {"entry123": {}}}
        
        with patch("custom_components.frame_art_shuffler.activity.async_dispatcher_send"):
            log_activity(hass, "entry123", "tv123", "motion_detected")
        
        history = hass.data[DOMAIN]["entry123"]["activity_history"]["tv123"]
        assert len(history) == 1
        assert history[0]["event_type"] == "motion_detected"
        assert history[0]["message"] == "Motion detected"
        assert history[0]["icon"] == "mdi:motion-sensor"

    def test_log_activity_custom_message(self):
        """Test log_activity with custom message."""
        hass = MagicMock()
        hass.data = {DOMAIN: {"entry123": {}}}
        
        with patch("custom_components.frame_art_shuffler.activity.async_dispatcher_send"):
            log_activity(
                hass, "entry123", "tv123",
                "brightness_adjusted",
                message="Brightness → 5 (lux: 59)",
            )
        
        history = hass.data[DOMAIN]["entry123"]["activity_history"]["tv123"]
        assert history[0]["message"] == "Brightness → 5 (lux: 59)"

    def test_log_activity_custom_icon(self):
        """Test log_activity with custom icon."""
        hass = MagicMock()
        hass.data = {DOMAIN: {"entry123": {}}}
        
        with patch("custom_components.frame_art_shuffler.activity.async_dispatcher_send"):
            log_activity(
                hass, "entry123", "tv123",
                "error",
                icon="mdi:alert",
            )
        
        history = hass.data[DOMAIN]["entry123"]["activity_history"]["tv123"]
        assert history[0]["icon"] == "mdi:alert"

    def test_log_activity_prepends_new_events(self):
        """Test that new events are prepended (most recent first)."""
        hass = MagicMock()
        hass.data = {DOMAIN: {"entry123": {}}}
        
        with patch("custom_components.frame_art_shuffler.activity.async_dispatcher_send"):
            log_activity(hass, "entry123", "tv123", "motion_detected", "First")
            log_activity(hass, "entry123", "tv123", "shuffle", "Second")
        
        history = hass.data[DOMAIN]["entry123"]["activity_history"]["tv123"]
        assert len(history) == 2
        assert history[0]["message"] == "Second"
        assert history[1]["message"] == "First"

    def test_log_activity_sends_dispatcher_signal(self):
        """Test that log_activity sends dispatcher signal."""
        hass = MagicMock()
        hass.data = {DOMAIN: {"entry123": {}}}
        
        with patch("custom_components.frame_art_shuffler.activity.async_dispatcher_send") as mock_send:
            log_activity(hass, "entry123", "tv123", "motion_detected")
        
        mock_send.assert_called_once()
        signal = mock_send.call_args[0][1]
        assert "entry123" in signal
        assert "tv123" in signal


class TestGetActivityHistory:
    """Tests for get_activity_history function."""

    def test_get_history_returns_list(self):
        """Test getting history returns the list."""
        hass = MagicMock()
        hass.data = {
            DOMAIN: {
                "entry123": {
                    "activity_history": {
                        "tv123": [
                            {"event_type": "motion_detected", "message": "Test"}
                        ]
                    }
                }
            }
        }
        
        history = get_activity_history(hass, "entry123", "tv123")
        assert len(history) == 1
        assert history[0]["message"] == "Test"

    def test_get_history_missing_entry(self):
        """Test getting history for missing entry returns empty list."""
        hass = MagicMock()
        hass.data = {DOMAIN: {}}
        
        history = get_activity_history(hass, "entry123", "tv123")
        assert history == []

    def test_get_history_missing_tv(self):
        """Test getting history for missing TV returns empty list."""
        hass = MagicMock()
        hass.data = {DOMAIN: {"entry123": {"activity_history": {}}}}
        
        history = get_activity_history(hass, "entry123", "tv123")
        assert history == []


class TestFrameArtActivitySensor:
    """Tests for FrameArtActivitySensor entity."""

    @pytest.fixture
    def mock_hass(self):
        """Create a mock Home Assistant instance."""
        hass = MagicMock()
        hass.data = {DOMAIN: {"entry123": {"activity_history": {}}}}
        return hass

    @pytest.fixture
    def mock_entry(self):
        """Create a mock config entry."""
        entry = MagicMock()
        entry.entry_id = "entry123"
        entry.data = {"tvs": {"tv123": {"name": "Office TV", "ip": "192.168.1.100"}}}
        return entry

    def test_sensor_init(self, mock_hass, mock_entry):
        """Test sensor initialization."""
        with patch("custom_components.frame_art_shuffler.activity.get_tv_config") as mock_get:
            mock_get.return_value = {"name": "Office TV"}
            sensor = FrameArtActivitySensor(mock_hass, mock_entry, "tv123")
        
        assert sensor._attr_unique_id == "entry123_tv123_recent_activity"
        assert sensor._attr_name == "Recent Activity"

    def test_sensor_native_value_no_history(self, mock_hass, mock_entry):
        """Test native value when no history exists."""
        with patch("custom_components.frame_art_shuffler.activity.get_tv_config") as mock_get:
            mock_get.return_value = {"name": "Office TV"}
            sensor = FrameArtActivitySensor(mock_hass, mock_entry, "tv123")
        
        assert sensor.native_value == "No activity"

    def test_sensor_native_value_with_history(self, mock_hass, mock_entry):
        """Test native value returns most recent event."""
        mock_hass.data[DOMAIN]["entry123"]["activity_history"] = {
            "tv123": [
                {"message": "Most Recent", "event_type": "motion_detected"},
                {"message": "Older", "event_type": "shuffle"},
            ]
        }
        
        with patch("custom_components.frame_art_shuffler.activity.get_tv_config") as mock_get:
            mock_get.return_value = {"name": "Office TV"}
            sensor = FrameArtActivitySensor(mock_hass, mock_entry, "tv123")
        
        assert sensor.native_value == "Most Recent"

    def test_sensor_extra_state_attributes(self, mock_hass, mock_entry):
        """Test extra state attributes include history."""
        mock_hass.data[DOMAIN]["entry123"]["activity_history"] = {
            "tv123": [
                {
                    "timestamp": "2025-11-27T10:30:00+00:00",
                    "message": "Test Event",
                    "event_type": "motion_detected",
                    "icon": "mdi:motion-sensor",
                }
            ]
        }
        
        with patch("custom_components.frame_art_shuffler.activity.get_tv_config") as mock_get:
            mock_get.return_value = {"name": "Office TV"}
            sensor = FrameArtActivitySensor(mock_hass, mock_entry, "tv123")
        
        attrs = sensor.extra_state_attributes
        assert "history" in attrs
        assert "formatted_history" in attrs
        assert "event_count" in attrs
        assert attrs["event_count"] == 1

    def test_sensor_icon_from_latest_event(self, mock_hass, mock_entry):
        """Test icon comes from most recent event."""
        mock_hass.data[DOMAIN]["entry123"]["activity_history"] = {
            "tv123": [
                {"icon": "mdi:shuffle-variant", "event_type": "shuffle", "message": "Shuffled"},
            ]
        }
        
        with patch("custom_components.frame_art_shuffler.activity.get_tv_config") as mock_get:
            mock_get.return_value = {"name": "Office TV"}
            sensor = FrameArtActivitySensor(mock_hass, mock_entry, "tv123")
        
        assert sensor.icon == "mdi:shuffle-variant"

    def test_sensor_default_icon_no_history(self, mock_hass, mock_entry):
        """Test default icon when no history."""
        with patch("custom_components.frame_art_shuffler.activity.get_tv_config") as mock_get:
            mock_get.return_value = {"name": "Office TV"}
            sensor = FrameArtActivitySensor(mock_hass, mock_entry, "tv123")
        
        assert sensor.icon == "mdi:history"


class TestEventTypes:
    """Tests for EVENT_TYPES constant."""

    def test_all_event_types_have_icon_and_message(self):
        """Test all event types have both icon and message."""
        for event_type, (icon, message) in EVENT_TYPES.items():
            assert icon.startswith("mdi:"), f"{event_type} icon should start with mdi:"
            assert len(message) > 0, f"{event_type} should have a message"

    def test_expected_event_types_exist(self):
        """Test that expected event types are defined."""
        expected = [
            "motion_detected",
            "motion_wake",
            "motion_off",
            "brightness_adjusted",
            "shuffle",
            "screen_on",
            "screen_off",
            "error",
            "integration_start",
        ]
        for et in expected:
            assert et in EVENT_TYPES, f"Expected event type {et} not found"


class TestTimeTrimming:
    """Tests for time-based event trimming."""

    def test_trim_old_events_removes_old(self):
        """Test that events older than MAX_HISTORY_AGE_DAYS are removed."""
        now = datetime.now(timezone.utc)
        old_time = now - timedelta(days=MAX_HISTORY_AGE_DAYS + 1)
        recent_time = now - timedelta(days=1)
        
        history = [
            {"timestamp": now.isoformat(), "message": "Most recent"},
            {"timestamp": recent_time.isoformat(), "message": "Recent"},
            {"timestamp": old_time.isoformat(), "message": "Old"},
        ]
        
        _trim_old_events(history)
        
        assert len(history) == 2
        assert history[0]["message"] == "Most recent"
        assert history[1]["message"] == "Recent"

    def test_trim_old_events_keeps_recent(self):
        """Test that recent events are kept."""
        now = datetime.now(timezone.utc)
        recent_time = now - timedelta(days=MAX_HISTORY_AGE_DAYS - 1)
        
        history = [
            {"timestamp": now.isoformat(), "message": "Now"},
            {"timestamp": recent_time.isoformat(), "message": "Recent"},
        ]
        
        _trim_old_events(history)
        
        assert len(history) == 2

    def test_trim_old_events_empty_list(self):
        """Test that trimming empty list doesn't error."""
        history = []
        _trim_old_events(history)
        assert len(history) == 0

    def test_trim_old_events_invalid_timestamp(self):
        """Test that invalid timestamps don't cause errors."""
        history = [
            {"timestamp": "invalid", "message": "Bad timestamp"},
            {"timestamp": datetime.now(timezone.utc).isoformat(), "message": "Good"},
        ]
        
        # Should not crash
        _trim_old_events(history)
        
        # Bad timestamp kept (safety), good one definitely kept
        assert len(history) >= 1

    def test_log_activity_trims_by_age(self):
        """Test that log_activity trims old events."""
        hass = MagicMock()
        hass.data = {DOMAIN: {"entry123": {}}}
        
        # Pre-populate with old event
        old_time = datetime.now(timezone.utc) - timedelta(days=MAX_HISTORY_AGE_DAYS + 1)
        hass.data[DOMAIN]["entry123"]["activity_history"] = {
            "tv123": [
                {"timestamp": old_time.isoformat(), "message": "Old event"}
            ]
        }
        
        with patch("custom_components.frame_art_shuffler.activity.async_dispatcher_send"):
            # Add new event (should trigger trim)
            log_activity(hass, "entry123", "tv123", "motion_detected", "New event")
        
        history = hass.data[DOMAIN]["entry123"]["activity_history"]["tv123"]
        
        # Should only have the new event
        assert len(history) == 1
        assert history[0]["message"] == "New event"
