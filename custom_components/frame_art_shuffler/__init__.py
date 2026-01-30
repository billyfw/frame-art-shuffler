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

import asyncio
import importlib
import importlib.util
import functools
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import voluptuous as vol

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
HomeAssistantView: Any = Any
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
        _exceptions = importlib.import_module("homeassistant.exceptions")
        _http = importlib.import_module("homeassistant.components.http")

        ConfigEntry = getattr(_config_entries, "ConfigEntry")
        Platform = getattr(_const, "Platform")
        HomeAssistant = getattr(_core, "HomeAssistant")
        callback = getattr(_core, "callback")
        ServiceCall = getattr(_core, "ServiceCall")
        ServiceValidationError = getattr(_exceptions, "ServiceValidationError")
        dr = _helpers_dr
        er = _helpers_er
        async_track_time_interval = getattr(_helpers_event, "async_track_time_interval")
        HomeAssistantView = getattr(_http, "HomeAssistantView")
        _HA_AVAILABLE = True
    except ModuleNotFoundError:
        _HA_AVAILABLE = False

if _HA_AVAILABLE:
    from .const import (
        CONF_ENABLE_AUTO_SHUFFLE,
        CONF_LOGGING_ENABLED,
        CONF_LOG_FLUSH_MINUTES,
        CONF_LOG_RETENTION_MONTHS,
        CONF_METADATA_PATH,
        CONF_OVERRIDE_EXPIRY_TIME,
        CONF_OVERRIDE_TAGSET,
        CONF_SELECTED_TAGSET,
        CONF_SHUFFLE_FREQUENCY,
        CONF_TAGSETS,
        CONF_TOKEN_DIR,
        DOMAIN,
        SIGNAL_AUTO_SHUFFLE_NEXT,
    )
    from .display_log import DisplayLogManager
    from .coordinator import FrameArtCoordinator
    from .config_entry import get_tv_config, get_global_tagsets, list_tv_configs, remove_tv_config, update_tv_config, update_global_tagsets, get_effective_tags
    from . import frame_tv
    from .frame_tv import TOKEN_DIR as DEFAULT_TOKEN_DIR, set_token_directory, tv_on, tv_off, set_art_mode, is_screen_on
    from .metadata import MetadataStore
    from .dashboard import async_generate_dashboard
    from .activity import log_activity
    from .shuffle import async_guarded_upload, async_shuffle_tv

    PLATFORMS = [Platform.NUMBER, Platform.BUTTON, Platform.SENSOR, Platform.SWITCH, Platform.BINARY_SENSOR]
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
                "name": tv_data.get("name"),
                "short_name": tv_data.get("short_name"),
                "motion_sensors": tv_data.get("motion_sensors", []),
                "light_sensor": tv_data.get("light_sensor"),
            }
        return structural


    def _calculate_pool_filenames(
        metadata_path: Path,
        include_tags: list[str],
        exclude_tags: list[str],
    ) -> set[str]:
        """Calculate the set of filenames in a TV's eligible pool based on tags.

        Args:
            metadata_path: Path to metadata.json
            include_tags: Tags that images must have at least one of
            exclude_tags: Tags that images must not have any of

        Returns:
            Set of eligible filenames
        """
        import json

        try:
            with open(metadata_path, "r", encoding="utf-8") as f:
                metadata = json.load(f)
        except (OSError, json.JSONDecodeError) as err:
            _LOGGER.warning(f"Failed to read metadata for pool calculation: {err}")
            return set()

        images = metadata.get("images", {})
        pool: set[str] = set()

        for filename, image_data in images.items():
            image_tags = set(image_data.get("tags", []))

            # Must have at least one include tag (if include_tags is specified)
            if include_tags and not any(tag in image_tags for tag in include_tags):
                continue

            # Must not have any exclude tag
            if exclude_tags and any(tag in image_tags for tag in exclude_tags):
                continue

            pool.add(filename)

        return pool


    # Default recency window settings (in hours)
    DEFAULT_SAME_TV_HOURS = 120
    DEFAULT_CROSS_TV_HOURS = 72
    MIN_RECENCY_HOURS = 6
    MAX_RECENCY_HOURS = 168  # 1 week

    def get_recency_windows(entry: Any) -> tuple[int, int]:
        """Get recency window settings from config entry options.

        Returns:
            Tuple of (same_tv_hours, cross_tv_hours)
        """
        same_tv = entry.options.get("same_tv_hours", DEFAULT_SAME_TV_HOURS)
        cross_tv = entry.options.get("cross_tv_hours", DEFAULT_CROSS_TV_HOURS)
        # Clamp to valid range
        same_tv = max(MIN_RECENCY_HOURS, min(MAX_RECENCY_HOURS, int(same_tv)))
        cross_tv = max(MIN_RECENCY_HOURS, min(MAX_RECENCY_HOURS, int(cross_tv)))
        return same_tv, cross_tv


    class PoolHealthView(HomeAssistantView):
        """API endpoint to get pool health data for all TVs."""

        url = "/api/frame_art_shuffler/pool_health"
        name = "api:frame_art_shuffler:pool_health"
        requires_auth = True

        def __init__(self, hass: Any, entry: Any) -> None:
            """Initialize the view."""
            self._hass = hass
            self._entry = entry

        async def get(self, request: Any) -> Any:
            """Handle GET request for pool health data.

            Optional query params for preview:
                same_tv_hours: Override same-TV window (6-168)
                cross_tv_hours: Override cross-TV window (6-168)
            """
            from aiohttp import web

            data = self._hass.data.get(DOMAIN, {}).get(self._entry.entry_id)
            if not data:
                return web.json_response(
                    {"error": "Integration data not available"},
                    status=500,
                )

            display_log = data.get("display_log")
            metadata_path = data.get("metadata_path")

            if not display_log or not metadata_path:
                return web.json_response(
                    {"error": "Display log or metadata not available"},
                    status=500,
                )

            # Get configured windows (from config entry options)
            configured_same_tv, configured_cross_tv = get_recency_windows(self._entry)

            # Allow query param overrides for preview (clamped to valid range)
            try:
                same_tv_hours = int(request.query.get("same_tv_hours", configured_same_tv))
                same_tv_hours = max(MIN_RECENCY_HOURS, min(MAX_RECENCY_HOURS, same_tv_hours))
            except (ValueError, TypeError):
                same_tv_hours = configured_same_tv

            try:
                cross_tv_hours = int(request.query.get("cross_tv_hours", configured_cross_tv))
                cross_tv_hours = max(MIN_RECENCY_HOURS, min(MAX_RECENCY_HOURS, cross_tv_hours))
            except (ValueError, TypeError):
                cross_tv_hours = configured_cross_tv

            tv_configs = list_tv_configs(self._entry)
            result: dict[str, Any] = {
                "tvs": {},
                "windows": {
                    "same_tv_hours": same_tv_hours,
                    "cross_tv_hours": cross_tv_hours,
                    "configured_same_tv_hours": configured_same_tv,
                    "configured_cross_tv_hours": configured_cross_tv,
                },
            }

            for tv_id, tv_config in tv_configs.items():
                tv_name = tv_config.get("name", tv_id)

                # Get shuffle frequency for this TV (default 60 minutes)
                shuffle_frequency = int(tv_config.get(CONF_SHUFFLE_FREQUENCY, 60) or 60)

                # Get effective tags for this TV (resolves tagset)
                include_tags, exclude_tags = get_effective_tags(self._entry, tv_id)

                # Calculate pool filenames
                pool_filenames = await self._hass.async_add_executor_job(
                    _calculate_pool_filenames,
                    metadata_path,
                    include_tags,
                    exclude_tags,
                )

                # Get pool health from display log
                health = display_log.get_pool_health(
                    tv_id=tv_id,
                    pool_filenames=pool_filenames,
                    same_tv_hours=same_tv_hours,
                    cross_tv_hours=cross_tv_hours,
                )

                # Get historical pool health for sparkline (last 7 days)
                history = display_log.get_pool_health_history(
                    tv_id=tv_id,
                    hours=168,
                )

                result["tvs"][tv_id] = {
                    "name": tv_name,
                    "shuffle_frequency_minutes": shuffle_frequency,
                    "history": history,
                    **health,
                }

            return web.json_response(result)


    async def async_setup_entry(hass: Any, entry: Any) -> bool:
        """Set up a config entry for Frame Art Shuffler."""

        metadata_path = Path(entry.data[CONF_METADATA_PATH])
        token_dir = Path(entry.data[CONF_TOKEN_DIR])

        token_dir.mkdir(parents=True, exist_ok=True)
        set_token_directory(token_dir)

        # Migrate TV data from metadata.json to config entry (one-time)
        if "tvs" not in entry.data or not entry.data["tvs"]:
            await _async_migrate_from_metadata(hass, entry, metadata_path)

        # Migrate motion_sensor (singular) to motion_sensors (list) - v1.1.0
        await _async_migrate_motion_sensors(hass, entry)

        # Migrate per-TV tagsets to global tagsets - v1.2.0
        await _async_migrate_tagsets_to_global(hass, entry)

        # Initialize global tagsets if not present (empty dict)
        if "tagsets" not in entry.data:
            data = {**entry.data, "tagsets": {}}
            hass.config_entries.async_update_entry(entry, data=data)

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

        display_log = DisplayLogManager(hass, entry)
        await display_log.async_setup()
        hass.data[DOMAIN][entry.entry_id]["display_log"] = display_log

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
                from datetime import datetime, timezone as dt_timezone

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

                # Update shuffle_cache with all current state (like shuffle does)
                # This ensures the dashboard sensors show the correct image/matte/filter
                shuffle_cache = data.setdefault("shuffle_cache", {}).setdefault(tv_id, {})
                shuffle_cache["current_image"] = display_filename
                shuffle_cache["current_matte"] = matte
                shuffle_cache["current_filter"] = filter_id
                shuffle_cache["matching_image_count"] = 0  # Not a shuffle

                # Send signal to update sensors
                signal = f"{DOMAIN}_shuffle_{target_entry.entry_id}_{tv_id}"
                async_dispatcher_send(hass, signal)

                if filename:
                    await coordinator.async_set_active_image(
                        tv_id, filename, is_shuffle=False
                    )

                # Update display log so this manual display is tracked
                display_log = data.get("display_log")
                if display_log and filename:
                    # Try to get image tags from metadata store
                    image_tags: list[str] = []
                    try:
                        from .metadata import MetadataStore
                        metadata_path = data.get("metadata_path")
                        if metadata_path:
                            store = MetadataStore(metadata_path)
                            image_meta = store.get_image(filename)
                            if image_meta:
                                image_tags = list(image_meta.get("tags", []))
                    except Exception:
                        pass  # If we can't get tags, just log without them

                    display_log.note_display_start(
                        tv_id=tv_id,
                        tv_name=tv_name,
                        filename=filename,
                        tags=image_tags,
                        source="manual",
                        shuffle_mode=None,
                        started_at=datetime.now(dt_timezone.utc),
                        matte=matte,
                    )
                    # Flush immediately to persist - don't wait for periodic flush
                    await display_log.async_flush(force=True)

                return True

            def _on_skip() -> None:
                _LOGGER.info(
                    "display_image skipped for %s (%s): upload already running",
                    tv_name,
                    tv_id,
                )
                raise ServiceValidationError(
                    f"Upload skipped for {tv_name}: another upload is already in progress. Please wait a moment and try again."
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

        log_options_schema = vol.Schema(
            {
                vol.Optional(CONF_LOGGING_ENABLED): bool,
                vol.Optional(CONF_LOG_RETENTION_MONTHS): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=12)
                ),
                vol.Optional(CONF_LOG_FLUSH_MINUTES): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=60)
                ),
            }
        )

        async def async_handle_set_log_options(call: ServiceCall) -> None:
            """Update logging runtime settings without requiring a reload."""

            data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
            if not data:
                raise ValueError("Integration data not available for logging update")

            updated_options = dict(entry.options or {})
            changed = False

            if CONF_LOGGING_ENABLED in call.data:
                value = bool(call.data[CONF_LOGGING_ENABLED])
                if updated_options.get(CONF_LOGGING_ENABLED, DEFAULT_LOGGING_ENABLED) != value:
                    updated_options[CONF_LOGGING_ENABLED] = value
                    changed = True

            if CONF_LOG_RETENTION_MONTHS in call.data:
                value = int(call.data[CONF_LOG_RETENTION_MONTHS])
                if updated_options.get(
                    CONF_LOG_RETENTION_MONTHS,
                    DEFAULT_LOG_RETENTION_MONTHS,
                ) != value:
                    updated_options[CONF_LOG_RETENTION_MONTHS] = value
                    changed = True

            if CONF_LOG_FLUSH_MINUTES in call.data:
                value = int(call.data[CONF_LOG_FLUSH_MINUTES])
                if updated_options.get(
                    CONF_LOG_FLUSH_MINUTES,
                    DEFAULT_LOG_FLUSH_MINUTES,
                ) != value:
                    updated_options[CONF_LOG_FLUSH_MINUTES] = value
                    changed = True

            if not changed:
                return

            hass.config_entries.async_update_entry(
                entry,
                options=updated_options,
            )

        hass.services.async_register(
            DOMAIN,
            "set_log_options",
            async_handle_set_log_options,
            schema=log_options_schema,
        )

        async def async_handle_flush_display_log(call: ServiceCall) -> None:
            """Manually flush pending display log sessions to disk."""
            data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
            if not data:
                _LOGGER.warning("Integration data not available for flush")
                return

            display_log = data.get("display_log")
            if not display_log:
                _LOGGER.warning("Display log manager not initialized")
                return

            await display_log.async_flush(force=True)
            _LOGGER.info("Display log flushed successfully")

        hass.services.async_register(
            DOMAIN,
            "flush_display_log",
            async_handle_flush_display_log,
        )

        async def async_handle_clear_display_log(call: ServiceCall) -> None:
            """Clear all display log data."""
            data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
            if not data:
                _LOGGER.warning("Integration data not available for clear")
                return

            display_log = data.get("display_log")
            if not display_log:
                _LOGGER.warning("Display log manager not initialized")
                return

            await display_log.async_clear_logs()
            _LOGGER.info("Display logs cleared successfully")

        hass.services.async_register(
            DOMAIN,
            "clear_display_log",
            async_handle_clear_display_log,
        )

        # --- TV Power Control Services ---
        async def _resolve_tv_from_call(call: ServiceCall) -> tuple[Any, str, dict[str, Any]]:
            """Resolve device_id/entity_id to config entry, tv_id, and tv_data."""
            device_id = call.data.get("device_id")
            entity_id = call.data.get("entity_id")

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

            target_entry: Any | None = None
            for eid in device.config_entries:
                config_entry = hass.config_entries.async_get_entry(eid)
                if config_entry and config_entry.domain == DOMAIN:
                    target_entry = config_entry
                    break

            if not target_entry:
                raise ValueError(f"No config entry found for device {device_id}")

            data = hass.data.get(DOMAIN, {}).get(target_entry.entry_id)
            if not data:
                raise ValueError(f"Integration data not found for entry {target_entry.entry_id}")

            tv_id = None
            for identifier in device.identifiers:
                if identifier[0] == DOMAIN:
                    tv_id = identifier[1]
                    break

            if not tv_id:
                raise ValueError(f"Could not determine TV ID from device {device_id}")

            coordinator = data["coordinator"]
            tv_data = next((tv for tv in coordinator.data if tv["id"] == tv_id), None)
            if not tv_data:
                raise ValueError(f"TV {tv_id} not found in coordinator data")

            return target_entry, tv_id, tv_data

        async def async_handle_turn_on_tv(call: ServiceCall) -> None:
            """Handle the turn_on_tv service."""
            target_entry, tv_id, tv_data = await _resolve_tv_from_call(call)
            reason = call.data.get("reason")

            ip = tv_data["ip"]
            mac = tv_data.get("mac")
            tv_name = tv_data.get("name", tv_id)

            if not mac:
                raise ValueError(f"Cannot turn on {tv_name}: missing MAC address")

            try:
                await hass.async_add_executor_job(tv_on, ip, mac)
                _LOGGER.info(f"Sent Wake-on-LAN to {tv_name}")

                await hass.async_add_executor_job(set_art_mode, ip)
                _LOGGER.info(f"Switched {tv_name} to art mode")

                # Update status cache
                data = hass.data.get(DOMAIN, {}).get(target_entry.entry_id, {})
                status_cache = data.get("tv_status_cache", {})
                if tv_id in status_cache:
                    status_cache[tv_id]["screen_on"] = True

                # Log activity with optional reason
                if reason:
                    message = f"Screen turned on ({reason})"
                else:
                    message = "Screen turned on (turn_on_tv service)"
                log_activity(hass, target_entry.entry_id, tv_id, "screen_on", message)

                # Start display log session for the current image
                display_log = data.get("display_log")
                if display_log:
                    # Get current image from shuffle_cache or config
                    shuffle_cache = data.get("shuffle_cache", {}).get(tv_id, {})
                    current_image = shuffle_cache.get("current_image")
                    if not current_image:
                        current_image = tv_config.get("current_image") if tv_config else None
                    
                    if current_image:
                        # Try to get image tags from metadata
                        metadata_path = data.get("metadata_path")
                        image_tags: list[str] = []
                        if metadata_path:
                            try:
                                from .metadata import MetadataStore
                                store = MetadataStore(metadata_path)
                                image_meta = store.get_image(current_image)
                                if image_meta:
                                    image_tags = list(image_meta.get("tags", []))
                            except Exception:
                                pass
                        
                        # Get TV's configured tags for matched_tags computation
                        tv_tags = tv_config.get("include_tags") if tv_config else None
                        
                        display_log.note_screen_on(
                            tv_id=tv_id,
                            tv_name=tv_name,
                            filename=current_image,
                            tags=image_tags,
                            tv_tags=tv_tags,
                        )

                # Start motion off timer if enabled
                tv_config = get_tv_config(target_entry, tv_id)
                if tv_config and tv_config.get("enable_motion_control", False):
                    start_motion_off_timer = data.get("start_motion_off_timer")
                    if start_motion_off_timer:
                        start_motion_off_timer(tv_id)

            except Exception as err:
                _LOGGER.error(f"Failed to turn on {tv_name}: {err}")
                raise

        async def async_handle_turn_off_tv(call: ServiceCall) -> None:
            """Handle the turn_off_tv service."""
            target_entry, tv_id, tv_data = await _resolve_tv_from_call(call)
            reason = call.data.get("reason")

            ip = tv_data["ip"]
            tv_name = tv_data.get("name", tv_id)

            try:
                await hass.async_add_executor_job(tv_off, ip)
                _LOGGER.info(f"Turned off {tv_name} screen")

                # Update status cache
                data = hass.data.get(DOMAIN, {}).get(target_entry.entry_id, {})
                status_cache = data.get("tv_status_cache", {})
                if tv_id in status_cache:
                    status_cache[tv_id]["screen_on"] = False

                # Log activity with optional reason
                if reason:
                    message = f"Screen turned off ({reason})"
                else:
                    message = "Screen turned off (turn_off_tv service)"
                log_activity(hass, target_entry.entry_id, tv_id, "screen_off", message)

                # Close display log session since screen is turning off
                display_log = data.get("display_log")
                if display_log:
                    display_log.note_screen_off(tv_id=tv_id, tv_name=tv_name)

                # Cancel motion off timer if enabled
                tv_config = get_tv_config(target_entry, tv_id)
                if tv_config and tv_config.get("enable_motion_control", False):
                    cancel_motion_off_timer = data.get("cancel_motion_off_timer")
                    if cancel_motion_off_timer:
                        cancel_motion_off_timer(tv_id)

            except Exception as err:
                _LOGGER.error(f"Failed to turn off {tv_name}: {err}")
                raise

        hass.services.async_register(
            DOMAIN,
            "turn_on_tv",
            async_handle_turn_on_tv,
        )

        hass.services.async_register(
            DOMAIN,
            "turn_off_tv",
            async_handle_turn_off_tv,
        )

        # ===== TAGSET SERVICES =====
        # Timer management for tagset override expiry
        tagset_override_timers: dict[str, Callable[[], None]] = {}

        def cancel_tagset_override_timer(tv_id: str) -> None:
            """Cancel the tagset override expiry timer for a TV."""
            if tv_id in tagset_override_timers:
                tagset_override_timers[tv_id]()
                del tagset_override_timers[tv_id]

        def start_tagset_override_timer(tv_id: str, expiry_time: datetime) -> None:
            """Start the tagset override expiry timer for a TV."""
            from homeassistant.helpers.event import async_track_point_in_time
            
            cancel_tagset_override_timer(tv_id)

            async def async_override_expiry_callback(_now: Any) -> None:
                """Timer callback to clear tagset override."""
                tv_config = get_tv_config(entry, tv_id)
                if not tv_config:
                    return

                tv_name = tv_config.get("name", tv_id)
                override_name = tv_config.get(CONF_OVERRIDE_TAGSET)
                
                # Clear the override
                update_tv_config(hass, entry, tv_id, {
                    CONF_OVERRIDE_TAGSET: None,
                    CONF_OVERRIDE_EXPIRY_TIME: None,
                })
                
                _LOGGER.info(f"Tagset override '{override_name}' expired for {tv_name}")
                log_activity(
                    hass, entry.entry_id, tv_id,
                    "tagset_override_expired",
                    f"Override '{override_name}' expired, reverted to selected tagset",
                )
                
                # Signal sensors to update
                async_dispatcher_send(hass, f"{DOMAIN}_tagset_updated_{entry.entry_id}_{tv_id}")
                
                # Clean up timer reference
                if tv_id in tagset_override_timers:
                    del tagset_override_timers[tv_id]

            unsubscribe = async_track_point_in_time(
                hass,
                async_override_expiry_callback,
                expiry_time,
            )
            tagset_override_timers[tv_id] = unsubscribe
            _LOGGER.debug(f"Tagset override timer set for {tv_id} at {expiry_time}")

        # Store timer functions for access elsewhere
        hass.data[DOMAIN][entry.entry_id]["cancel_tagset_override_timer"] = cancel_tagset_override_timer
        hass.data[DOMAIN][entry.entry_id]["start_tagset_override_timer"] = start_tagset_override_timer

        # Restore any pending override timers on startup
        for tv_id, tv_config in list_tv_configs(entry).items():
            expiry_str = tv_config.get(CONF_OVERRIDE_EXPIRY_TIME)
            if expiry_str:
                try:
                    expiry_time = datetime.fromisoformat(expiry_str)
                    if expiry_time > datetime.now(timezone.utc):
                        start_tagset_override_timer(tv_id, expiry_time)
                        _LOGGER.info(f"Restored tagset override timer for {tv_config.get('name', tv_id)}")
                    else:
                        # Expired while HA was down - clear it
                        update_tv_config(hass, entry, tv_id, {
                            CONF_OVERRIDE_TAGSET: None,
                            CONF_OVERRIDE_EXPIRY_TIME: None,
                        })
                        _LOGGER.info(f"Cleared expired tagset override for {tv_config.get('name', tv_id)}")
                except (ValueError, TypeError) as e:
                    _LOGGER.warning(f"Invalid override expiry time for {tv_id}: {e}")

        async def async_handle_upsert_tagset(call: ServiceCall) -> None:
            """Create or update a global tagset definition.
            
            Tagsets are global (not per-TV). Any TV can be assigned to use any tagset.
            No device_id is required for this service.
            
            If original_name is provided and differs from name, the tagset is renamed.
            Any TVs referencing the old name will be updated to the new name.
            """
            name = call.data.get("name", "").strip()
            original_name = call.data.get("original_name", "").strip()
            tags = call.data.get("tags", [])
            exclude_tags = call.data.get("exclude_tags", [])
            tag_weights = call.data.get("tag_weights", {})
            weighting_type = call.data.get("weighting_type", "image")
            
            if not name:
                raise ServiceValidationError("Tagset name is required")
            if not tags:
                raise ServiceValidationError("Tagset must have at least one tag")
            if weighting_type not in ("image", "tag"):
                raise ServiceValidationError("weighting_type must be 'image' or 'tag'")
            
            # Validate and clamp weights (only relevant if weighting_type is "tag")
            validated_weights = {}
            for tag, weight in tag_weights.items():
                try:
                    w = float(weight)
                    if w < 0.1 or w > 10:
                        _LOGGER.warning(
                            "Weight %.2f for tag '%s' out of range, clamping to 0.1-10",
                            w, tag
                        )
                        w = max(0.1, min(10.0, w))
                    validated_weights[tag] = w
                except (ValueError, TypeError):
                    _LOGGER.warning(
                        "Invalid weight '%s' for tag '%s', ignoring",
                        weight, tag
                    )
            
            # Warn about weights for tags not in the include list
            for tag in validated_weights:
                if tag not in tags:
                    _LOGGER.warning(
                        "Weight specified for tag '%s' which is not in include tags, ignoring",
                        tag
                    )
            
            # Only keep weights for tags that are in the include list
            validated_weights = {t: w for t, w in validated_weights.items() if t in tags}
            
            # Get global tagsets from config entry root
            tagsets = get_global_tagsets(entry).copy()
            
            # Handle rename case
            is_rename = original_name and original_name != name and original_name in tagsets
            if is_rename:
                # Check if new name already exists
                if name in tagsets:
                    raise ServiceValidationError(f"Cannot rename: tagset '{name}' already exists")
                
                # Remove old tagset
                del tagsets[original_name]
                
                # Update any TVs that reference the old name
                tvs = list_tv_configs(entry)
                for tv_id, tv_config in tvs.items():
                    updates = {}
                    if tv_config.get(CONF_SELECTED_TAGSET) == original_name:
                        updates[CONF_SELECTED_TAGSET] = name
                    if tv_config.get(CONF_OVERRIDE_TAGSET) == original_name:
                        updates[CONF_OVERRIDE_TAGSET] = name
                    if updates:
                        update_tv_config(hass, entry, tv_id, updates)
                
                _LOGGER.info(f"Renamed tagset '{original_name}' to '{name}'")
            
            is_new = name not in tagsets and not is_rename
            tagset_data = {
                "tags": tags,
                "exclude_tags": exclude_tags,
                "weighting_type": weighting_type,
            }
            # Only store tag_weights if there are any non-default weights
            # (tag_weights are only used when weighting_type is "tag")
            if validated_weights:
                tagset_data["tag_weights"] = validated_weights
            
            tagsets[name] = tagset_data
            
            update_global_tagsets(hass, entry, tagsets)
            
            if is_rename:
                action = "renamed"
                msg = f"Global tagset '{original_name}' renamed to '{name}'"
            elif is_new:
                action = "created"
                msg = f"Global tagset '{name}' created"
            else:
                action = "updated"
                msg = f"Global tagset '{name}' updated"
            
            _LOGGER.info(msg)
            log_activity(
                hass, entry.entry_id, None,
                f"tagset_{action}",
                msg,
            )
            # Signal all TVs to refresh since tagset content may have changed
            async_dispatcher_send(hass, f"{DOMAIN}_tagset_updated_{entry.entry_id}")

        async def async_handle_delete_tagset(call: ServiceCall) -> None:
            """Delete a global tagset definition.
            
            Cannot delete a tagset that is currently selected or overridden by any TV.
            """
            name = call.data.get("name", "").strip()
            if not name:
                raise ServiceValidationError("Tagset name is required")
            
            tagsets = get_global_tagsets(entry).copy()
            
            if name not in tagsets:
                raise ServiceValidationError(f"Tagset '{name}' not found")
            
            if len(tagsets) <= 1:
                raise ServiceValidationError("Cannot delete the only tagset")
            
            # Check if any TV is using this tagset
            for tv_id, tv_config in list_tv_configs(entry).items():
                tv_name = tv_config.get("name", tv_id)
                selected = tv_config.get(CONF_SELECTED_TAGSET)
                if name == selected:
                    raise ServiceValidationError(
                        f"Cannot delete tagset '{name}': selected by {tv_name}. "
                        "Select a different tagset for that TV first."
                    )
                
                override = tv_config.get(CONF_OVERRIDE_TAGSET)
                if name == override:
                    raise ServiceValidationError(
                        f"Cannot delete tagset '{name}': active override on {tv_name}. "
                        "Clear the override first."
                    )
            
            del tagsets[name]
            update_global_tagsets(hass, entry, tagsets)
            
            _LOGGER.info(f"Global tagset '{name}' deleted")
            log_activity(
                hass, entry.entry_id, None,
                "tagset_deleted",
                f"Global tagset '{name}' deleted",
            )
            async_dispatcher_send(hass, f"{DOMAIN}_tagset_updated_{entry.entry_id}")

        async def async_handle_select_tagset(call: ServiceCall) -> None:
            """Permanently switch which tagset a TV uses.
            
            Requires device_id - this is a per-TV assignment.
            """
            target_entry, tv_id, tv_data = await _resolve_tv_from_call(call)
            
            name = call.data.get("name", "").strip()
            if not name:
                raise ServiceValidationError("Tagset name is required")
            
            tv_name = tv_data.get("name", tv_id)
            
            # Check global tagsets
            tagsets = get_global_tagsets(target_entry)
            if name not in tagsets:
                raise ServiceValidationError(f"Tagset '{name}' not found")
            
            update_tv_config(hass, target_entry, tv_id, {CONF_SELECTED_TAGSET: name})
            
            _LOGGER.info(f"Selected tagset '{name}' for {tv_name}")
            log_activity(
                hass, target_entry.entry_id, tv_id,
                "tagset_selected",
                f"Selected tagset '{name}'",
            )
            async_dispatcher_send(hass, f"{DOMAIN}_tagset_updated_{target_entry.entry_id}_{tv_id}")

        async def async_handle_override_tagset(call: ServiceCall) -> None:
            """Apply a temporary tagset override with required expiry.
            
            Requires device_id - this is a per-TV operation.
            """
            target_entry, tv_id, tv_data = await _resolve_tv_from_call(call)
            
            name = call.data.get("name", "").strip()
            duration_minutes = call.data.get("duration_minutes")
            
            if not name:
                raise ServiceValidationError("Tagset name is required")
            if not duration_minutes or duration_minutes <= 0:
                raise ServiceValidationError("duration_minutes is required and must be > 0")
            
            tv_name = tv_data.get("name", tv_id)
            
            # Check global tagsets
            tagsets = get_global_tagsets(target_entry)
            if name not in tagsets:
                raise ServiceValidationError(f"Tagset '{name}' not found")
            
            expiry_time = datetime.now(timezone.utc) + timedelta(minutes=duration_minutes)
            
            update_tv_config(hass, target_entry, tv_id, {
                CONF_OVERRIDE_TAGSET: name,
                CONF_OVERRIDE_EXPIRY_TIME: expiry_time.isoformat(),
            })
            
            start_tagset_override_timer(tv_id, expiry_time)
            
            _LOGGER.info(f"Tagset override '{name}' applied for {tv_name} ({duration_minutes}m)")
            log_activity(
                hass, target_entry.entry_id, tv_id,
                "tagset_override_applied",
                f"Override '{name}' applied for {duration_minutes}m",
            )
            async_dispatcher_send(hass, f"{DOMAIN}_tagset_updated_{target_entry.entry_id}_{tv_id}")
            
            # Trigger immediate shuffle to apply the override tagset
            await async_shuffle_tv(hass, target_entry, tv_id, reason="override")

        async def async_handle_clear_tagset_override(call: ServiceCall) -> None:
            """Clear an active tagset override early."""
            target_entry, tv_id, tv_data = await _resolve_tv_from_call(call)
            
            tv_config = get_tv_config(target_entry, tv_id)
            tv_name = tv_data.get("name", tv_id)
            override_name = tv_config.get(CONF_OVERRIDE_TAGSET) if tv_config else None
            
            cancel_tagset_override_timer(tv_id)
            
            update_tv_config(hass, target_entry, tv_id, {
                CONF_OVERRIDE_TAGSET: None,
                CONF_OVERRIDE_EXPIRY_TIME: None,
            })
            
            if override_name:
                _LOGGER.info(f"Tagset override '{override_name}' cleared for {tv_name}")
                log_activity(
                    hass, target_entry.entry_id, tv_id,
                    "tagset_override_cleared",
                    f"Override '{override_name}' cleared",
                )
            async_dispatcher_send(hass, f"{DOMAIN}_tagset_updated_{target_entry.entry_id}_{tv_id}")

        # Register tagset services
        hass.services.async_register(
            DOMAIN,
            "upsert_tagset",
            async_handle_upsert_tagset,
        )

        hass.services.async_register(
            DOMAIN,
            "delete_tagset",
            async_handle_delete_tagset,
        )

        hass.services.async_register(
            DOMAIN,
            "select_tagset",
            async_handle_select_tagset,
        )

        hass.services.async_register(
            DOMAIN,
            "override_tagset",
            async_handle_override_tagset,
        )

        hass.services.async_register(
            DOMAIN,
            "clear_tagset_override",
            async_handle_clear_tagset_override,
        )

        # Service to set recency windows
        async def async_handle_set_recency_windows(call: Any) -> None:
            """Handle set_recency_windows service call."""
            same_tv_hours = call.data.get("same_tv_hours")
            cross_tv_hours = call.data.get("cross_tv_hours")

            # Build new options dict
            new_options = dict(entry.options)

            if same_tv_hours is not None:
                same_tv_hours = max(MIN_RECENCY_HOURS, min(MAX_RECENCY_HOURS, int(same_tv_hours)))
                new_options["same_tv_hours"] = same_tv_hours

            if cross_tv_hours is not None:
                cross_tv_hours = max(MIN_RECENCY_HOURS, min(MAX_RECENCY_HOURS, int(cross_tv_hours)))
                new_options["cross_tv_hours"] = cross_tv_hours

            # Update config entry options
            hass.config_entries.async_update_entry(entry, options=new_options)
            _LOGGER.info(
                "Recency windows updated: same_tv=%sh, cross_tv=%sh",
                new_options.get("same_tv_hours", DEFAULT_SAME_TV_HOURS),
                new_options.get("cross_tv_hours", DEFAULT_CROSS_TV_HOURS),
            )

        hass.services.async_register(
            DOMAIN,
            "set_recency_windows",
            async_handle_set_recency_windows,
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

        # ===== BRIGHTNESS SETTING WITH RETRY =====
        async def async_set_brightness_with_retry(
            tv_id: str,
            brightness: int,
            *,
            reason: str = "manual",
            max_attempts: int = 2,
            retry_delay_seconds: int = 5,
            log_success: bool = True,
        ) -> bool:
            """Set TV brightness with retry logic and activity logging on failure.
            
            Args:
                tv_id: The TV identifier
                brightness: Target brightness (1-10)
                reason: Description for activity log (e.g., "auto, lux: 150" or "post-shuffle sync")
                max_attempts: Number of attempts before giving up
                retry_delay_seconds: Delay between retries
                log_success: Whether to log activity entry on success (default True)
                
            Returns:
                True if brightness was set successfully, False otherwise
            """
            import asyncio
            
            tv_configs = list_tv_configs(entry)
            tv_config = tv_configs.get(tv_id)
            if not tv_config:
                _LOGGER.warning(f"Brightness: TV config not found for {tv_id}")
                return False
            
            data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
            if not data:
                return False
            
            coordinator = data["coordinator"]
            tv_data = next((tv for tv in coordinator.data if tv["id"] == tv_id), None)
            if not tv_data:
                return False
            
            ip = tv_data["ip"]
            tv_name = tv_config.get("name", tv_id)
            
            last_error = None
            for attempt in range(1, max_attempts + 1):
                try:
                    _LOGGER.info(
                        f"Brightness: Attempting to set {tv_name} ({ip}) to {brightness} "
                        f"(attempt {attempt}/{max_attempts})"
                    )
                    await hass.async_add_executor_job(
                        functools.partial(
                            frame_tv.set_tv_brightness,
                            ip,
                            brightness,
                        )
                    )
                    
                    # Success! Store timestamp and brightness
                    from .config_entry import update_tv_config as update_config
                    update_config(
                        hass,
                        entry,
                        tv_id,
                        {
                            "last_auto_brightness_timestamp": datetime.now(timezone.utc).isoformat(),
                            "current_brightness": brightness,
                        },
                    )
                    
                    # Also store in hass.data for lightweight entity sync
                    brightness_cache = hass.data[DOMAIN][entry.entry_id].setdefault("brightness_cache", {})
                    brightness_cache[tv_id] = brightness
                    
                    # Send brightness signal so sensors update
                    signal = f"{DOMAIN}_brightness_adjusted_{entry.entry_id}_{tv_id}"
                    async_dispatcher_send(hass, signal)
                    
                    _LOGGER.info(f"Brightness: {tv_name} successfully set to {brightness}")
                    
                    # Log activity on success (can be suppressed for background operations)
                    if log_success:
                        log_activity(
                            hass, entry.entry_id, tv_id,
                            "brightness_adjusted",
                            f"Brightness → {brightness} ({reason})",
                        )
                    
                    return True
                    
                except Exception as err:
                    last_error = err
                    if attempt < max_attempts:
                        _LOGGER.warning(
                            f"Brightness attempt {attempt}/{max_attempts} failed for {tv_name}: {err}. "
                            f"Retrying in {retry_delay_seconds}s..."
                        )
                        await asyncio.sleep(retry_delay_seconds)
                    else:
                        _LOGGER.error(
                            f"Brightness failed for {tv_name} after {max_attempts} attempts: {err}"
                        )
            
            # All attempts failed - only log to activity if screen was on (unexpected failure)
            # When screen is off, brightness commands are expected to fail
            status_cache = data.get("tv_status_cache", {})
            screen_on = status_cache.get(tv_id, {}).get("screen_on", True)  # Default True to be safe
            
            if screen_on:
                log_activity(
                    hass, entry.entry_id, tv_id,
                    "brightness_failed",
                    f"Brightness → {brightness} failed: {last_error}",
                )
            else:
                _LOGGER.debug(
                    f"Brightness: Skipped failure log for {tv_name} - screen is off (expected)"
                )
            return False

        async def async_sync_brightness_after_shuffle(tv_id: str) -> bool:
            """Sync brightness to the TV after a shuffle completes.
            
            This ensures the TV has the correct brightness even if the previous
            set command was lost or the TV reset to a different value.
            Uses the cached brightness value (from auto-brightness or manual set),
            or calculates from lux sensor if auto-brightness is enabled.
            """
            tv_configs = list_tv_configs(entry)
            tv_config = tv_configs.get(tv_id)
            if not tv_config:
                return False
            
            tv_name = tv_config.get("name", tv_id)
            data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
            
            # Determine target brightness
            target_brightness = None
            reason = "post-shuffle sync"
            
            # If auto-brightness is enabled, calculate from lux
            if tv_config.get("enable_dynamic_brightness", False):
                lux_entity_id = tv_config.get("light_sensor")
                if lux_entity_id:
                    lux_state = hass.states.get(lux_entity_id)
                    if lux_state and lux_state.state not in ("unavailable", "unknown"):
                        try:
                            current_lux = float(lux_state.state)
                            min_lux = tv_config.get("min_lux", 0)
                            max_lux = tv_config.get("max_lux", 1000)
                            min_brightness = tv_config.get("min_brightness", 1)
                            max_brightness = tv_config.get("max_brightness", 10)
                            
                            if max_lux > min_lux:
                                normalized = (current_lux - min_lux) / (max_lux - min_lux)
                                normalized = max(0.0, min(1.0, normalized))
                                target_brightness = int(round(
                                    min_brightness + normalized * (max_brightness - min_brightness)
                                ))
                                target_brightness = max(min_brightness, min(max_brightness, target_brightness))
                                reason = f"post-shuffle sync, lux: {current_lux:.0f}"
                        except (ValueError, TypeError):
                            pass
            
            # Fallback to cached brightness if auto-brightness didn't provide a value
            if target_brightness is None:
                brightness_cache = data.get("brightness_cache", {})
                target_brightness = brightness_cache.get(tv_id)
            
            # Final fallback to stored config brightness
            if target_brightness is None:
                target_brightness = tv_config.get("current_brightness")
            
            if target_brightness is None:
                _LOGGER.debug(f"Post-shuffle brightness sync: No brightness value for {tv_name}, skipping")
                return True  # Not an error, just nothing to sync
            
            _LOGGER.info(f"Post-shuffle brightness sync: Setting {tv_name} to {target_brightness}")
            
            # Get TV IP for verification
            coordinator = data.get("coordinator")
            tv_data = next((tv for tv in coordinator.data if tv["id"] == tv_id), None) if coordinator else None
            ip = tv_data["ip"] if tv_data else None
            
            success = await async_set_brightness_with_retry(
                tv_id,
                int(target_brightness),
                reason=reason,
                log_success=False,  # Don't create noisy activity entries for background sync
            )
            
            if success and ip:
                # Schedule delayed verification and reinforcement to catch brightness drift
                # See docs/BRIGHTNESS_DRIFT.md for details on this issue
                async def _delayed_brightness_check() -> None:
                    _LOGGER.debug(f"Starting delayed brightness verification for {tv_name}")
                    await asyncio.sleep(5)  # Wait for TV to settle after image render
                    try:
                        actual = await hass.async_add_executor_job(
                            frame_tv.get_tv_brightness, ip
                        )
                        if actual is not None and actual != target_brightness:
                            _LOGGER.warning(
                                f"Brightness drift detected for {tv_name}: expected {target_brightness}, "
                                f"TV reports {actual}. Re-setting brightness."
                            )
                            # Re-set brightness to correct the drift
                            await async_set_brightness_with_retry(
                                tv_id,
                                int(target_brightness),
                                reason="drift correction",
                                log_success=False,
                            )
                        else:
                            _LOGGER.debug(
                                f"Post-shuffle brightness verified for {tv_name}: {actual}"
                            )
                    except Exception as err:
                        _LOGGER.debug(f"Post-shuffle brightness verification failed for {tv_name}: {err}")
                
                hass.async_create_task(_delayed_brightness_check())
            
            return success

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

            # Set brightness on TV with retry logic
            success = await async_set_brightness_with_retry(
                tv_id,
                target_brightness,
                reason=f"auto, lux: {current_lux:.0f}",
            )
            
            # Restart timer if requested (e.g., from Trigger Now button)
            if restart_timer and tv_config.get("enable_dynamic_brightness", False):
                start_tv_timer(tv_id)
            
            return success

        # Store helper functions so buttons/switches/shuffle can use them
        hass.data[DOMAIN][entry.entry_id]["async_adjust_tv_brightness"] = async_adjust_tv_brightness
        hass.data[DOMAIN][entry.entry_id]["async_set_brightness_with_retry"] = async_set_brightness_with_retry
        hass.data[DOMAIN][entry.entry_id]["async_sync_brightness_after_shuffle"] = async_sync_brightness_after_shuffle
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

        def _set_auto_shuffle_next_time(tv_id: str, next_time: datetime | None) -> None:
            if next_time is None:
                auto_shuffle_next_times.pop(tv_id, None)
            else:
                auto_shuffle_next_times[tv_id] = next_time
            signal = f"{SIGNAL_AUTO_SHUFFLE_NEXT}_{entry.entry_id}_{tv_id}"
            async_dispatcher_send(hass, signal)

        def cancel_auto_shuffle_timer(tv_id: str) -> None:
            """Cancel the auto shuffle timer for a specific TV."""
            if tv_id in auto_shuffle_timers:
                auto_shuffle_timers[tv_id]()
                del auto_shuffle_timers[tv_id]
            _set_auto_shuffle_next_time(tv_id, None)

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

            # Get recent images for recency preference using dual time windows:
            # - Same-TV: 120 hours (5 days) — "don't show what I've seen on this TV recently"
            # - Cross-TV: 72 hours (3 days) — "don't show what was recently on another TV"
            #
            # The all-TVs query includes the current TV, so there's some overlap
            # with the same-TV query. This is harmless — unioning sets just means
            # some images appear in both, but the final "recent" set is the same.
            recent_images: set[str] = set()
            display_log = data.get("display_log")
            if display_log:
                # Get recency windows from config (with defaults)
                same_tv_hours, cross_tv_hours = get_recency_windows(entry)
                same_tv_recent = display_log.get_recent_auto_shuffle_images(tv_id=tv_id, hours=same_tv_hours)
                cross_tv_recent = display_log.get_recent_auto_shuffle_images(tv_id=None, hours=cross_tv_hours)
                recent_images = same_tv_recent | cross_tv_recent

            await async_shuffle_tv(
                hass,
                entry,
                tv_id,
                reason="auto",
                skip_if_screen_off=True,
                recent_images=recent_images,
            )

        def start_auto_shuffle_timer(tv_id: str) -> None:
            """Start or restart the auto shuffle timer for a TV."""
            tv_configs = list_tv_configs(entry)
            tv_config = tv_configs.get(tv_id)
            if not tv_config or not tv_config.get(CONF_ENABLE_AUTO_SHUFFLE, False):
                cancel_auto_shuffle_timer(tv_id)
                return

            cancel_auto_shuffle_timer(tv_id)

            frequency_minutes = int(tv_config.get(CONF_SHUFFLE_FREQUENCY, 60) or 60)
            if frequency_minutes <= 0:
                frequency_minutes = 1
            interval = timedelta(minutes=frequency_minutes)
            tv_name = tv_config.get("name", tv_id)

            async def async_auto_shuffle_tick(_now: Any) -> None:
                tv_configs_inner = list_tv_configs(entry)
                tv_config_inner = tv_configs_inner.get(tv_id)
                if not tv_config_inner or not tv_config_inner.get(CONF_ENABLE_AUTO_SHUFFLE, False):
                    cancel_auto_shuffle_timer(tv_id)
                    return

                _set_auto_shuffle_next_time(tv_id, datetime.now(timezone.utc) + interval)
                await async_run_auto_shuffle(tv_id)

            unsubscribe = async_track_time_interval(
                hass,
                async_auto_shuffle_tick,
                interval,
            )
            auto_shuffle_timers[tv_id] = unsubscribe
            entry.async_on_unload(unsubscribe)

            next_time = datetime.now(timezone.utc) + interval
            _set_auto_shuffle_next_time(tv_id, next_time)
            _LOGGER.debug(
                "Auto shuffle (%s): Next shuffle scheduled at %s",
                tv_name,
                next_time.isoformat(),
            )


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

        def _get_sensor_short_name(sensor_id: str) -> str:
            """Extract a friendly short name from a sensor entity ID."""
            # binary_sensor.kitchen_motion -> kitchen_motion
            if "." in sensor_id:
                return sensor_id.split(".", 1)[1]
            return sensor_id

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

        # Constants for upload-in-progress reschedule behavior
        UPLOAD_WAIT_RESCHEDULE_SECONDS = 30
        UPLOAD_WAIT_MAX_RESCHEDULES = 10  # 10 * 30s = 5 minutes max wait

        def start_motion_off_timer(tv_id: str, reschedule_count: int = 0) -> None:
            """Start or restart the motion off timer for a specific TV.
            
            Always starts a fresh timer from now. If auto-motion is enabled
            and the TV is on, we manage its power state.
            
            Args:
                tv_id: The TV identifier
                reschedule_count: Number of times we've rescheduled due to upload-in-progress.
                    Used internally for the safety net; callers should not pass this.
            """
            tv_configs = list_tv_configs(entry)
            tv_config = tv_configs.get(tv_id)
            if not tv_config:
                return

            # If this is a reschedule due to upload-in-progress, use short delay
            # Otherwise use the configured off_delay_minutes
            if reschedule_count > 0:
                off_time = datetime.now(timezone.utc) + timedelta(seconds=UPLOAD_WAIT_RESCHEDULE_SECONDS)
            else:
                off_delay_minutes = tv_config.get("motion_off_delay", 15)
                off_time = datetime.now(timezone.utc) + timedelta(minutes=off_delay_minutes)
            
            tv_name = tv_config.get("name", tv_id)
            
            cancel_motion_off_timer(tv_id)
            motion_off_times[tv_id] = off_time
            
            # Signal sensors to update
            async_dispatcher_send(hass, f"{DOMAIN}_motion_off_time_updated_{entry.entry_id}_{tv_id}")

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

                # Check if an upload is in progress for this TV - if so, delay turn-off
                # to avoid killing the connection mid-upload and causing spurious errors
                upload_flags = hass.data.get(DOMAIN, {}).get(entry.entry_id, {}).get("upload_in_progress", set())
                if tv_id in upload_flags:
                    # Safety net: limit max reschedules to prevent infinite loop if something
                    # goes very wrong. In practice this shouldn't be needed because:
                    # 1. async_guarded_upload uses try/finally to always clear the flag
                    # 2. Uploads have their own timeouts (websocket, HTTP)
                    # 3. HA restart would clear in-memory state anyway
                    # But we add this as defense-in-depth against unforeseen edge cases.
                    if reschedule_count >= UPLOAD_WAIT_MAX_RESCHEDULES:
                        _LOGGER.warning(
                            "Auto motion: Max reschedules (%d) reached for %s while waiting for upload. "
                            "Proceeding with turn-off anyway.",
                            UPLOAD_WAIT_MAX_RESCHEDULES, tv_name
                        )
                    else:
                        _LOGGER.debug(
                            "Auto motion: Delaying turn-off for %s - upload in progress (reschedule %d/%d)",
                            tv_name, reschedule_count + 1, UPLOAD_WAIT_MAX_RESCHEDULES
                        )
                        start_motion_off_timer(tv_id, reschedule_count + 1)
                        return

                try:
                    _LOGGER.info(f"Auto motion: Turning off {tv_name} ({ip}) due to no motion")
                    await hass.async_add_executor_job(frame_tv.tv_off, ip)
                    _LOGGER.info(f"Auto motion: {tv_name} turned off successfully")
                    
                    # Build message with last sensor info if available
                    motion_cache = hass.data[DOMAIN][entry.entry_id].get("motion_cache", {})
                    last_sensor = motion_cache.get(f"{tv_id}_last_sensor")
                    last_sensor_time_str = motion_cache.get(f"{tv_id}_last_sensor_time")
                    motion_off_msg = "Turned off (no motion)"
                    if last_sensor and last_sensor_time_str:
                        try:
                            last_sensor_time = datetime.fromisoformat(last_sensor_time_str)
                            minutes_ago = int((datetime.now(timezone.utc) - last_sensor_time).total_seconds() / 60)
                            sensor_short = _get_sensor_short_name(last_sensor)
                            motion_off_msg = f"Turned off - last: {sensor_short} {minutes_ago}m ago"
                        except (ValueError, TypeError):
                            pass
                    
                    log_activity(
                        hass, entry.entry_id, tv_id,
                        "motion_off",
                        motion_off_msg,
                    )
                    # Close the display log session since screen is turning off
                    display_log = hass.data[DOMAIN][entry.entry_id].get("display_log")
                    if display_log:
                        display_log.note_screen_off(tv_id=tv_id, tv_name=tv_name)
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
            # Note: Don't use entry.async_on_unload here - cancel_motion_off_timer 
            # handles cleanup, and we'd accumulate callbacks on repeated calls
            _LOGGER.debug(f"Auto motion: Off timer set for {tv_name} at {off_time}")

        async def async_handle_motion(tv_id: str, tv_config: dict, sensor_id: str | None = None) -> None:
            """Handle motion detection for a TV."""
            # Re-fetch tv_config to get current settings (e.g., verbose_motion_logging)
            # The passed tv_config may be stale if settings changed after listener started
            current_tv_configs = list_tv_configs(entry)
            current_tv_config = current_tv_configs.get(tv_id, tv_config)
            
            tv_name = current_tv_config.get("name", tv_id)
            ip = current_tv_config.get("ip")
            mac = current_tv_config.get("mac")

            if not ip:
                _LOGGER.warning(f"Auto motion: No IP for {tv_name}")
                return

            # Update last motion timestamp and sensor in runtime cache (NOT entry.data to avoid reload)
            motion_cache = hass.data[DOMAIN][entry.entry_id].setdefault("motion_cache", {})
            motion_cache[tv_id] = datetime.now(timezone.utc).isoformat()
            if sensor_id:
                motion_cache[f"{tv_id}_last_sensor"] = sensor_id
                motion_cache[f"{tv_id}_last_sensor_time"] = datetime.now(timezone.utc).isoformat()

            # Signal sensors to update
            async_dispatcher_send(hass, f"{DOMAIN}_motion_detected_{entry.entry_id}_{tv_id}")

            # Check if screen is on - if so, just reset timer
            try:
                screen_on = await hass.async_add_executor_job(frame_tv.is_screen_on, ip)
                if screen_on:
                    _LOGGER.debug(f"Auto motion: {tv_name} screen already on, resetting timer")
                    start_motion_off_timer(tv_id)
                    # Log if verbose motion logging is enabled
                    if current_tv_config.get("verbose_motion_logging", False) and sensor_id:
                        sensor_short = _get_sensor_short_name(sensor_id)
                        log_activity(
                            hass, entry.entry_id, tv_id,
                            "motion_detected",
                            f"Motion ({sensor_short}) - timer reset",
                        )
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
                    sensor_short = _get_sensor_short_name(sensor_id) if sensor_id else "motion"
                    log_activity(
                        hass, entry.entry_id, tv_id,
                        "motion_wake",
                        f"Screen on (woken by {sensor_short})",
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

            motion_sensors = tv_config.get("motion_sensors", [])
            if not motion_sensors:
                _LOGGER.warning(f"Auto motion: No motion sensors configured for {tv_id}")
                return

            tv_name = tv_config.get("name", tv_id)
            ip = tv_config.get("ip")

            # We don't check hass.states.get() here because sensors
            # might not be initialized yet (e.g. Z-Wave/Zigbee at startup).
            # async_track_state_change_event handles missing entities gracefully
            # and will trigger once the entity becomes available.

            @callback
            def motion_state_changed(event: Any) -> None:
                """Handle motion sensor state change."""
                new_state = event.data.get("new_state")
                if not new_state:
                    return

                # Only trigger on motion detected (state = "on")
                # Any sensor in the list reporting "on" will wake the TV (OR logic)
                if new_state.state == "on":
                    sensor_id = new_state.entity_id
                    _LOGGER.debug(f"Auto motion: Motion detected for {tv_name} (sensor: {sensor_id})")
                    hass.async_create_task(async_handle_motion(tv_id, tv_config, sensor_id))

            # Subscribe to state changes for all configured motion sensors
            from homeassistant.helpers.event import async_track_state_change_event
            unsubscribe = async_track_state_change_event(
                hass,
                motion_sensors,
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
                        _LOGGER.info(f"Auto motion: {tv_name} is on at startup, starting off timer")
                        start_motion_off_timer(tv_id)
                    else:
                        _LOGGER.info(f"Auto motion: {tv_name} is off, waiting for motion")
                except Exception as err:
                    _LOGGER.debug(f"Auto motion: Could not check {tv_name} screen state: {err}")
                    # If we can't check, don't start timer - wait for motion
            
            sensors_str = ", ".join(motion_sensors)
            _LOGGER.info(f"Auto motion: Started listener for {tv_name} (sensors: {sensors_str})")

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

        # Log integration start for all TVs
        for tv_id in tv_configs.keys():
            log_activity(
                hass, entry.entry_id, tv_id,
                "integration_start",
                "Integration loaded",
            )

        # Register pool health API endpoint
        hass.http.register_view(PoolHealthView(hass, entry))

        return True


    async def async_unload_entry(hass: Any, entry: Any) -> bool:
        """Unload a Frame Art Shuffler config entry."""

        unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
        if not unload_ok:
            return False

        data = hass.data.get(DOMAIN)
        if data and entry.entry_id in data:
            display_log: DisplayLogManager | None = data[entry.entry_id].get("display_log")
            if display_log:
                await display_log.async_shutdown()
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

                display_log: DisplayLogManager | None = data.get("display_log")
                if display_log:
                    display_log.update_settings(
                        enabled=entry.options.get(CONF_LOGGING_ENABLED),
                        retention_months=entry.options.get(CONF_LOG_RETENTION_MONTHS),
                        flush_minutes=entry.options.get(CONF_LOG_FLUSH_MINUTES),
                    )
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


    async def _async_migrate_motion_sensors(hass: Any, entry: Any) -> None:
        """Migrate motion_sensor (singular string) to motion_sensors (list).
        
        This migration converts the old single motion sensor config to the new
        multi-sensor list format. Added in v1.1.0.
        """
        tvs = entry.data.get("tvs", {})
        if not tvs:
            return

        # Check if any TV needs migration
        needs_migration = any(
            "motion_sensor" in tv_config and "motion_sensors" not in tv_config
            for tv_config in tvs.values()
        )

        if not needs_migration:
            return

        # Perform migration
        data = {**entry.data}
        tvs_copy = {tv_id: tv_data.copy() for tv_id, tv_data in tvs.items()}

        for tv_id, tv_config in tvs_copy.items():
            if "motion_sensor" in tv_config:
                old_value = tv_config.pop("motion_sensor")
                # Convert single value to list (or empty list if None/empty)
                tv_config["motion_sensors"] = [old_value] if old_value else []

        data["tvs"] = tvs_copy
        hass.config_entries.async_update_entry(entry, data=data)
        _LOGGER.info("Migrated motion_sensor config to motion_sensors list format")


    async def _async_migrate_tagsets_to_global(hass: Any, entry: Any) -> None:
        """Migrate per-TV tagsets to global tagsets.
        
        Old structure (v1.1.x): Each TV had its own tagsets dict
            tv_config["tagsets"] = {"everyday": {...}, "holiday": {...}}
        
        New structure (v1.2.0): Global tagsets at integration level
            entry.data["tagsets"] = {"everyday": {...}, "holiday": {...}}
            TVs reference global tagsets by name via selected_tagset/override_tagset
        
        Migration merges all per-TV tagsets into global, handling name conflicts
        by appending _tvname suffix.
        """
        # Skip if already migrated (global tagsets exist)
        if entry.data.get("tagsets"):
            return

        tvs = entry.data.get("tvs", {})
        if not tvs:
            return

        # Check if any TV has the old per-TV tagsets
        has_per_tv_tagsets = any(
            tv_config.get("tagsets")
            for tv_config in tvs.values()
        )

        if not has_per_tv_tagsets:
            return

        # Collect all tagsets from all TVs
        global_tagsets: dict[str, Any] = {}
        data = {**entry.data}
        tvs_copy = {tv_id: tv_data.copy() for tv_id, tv_data in tvs.items()}

        for tv_id, tv_config in tvs_copy.items():
            per_tv_tagsets = tv_config.get("tagsets", {})
            if not per_tv_tagsets:
                continue

            tv_name = tv_config.get("name", tv_id)
            
            for tagset_name, tagset_data in per_tv_tagsets.items():
                # If name already exists in global, append TV name suffix
                final_name = tagset_name
                if tagset_name in global_tagsets:
                    # Check if it's identical (same tags)
                    existing = global_tagsets[tagset_name]
                    if (existing.get("tags") == tagset_data.get("tags") and
                        existing.get("exclude_tags") == tagset_data.get("exclude_tags")):
                        # Identical, no need to create duplicate
                        pass
                    else:
                        # Different content, add with suffix
                        suffix = tv_name.lower().replace(" ", "_")
                        final_name = f"{tagset_name}_{suffix}"
                        while final_name in global_tagsets:
                            final_name = f"{final_name}_2"
                        global_tagsets[final_name] = tagset_data.copy()
                        # Update TV's selected/override if it was using this tagset
                        if tv_config.get("selected_tagset") == tagset_name:
                            tv_config["selected_tagset"] = final_name
                        if tv_config.get("override_tagset") == tagset_name:
                            tv_config["override_tagset"] = final_name
                else:
                    global_tagsets[final_name] = tagset_data.copy()

            # Remove per-TV tagsets after migration
            if "tagsets" in tv_config:
                del tv_config["tagsets"]

        data["tvs"] = tvs_copy
        data["tagsets"] = global_tagsets
        hass.config_entries.async_update_entry(entry, data=data)
        _LOGGER.info(
            "Migrated per-TV tagsets to global tagsets: %d tagsets created",
            len(global_tagsets)
        )


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
