"""Button entities for Frame Art Shuffler TV management."""

from __future__ import annotations

import functools
import logging
import random
from datetime import datetime
from pathlib import Path
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers import device_registry as dr

from .config_entry import get_tv_config, update_tv_config
from .const import DOMAIN
from .coordinator import FrameArtCoordinator
from .frame_tv import tv_on, tv_off, set_art_on_tv_deleteothers, set_art_mode, delete_token, FrameArtError
from .activity import log_activity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Frame Art button entities for a config entry."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: FrameArtCoordinator = data["coordinator"]

    tracked_art_mode: dict[str, FrameArtArtModeButton] = {}
    tracked_on_art: dict[str, FrameArtOnArtModeButton] = {}
    tracked_shuffle: dict[str, FrameArtShuffleButton] = {}
    tracked_clear_token: dict[str, FrameArtClearTokenButton] = {}
    tracked_calibrate_dark: dict[str, FrameArtCalibrateDarkButton] = {}
    tracked_calibrate_bright: dict[str, FrameArtCalibrateBrightButton] = {}
    tracked_trigger_brightness: dict[str, FrameArtTriggerBrightnessButton] = {}
    tracked_trigger_motion_off: dict[str, FrameArtTriggerMotionOffButton] = {}

    @callback
    def _process_tvs(tvs: list[dict[str, Any]]) -> None:
        new_entities: list[ButtonEntity] = []
        current_tv_ids = {tv.get("id") for tv in tvs if tv.get("id")}

        # Remove entities for TVs that no longer exist
        for tv_id in list(tracked_art_mode.keys()):
            if tv_id not in current_tv_ids:
                tracked_art_mode.pop(tv_id)
        for tv_id in list(tracked_on_art.keys()):
            if tv_id not in current_tv_ids:
                tracked_on_art.pop(tv_id)
        for tv_id in list(tracked_shuffle.keys()):
            if tv_id not in current_tv_ids:
                tracked_shuffle.pop(tv_id)
        for tv_id in list(tracked_clear_token.keys()):
            if tv_id not in current_tv_ids:
                tracked_clear_token.pop(tv_id)
        for tv_id in list(tracked_calibrate_dark.keys()):
            if tv_id not in current_tv_ids:
                tracked_calibrate_dark.pop(tv_id)
        for tv_id in list(tracked_calibrate_bright.keys()):
            if tv_id not in current_tv_ids:
                tracked_calibrate_bright.pop(tv_id)
        for tv_id in list(tracked_trigger_brightness.keys()):
            if tv_id not in current_tv_ids:
                tracked_trigger_brightness.pop(tv_id)
        for tv_id in list(tracked_trigger_motion_off.keys()):
            if tv_id not in current_tv_ids:
                tracked_trigger_motion_off.pop(tv_id)

        # Add entities for new TVs
        for tv in tvs:
            tv_id = tv.get("id")
            if not tv_id:
                continue
            
            # Add Art Mode button
            if tv_id not in tracked_art_mode:
                entity = FrameArtArtModeButton(coordinator, entry, tv_id)
                tracked_art_mode[tv_id] = entity
                new_entities.append(entity)
            
            # Add On+Art Mode button
            if tv_id not in tracked_on_art:
                entity = FrameArtOnArtModeButton(coordinator, entry, tv_id)
                tracked_on_art[tv_id] = entity
                new_entities.append(entity)
            
            # Add Shuffle button
            if tv_id not in tracked_shuffle:
                entity = FrameArtShuffleButton(coordinator, entry, tv_id)
                tracked_shuffle[tv_id] = entity
                new_entities.append(entity)

            # Add Clear Token button
            if tv_id not in tracked_clear_token:
                entity = FrameArtClearTokenButton(coordinator, entry, tv_id)
                tracked_clear_token[tv_id] = entity
                new_entities.append(entity)

            # Add Calibrate Dark button
            if tv_id not in tracked_calibrate_dark:
                entity = FrameArtCalibrateDarkButton(coordinator, entry, tv_id)
                tracked_calibrate_dark[tv_id] = entity
                new_entities.append(entity)

            # Add Calibrate Bright button
            if tv_id not in tracked_calibrate_bright:
                entity = FrameArtCalibrateBrightButton(coordinator, entry, tv_id)
                tracked_calibrate_bright[tv_id] = entity
                new_entities.append(entity)

            # Add Trigger Brightness button
            if tv_id not in tracked_trigger_brightness:
                entity = FrameArtTriggerBrightnessButton(coordinator, entry, tv_id)
                tracked_trigger_brightness[tv_id] = entity
                new_entities.append(entity)

            # Add Trigger Motion Off button
            if tv_id not in tracked_trigger_motion_off:
                entity = FrameArtTriggerMotionOffButton(hass, coordinator, entry, tv_id)
                tracked_trigger_motion_off[tv_id] = entity
                new_entities.append(entity)

        if new_entities:
            async_add_entities(new_entities)

    coordinator.async_add_listener(lambda: _process_tvs(coordinator.data or []))
    _process_tvs(coordinator.data or [])
class FrameArtRemoveTVButton(CoordinatorEntity[FrameArtCoordinator], ButtonEntity):  # type: ignore[misc]
    """Button entity to remove a TV."""

    _attr_has_entity_name = True
    _attr_name = "zzDANGER-DEL THIS TV"
    _attr_icon = "mdi:delete-alert"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: FrameArtCoordinator,
        entry: ConfigEntry,
        tv_id: str,
    ) -> None:
        """Initialize the button entity."""
        super().__init__(coordinator)
        self._tv_id = tv_id
        self._entry = entry

        # Get TV name from config entry
        tv_config = get_tv_config(entry, tv_id)
        self._tv_name = tv_config.get("name", tv_id) if tv_config else tv_id
        self._tv_ip = tv_config.get("ip") if tv_config else None
        
        # Use tv_id as identifier (no home prefix)
        identifier = tv_id

        self._attr_unique_id = f"{tv_id}_remove"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, identifier)},
            name=self._tv_name,
            manufacturer="Samsung",
            model="Frame TV",
        )

    async def async_press(self) -> None:
        """Handle the button press - remove this TV."""
        # First, try to clean up the token file
        if self._tv_ip:
            try:
                await self.hass.async_add_executor_job(delete_token, self._tv_ip)
                _LOGGER.info(f"Deleted token for {self._tv_name} ({self._tv_ip})")
            except Exception as err:
                _LOGGER.warning(f"Failed to delete token for {self._tv_name}: {err}")

        device_registry = dr.async_get(self.hass)
        
        # Find the device for this TV
        identifier = self._tv_id
        device = device_registry.async_get_device(identifiers={(DOMAIN, identifier)})
        
        if device:
            # Remove the device (this will trigger our device_removed listener)
            device_registry.async_remove_device(device.id)
            _LOGGER.info(f"Removed TV device: {self._tv_name}")
        
        # Also remove from config entry so it doesn't reappear on reload
        from .config_entry import remove_tv_config
        remove_tv_config(self.hass, self._entry, self._tv_id)
        _LOGGER.info(f"Removed TV {self._tv_name} from config entry")


class FrameArtArtModeButton(CoordinatorEntity[FrameArtCoordinator], ButtonEntity):  # type: ignore[misc]
    """Button entity to switch TV to art mode."""

    _attr_has_entity_name = True
    _attr_name = "Art Mode"
    _attr_icon = "mdi:palette"

    def __init__(
        self,
        coordinator: FrameArtCoordinator,
        entry: ConfigEntry,
        tv_id: str,
    ) -> None:
        """Initialize the button entity."""
        super().__init__(coordinator)
        self._tv_id = tv_id
        self._entry = entry

        # Get TV config
        tv_config = get_tv_config(entry, tv_id)
        if tv_config:
            self._tv_name = tv_config.get("name", tv_id)
            self._tv_ip = tv_config.get("ip")
        else:
            self._tv_name = tv_id
            self._tv_ip = None

        self._attr_unique_id = f"{tv_id}_art_mode"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tv_id)},
            name=self._tv_name,
            manufacturer="Samsung",
            model="Frame TV",
        )

    async def async_press(self) -> None:
        """Handle the button press - switch TV to art mode."""
        if not self._tv_ip:
            _LOGGER.error(f"Cannot switch {self._tv_name} to art mode: missing IP address in config")
            return

        try:
            await self.hass.async_add_executor_job(set_art_mode, self._tv_ip)
            _LOGGER.info(f"Switched {self._tv_name} to art mode")
        except FrameArtError as err:
            _LOGGER.error(f"Failed to switch {self._tv_name} to art mode: {err}")


class FrameArtOnArtModeButton(CoordinatorEntity[FrameArtCoordinator], ButtonEntity):  # type: ignore[misc]
    """Button entity to turn TV on and then switch to art mode."""

    _attr_has_entity_name = True
    _attr_name = "On+Art Mode (~12s)"
    _attr_icon = "mdi:television-ambient-light"

    def __init__(
        self,
        coordinator: FrameArtCoordinator,
        entry: ConfigEntry,
        tv_id: str,
    ) -> None:
        """Initialize the button entity."""
        super().__init__(coordinator)
        self._tv_id = tv_id
        self._entry = entry

        # Get TV config
        tv_config = get_tv_config(entry, tv_id)
        if tv_config:
            self._tv_name = tv_config.get("name", tv_id)
            self._tv_ip = tv_config.get("ip")
            self._tv_mac = tv_config.get("mac")
        else:
            self._tv_name = tv_id
            self._tv_ip = None
            self._tv_mac = None

        self._attr_unique_id = f"{tv_id}_on_art_mode"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tv_id)},
            name=self._tv_name,
            manufacturer="Samsung",
            model="Frame TV",
        )

    async def async_press(self) -> None:
        """Handle the button press - turn TV on and switch to art mode."""
        if not self._tv_ip or not self._tv_mac:
            _LOGGER.error(f"Cannot turn on {self._tv_name}: missing IP or MAC address in config")
            return

        try:
            # First turn on the TV
            await self.hass.async_add_executor_job(tv_on, self._tv_ip, self._tv_mac)
            _LOGGER.info(f"Sent Wake-on-LAN to {self._tv_name}, waiting for TV to be ready...")
            
            # tv_on already includes the ~12 second wait for the TV to be ready
            # Now switch to art mode
            await self.hass.async_add_executor_job(set_art_mode, self._tv_ip)
            _LOGGER.info(f"Switched {self._tv_name} to art mode")
        except FrameArtError as err:
            _LOGGER.error(f"Failed to turn on and switch {self._tv_name} to art mode: {err}")


class FrameArtShuffleButton(CoordinatorEntity[FrameArtCoordinator], ButtonEntity):  # type: ignore[misc]
    """Button entity to shuffle to a random image."""

    _attr_has_entity_name = True
    _attr_name = "Shuffle Image"
    _attr_icon = "mdi:shuffle-variant"

    def __init__(
        self,
        coordinator: FrameArtCoordinator,
        entry: ConfigEntry,
        tv_id: str,
    ) -> None:
        """Initialize the shuffle button entity."""
        super().__init__(coordinator)
        self._tv_id = tv_id
        self._entry = entry

        # Get TV config
        tv_config = get_tv_config(entry, tv_id)
        if tv_config:
            self._tv_name = tv_config.get("name", tv_id)
            self._tv_ip = tv_config.get("ip")
        else:
            self._tv_name = tv_id
            self._tv_ip = None

        self._attr_unique_id = f"{tv_id}_shuffle"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tv_id)},
            name=self._tv_name,
            manufacturer="Samsung",
            model="Frame TV",
        )

    async def async_press(self) -> None:
        """Handle the button press - shuffle to a random image."""
        if not self._tv_ip:
            _LOGGER.error(f"Cannot shuffle {self._tv_name}: missing IP address in config")
            return

        # Get TV config to access tags and current image
        tv_config = get_tv_config(self._entry, self._tv_id)
        if not tv_config:
            _LOGGER.error(f"Cannot shuffle {self._tv_name}: TV config not found")
            return

        include_tags = tv_config.get("tags", [])
        exclude_tags = tv_config.get("exclude_tags", [])
        current_image = tv_config.get("current_image")

        # Get metadata path and load images
        metadata_path = Path(self._entry.data.get("metadata_path", ""))
        if not metadata_path.exists():
            _LOGGER.error(
                f"Cannot shuffle {self._tv_name}: metadata file not found at {metadata_path}"
            )
            return

        # Select random image using executor job
        try:
            selected_image = await self.hass.async_add_executor_job(
                self._select_random_image,
                metadata_path,
                include_tags,
                exclude_tags,
                current_image,
            )
        except Exception as err:
            _LOGGER.error(f"Failed to select image for {self._tv_name}: {err}")
            return

        if selected_image is None:
            # Logged in _select_random_image
            return

        # Upload the image
        image_filename = selected_image["filename"]
        # Images are stored in the library subdirectory relative to metadata.json
        image_path = metadata_path.parent / "library" / image_filename

        if not image_path.exists():
            _LOGGER.error(
                f"Cannot shuffle {self._tv_name}: image file not found at {image_path}"
            )
            return

        try:
            _LOGGER.info(f"Uploading {image_filename} to {self._tv_name}...")
            # Get matte and filter from selected image metadata
            image_matte = selected_image.get("matte")
            image_filter = selected_image.get("filter")
            if image_filter and image_filter.lower() == "none":
                image_filter = None
            # Use functools.partial to bind keyword-only argument
            upload_func = functools.partial(
                set_art_on_tv_deleteothers,
                delete_others=True,
                matte=image_matte,
                photo_filter=image_filter
            )
            await self.hass.async_add_executor_job(
                upload_func,
                self._tv_ip,
                str(image_path),
            )
            _LOGGER.info(f"Successfully uploaded {image_filename} to {self._tv_name}")

            # Log activity
            log_activity(
                self.hass, self._entry.entry_id, self._tv_id,
                "shuffle",
                f"Shuffled to {image_filename}",
            )

            # Update current_image and last_shuffle_timestamp in config
            await self.coordinator.async_set_active_image(self._tv_id, image_filename, is_shuffle=True)

        except FrameArtError as err:
            _LOGGER.error(f"Failed to upload {image_filename} to {self._tv_name}: {err}")
        except Exception as err:
            _LOGGER.exception(f"Unexpected error during shuffle for {self._tv_name}: {err}")

    def _select_random_image(
        self,
        metadata_path: Path,
        include_tags: list[str],
        exclude_tags: list[str],
        current_image: str | None,
    ) -> dict[str, Any] | None:
        """Select a random image matching tag criteria (runs in executor).
        
        Returns the selected image dict or None if no suitable image found.
        """
        import json

        # Load metadata
        try:
            with open(metadata_path, "r", encoding="utf-8") as f:
                metadata = json.load(f)
        except Exception as err:
            _LOGGER.error(f"Failed to load metadata from {metadata_path}: {err}")
            return None

        images = metadata.get("images", {})
        if not images:
            _LOGGER.warning(f"No images found in metadata for {self._tv_name}")
            return None

        # Filter images by tags
        eligible_images = []
        for filename, image_data in images.items():
            image_tags = set(image_data.get("tags", []))
            
            # Must have at least one include tag (if include_tags is not empty)
            if include_tags:
                has_include = any(tag in image_tags for tag in include_tags)
                if not has_include:
                    continue
            
            # Must not have any exclude tags
            if exclude_tags:
                has_exclude = any(tag in image_tags for tag in exclude_tags)
                if has_exclude:
                    continue
            
            # Add filename to image_data for easier handling
            image_data_with_filename = {**image_data, "filename": filename}
            eligible_images.append(image_data_with_filename)

        if not eligible_images:
            _LOGGER.warning(
                f"No images matching tag criteria for {self._tv_name} "
                f"(include: {include_tags}, exclude: {exclude_tags})"
            )
            return None

        # Log the eligible set
        eligible_filenames = [img["filename"] for img in eligible_images]
        _LOGGER.info(
            f"Shuffle for {self._tv_name}: Found {len(eligible_images)} images matching criteria "
            f"(include: {include_tags}, exclude: {exclude_tags}). "
            f"Candidates: {eligible_filenames}"
        )

        # Remove current image from candidates
        candidates = [img for img in eligible_images if img["filename"] != current_image]

        # If only one image meets criteria and it's current, do nothing
        if not candidates:
            if len(eligible_images) == 1:
                _LOGGER.info(
                    f"Only one image ({eligible_images[0]['filename']}) matches criteria "
                    f"for {self._tv_name} and it's already displayed. No shuffle performed."
                )
                return None
            else:
                # This shouldn't happen (all eligible == current?)
                _LOGGER.warning(
                    f"No candidate images for {self._tv_name} after removing current image"
                )
                return None

        # Select random image
        selected = random.choice(candidates)
        _LOGGER.info(
            f"{selected['filename']} selected for TV {self._tv_name} "
            f"from {len(eligible_images)} eligible images"
        )

        return selected


class FrameArtClearTokenButton(CoordinatorEntity[FrameArtCoordinator], ButtonEntity):  # type: ignore[misc]
    """Button entity to clear the saved token for a TV."""

    _attr_has_entity_name = True
    _attr_name = "Clear Token"
    _attr_icon = "mdi:key-remove"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: FrameArtCoordinator,
        entry: ConfigEntry,
        tv_id: str,
    ) -> None:
        """Initialize the button entity."""
        super().__init__(coordinator)
        self._tv_id = tv_id
        self._entry = entry

        # Get TV config
        tv_config = get_tv_config(entry, tv_id)
        if tv_config:
            self._tv_name = tv_config.get("name", tv_id)
            self._tv_ip = tv_config.get("ip")
        else:
            self._tv_name = tv_id
            self._tv_ip = None

        self._attr_unique_id = f"{tv_id}_clear_token"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tv_id)},
            name=self._tv_name,
            manufacturer="Samsung",
            model="Frame TV",
        )

    async def async_press(self) -> None:
        """Handle the button press - delete the token file."""
        if not self._tv_ip:
            _LOGGER.error(f"Cannot clear token for {self._tv_name}: missing IP address in config")
            return

        try:
            await self.hass.async_add_executor_job(delete_token, self._tv_ip)
            _LOGGER.info(f"Cleared token for {self._tv_name}")
        except FrameArtError as err:
            _LOGGER.error(f"Failed to clear token for {self._tv_name}: {err}")


class FrameArtCalibrateDarkButton(CoordinatorEntity[FrameArtCoordinator], ButtonEntity):  # type: ignore[misc]
    """Button entity to calibrate min lux (set to current sensor value)."""

    _attr_has_entity_name = True
    _attr_name = "Auto-Bright Calibrate Dark"
    _attr_icon = "mdi:brightness-5"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: FrameArtCoordinator,
        entry: ConfigEntry,
        tv_id: str,
    ) -> None:
        """Initialize the button entity."""
        super().__init__(coordinator)
        self._tv_id = tv_id
        self._entry = entry

        tv_config = get_tv_config(entry, tv_id)
        self._tv_name = tv_config.get("name", tv_id) if tv_config else tv_id

        self._attr_unique_id = f"{tv_id}_calibrate_dark"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tv_id)},
            name=self._tv_name,
            manufacturer="Samsung",
            model="Frame TV",
        )

    async def async_press(self) -> None:
        """Handle the button press - set min_lux to current sensor value."""
        tv_config = get_tv_config(self._entry, self._tv_id)
        if not tv_config:
            _LOGGER.error(f"Cannot calibrate {self._tv_name}: TV config not found")
            return

        light_sensor = tv_config.get("light_sensor")
        if not light_sensor:
            _LOGGER.warning(f"Cannot calibrate {self._tv_name}: no light sensor configured")
            return

        state = self.hass.states.get(light_sensor)
        if not state or state.state in ("unknown", "unavailable"):
            _LOGGER.warning(f"Cannot calibrate {self._tv_name}: sensor {light_sensor} is unavailable")
            return

        try:
            current_lux = float(state.state)
        except ValueError:
            _LOGGER.warning(f"Cannot calibrate {self._tv_name}: sensor value '{state.state}' is not a number")
            return

        update_tv_config(
            self.hass,
            self._entry,
            self._tv_id,
            {"min_lux": int(current_lux)},
        )
        _LOGGER.info(f"Calibrated min_lux for {self._tv_name} to {int(current_lux)}")
        await self.coordinator.async_request_refresh()


class FrameArtCalibrateBrightButton(CoordinatorEntity[FrameArtCoordinator], ButtonEntity):  # type: ignore[misc]
    """Button entity to calibrate max lux (set to current sensor value)."""

    _attr_has_entity_name = True
    _attr_name = "Auto-Bright Calibrate Bright"
    _attr_icon = "mdi:brightness-7"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: FrameArtCoordinator,
        entry: ConfigEntry,
        tv_id: str,
    ) -> None:
        """Initialize the button entity."""
        super().__init__(coordinator)
        self._tv_id = tv_id
        self._entry = entry

        tv_config = get_tv_config(entry, tv_id)
        self._tv_name = tv_config.get("name", tv_id) if tv_config else tv_id

        self._attr_unique_id = f"{tv_id}_calibrate_bright"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tv_id)},
            name=self._tv_name,
            manufacturer="Samsung",
            model="Frame TV",
        )

    async def async_press(self) -> None:
        """Handle the button press - set max_lux to current sensor value."""
        tv_config = get_tv_config(self._entry, self._tv_id)
        if not tv_config:
            _LOGGER.error(f"Cannot calibrate {self._tv_name}: TV config not found")
            return

        light_sensor = tv_config.get("light_sensor")
        if not light_sensor:
            _LOGGER.warning(f"Cannot calibrate {self._tv_name}: no light sensor configured")
            return

        state = self.hass.states.get(light_sensor)
        if not state or state.state in ("unknown", "unavailable"):
            _LOGGER.warning(f"Cannot calibrate {self._tv_name}: sensor {light_sensor} is unavailable")
            return

        try:
            current_lux = float(state.state)
        except ValueError:
            _LOGGER.warning(f"Cannot calibrate {self._tv_name}: sensor value '{state.state}' is not a number")
            return

        update_tv_config(
            self.hass,
            self._entry,
            self._tv_id,
            {"max_lux": int(current_lux)},
        )
        _LOGGER.info(f"Calibrated max_lux for {self._tv_name} to {int(current_lux)}")
        await self.coordinator.async_request_refresh()


class FrameArtTriggerBrightnessButton(CoordinatorEntity[FrameArtCoordinator], ButtonEntity):  # type: ignore[misc]
    """Button entity to trigger auto brightness adjustment now."""

    _attr_has_entity_name = True
    _attr_name = "Auto-Bright Trigger Now"
    _attr_icon = "mdi:brightness-auto"
    # No entity_category = shows in Controls section

    def __init__(
        self,
        coordinator: FrameArtCoordinator,
        entry: ConfigEntry,
        tv_id: str,
    ) -> None:
        """Initialize the button entity."""
        super().__init__(coordinator)
        self._tv_id = tv_id
        self._entry = entry

        tv_config = get_tv_config(entry, tv_id)
        self._tv_name = tv_config.get("name", tv_id) if tv_config else tv_id

        self._attr_unique_id = f"{tv_id}_trigger_brightness"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tv_id)},
            name=self._tv_name,
            manufacturer="Samsung",
            model="Frame TV",
        )

    async def async_press(self) -> None:
        """Handle the button press - trigger auto brightness adjustment."""
        # Get the helper function from hass.data
        data = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id)
        if not data:
            _LOGGER.error(f"Cannot trigger auto brightness for {self._tv_name}: integration data not found")
            return

        async_adjust_tv_brightness = data.get("async_adjust_tv_brightness")
        if not async_adjust_tv_brightness:
            _LOGGER.error(f"Cannot trigger auto brightness for {self._tv_name}: brightness function not found")
            return

        # Pass restart_timer=True to reset the per-TV timer
        success = await async_adjust_tv_brightness(self._tv_id, restart_timer=True)
        if success:
            _LOGGER.info(f"Triggered auto brightness adjustment for {self._tv_name}")
        else:
            _LOGGER.warning(f"Auto brightness adjustment failed for {self._tv_name}")
        
        await self.coordinator.async_request_refresh()


class FrameArtTriggerMotionOffButton(CoordinatorEntity[FrameArtCoordinator], ButtonEntity):  # type: ignore[misc]
    """Button entity to trigger auto motion off (turn TV off) now."""

    _attr_has_entity_name = True
    _attr_name = "Auto-Motion Off Now"
    _attr_icon = "mdi:television-off"
    # No entity_category = shows in Controls section

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: FrameArtCoordinator,
        entry: ConfigEntry,
        tv_id: str,
    ) -> None:
        """Initialize the button entity."""
        super().__init__(coordinator)
        self._hass = hass
        self._tv_id = tv_id
        self._entry = entry

        tv_config = get_tv_config(entry, tv_id)
        self._tv_name = tv_config.get("name", tv_id) if tv_config else tv_id

        self._attr_unique_id = f"{tv_id}_trigger_motion_off"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tv_id)},
            name=self._tv_name,
            manufacturer="Samsung",
            model="Frame TV",
        )

    async def async_press(self) -> None:
        """Handle the button press - turn TV off and cancel motion timer."""
        from datetime import datetime, timezone
        
        tv_config = get_tv_config(self._entry, self._tv_id)
        if not tv_config:
            _LOGGER.error(f"Cannot trigger motion off for {self._tv_name}: TV config not found")
            return

        ip = tv_config.get("ip")
        if not ip:
            _LOGGER.error(f"Cannot trigger motion off for {self._tv_name}: no IP address")
            return

        # Cancel any pending off timer
        data = self._hass.data.get(DOMAIN, {}).get(self._entry.entry_id)
        if data:
            # Clear the scheduled off time
            motion_off_times = data.get("motion_off_times", {})
            if self._tv_id in motion_off_times:
                del motion_off_times[self._tv_id]

        # Turn off the TV
        try:
            _LOGGER.info(f"Auto motion trigger: Turning off {self._tv_name} ({ip})")
            await self._hass.async_add_executor_job(tv_off, ip)
            _LOGGER.info(f"Auto motion trigger: {self._tv_name} turned off successfully")
        except Exception as err:
            _LOGGER.warning(f"Auto motion trigger: Failed to turn off {self._tv_name}: {err}")

        await self.coordinator.async_request_refresh()
