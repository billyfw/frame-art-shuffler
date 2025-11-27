"""Sensor platform for Frame Art Shuffler TVs."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription, SensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_NAME, EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .config_entry import get_tv_config
from .const import (
    CONF_SHUFFLE_FREQUENCY,
    CONF_MOTION_SENSOR,
    CONF_LIGHT_SENSOR,
    DOMAIN,
)
from .coordinator import FrameArtCoordinator

_LOGGER = logging.getLogger(__name__)

# Auto brightness interval (must match __init__.py)
AUTO_BRIGHTNESS_INTERVAL_MINUTES = 10


TV_DESCRIPTION = SensorEntityDescription(
    key="current_artwork",
    icon="mdi:image-frame",
    translation_key="current_artwork",
)

LAST_SHUFFLE_IMAGE_DESCRIPTION = SensorEntityDescription(
    key="last_shuffle_image",
    icon="mdi:image-multiple",
    translation_key="last_shuffle_image",
)

LAST_SHUFFLE_TIMESTAMP_DESCRIPTION = SensorEntityDescription(
    key="last_shuffle_timestamp",
    icon="mdi:clock-outline",
    device_class=SensorDeviceClass.TIMESTAMP,
    translation_key="last_shuffle_timestamp",
)

IP_DESCRIPTION = SensorEntityDescription(
    key="ip_address",
    icon="mdi:ip-network",
    entity_category=EntityCategory.DIAGNOSTIC,
    translation_key="ip_address",
)

MAC_DESCRIPTION = SensorEntityDescription(
    key="mac_address",
    icon="mdi:ethernet",
    entity_category=EntityCategory.DIAGNOSTIC,
    translation_key="mac_address",
)

MOTION_SENSOR_DESCRIPTION = SensorEntityDescription(
    key="motion_sensor",
    icon="mdi:motion-sensor",
    entity_category=EntityCategory.DIAGNOSTIC,
    translation_key="motion_sensor",
)

LIGHT_SENSOR_DESCRIPTION = SensorEntityDescription(
    key="light_sensor",
    icon="mdi:brightness-auto",
    entity_category=EntityCategory.DIAGNOSTIC,
    translation_key="light_sensor",
)

AUTO_BRIGHT_LAST_ADJUST_DESCRIPTION = SensorEntityDescription(
    key="auto_bright_last_adjust",
    icon="mdi:clock-check-outline",
    device_class=SensorDeviceClass.TIMESTAMP,
    entity_category=EntityCategory.DIAGNOSTIC,
    translation_key="auto_bright_last_adjust",
)

AUTO_BRIGHT_NEXT_ADJUST_DESCRIPTION = SensorEntityDescription(
    key="auto_bright_next_adjust",
    icon="mdi:clock-fast",
    device_class=SensorDeviceClass.TIMESTAMP,
    entity_category=EntityCategory.DIAGNOSTIC,
    translation_key="auto_bright_next_adjust",
)

AUTO_BRIGHT_TARGET_DESCRIPTION = SensorEntityDescription(
    key="auto_bright_target",
    icon="mdi:brightness-percent",
    entity_category=EntityCategory.DIAGNOSTIC,
    translation_key="auto_bright_target",
)

AUTO_BRIGHT_SENSOR_LUX_DESCRIPTION = SensorEntityDescription(
    key="auto_bright_sensor_lux",
    icon="mdi:brightness-5",
    device_class=SensorDeviceClass.ILLUMINANCE,
    native_unit_of_measurement="lx",
    entity_category=EntityCategory.DIAGNOSTIC,
    translation_key="auto_bright_sensor_lux",
)

AUTO_MOTION_LAST_MOTION_DESCRIPTION = SensorEntityDescription(
    key="auto_motion_last_motion",
    icon="mdi:clock-check-outline",
    device_class=SensorDeviceClass.TIMESTAMP,
    entity_category=EntityCategory.DIAGNOSTIC,
    translation_key="auto_motion_last_motion",
)

AUTO_MOTION_OFF_AT_DESCRIPTION = SensorEntityDescription(
    key="auto_motion_off_at",
    icon="mdi:clock-alert-outline",
    device_class=SensorDeviceClass.TIMESTAMP,
    entity_category=EntityCategory.DIAGNOSTIC,
    translation_key="auto_motion_off_at",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities,
) -> None:
    """Set up Frame Art TV sensors for a config entry."""

    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: FrameArtCoordinator = data["coordinator"]

    tracked: dict[str, tuple] = {}

    @callback
    def _process_tvs(tvs: Iterable[dict[str, Any]]) -> None:
        new_entities: list[SensorEntity] = []
        for tv in tvs:
            tv_id = tv.get("id")
            if not tv_id or tv_id in tracked:
                continue
            
            # Create all sensors per TV
            current_artwork_entity = FrameArtTVEntity(coordinator, entry, tv_id)
            last_image_entity = FrameArtLastShuffleImageEntity(coordinator, entry, tv_id)
            last_timestamp_entity = FrameArtLastShuffleTimestampEntity(coordinator, entry, tv_id)
            ip_entity = FrameArtIPEntity(coordinator, entry, tv_id)
            mac_entity = FrameArtMACEntity(coordinator, entry, tv_id)
            motion_entity = FrameArtMotionSensorEntity(coordinator, entry, tv_id)
            light_entity = FrameArtLightSensorEntity(coordinator, entry, tv_id)
            # Auto brightness sensors
            auto_bright_last_entity = FrameArtAutoBrightLastAdjustEntity(coordinator, entry, tv_id)
            auto_bright_next_entity = FrameArtAutoBrightNextAdjustEntity(coordinator, entry, tv_id)
            auto_bright_target_entity = FrameArtAutoBrightTargetEntity(hass, coordinator, entry, tv_id)
            auto_bright_lux_entity = FrameArtAutoBrightSensorLuxEntity(hass, coordinator, entry, tv_id)
            # Auto motion sensors
            auto_motion_last_entity = FrameArtAutoMotionLastMotionEntity(hass, coordinator, entry, tv_id)
            auto_motion_off_at_entity = FrameArtAutoMotionOffAtEntity(hass, coordinator, entry, tv_id)
            
            tracked[tv_id] = (current_artwork_entity, last_image_entity, last_timestamp_entity, ip_entity, mac_entity, motion_entity, light_entity, auto_bright_last_entity, auto_bright_next_entity, auto_bright_target_entity, auto_bright_lux_entity, auto_motion_last_entity, auto_motion_off_at_entity)
            new_entities.extend([current_artwork_entity, last_image_entity, last_timestamp_entity, ip_entity, mac_entity, motion_entity, light_entity, auto_bright_last_entity, auto_bright_next_entity, auto_bright_target_entity, auto_bright_lux_entity, auto_motion_last_entity, auto_motion_off_at_entity])
            
        if new_entities:
            async_add_entities(new_entities)

    _process_tvs(coordinator.data or [])

    @callback
    def _handle_coordinator_update() -> None:
        _process_tvs(coordinator.data or [])

    unsubscribe = coordinator.async_add_listener(_handle_coordinator_update)
    entry.async_on_unload(unsubscribe)


class FrameArtTVEntity(CoordinatorEntity[FrameArtCoordinator], SensorEntity):
    """Representation of a Frame TV from metadata."""

    entity_description = TV_DESCRIPTION
    _attr_has_entity_name = True
    _attr_name = "Current Artwork"

    def __init__(self, coordinator: FrameArtCoordinator, entry: ConfigEntry, tv_id: str) -> None:
        super().__init__(coordinator)
        self._tv_id = tv_id
        # Use just tv_id as identifier (no home prefix)
        identifier = tv_id
        self._attr_unique_id = f"{entry.entry_id}_{tv_id}"

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, identifier)},
            name=self._derive_name(),
            manufacturer="Samsung",
            model="Frame TV",
        )

    def _derive_name(self) -> str:
        tv = self._current_tv
        if not tv:
            return "Frame TV"
        return tv.get(CONF_NAME) or tv.get("name") or "Frame TV"

    @property
    def _current_tv(self) -> dict[str, Any] | None:
        tvs = self.coordinator.data or []
        for tv in tvs:
            if tv.get("id") == self._tv_id:
                return tv
        return None

    @property
    def native_value(self) -> str | None:  # type: ignore[override]
        """Return the current artwork."""
        tv = self._current_tv
        if not tv:
            return None
        
        # Check top-level current_image first (set by button.py)
        current = tv.get("current_image")
        if current:
            return str(current)

        # Fallback to legacy shuffle structure
        shuffle = tv.get("shuffle", {})
        if isinstance(shuffle, dict):
            current = shuffle.get("currentImage") or shuffle.get("current")
            if current:
                # Extract filename from path if it's a full path
                if isinstance(current, str) and "/" in current:
                    return current.split("/")[-1]
                return str(current)
        return "Unknown"

    @property
    def available(self) -> bool:  # type: ignore[override]
        """Return if entity is available."""
        return self._current_tv is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:  # type: ignore[override]
        """Return extra state attributes."""
        tv = self._current_tv
        if not tv:
            return None
        data = {
            "ip": tv.get("ip"),
            "mac": tv.get("mac"),
            "tags": tv.get("tags", []),
            "exclude_tags": tv.get("notTags", []),
            "motion_sensor": tv.get(CONF_MOTION_SENSOR),
            "light_sensor": tv.get(CONF_LIGHT_SENSOR),
        }
        shuffle = tv.get("shuffle") or {}
        if isinstance(shuffle, dict):
            data["shuffle_frequency"] = shuffle.get(CONF_SHUFFLE_FREQUENCY)
        return data


class FrameArtLastShuffleImageEntity(CoordinatorEntity[FrameArtCoordinator], SensorEntity):
    """Sensor entity for last shuffled image filename."""

    entity_description = LAST_SHUFFLE_IMAGE_DESCRIPTION
    _attr_has_entity_name = True
    _attr_name = "Last Shuffle Image"

    def __init__(self, coordinator: FrameArtCoordinator, entry: ConfigEntry, tv_id: str) -> None:
        super().__init__(coordinator)
        self._tv_id = tv_id
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{tv_id}_last_shuffle_image"

        tv_config = get_tv_config(entry, tv_id)
        tv_name = tv_config.get("name", tv_id) if tv_config else tv_id

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tv_id)},
            name=tv_name,
            manufacturer="Samsung",
            model="Frame TV",
        )

    @property
    def native_value(self) -> str | None:  # type: ignore[override]
        """Return the last shuffled image filename."""
        tv_config = get_tv_config(self._entry, self._tv_id)
        if not tv_config:
            return None
        return tv_config.get("last_shuffle_image")

    @property
    def available(self) -> bool:  # type: ignore[override]
        """Return if entity is available."""
        return get_tv_config(self._entry, self._tv_id) is not None


class FrameArtLastShuffleTimestampEntity(CoordinatorEntity[FrameArtCoordinator], SensorEntity):
    """Sensor entity for last shuffle timestamp."""

    entity_description = LAST_SHUFFLE_TIMESTAMP_DESCRIPTION
    _attr_has_entity_name = True
    _attr_name = "Last Shuffle Timestamp"

    def __init__(self, coordinator: FrameArtCoordinator, entry: ConfigEntry, tv_id: str) -> None:
        super().__init__(coordinator)
        self._tv_id = tv_id
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{tv_id}_last_shuffle_timestamp"

        tv_config = get_tv_config(entry, tv_id)
        tv_name = tv_config.get("name", tv_id) if tv_config else tv_id

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tv_id)},
            name=tv_name,
            manufacturer="Samsung",
            model="Frame TV",
        )

    @property
    def native_value(self) -> datetime | None:  # type: ignore[override]
        """Return the last shuffle timestamp."""
        tv_config = get_tv_config(self._entry, self._tv_id)
        if not tv_config:
            return None
        
        timestamp_str = tv_config.get("last_shuffle_timestamp")
        if not timestamp_str:
            return None
        
        try:
            dt = datetime.fromisoformat(timestamp_str)
            # Ensure timezone awareness if missing (assume local/system time if naive)
            if dt.tzinfo is None:
                from homeassistant.util import dt as dt_util
                return dt.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
            return dt
        except (ValueError, TypeError):
            return None

    @property
    def available(self) -> bool:  # type: ignore[override]
        """Return if entity is available."""
        return get_tv_config(self._entry, self._tv_id) is not None


class FrameArtIPEntity(CoordinatorEntity[FrameArtCoordinator], SensorEntity):
    """Diagnostic sensor for TV IP address."""

    entity_description = IP_DESCRIPTION
    _attr_has_entity_name = True
    _attr_name = "IP Address"

    def __init__(self, coordinator: FrameArtCoordinator, entry: ConfigEntry, tv_id: str) -> None:
        super().__init__(coordinator)
        self._tv_id = tv_id
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{tv_id}_ip"

        tv_config = get_tv_config(entry, tv_id)
        tv_name = tv_config.get("name", tv_id) if tv_config else tv_id

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tv_id)},
            name=tv_name,
            manufacturer="Samsung",
            model="Frame TV",
        )

    @property
    def native_value(self) -> str | None:  # type: ignore[override]
        """Return the IP address."""
        tv_config = get_tv_config(self._entry, self._tv_id)
        if not tv_config:
            return None
        return tv_config.get("ip")


class FrameArtMACEntity(CoordinatorEntity[FrameArtCoordinator], SensorEntity):
    """Diagnostic sensor for TV MAC address."""

    entity_description = MAC_DESCRIPTION
    _attr_has_entity_name = True
    _attr_name = "MAC Address"

    def __init__(self, coordinator: FrameArtCoordinator, entry: ConfigEntry, tv_id: str) -> None:
        super().__init__(coordinator)
        self._tv_id = tv_id
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{tv_id}_mac"

        tv_config = get_tv_config(entry, tv_id)
        tv_name = tv_config.get("name", tv_id) if tv_config else tv_id

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tv_id)},
            name=tv_name,
            manufacturer="Samsung",
            model="Frame TV",
        )

    @property
    def native_value(self) -> str | None:  # type: ignore[override]
        """Return the MAC address."""
        tv_config = get_tv_config(self._entry, self._tv_id)
        if not tv_config:
            return None
        return tv_config.get("mac")


class FrameArtMotionSensorEntity(CoordinatorEntity[FrameArtCoordinator], SensorEntity):
    """Diagnostic sensor for TV motion sensor entity ID."""

    entity_description = MOTION_SENSOR_DESCRIPTION
    _attr_has_entity_name = True
    _attr_name = "Auto-Motion Sensor"

    def __init__(self, coordinator: FrameArtCoordinator, entry: ConfigEntry, tv_id: str) -> None:
        super().__init__(coordinator)
        self._tv_id = tv_id
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{tv_id}_motion_sensor"

        tv_config = get_tv_config(entry, tv_id)
        tv_name = tv_config.get("name", tv_id) if tv_config else tv_id

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tv_id)},
            name=tv_name,
            manufacturer="Samsung",
            model="Frame TV",
        )

    @property
    def native_value(self) -> str | None:  # type: ignore[override]
        """Return the motion sensor entity ID."""
        tv_config = get_tv_config(self._entry, self._tv_id)
        if not tv_config:
            return None
        return tv_config.get("motion_sensor")


class FrameArtLightSensorEntity(CoordinatorEntity[FrameArtCoordinator], SensorEntity):
    """Diagnostic sensor for TV light sensor entity ID."""

    entity_description = LIGHT_SENSOR_DESCRIPTION
    _attr_has_entity_name = True
    _attr_name = "Light Source"

    def __init__(self, coordinator: FrameArtCoordinator, entry: ConfigEntry, tv_id: str) -> None:
        super().__init__(coordinator)
        self._tv_id = tv_id
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{tv_id}_light_sensor"

        tv_config = get_tv_config(entry, tv_id)
        tv_name = tv_config.get("name", tv_id) if tv_config else tv_id

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tv_id)},
            name=tv_name,
            manufacturer="Samsung",
            model="Frame TV",
        )

    @property
    def native_value(self) -> str | None:  # type: ignore[override]
        """Return the light sensor entity ID."""
        tv_config = get_tv_config(self._entry, self._tv_id)
        if not tv_config:
            return None
        return tv_config.get("light_sensor")


class FrameArtAutoBrightLastAdjustEntity(CoordinatorEntity[FrameArtCoordinator], SensorEntity):
    """Sensor for last auto brightness adjustment timestamp."""

    entity_description = AUTO_BRIGHT_LAST_ADJUST_DESCRIPTION
    _attr_has_entity_name = True
    _attr_name = "Auto-Bright Last Adjust"

    def __init__(self, coordinator: FrameArtCoordinator, entry: ConfigEntry, tv_id: str) -> None:
        super().__init__(coordinator)
        self._tv_id = tv_id
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{tv_id}_auto_bright_last"

        tv_config = get_tv_config(entry, tv_id)
        tv_name = tv_config.get("name", tv_id) if tv_config else tv_id

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tv_id)},
            name=tv_name,
            manufacturer="Samsung",
            model="Frame TV",
        )

    @property
    def native_value(self) -> datetime | None:  # type: ignore[override]
        """Return the last auto brightness adjustment timestamp."""
        tv_config = get_tv_config(self._entry, self._tv_id)
        if not tv_config:
            return None
        
        timestamp_str = tv_config.get("last_auto_brightness_timestamp")
        if not timestamp_str:
            return None
        
        try:
            dt = datetime.fromisoformat(timestamp_str)
            if dt.tzinfo is None:
                from homeassistant.util import dt as dt_util
                return dt.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
            return dt
        except (ValueError, TypeError):
            return None


class FrameArtAutoBrightNextAdjustEntity(CoordinatorEntity[FrameArtCoordinator], SensorEntity):
    """Sensor for next auto brightness adjustment timestamp."""

    entity_description = AUTO_BRIGHT_NEXT_ADJUST_DESCRIPTION
    _attr_has_entity_name = True
    _attr_name = "Auto-Bright Next Adjust"

    def __init__(self, coordinator: FrameArtCoordinator, entry: ConfigEntry, tv_id: str) -> None:
        super().__init__(coordinator)
        self._tv_id = tv_id
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{tv_id}_auto_bright_next"

        tv_config = get_tv_config(entry, tv_id)
        tv_name = tv_config.get("name", tv_id) if tv_config else tv_id

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tv_id)},
            name=tv_name,
            manufacturer="Samsung",
            model="Frame TV",
        )

    @property
    def native_value(self) -> datetime | None:  # type: ignore[override]
        """Return the next auto brightness adjustment timestamp."""
        tv_config = get_tv_config(self._entry, self._tv_id)
        if not tv_config:
            return None
        
        # If auto brightness is not enabled, return None
        if not tv_config.get("enable_dynamic_brightness", False):
            return None
        
        timestamp_str = tv_config.get("last_auto_brightness_timestamp")
        if not timestamp_str:
            # No previous adjustment - next will be soon (on next interval tick)
            return None
        
        try:
            last_dt = datetime.fromisoformat(timestamp_str)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            next_dt = last_dt + timedelta(minutes=AUTO_BRIGHTNESS_INTERVAL_MINUTES)
            return next_dt
        except (ValueError, TypeError):
            return None


class FrameArtAutoBrightTargetEntity(CoordinatorEntity[FrameArtCoordinator], SensorEntity):
    """Sensor for calculated target brightness based on current lux."""

    entity_description = AUTO_BRIGHT_TARGET_DESCRIPTION
    _attr_has_entity_name = True
    _attr_name = "Auto-Bright Target"

    def __init__(self, hass: HomeAssistant, coordinator: FrameArtCoordinator, entry: ConfigEntry, tv_id: str) -> None:
        super().__init__(coordinator)
        self._hass = hass
        self._tv_id = tv_id
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{tv_id}_auto_bright_target"

        tv_config = get_tv_config(entry, tv_id)
        tv_name = tv_config.get("name", tv_id) if tv_config else tv_id

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tv_id)},
            name=tv_name,
            manufacturer="Samsung",
            model="Frame TV",
        )
        self._unsubscribe_light_sensor: Callable[[], None] | None = None

    async def async_added_to_hass(self) -> None:
        """Subscribe to light sensor state changes for real-time updates."""
        await super().async_added_to_hass()
        
        tv_config = get_tv_config(self._entry, self._tv_id)
        light_sensor = tv_config.get("light_sensor") if tv_config else None
        
        if light_sensor:
            from homeassistant.helpers.event import async_track_state_change_event
            
            @callback
            def _light_sensor_changed(event: Any) -> None:
                """Handle light sensor state change."""
                self.async_write_ha_state()
            
            self._unsubscribe_light_sensor = async_track_state_change_event(
                self._hass,
                [light_sensor],
                _light_sensor_changed,
            )

    async def async_will_remove_from_hass(self) -> None:
        """Unsubscribe from light sensor state changes."""
        if self._unsubscribe_light_sensor:
            self._unsubscribe_light_sensor()
            self._unsubscribe_light_sensor = None
        await super().async_will_remove_from_hass()

    @property
    def native_value(self) -> int | None:  # type: ignore[override]
        """Return the calculated target brightness based on current lux."""
        tv_config = get_tv_config(self._entry, self._tv_id)
        if not tv_config:
            return None
        
        # Get the light sensor entity ID
        light_sensor = tv_config.get("light_sensor")
        if not light_sensor:
            return None
        
        # Get current lux value from the sensor
        lux_state = self._hass.states.get(light_sensor)
        if not lux_state or lux_state.state in ("unavailable", "unknown"):
            return None
        
        try:
            current_lux = float(lux_state.state)
        except (ValueError, TypeError):
            return None
        
        # Get calibration values
        min_lux = tv_config.get("min_lux", 0)
        max_lux = tv_config.get("max_lux", 1000)
        min_brightness = tv_config.get("min_brightness", 1)
        max_brightness = tv_config.get("max_brightness", 10)
        
        # Avoid division by zero
        if max_lux <= min_lux:
            return None
        
        # Calculate normalized value (0-1) with clamping
        normalized = (current_lux - min_lux) / (max_lux - min_lux)
        normalized = max(0.0, min(1.0, normalized))
        
        # Calculate target brightness
        target = int(round(min_brightness + normalized * (max_brightness - min_brightness)))
        return max(min_brightness, min(max_brightness, target))


class FrameArtAutoBrightSensorLuxEntity(CoordinatorEntity[FrameArtCoordinator], SensorEntity):
    """Sensor that mirrors the configured light sensor's lux value."""

    entity_description = AUTO_BRIGHT_SENSOR_LUX_DESCRIPTION
    _attr_has_entity_name = True
    _attr_name = "Auto-Bright Sensor Lux"

    def __init__(self, hass: HomeAssistant, coordinator: FrameArtCoordinator, entry: ConfigEntry, tv_id: str) -> None:
        super().__init__(coordinator)
        self._hass = hass
        self._tv_id = tv_id
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{tv_id}_auto_bright_sensor_lux"

        tv_config = get_tv_config(entry, tv_id)
        tv_name = tv_config.get("name", tv_id) if tv_config else tv_id

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tv_id)},
            name=tv_name,
            manufacturer="Samsung",
            model="Frame TV",
        )
        self._unsubscribe_light_sensor: Callable[[], None] | None = None

    async def async_added_to_hass(self) -> None:
        """Subscribe to light sensor state changes for real-time updates."""
        await super().async_added_to_hass()
        
        tv_config = get_tv_config(self._entry, self._tv_id)
        light_sensor = tv_config.get("light_sensor") if tv_config else None
        
        if light_sensor:
            from homeassistant.helpers.event import async_track_state_change_event
            
            @callback
            def _light_sensor_changed(event: Any) -> None:
                """Handle light sensor state change."""
                self.async_write_ha_state()
            
            self._unsubscribe_light_sensor = async_track_state_change_event(
                self._hass,
                [light_sensor],
                _light_sensor_changed,
            )

    async def async_will_remove_from_hass(self) -> None:
        """Unsubscribe from light sensor state changes."""
        if self._unsubscribe_light_sensor:
            self._unsubscribe_light_sensor()
            self._unsubscribe_light_sensor = None
        await super().async_will_remove_from_hass()

    @property
    def native_value(self) -> float | None:  # type: ignore[override]
        """Return the current lux value from the configured light sensor."""
        tv_config = get_tv_config(self._entry, self._tv_id)
        if not tv_config:
            return None
        
        # Get the light sensor entity ID
        light_sensor = tv_config.get("light_sensor")
        if not light_sensor:
            return None
        
        # Get current lux value from the sensor
        lux_state = self._hass.states.get(light_sensor)
        if not lux_state or lux_state.state in ("unavailable", "unknown"):
            return None
        
        try:
            return float(lux_state.state)
        except (ValueError, TypeError):
            return None


class FrameArtAutoMotionLastMotionEntity(CoordinatorEntity[FrameArtCoordinator], SensorEntity):
    """Sensor for last detected motion timestamp."""

    entity_description = AUTO_MOTION_LAST_MOTION_DESCRIPTION
    _attr_has_entity_name = True
    _attr_name = "Auto-Motion Last Motion"

    def __init__(self, hass: HomeAssistant, coordinator: FrameArtCoordinator, entry: ConfigEntry, tv_id: str) -> None:
        super().__init__(coordinator)
        self._hass = hass
        self._tv_id = tv_id
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{tv_id}_auto_motion_last"
        self._last_motion: datetime | None = None
        self._unsubscribe_motion_sensor: Callable[[], None] | None = None

        tv_config = get_tv_config(entry, tv_id)
        tv_name = tv_config.get("name", tv_id) if tv_config else tv_id

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tv_id)},
            name=tv_name,
            manufacturer="Samsung",
            model="Frame TV",
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to motion detected signals for real-time updates."""
        await super().async_added_to_hass()
        
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        
        @callback
        def _motion_detected() -> None:
            """Handle motion detected signal."""
            # Clear local cache to force read from config
            self._last_motion = None
            self.async_write_ha_state()
        
        signal = f"{DOMAIN}_motion_detected_{self._entry.entry_id}_{self._tv_id}"
        self._unsubscribe_motion_sensor = async_dispatcher_connect(
            self._hass,
            signal,
            _motion_detected,
        )

    async def async_will_remove_from_hass(self) -> None:
        """Unsubscribe from motion detected signals."""
        if self._unsubscribe_motion_sensor:
            self._unsubscribe_motion_sensor()
            self._unsubscribe_motion_sensor = None
        await super().async_will_remove_from_hass()

    @property
    def native_value(self) -> datetime | None:  # type: ignore[override]
        """Return the last motion timestamp."""
        # Fall back to persisted config value (from auto-motion handler)
        tv_config = get_tv_config(self._entry, self._tv_id)
        if not tv_config:
            return None
        
        timestamp_str = tv_config.get("last_motion_timestamp")
        if not timestamp_str:
            return None
        
        try:
            dt = datetime.fromisoformat(timestamp_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, TypeError):
            return None


class FrameArtAutoMotionOffAtEntity(CoordinatorEntity[FrameArtCoordinator], SensorEntity):
    """Sensor for when TV will turn off due to no motion."""

    entity_description = AUTO_MOTION_OFF_AT_DESCRIPTION
    _attr_has_entity_name = True
    _attr_name = "Auto-Motion Off At"

    def __init__(self, hass: HomeAssistant, coordinator: FrameArtCoordinator, entry: ConfigEntry, tv_id: str) -> None:
        super().__init__(coordinator)
        self._hass = hass
        self._tv_id = tv_id
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{tv_id}_auto_motion_off_at"
        self._unsubscribe_dispatcher: Callable[[], None] | None = None

        tv_config = get_tv_config(entry, tv_id)
        tv_name = tv_config.get("name", tv_id) if tv_config else tv_id

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tv_id)},
            name=tv_name,
            manufacturer="Samsung",
            model="Frame TV",
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to off time update signals."""
        await super().async_added_to_hass()
        
        from homeassistant.helpers.dispatcher import async_dispatcher_connect
        
        # Capture self references for use in callback
        entity = self
        tv_id = self._tv_id
        
        @callback
        def _off_time_updated() -> None:
            """Handle off time update signal."""
            _LOGGER.debug(f"Auto motion: Sensor received off time update signal for {tv_id}")
            entity.async_write_ha_state()
        
        signal = f"{DOMAIN}_motion_off_time_updated_{self._entry.entry_id}_{self._tv_id}"
        self._unsubscribe_dispatcher = async_dispatcher_connect(
            self._hass,
            signal,
            _off_time_updated,
        )

    async def async_will_remove_from_hass(self) -> None:
        """Unsubscribe from off time update signals."""
        if self._unsubscribe_dispatcher:
            self._unsubscribe_dispatcher()
            self._unsubscribe_dispatcher = None
        await super().async_will_remove_from_hass()

    @property
    def available(self) -> bool:
        """Return if entity is available (only when auto-motion is enabled)."""
        tv_config = get_tv_config(self._entry, self._tv_id)
        if not tv_config:
            return False
        return tv_config.get("enable_motion_control", False)

    @property
    def native_value(self) -> datetime | None:  # type: ignore[override]
        """Return when the TV will turn off."""
        # Get the scheduled off time from hass.data
        data = self._hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})
        motion_off_times = data.get("motion_off_times", {})
        off_time = motion_off_times.get(self._tv_id)
        
        _LOGGER.debug(f"Auto motion Off At sensor: entry_id={self._entry.entry_id}, tv_id={self._tv_id}, dict_id={id(motion_off_times)}, off_time={off_time}")
        
        if off_time and isinstance(off_time, datetime):
            if off_time.tzinfo is None:
                off_time = off_time.replace(tzinfo=timezone.utc)
            return off_time
        
        return None
