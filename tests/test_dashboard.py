"""Tests for the dashboard generator module."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Test the dashboard module functions
from custom_components.frame_art_shuffler.dashboard import (
    _get_platform_for_key,
    _build_artwork_section,
    _build_combined_brightness_section,
    _build_auto_motion_section,
    DASHBOARD_HEADER,
)


class TestGetPlatformForKey:
    """Test the _get_platform_for_key helper."""

    def test_binary_sensor_keys(self):
        """Test binary sensor entity keys."""
        assert _get_platform_for_key("screen_on") == "binary_sensor"

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
        assert _get_platform_for_key("power") == "switch"
        assert _get_platform_for_key("dynamic_brightness") == "switch"
        assert _get_platform_for_key("motion_control") == "switch"

    def test_button_keys(self):
        """Test button entity keys."""
        assert _get_platform_for_key("shuffle") == "button"
        assert _get_platform_for_key("trigger_brightness") == "button"

    def test_unknown_key_defaults_to_sensor(self):
        """Test unknown keys default to sensor."""
        assert _get_platform_for_key("unknown_key") == "sensor"


class TestBuildArtworkSection:
    """Test the _build_artwork_section helper."""

    def test_with_all_entities(self):
        """Artwork card should include auto shuffle controls when available."""
        entities = {
            "current_artwork": "sensor.tv_current_artwork",
            "shuffle": "button.tv_shuffle",
            "auto_shuffle_switch": "switch.tv_auto_shuffle",
            "auto_shuffle_next": "sensor.tv_auto_shuffle_next",
            "shuffle_frequency": "number.tv_shuffle_frequency",
            "last_shuffle_timestamp": "sensor.tv_last_shuffle",
            "matte_filter": "sensor.tv_matte_filter",
        }
        result = _build_artwork_section(entities)

        assert result is not None
        assert result["type"] == "vertical-stack"
        assert len(result["cards"]) == 2  # markdown + entities card
        entities_card = result["cards"][1]
        entity_ids = [item["entity"] for item in entities_card["entities"]]
        assert entity_ids[:2] == [
            "switch.tv_auto_shuffle",
            "button.tv_shuffle",
        ]
        assert "sensor.tv_auto_shuffle_next" in entity_ids

    def test_with_no_entities(self):
        """If no artwork entities exist, return None."""
        result = _build_artwork_section({})
        assert result is None


class TestBuildBrightnessSection:
    """Test the combined brightness helper."""

    def test_with_brightness_entities(self):
        """Card should render when at least one brightness entity exists."""
        entities = {
            "dynamic_brightness": "switch.tv_dynamic_brightness",
            "trigger_brightness": "button.tv_trigger_brightness",
            "brightness": "number.tv_brightness",
        }
        result = _build_combined_brightness_section(entities)

        assert result is not None
        assert result["type"] == "entities"
        assert result["entities"][0]["entity"] == "switch.tv_dynamic_brightness"

    def test_without_brightness_entities(self):
        """No card when nothing is supplied."""
        result = _build_combined_brightness_section({})
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
        assert "Motion" in result["title"]
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
