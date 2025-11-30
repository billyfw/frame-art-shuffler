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

import importlib
import importlib.util
import functools
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from homeassistant.helpers.dispatcher import async_dispatcher_send

_LOGGER = logging.getLogger(__name__)

HA_IMPORT_ERROR_MESSAGE = (
    "Home Assistant is required for the Frame Art Shuffler integration. "
    "Install the 'homeassistant' package to enable integration entry points."
)

_HA_AVAILABLE = False

HomeAssistant: Any = Any
ConfigEntry: Any = Any
ServiceCall: Any = Any
Platform: Any = Any
callback: Callable[..., Any] = lambda func, *args, **kwargs: func  # type: ignore[assignment]
dr = None

ha_spec = importlib.util.find_spec("homeassistant")
if ha_spec is not None:  # pragma: no cover - depends on optional dependency
    try:
        _config_entries = importlib.import_module("homeassistant.config_entries")
        _const = importlib.import_module("homeassistant.const")
        _core = importlib.import_module("homeassistant.core")
        _helpers_dr = importlib.import_module("homeassistant.helpers.device_registry")
        _helpers_er = importlib.import_module("homeassistant.helpers.entity_registry")
        _helpers_event = importlib.import_module("homeassistant.helpers.event")

        ConfigEntry = getattr(_config_entries, "ConfigEntry")
        Platform = getattr(_const, "Platform")
        HomeAssistant = getattr(_core, "HomeAssistant")
        callback = getattr(_core, "callback")
        ServiceCall = getattr(_core, "ServiceCall")
        dr = _helpers_dr
        er = _helpers_er
        async_track_time_interval = getattr(_helpers_event, "async_track_time_interval")
        _HA_AVAILABLE = True
    except ModuleNotFoundError:
        _HA_AVAILABLE = False

if _HA_AVAILABLE:
    from .const import (
        CONF_ENABLE_AUTO_SHUFFLE,
        CONF_METADATA_PATH,
        CONF_NEXT_SHUFFLE_TIME,
        CONF_SHUFFLE_FREQUENCY,
        CONF_TOKEN_DIR,
        DOMAIN,
        SIGNAL_AUTO_SHUFFLE_NEXT,
    )
    from .coordinator import FrameArtCoordinator
    from .config_entry import get_tv_config, list_tv_configs, remove_tv_config, update_tv_config
    from . import frame_tv
    from .frame_tv import TOKEN_DIR as DEFAULT_TOKEN_DIR, set_token_directory
    from .metadata import MetadataStore
    from .dashboard import async_generate_dashboard
    from .activity import log_activity
    from .shuffle import async_guarded_upload, async_shuffle_tv

    PLATFORMS = [Platform.TEXT, Platform.NUMBER, Platform.BUTTON, Platform.SENSOR, Platform.SWITCH, Platform.BINARY_SENSOR]
else:
    DEFAULT_TOKEN_DIR = Path(__file__).resolve().parent / "tokens"
    PLATFORMS: list[Any] = []


if _HA_AVAILABLE:

    async def async_setup(hass: Any, config: dict) -> bool:
        """Set up the Frame Art Shuffler integration."""
        hass.data.setdefault(DOMAIN, {})
        return True


    async def _async_setup_dashboard(hass: Any, entry: Any) -> None:
        """Generate the dashboard YAML file.
        
        Note: The dashboard must be manually registered in configuration.yaml.
        See README.md for setup instructions.
        """
        try:
            success = await async_generate_dashboard(hass, entry)
            if success:
                _LOGGER.info(
                    "Dashboard YAML generated at custom_components/frame_art_shuffler/dashboards/frame_tv_manager.yaml. "
                    "See README.md for manual registration instructions."
                )
            else:
                _LOGGER.debug("Dashboard generation skipped (no TVs configured)")
        except Exception as err:
            _LOGGER.warning(f"Failed to generate dashboard: {err}")


    def _get_structural_config(data: dict[str, Any]) -> dict[str, Any]:
        """Extract structural config data that requires a reload when changed.
        
        Structural changes include:
        - Adding/removing TVs
        - Changing IP/MAC addresses
        - Changing sensor entity IDs (requires re-attaching listeners)
        
        Runtime changes (skipped) include:
        - Toggling features (motion/brightness)
        - Changing thresholds/delays

        MAINTENANCE NOTE:
        If you add new configuration fields that require a component reload to take effect
        (e.g. new connection parameters, new entity IDs that need listeners), you MUST
        add them to the dictionary below. Otherwise, changing them will not trigger a reload.
        """
        tvs = data.get("tvs", {})
        structural = {}
        for tv_id, tv_data in tvs.items():
            structural[tv_id] = {
                "ip": tv_data.get("ip"),
                "mac": tv_data.get("mac"),
                "motion_sensor": tv_data.get("motion_sensor"),
                "light_sensor": tv_data.get("light_sensor"),
            }
        return structural


    async def async_setup_entry(hass: Any, entry: Any) -> bool:
        """Set up a config entry for Frame Art Shuffler."""

        metadata_path = Path(entry.data[CONF_METADATA_PATH])
        token_dir = Path(entry.data[CONF_TOKEN_DIR])

        token_dir.mkdir(parents=True, exist_ok=True)
        set_token_directory(token_dir)

        # Migrate TV data from metadata.json to config entry (one-time)
        if "tvs" not in entry.data or not entry.data["tvs"]:
            await _async_migrate_from_metadata(hass, entry, metadata_path)

        coordinator = FrameArtCoordinator(hass, entry, metadata_path)
        await coordinator.async_config_entry_first_refresh()

        hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
            "coordinator": coordinator,
            "metadata_path": metadata_path,
            "token_dir": token_dir,
            "config_snapshot": _get_structural_config(entry.data),
            # Initialize dicts that sensors need to read from
            # These will be populated by the timer code after platforms are set up
            "auto_brightness_next_times": {},
            "motion_off_times": {},
            "shuffle_cache": {},
            "upload_in_progress": set(),
            "auto_shuffle_next_times": {},
        }

        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        entry.async_on_unload(entry.add_update_listener(_async_reload_entry))

        # Register device removal handler
        entry.async_on_unload(
            _register_device_removal_listener(hass, entry, metadata_path)
        )

        async def async_handle_display_image(call: ServiceCall) -> None:
            """Handle the display_image service."""
            device_id = call.data.get("device_id")
            entity_id = call.data.get("entity_id")
            image_path = call.data.get("image_path")
            image_url = call.data.get("image_url")
            filename = call.data.get("filename")
            matte = call.data.get("matte")
            filter_id = call.data.get("filter")

            # Resolve entity_id to device_id if needed
            if entity_id and not device_id:
                ent_reg = er.async_get(hass)
                entity_entry = ent_reg.async_get(entity_id)
                if entity_entry:
                    device_id = entity_entry.device_id
            
            if not device_id:
                raise ValueError("Must provide device_id or entity_id")

            device_registry = dr.async_get(hass)
            device = device_registry.async_get(device_id)
            if not device:
                raise ValueError(f"Device {device_id} not found")

            # Find the config entry for this device
            target_entry: Any | None = None
            for eid in device.config_entries:
                config_entry = hass.config_entries.async_get_entry(eid)
                if config_entry and config_entry.domain == DOMAIN:
                    target_entry = config_entry
                    break
            
            if not target_entry:
                raise ValueError(
                    f"No config entry found for device {device_id} in domain {DOMAIN}"
                )

            # Get coordinator
            data = hass.data.get(DOMAIN, {}).get(target_entry.entry_id)
            if not data:
                raise ValueError(
                    f"Integration data not found for entry {target_entry.entry_id}"
                )

            coordinator = data["coordinator"]
            
            # Resolve image path
            final_path = None
            if image_path:
                final_path = image_path
            elif image_url:
                if image_url.startswith("/local/"):
                    final_path = hass.config.path("www", image_url[7:])
                else:
                    raise ValueError("image_url must start with /local/")
            elif filename:
                # Use metadata path to find library root
                metadata_path = data["metadata_path"]
                # metadata_path is like /config/www/frame_art/metadata.json
                # so library root is /config/www/frame_art/
                # Images are stored in the 'library' subdirectory
                final_path = str(metadata_path.parent / "library" / filename)
            
            if not final_path:
                raise ValueError("Must provide image_path, image_url, or filename")

            # Find TV IP
            tv_id = None
            for identifier in device.identifiers:
                if identifier[0] == DOMAIN:
                    tv_id = identifier[1]
                    break
            
            if not tv_id:
                raise ValueError(f"Could not determine TV ID from device {device_id}")

            # Look up TV in coordinator data
            tv_data = next((tv for tv in coordinator.data if tv["id"] == tv_id), None)
            if not tv_data:
                raise ValueError(f"TV {tv_id} not found in coordinator data")
            
            ip = tv_data["ip"]
            mac = tv_data.get("mac")

            tv_name = tv_data.get("name", tv_id)

            # Determine display filename for logging
            if filename:
                display_filename = filename
            elif final_path:
                display_filename = Path(final_path).name
            else:
                display_filename = "unknown"

            async def _perform_upload() -> bool:
                log_activity(
                    hass,
                    target_entry.entry_id,
                    tv_id,
                    "display_image",
                    f"Displaying custom image ({display_filename}) via service call",
                )

                await hass.async_add_executor_job(
                    functools.partial(
                        frame_tv.set_art_on_tv_deleteothers,
                        ip,
                        final_path,
                        mac_address=mac,
                        matte=matte,
                        photo_filter=filter_id,
                        delete_others=True,
                    )
                )

                # Set matching_image_count to 0 since this is not a shuffle
                shuffle_cache = data.setdefault("shuffle_cache", {}).setdefault(tv_id, {})
                shuffle_cache["matching_image_count"] = 0

                # Send signal to update sensors
                signal = f"{DOMAIN}_shuffle_{target_entry.entry_id}_{tv_id}"
                async_dispatcher_send(hass, signal)

                if filename:
                    await coordinator.async_set_active_image(
                        tv_id, filename, is_shuffle=False
                    )

                return True

            def _on_skip() -> None:
                _LOGGER.info(
                    "display_image skipped for %s (%s): upload already running",
                    tv_name,
                    tv_id,
                )

            await async_guarded_upload(
                hass,
                target_entry,
                tv_id,
                "display_image",
                _perform_upload,
                _on_skip,
            )

        hass.services.async_register(
            DOMAIN, "display_image", async_handle_display_image
        )

        # Per-TV auto brightness timer management
        auto_brightness_timers: dict[str, Callable[[], None]] = {}
        # Use the dict already initialized in hass.data so sensors can access it
        auto_brightness_next_times = hass.data[DOMAIN][entry.entry_id]["auto_brightness_next_times"]

        def cancel_tv_timer(tv_id: str) -> None:
            """Cancel the auto brightness timer for a specific TV."""
            if tv_id in auto_brightness_timers:
                auto_brightness_timers[tv_id]()
                del auto_brightness_timers[tv_id]
            if tv_id in auto_brightness_next_times:
                del auto_brightness_next_times[tv_id]

        def start_tv_timer(tv_id: str) -> None:
            """Start or restart the auto brightness timer for a specific TV."""
            # Cancel existing timer if any
            cancel_tv_timer(tv_id)

            async def async_tv_brightness_tick(_now: Any) -> None:
                """Timer callback for a single TV's auto brightness."""
                tv_configs = list_tv_configs(entry)
                tv_config = tv_configs.get(tv_id)
                
                # If TV no longer exists or auto brightness disabled, cancel timer
                if not tv_config or not tv_config.get("enable_dynamic_brightness", False):
                    cancel_tv_timer(tv_id)
                    return
                
                # Update next scheduled time before running
                auto_brightness_next_times[tv_id] = datetime.now(timezone.utc) + timedelta(minutes=10)
                
                await async_adjust_tv_brightness(tv_id)

            # Schedule timer for this TV
            unsubscribe = async_track_time_interval(
                hass,
                async_tv_brightness_tick,
                timedelta(minutes=10),
            )
            auto_brightness_timers[tv_id] = unsubscribe
            entry.async_on_unload(unsubscribe)

            # Store the next scheduled time so the sensor can show it accurately
            # async_track_time_interval fires 10 minutes from now
            next_time = datetime.now(timezone.utc) + timedelta(minutes=10)
            auto_brightness_next_times[tv_id] = next_time
            _LOGGER.debug(f"Auto brightness: Next adjust for {tv_id} scheduled at {next_time}")

            # Trigger immediate adjustment so we don't wait 10 minutes
            hass.async_create_task(async_adjust_tv_brightness(tv_id))

        # Auto brightness helper for a single TV
        async def async_adjust_tv_brightness(tv_id: str, restart_timer: bool = False) -> bool:
            """Adjust brightness for a single TV. Returns True on success."""
            tv_configs = list_tv_configs(entry)
            tv_config = tv_configs.get(tv_id)
            if not tv_config:
                _LOGGER.warning(f"Auto brightness: TV config not found for {tv_id}")
                return False

            lux_entity_id = tv_config.get("light_sensor")
            if not lux_entity_id:
                _LOGGER.debug(f"Auto brightness: No light sensor configured for {tv_id}")
                return False

            # Get current lux value from the sensor
            lux_state = hass.states.get(lux_entity_id)
            if not lux_state or lux_state.state in ("unavailable", "unknown"):
                _LOGGER.debug(f"Lux sensor {lux_entity_id} unavailable for {tv_id}")
                return False

            try:
                current_lux = float(lux_state.state)
            except (ValueError, TypeError):
                _LOGGER.warning(f"Invalid lux value from {lux_entity_id}: {lux_state.state}")
                return False

            # Get calibration values
            min_lux = tv_config.get("min_lux", 0)
            max_lux = tv_config.get("max_lux", 1000)
            min_brightness = tv_config.get("min_brightness", 1)
            max_brightness = tv_config.get("max_brightness", 10)

            # Avoid division by zero
            if max_lux <= min_lux:
                _LOGGER.warning(f"Invalid lux range for {tv_id}: max_lux must be > min_lux")
                return False

            # Calculate normalized value (0-1) with clamping
            normalized = (current_lux - min_lux) / (max_lux - min_lux)
            normalized = max(0.0, min(1.0, normalized))

            # Calculate target brightness
            target_brightness = int(round(
                min_brightness + normalized * (max_brightness - min_brightness)
            ))
            target_brightness = max(min_brightness, min(max_brightness, target_brightness))

            # Get TV data from coordinator
            data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
            if not data:
                return False

            coordinator = data["coordinator"]
            tv_data = next((tv for tv in coordinator.data if tv["id"] == tv_id), None)
            if not tv_data:
                return False

            ip = tv_data["ip"]
            tv_name = tv_config.get("name", tv_id)

            # Check if brightness already matches target - skip unnecessary command
            brightness_cache = data.get("brightness_cache", {})
            current_brightness = brightness_cache.get(tv_id)
            if current_brightness is None:
                current_brightness = tv_config.get("current_brightness")
            
            if current_brightness is not None and int(current_brightness) == target_brightness:
                _LOGGER.debug(
                    f"Auto brightness: {tv_name} already at brightness {target_brightness}, skipping"
                )
                # Log that we checked but didn't need to adjust
                # log_activity(
                #     hass, entry.entry_id, tv_id,
                #     "brightness_skipped",
                #     f"Already at brightness {target_brightness}",
                # )
                # Still restart timer if requested
                if restart_timer and tv_config.get("enable_dynamic_brightness", False):
                    start_tv_timer(tv_id)
                return True

            # Set brightness on TV
            try:
                _LOGGER.info(
                    f"Auto brightness: Attempting to set {tv_name} ({ip}) to brightness {target_brightness}"
                )
                await hass.async_add_executor_job(
                    functools.partial(
                        frame_tv.set_tv_brightness,
                        ip,
                        target_brightness,
                    )
                )
                # Store timestamp and brightness for successful adjustment (persisted for restart)
                from .config_entry import update_tv_config as update_config
                update_config(
                    hass,
                    entry,
                    tv_id,
                    {
                        "last_auto_brightness_timestamp": datetime.now(timezone.utc).isoformat(),
                        "current_brightness": target_brightness,
                    },
                )
                # Also store in hass.data for lightweight entity sync
                brightness_cache = hass.data[DOMAIN][entry.entry_id].setdefault("brightness_cache", {})
                brightness_cache[tv_id] = target_brightness
                
                # Send brightness signal so sensors update
                from homeassistant.helpers.dispatcher import async_dispatcher_send
                signal = f"{DOMAIN}_brightness_adjusted_{entry.entry_id}_{tv_id}"
                async_dispatcher_send(hass, signal)
                
                _LOGGER.info(
                    f"Auto brightness: {tv_name} successfully set to {target_brightness} "
                    f"(lux={current_lux}, normalized={normalized:.2f})"
                )
                
                # Log activity
                log_activity(
                    hass, entry.entry_id, tv_id,
                    "brightness_adjusted",
                    f"Brightness → {target_brightness} (auto, lux: {current_lux:.0f})",
                )
                
                # Restart timer if requested (e.g., from Trigger Now button)
                if restart_timer and tv_config.get("enable_dynamic_brightness", False):
                    start_tv_timer(tv_id)
                
                return True
            except Exception as err:
                _LOGGER.warning(f"Failed to set brightness for {tv_name}: {err}")
                return False

        # Store helper functions so buttons/switches can use them
        hass.data[DOMAIN][entry.entry_id]["async_adjust_tv_brightness"] = async_adjust_tv_brightness
        hass.data[DOMAIN][entry.entry_id]["start_tv_timer"] = start_tv_timer
        hass.data[DOMAIN][entry.entry_id]["cancel_tv_timer"] = cancel_tv_timer

        # Start timers for all TVs that have auto brightness enabled
        tv_configs = list_tv_configs(entry)
        for tv_id, tv_config in tv_configs.items():
            if tv_config.get("enable_dynamic_brightness", False):
                _LOGGER.info(f"Auto brightness: Starting timer for {tv_config.get('name', tv_id)}")
                start_tv_timer(tv_id)

        # Trigger a coordinator refresh so sensors pick up the new next_times
        await coordinator.async_request_refresh()

        # ===== AUTO SHUFFLE MANAGEMENT =====
        auto_shuffle_timers: dict[str, Callable[[], None]] = {}
        auto_shuffle_next_times = hass.data[DOMAIN][entry.entry_id]["auto_shuffle_next_times"]
        _drift_tolerance = timedelta(seconds=30)

        def _set_auto_shuffle_next_time(tv_id: str, next_time: datetime | None, persist: bool = True) -> None:
            if next_time is None:
                auto_shuffle_next_times.pop(tv_id, None)
                if persist:
                    update_tv_config(hass, entry, tv_id, {CONF_NEXT_SHUFFLE_TIME: None})
            else:
                auto_shuffle_next_times[tv_id] = next_time
                if persist:
                    update_tv_config(hass, entry, tv_id, {CONF_NEXT_SHUFFLE_TIME: next_time.isoformat()})
            signal = f"{SIGNAL_AUTO_SHUFFLE_NEXT}_{entry.entry_id}_{tv_id}"
            async_dispatcher_send(hass, signal)

        def cancel_auto_shuffle_timer(tv_id: str, *, persist: bool = True) -> None:
            """Cancel the auto shuffle timer for a specific TV."""
            if tv_id in auto_shuffle_timers:
                auto_shuffle_timers[tv_id]()
                del auto_shuffle_timers[tv_id]
            _set_auto_shuffle_next_time(tv_id, None, persist=persist)

        async def async_run_auto_shuffle(tv_id: str) -> None:
            """Execute an auto shuffle cycle for a TV."""
            tv_configs = list_tv_configs(entry)
            tv_config = tv_configs.get(tv_id)
            if not tv_config or not tv_config.get(CONF_ENABLE_AUTO_SHUFFLE, False):
                cancel_auto_shuffle_timer(tv_id)
                return

            tv_name = tv_config.get("name", tv_id)
            data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
            status_cache = data.get("tv_status_cache", {})
            screen_state = status_cache.get(tv_id, {}).get("screen_on")

            if screen_state is False:
                log_activity(
                    hass,
                    entry.entry_id,
                    tv_id,
                    "shuffle_skipped",
                    "Auto shuffle skipped: Screen off, waiting for art mode",
                )
                return

            if screen_state is None:
                log_activity(
                    hass,
                    entry.entry_id,
                    tv_id,
                    "shuffle_skipped",
                    "Auto shuffle skipped: Screen state unknown",
                )
                return

            await async_shuffle_tv(
                hass,
                entry,
                tv_id,
                reason="auto",
                skip_if_screen_off=True,
            )

        def start_auto_shuffle_timer(tv_id: str) -> None:
            """Start or restart the auto shuffle timer for a TV."""
            tv_configs = list_tv_configs(entry)
            tv_config = tv_configs.get(tv_id)
            if not tv_config or not tv_config.get(CONF_ENABLE_AUTO_SHUFFLE, False):
                cancel_auto_shuffle_timer(tv_id)
                return

            # Stop any existing timer but keep persisted next time for restoration
            cancel_auto_shuffle_timer(tv_id, persist=False)

            frequency_minutes = int(tv_config.get(CONF_SHUFFLE_FREQUENCY, 60) or 60)
            if frequency_minutes <= 0:
                frequency_minutes = 1
            interval = timedelta(minutes=frequency_minutes)
            tv_name = tv_config.get("name", tv_id)

            # Try to restore persisted next shuffle time
            now = datetime.now(timezone.utc)
            persisted_next_str = tv_config.get(CONF_NEXT_SHUFFLE_TIME)
            _LOGGER.debug(
                "Auto shuffle (%s): Checking persisted time, value='%s'",
                tv_name, persisted_next_str
            )
            if persisted_next_str:
                try:
                    persisted_next = datetime.fromisoformat(persisted_next_str)
                    if persisted_next > now:
                        # Future time - use it
                        next_time = persisted_next
                        _LOGGER.debug(
                            "Auto shuffle (%s): Restored next shuffle time %s",
                            tv_name, next_time.isoformat()
                        )
                    else:
                        # Past time - schedule fresh and log activity
                        next_time = now + interval
                        log_activity(
                            hass,
                            entry.entry_id,
                            tv_id,
                            "auto_shuffle_rescheduled",
                            f"Missed shuffle during restart; next in {frequency_minutes} min",
                        )
                        _LOGGER.info(
                            "Auto shuffle (%s): Persisted time was in past, rescheduling to %s",
                            tv_name, next_time.isoformat()
                        )
                except (ValueError, TypeError) as err:
                    _LOGGER.warning(
                        "Auto shuffle (%s): Failed to parse persisted time '%s': %s",
                        tv_name, persisted_next_str, err
                    )
                    next_time = now + interval
            else:
                next_time = now + interval

            _set_auto_shuffle_next_time(tv_id, next_time)

            async def async_auto_shuffle_tick(_now: Any) -> None:
                tv_configs_inner = list_tv_configs(entry)
                tv_config_inner = tv_configs_inner.get(tv_id)
                if not tv_config_inner or not tv_config_inner.get(CONF_ENABLE_AUTO_SHUFFLE, False):
                    cancel_auto_shuffle_timer(tv_id)
                    return

                now = datetime.now(timezone.utc)
                stored_next = auto_shuffle_next_times.get(tv_id)
                if stored_next and stored_next < now - _drift_tolerance:
                    drift_seconds = int((now - stored_next).total_seconds())
                    message = f"Schedule drift detected ({drift_seconds}s late); rescheduling"
                    _LOGGER.error("Auto shuffle (%s): %s", tv_config_inner.get("name", tv_id), message)
                    log_activity(
                        hass,
                        entry.entry_id,
                        tv_id,
                        "auto_shuffle_error",
                        message,
                    )

                _set_auto_shuffle_next_time(tv_id, now + interval)
                await async_run_auto_shuffle(tv_id)

            unsubscribe = async_track_time_interval(
                hass,
                async_auto_shuffle_tick,
                interval,
            )
            auto_shuffle_timers[tv_id] = unsubscribe
            entry.async_on_unload(unsubscribe)


        hass.data[DOMAIN][entry.entry_id]["start_auto_shuffle_timer"] = start_auto_shuffle_timer
        hass.data[DOMAIN][entry.entry_id]["cancel_auto_shuffle_timer"] = cancel_auto_shuffle_timer
        hass.data[DOMAIN][entry.entry_id]["async_run_auto_shuffle"] = async_run_auto_shuffle

        tv_configs = list_tv_configs(entry)
        for tv_id, tv_config in tv_configs.items():
            if tv_config.get(CONF_ENABLE_AUTO_SHUFFLE, False):
                _LOGGER.debug("Auto shuffle: Starting timer for %s", tv_config.get("name", tv_id))
                start_auto_shuffle_timer(tv_id)

        # ===== AUTO MOTION CONTROL =====
        # Per-TV motion listener and off-timer management
        motion_listeners: dict[str, Callable[[], None]] = {}
        motion_off_timers: dict[str, Callable[[], None]] = {}
        # Use the dict already initialized in hass.data so sensors can access it
        motion_off_times = hass.data[DOMAIN][entry.entry_id]["motion_off_times"]

        def cancel_motion_off_timer(tv_id: str) -> None:
            """Cancel the motion off timer for a specific TV."""
            _LOGGER.debug(f"Auto motion: Cancelling off timer for {tv_id}")
            if tv_id in motion_off_timers:
                motion_off_timers[tv_id]()
                del motion_off_timers[tv_id]
            if tv_id in motion_off_times:
                del motion_off_times[tv_id]
                # Signal sensors to update
                async_dispatcher_send(hass, f"{DOMAIN}_motion_off_time_updated_{entry.entry_id}_{tv_id}")

        def start_motion_off_timer(tv_id: str, check_staleness: bool = False) -> None:
            """Start or restart the motion off timer for a specific TV.
            
            Args:
                tv_id: The TV identifier
                check_staleness: If True, only start timer if last_motion_timestamp is recent.
                                 If False, start a fresh timer from now (for motion detection).
            """
            tv_configs = list_tv_configs(entry)
            tv_config = tv_configs.get(tv_id)
            if not tv_config:
                return

            off_delay_minutes = tv_config.get("motion_off_delay", 15)
            tv_name = tv_config.get("name", tv_id)
            
            # If checking staleness, verify last motion was recent enough
            if check_staleness:
                # Check runtime cache first, then fall back to config
                motion_cache = hass.data[DOMAIN][entry.entry_id].get("motion_cache", {})
                last_motion_str = motion_cache.get(tv_id) or tv_config.get("last_motion_timestamp")
                if last_motion_str:
                    try:
                        last_motion = datetime.fromisoformat(last_motion_str)
                        if last_motion.tzinfo is None:
                            last_motion = last_motion.replace(tzinfo=timezone.utc)
                        
                        elapsed = datetime.now(timezone.utc) - last_motion
                        elapsed_minutes = elapsed.total_seconds() / 60
                        
                        if elapsed_minutes >= off_delay_minutes:
                            _LOGGER.debug(
                                f"Auto motion: Skipping timer for {tv_name} - motion was {elapsed_minutes:.1f}m ago "
                                f"(> {off_delay_minutes}m delay)"
                            )
                            return
                        
                        # Motion was recent - calculate off time based on last motion
                        off_time = last_motion + timedelta(minutes=off_delay_minutes)
                        remaining_minutes = (off_time - datetime.now(timezone.utc)).total_seconds() / 60
                        _LOGGER.info(
                            f"Auto motion: Timer for {tv_name} - motion was {elapsed_minutes:.1f}m ago, "
                            f"off in {remaining_minutes:.1f}m"
                        )
                    except (ValueError, TypeError) as err:
                        _LOGGER.debug(f"Auto motion: Could not parse last_motion_timestamp: {err}")
                        return
                else:
                    _LOGGER.debug(f"Auto motion: Skipping timer for {tv_name} - no motion history")
                    return
            else:
                # Fresh timer from now
                off_time = datetime.now(timezone.utc) + timedelta(minutes=off_delay_minutes)
            
            cancel_motion_off_timer(tv_id)
            motion_off_times[tv_id] = off_time
            _LOGGER.debug(f"Auto motion: Off timer set for {tv_name} at {off_time} (tv_id={tv_id}, entry_id={entry.entry_id})")
            _LOGGER.debug(f"Auto motion: motion_off_times dict id={id(motion_off_times)}, contents={motion_off_times}")
            
            # Signal sensors to update
            signal = f"{DOMAIN}_motion_off_time_updated_{entry.entry_id}_{tv_id}"
            _LOGGER.debug(f"Auto motion: Sending dispatcher signal: {signal}")
            async_dispatcher_send(hass, signal)

            async def async_motion_off_callback(_now: Any) -> None:
                """Timer callback to turn off TV."""
                tv_configs = list_tv_configs(entry)
                tv_config = tv_configs.get(tv_id)
                if not tv_config or not tv_config.get("enable_motion_control", False):
                    cancel_motion_off_timer(tv_id)
                    return

                tv_name = tv_config.get("name", tv_id)
                ip = tv_config.get("ip")
                if not ip:
                    _LOGGER.warning(f"Auto motion: No IP for {tv_name}")
                    return

                try:
                    _LOGGER.info(f"Auto motion: Turning off {tv_name} ({ip}) due to no motion")
                    await hass.async_add_executor_job(frame_tv.tv_off, ip)
                    _LOGGER.info(f"Auto motion: {tv_name} turned off successfully")
                    log_activity(
                        hass, entry.entry_id, tv_id,
                        "motion_off",
                        "Turned off (no motion)",
                    )
                except Exception as err:
                    _LOGGER.warning(f"Auto motion: Failed to turn off {tv_name}: {err}")
                    log_activity(
                        hass, entry.entry_id, tv_id,
                        "error",
                        f"Turn off failed: {err}",
                    )
                finally:
                    # Clear timer state
                    if tv_id in motion_off_times:
                        del motion_off_times[tv_id]
                    # Signal sensors to update
                    async_dispatcher_send(hass, f"{DOMAIN}_motion_off_time_updated_{entry.entry_id}_{tv_id}")
                    # Refresh coordinator to update all entities
                    await coordinator.async_request_refresh()

            # Schedule one-shot timer using async_track_point_in_time
            from homeassistant.helpers.event import async_track_point_in_time
            unsubscribe = async_track_point_in_time(
                hass,
                async_motion_off_callback,
                off_time,
            )
            motion_off_timers[tv_id] = unsubscribe
            entry.async_on_unload(unsubscribe)
            _LOGGER.debug(f"Auto motion: Off timer set for {tv_name} at {off_time}")

        async def async_handle_motion(tv_id: str, tv_config: dict) -> None:
            """Handle motion detection for a TV."""
            tv_name = tv_config.get("name", tv_id)
            ip = tv_config.get("ip")
            mac = tv_config.get("mac")

            if not ip:
                _LOGGER.warning(f"Auto motion: No IP for {tv_name}")
                return

            # Update last motion timestamp in runtime cache (NOT entry.data to avoid reload)
            motion_cache = hass.data[DOMAIN][entry.entry_id].setdefault("motion_cache", {})
            motion_cache[tv_id] = datetime.now(timezone.utc).isoformat()

            # Signal sensors to update
            async_dispatcher_send(hass, f"{DOMAIN}_motion_detected_{entry.entry_id}_{tv_id}")

            # Check if screen is on - if so, just reset timer (no activity log - too noisy)
            try:
                screen_on = await hass.async_add_executor_job(frame_tv.is_screen_on, ip)
                if screen_on:
                    _LOGGER.debug(f"Auto motion: {tv_name} screen already on, resetting timer")
                    start_motion_off_timer(tv_id)
                    return
            except Exception as err:
                _LOGGER.debug(f"Auto motion: Could not check screen state for {tv_name}: {err}")
                # Continue to wake anyway - WOL is harmless if TV is already on

            power_on_in_progress = hass.data[DOMAIN][entry.entry_id].setdefault("power_on_in_progress", {})

            if power_on_in_progress.get(tv_id):
                _LOGGER.debug(f"Auto motion: {tv_name} power-on already in progress, skipping")
                return

            # Optimistically start the off timer so UI updates immediately
            # (The 15s wake sequence would otherwise leave the sensor 'unknown' for too long)
            start_motion_off_timer(tv_id)

            # Turn on TV via Wake-on-LAN
            if mac:
                try:
                    power_on_in_progress[tv_id] = True
                    _LOGGER.info(f"Auto motion: Waking {tv_name} ({ip}) via WOL")
                    await hass.async_add_executor_job(frame_tv.tv_on, ip, mac)
                    _LOGGER.info(f"Auto motion: {tv_name} wake sequence complete")
                    log_activity(
                        hass, entry.entry_id, tv_id,
                        "motion_wake",
                        "Woken by motion",
                    )
                except Exception as err:
                    _LOGGER.warning(f"Auto motion: Failed to wake {tv_name}: {err}")
                    log_activity(
                        hass, entry.entry_id, tv_id,
                        "error",
                        f"Wake failed: {err}",
                    )
                    # If wake failed, cancel the timer we just started
                    cancel_motion_off_timer(tv_id)
                finally:
                    power_on_in_progress.pop(tv_id, None)
            else:
                _LOGGER.warning(f"Auto motion: No MAC address for {tv_name}, cannot wake")
                cancel_motion_off_timer(tv_id)

        def stop_motion_listener(tv_id: str) -> None:
            """Stop listening for motion for a specific TV."""
            if tv_id in motion_listeners:
                motion_listeners[tv_id]()
                del motion_listeners[tv_id]
            cancel_motion_off_timer(tv_id)
            tv_configs = list_tv_configs(entry)
            tv_config = tv_configs.get(tv_id)
            tv_name = tv_config.get("name", tv_id) if tv_config else tv_id
            _LOGGER.info(f"Auto motion: Stopped listener for {tv_name}")

        async def async_start_motion_listener(tv_id: str) -> None:
            """Start listening for motion for a specific TV."""
            # Stop existing listener if any
            stop_motion_listener(tv_id)

            tv_configs = list_tv_configs(entry)
            tv_config = tv_configs.get(tv_id)
            if not tv_config:
                return

            motion_sensor = tv_config.get("motion_sensor")
            if not motion_sensor:
                _LOGGER.warning(f"Auto motion: No motion sensor configured for {tv_id}")
                return

            tv_name = tv_config.get("name", tv_id)
            ip = tv_config.get("ip")

            @callback
            def motion_state_changed(event: Any) -> None:
                """Handle motion sensor state change."""
                new_state = event.data.get("new_state")
                if not new_state:
                    return

                # Only trigger on motion detected (state = "on")
                if new_state.state == "on":
                    _LOGGER.debug(f"Auto motion: Motion detected for {tv_name}")
                    # Don't log here - async_handle_motion logs appropriately based on TV state
                    hass.async_create_task(async_handle_motion(tv_id, tv_config))

            # Subscribe to state changes
            from homeassistant.helpers.event import async_track_state_change_event
            unsubscribe = async_track_state_change_event(
                hass,
                [motion_sensor],
                motion_state_changed,
            )
            motion_listeners[tv_id] = unsubscribe
            entry.async_on_unload(unsubscribe)

            # Only start the off timer if the TV is currently on AND motion was recent
            # This handles HA restart - if motion is stale, don't set timer (TV was probably turned on manually)
            if ip:
                try:
                    screen_on = await hass.async_add_executor_job(frame_tv.is_screen_on, ip)
                    if screen_on:
                        _LOGGER.info(f"Auto motion: {tv_name} is on at startup, checking motion staleness")
                        start_motion_off_timer(tv_id, check_staleness=True)
                    else:
                        _LOGGER.info(f"Auto motion: {tv_name} is off, waiting for motion")
                except Exception as err:
                    _LOGGER.debug(f"Auto motion: Could not check {tv_name} screen state: {err}")
                    # If we can't check, don't start timer - wait for motion
            
            _LOGGER.info(f"Auto motion: Started listener for {tv_name} (sensor: {motion_sensor})")

        def start_motion_listener(tv_id: str) -> None:
            """Sync wrapper to start motion listener."""
            hass.async_create_task(async_start_motion_listener(tv_id))

        # Store helper functions for switches and other platforms
        hass.data[DOMAIN][entry.entry_id]["start_motion_listener"] = start_motion_listener
        hass.data[DOMAIN][entry.entry_id]["stop_motion_listener"] = stop_motion_listener
        hass.data[DOMAIN][entry.entry_id]["start_motion_off_timer"] = start_motion_off_timer
        hass.data[DOMAIN][entry.entry_id]["cancel_motion_off_timer"] = cancel_motion_off_timer

        # Start motion listeners for all TVs that have motion control enabled
        tv_configs = list_tv_configs(entry)
        for tv_id, tv_config in tv_configs.items():
            if tv_config.get("enable_motion_control", False):
                start_motion_listener(tv_id)

        # Generate and register the Lovelace dashboard
        await _async_setup_dashboard(hass, entry)

        return True


    async def async_unload_entry(hass: Any, entry: Any) -> bool:
        """Unload a Frame Art Shuffler config entry."""

        unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
        if not unload_ok:
            return False

        data = hass.data.get(DOMAIN)
        if data and entry.entry_id in data:
            data.pop(entry.entry_id)

        if not hass.config_entries.async_entries(DOMAIN):
            set_token_directory(DEFAULT_TOKEN_DIR)

        return True


    async def _async_reload_entry(hass: Any, entry: Any) -> None:
        """Reload config entry."""
        # Check if reload is necessary
        data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
        if data and "config_snapshot" in data:
            old_structural = data["config_snapshot"]
            new_structural = _get_structural_config(entry.data)
            
            if old_structural == new_structural:
                _LOGGER.debug("Skipping reload for runtime config change")
                # Update snapshot just in case (though it should be identical)
                data["config_snapshot"] = new_structural
                return

        _LOGGER.info("Reloading entry due to structural config change")
        await hass.config_entries.async_reload(entry.entry_id)


    async def _async_migrate_from_metadata(
        hass: Any,
        entry: Any,
        metadata_path: Path,
    ) -> None:
        """One-time migration: import TV data from metadata.json into config entry."""
        store = MetadataStore(metadata_path)

        try:
            metadata_tvs = await hass.async_add_executor_job(store.list_tvs)
        except Exception:
            # metadata.json might not exist yet or be empty
            return

        if not metadata_tvs:
            return

        tvs = {}
        for tv in metadata_tvs:
            tv_id = tv.get("id")
            if not tv_id:
                continue

            shuffle_data = tv.get("shuffle", {})
            tvs[tv_id] = {
                "id": tv_id,
                "name": tv.get("name"),
                "ip": tv.get("ip"),
                "mac": tv.get("mac"),
                "shuffle_frequency_minutes": shuffle_data.get("frequencyMinutes", 60) if isinstance(shuffle_data, dict) else 60,
                "tags": tv.get("tags", []),
                "exclude_tags": tv.get("notTags", []),
            }

        if tvs:
            data = {**entry.data, "tvs": tvs}
            hass.config_entries.async_update_entry(entry, data=data)


    @callback
    def _register_device_removal_listener(
        hass: Any,
        entry: Any,
        metadata_path: Path,
    ) -> Callable[[], None]:
        """Register a listener for device removal to clean up metadata."""

        @callback
        def device_removed(event):
            """Handle device removal."""
            device_id = event.data["device_id"]
            device_registry = dr.async_get(hass)
            device = device_registry.async_get(device_id)

            if not device:
                return

            # Check if this device belongs to our integration
            if not any(entry.entry_id in entry_id for entry_id in device.config_entries):
                return

            # Extract TV ID from device identifiers
            # Format is now just tv_id (no home prefix)
            tv_id = None
            for identifier in device.identifiers:
                if identifier[0] == DOMAIN:
                    tv_id = identifier[1]
                    break

            if not tv_id:
                return

            # Remove from metadata
            async def _remove_tv():
                store = MetadataStore(metadata_path)
                token_dir = hass.data.get(DOMAIN, {}).get(entry.entry_id, {}).get("token_dir")
                try:
                    # Get TV data before removing to find token file
                    tv_data = await hass.async_add_executor_job(store.get_tv, tv_id)
                    tv_ip = tv_data.get("ip") if tv_data else None

                    # Remove from config entry
                    remove_tv_config(hass, entry, tv_id)

                    # Delete token file if it exists
                    if token_dir and tv_ip:
                        from .flow_utils import safe_token_filename
                        token_path = Path(token_dir) / f"{safe_token_filename(tv_ip)}.token"
                        if token_path.exists():
                            await hass.async_add_executor_job(token_path.unlink)

                    # Refresh coordinator
                    data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
                    if data:
                        coordinator = data.get("coordinator")
                        if coordinator:
                            await coordinator.async_request_refresh()
                except Exception:
                    # TV might already be deleted, ignore
                    pass

            hass.async_create_task(_remove_tv())

        return hass.bus.async_listen("device_registry_updated", device_removed)

else:

    async def async_setup(*args: Any, **kwargs: Any) -> bool:  # pragma: no cover - fallback path
        raise ImportError(HA_IMPORT_ERROR_MESSAGE)


    async def async_setup_entry(*args: Any, **kwargs: Any) -> bool:  # pragma: no cover - fallback path
        raise ImportError(HA_IMPORT_ERROR_MESSAGE)


    async def async_unload_entry(*args: Any, **kwargs: Any) -> bool:  # pragma: no cover - fallback path
        raise ImportError(HA_IMPORT_ERROR_MESSAGE)


    async def _async_reload_entry(*args: Any, **kwargs: Any) -> None:  # pragma: no cover - fallback path
        raise ImportError(HA_IMPORT_ERROR_MESSAGE)


    async def _async_migrate_from_metadata(*args: Any, **kwargs: Any) -> None:  # pragma: no cover - fallback path
        raise ImportError(HA_IMPORT_ERROR_MESSAGE)


    def _register_device_removal_listener(*args: Any, **kwargs: Any) -> Callable[[], None]:  # pragma: no cover - fallback path
        raise ImportError(HA_IMPORT_ERROR_MESSAGE)
