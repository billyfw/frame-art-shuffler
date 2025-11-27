"""Tests for the dashboard generator module."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Test the dashboard module functions
from custom_components.frame_art_shuffler.dashboard import (
    _get_platform_for_key,
    _build_status_section,
    _build_image_section,
    _build_brightness_section,
    _build_auto_brightness_section,
    _build_auto_motion_section,
    DASHBOARD_HEADER,
)


class TestGetPlatformForKey:
    """Test the _get_platform_for_key helper."""

    def test_binary_sensor_keys(self):
        """Test binary sensor entity keys."""
        assert _get_platform_for_key("screen_on") == "binary_sensor"
        assert _get_platform_for_key("art_mode") == "binary_sensor"

    def test_sensor_keys(self):
        """Test sensor entity keys."""
        assert _get_platform_for_key("current_artwork") == "sensor"
        assert _get_platform_for_key("last_shuffle_image") == "sensor"
        assert _get_platform_for_key("auto_bright_next") == "sensor"
        assert _get_platform_for_key("auto_motion_off_at") == "sensor"

    def test_number_keys(self):
        """Test number entity keys."""
        assert _get_platform_for_key("brightness") == "number"
        assert _get_platform_for_key("min_lux") == "number"
        assert _get_platform_for_key("motion_off_delay") == "number"

    def test_switch_keys(self):
        """Test switch entity keys."""
        assert _get_platform_for_key("dynamic_brightness") == "switch"
        assert _get_platform_for_key("motion_control") == "switch"

    def test_button_keys(self):
        """Test button entity keys."""
        assert _get_platform_for_key("tv_on") == "button"
        assert _get_platform_for_key("shuffle") == "button"
        assert _get_platform_for_key("trigger_brightness") == "button"

    def test_unknown_key_defaults_to_sensor(self):
        """Test unknown keys default to sensor."""
        assert _get_platform_for_key("unknown_key") == "sensor"


class TestBuildStatusSection:
    """Test the _build_status_section helper."""

    def test_with_all_entities(self):
        """Test with all status entities present."""
        entities = {
            "screen_on": "binary_sensor.tv_screen_on",
            "art_mode": "binary_sensor.tv_art_mode",
            "tv_on": "button.tv_on",
            "tv_off": "button.tv_off",
            "art_mode_button": "button.tv_art_mode",
            "on_art_mode": "button.tv_on_art_mode",
        }
        result = _build_status_section(entities)
        
        assert result is not None
        assert result["type"] == "vertical-stack"
        assert len(result["cards"]) == 2

    def test_with_no_entities(self):
        """Test with no status entities."""
        result = _build_status_section({})
        assert result is None

    def test_with_partial_entities(self):
        """Test with only some entities present."""
        entities = {
            "screen_on": "binary_sensor.tv_screen_on",
        }
        result = _build_status_section(entities)
        
        assert result is not None
        assert result["type"] == "vertical-stack"


class TestBuildImageSection:
    """Test the _build_image_section helper."""

    def test_with_all_entities(self):
        """Test with all image entities present."""
        entities = {
            "current_artwork": "sensor.tv_current_artwork",
            "shuffle": "button.tv_shuffle",
            "shuffle_frequency": "number.tv_shuffle_frequency",
            "last_shuffle_timestamp": "sensor.tv_last_shuffle",
        }
        result = _build_image_section(entities)
        
        assert result is not None
        assert result["type"] == "entities"
        assert "🎨 Current Artwork" in result["title"]
        assert len(result["entities"]) == 4

    def test_with_no_entities(self):
        """Test with no image entities."""
        result = _build_image_section({})
        assert result is None


class TestBuildBrightnessSection:
    """Test the _build_brightness_section helper."""

    def test_with_brightness_entity(self):
        """Test with brightness entity present."""
        entities = {
            "brightness": "number.tv_brightness",
        }
        result = _build_brightness_section(entities)
        
        assert result is not None
        assert result["type"] == "entities"
        assert "💡 Brightness" in result["title"]

    def test_without_brightness_entity(self):
        """Test without brightness entity."""
        result = _build_brightness_section({})
        assert result is None


class TestBuildAutoBrightnessSection:
    """Test the _build_auto_brightness_section helper."""

    def test_with_all_entities(self):
        """Test with all auto-brightness entities."""
        entities = {
            "dynamic_brightness": "switch.tv_dynamic_brightness",
            "trigger_brightness": "button.tv_trigger_brightness",
            "auto_bright_sensor_lux": "sensor.tv_auto_bright_lux",
            "auto_bright_target": "sensor.tv_auto_bright_target",
            "min_lux": "number.tv_min_lux",
            "max_lux": "number.tv_max_lux",
            "calibrate_dark": "button.tv_calibrate_dark",
        }
        result = _build_auto_brightness_section(entities)
        
        assert result is not None
        assert result["type"] == "vertical-stack"
        assert len(result["cards"]) == 2

    def test_with_no_entities(self):
        """Test with no auto-brightness entities."""
        result = _build_auto_brightness_section({})
        assert result is None


class TestBuildAutoMotionSection:
    """Test the _build_auto_motion_section helper."""

    def test_with_all_entities(self):
        """Test with all auto-motion entities."""
        entities = {
            "motion_control": "switch.tv_motion_control",
            "trigger_motion_off": "button.tv_trigger_motion_off",
            "motion_off_delay": "number.tv_motion_off_delay",
            "auto_motion_off_at": "sensor.tv_motion_off_at",
            "auto_motion_last": "sensor.tv_last_motion",
        }
        result = _build_auto_motion_section(entities)
        
        assert result is not None
        assert result["type"] == "entities"
        assert "🚶 Auto-Motion" in result["title"]
        assert len(result["entities"]) == 5

    def test_with_no_entities(self):
        """Test with no auto-motion entities."""
        result = _build_auto_motion_section({})
        assert result is None


class TestDashboardHeader:
    """Test the dashboard header content."""

    def test_header_contains_warning(self):
        """Test that the header contains auto-generated warning."""
        assert "AUTO-GENERATED FILE" in DASHBOARD_HEADER
        assert "DO NOT EDIT" in DASHBOARD_HEADER
        assert "overwritten" in DASHBOARD_HEADER
