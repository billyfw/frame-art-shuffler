"""Config flow for the Frame Art Shuffler integration."""

from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import Any, Dict, Optional

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_MAC, CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigFlowResult

from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
)

from .const import (
    CONF_EXCLUDE_TAGS,
    CONF_LOGGING_ENABLED,
    CONF_LOG_FLUSH_MINUTES,
    CONF_LOG_RETENTION_MONTHS,
    CONF_METADATA_PATH,
    CONF_SELECTED_TAGSET,
    CONF_SHORT_NAME,
    CONF_SHUFFLE_FREQUENCY,
    CONF_TAGS,
    CONF_TAGSETS,
    CONF_TOKEN_DIR,
    CONF_TV_ID,
    CONF_MOTION_SENSOR,  # Deprecated: for migration only
    CONF_MOTION_SENSORS,
    CONF_LIGHT_SENSOR,
    CONF_ENABLE_AUTO_SHUFFLE,
    CONF_MIN_LUX,
    CONF_MAX_LUX,
    CONF_MIN_BRIGHTNESS,
    CONF_MAX_BRIGHTNESS,
    CONF_ENABLE_DYNAMIC_BRIGHTNESS,
    CONF_ENABLE_MOTION_CONTROL,
    CONF_MOTION_OFF_DELAY,
    DEFAULT_LOGGING_ENABLED,
    DEFAULT_LOG_FLUSH_MINUTES,
    DEFAULT_LOG_RETENTION_MONTHS,
    DEFAULT_METADATA_RELATIVE_PATH,
    DOMAIN,
    TOKEN_DIR_NAME,
)
from .flow_utils import parse_tag_string, pair_tv, safe_token_filename, validate_host
from .metadata import (
    MetadataStore,
    TVNotFoundError,
    normalize_mac,
)

CONF_SKIP_PAIRING = "skip_pairing"
CONF_REPAIR = "re_pair"

LOG_RETENTION_MIN = 1
LOG_RETENTION_MAX = 12
LOG_FLUSH_MIN = 1
LOG_FLUSH_MAX = 60


def _default_metadata_path(hass: HomeAssistant) -> Path:
    return Path(hass.config.path(DEFAULT_METADATA_RELATIVE_PATH))


def _default_token_dir(hass: HomeAssistant) -> Path:
    return Path(hass.config.path(TOKEN_DIR_NAME))


class FrameArtConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Frame Art Shuffler."""

    VERSION = 1

    def __init__(self) -> None:
        self._metadata_path: Optional[Path] = None
        self._token_dir: Optional[Path] = None
        self._reauth_entry: Optional[config_entries.ConfigEntry] = None
        self._reauth_tv_id: Optional[str] = None

    async def async_step_user(self, user_input: Optional[Dict[str, Any]] = None) -> ConfigFlowResult:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        errors: Dict[str, str] = {}

        if user_input is not None:
            metadata_path = _default_metadata_path(self.hass)
            token_dir = _default_token_dir(self.hass)
            
            self._metadata_path = metadata_path
            self._token_dir = token_dir
            data = {
                CONF_METADATA_PATH: str(metadata_path),
                CONF_TOKEN_DIR: str(token_dir),
            }
            return self.async_create_entry(
                title="Frame Art Shuffler",
                data=data,
            )

        # Just need a confirmation, no home required
        schema = vol.Schema({})
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_reauth(self, data: Dict[str, Any]) -> ConfigFlowResult:
        entry_id = self.context.get("entry_id")
        self._reauth_tv_id = data.get(CONF_TV_ID)
        if not entry_id or not self._reauth_tv_id:
            return self.async_abort(reason="reauth_failed")

        entry = self.hass.config_entries.async_get_entry(entry_id)
        if entry is None:
            return self.async_abort(reason="reauth_failed")

        self._reauth_entry = entry
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: Optional[Dict[str, Any]] = None) -> ConfigFlowResult:
        entry = self._reauth_entry
        tv_id = self._reauth_tv_id
        if entry is None or tv_id is None:
            return self.async_abort(reason="reauth_failed")

        store = MetadataStore(Path(entry.data[CONF_METADATA_PATH]))

        try:
            tv = await self.hass.async_add_executor_job(store.get_tv, tv_id)
        except TVNotFoundError:
            return self.async_abort(reason="unknown_tv")
        except Exception:  # pragma: no cover - unexpected file errors
            return self.async_abort(reason="metadata_error")

        errors: Dict[str, str] = {}

        if user_input is not None:
            token_dir = Path(entry.data[CONF_TOKEN_DIR])
            token_dir.mkdir(parents=True, exist_ok=True)
            token_path = token_dir / f"{safe_token_filename(tv.get('ip', tv_id))}.token"
            success = await self._async_pair_tv(
                tv.get("ip", ""),
                token_path,
                mac=tv.get("mac"),
            )
            if success:
                self._async_schedule_refresh(entry.entry_id)
                return self.async_create_entry(title="", data={})
            errors["base"] = "pairing_failed"

        schema = vol.Schema({vol.Required("confirm", default=True): bool})
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "tv_name": tv.get("name", tv_id),
                "tv_host": tv.get("ip", ""),
            },
        )

    def _async_schedule_refresh(self, entry_id: str) -> None:
        domain_data = self.hass.data.get(DOMAIN)
        if not domain_data:
            return
        entry_data = domain_data.get(entry_id)
        if not entry_data:
            return
        coordinator = entry_data.get("coordinator")
        if coordinator is not None:
            self.hass.async_create_task(coordinator.async_request_refresh())

    async def _async_pair_tv(self, host: str, token_path: Path, *, mac: str | None = None) -> bool:
        """Pair with a TV."""
        bound = partial(pair_tv, host, token_path, mac=mac)
        return await self.hass.async_add_executor_job(bound)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        return FrameArtOptionsFlowHandler(config_entry)


class FrameArtOptionsFlowHandler(config_entries.OptionsFlow):
    """Options flow for adding TVs."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    @property
    def _metadata_path(self) -> Path:
        return Path(self.config_entry.data[CONF_METADATA_PATH])

    def _store(self) -> MetadataStore:
        return MetadataStore(self._metadata_path)

    async def _list_tvs(self) -> list[dict[str, Any]]:
        return await self.hass.async_add_executor_job(self._store().list_tvs)

    def _logging_option_defaults(self) -> dict[str, Any]:
        options = dict(self.config_entry.options or {})
        return {
            CONF_LOGGING_ENABLED: options.get(CONF_LOGGING_ENABLED, DEFAULT_LOGGING_ENABLED),
            CONF_LOG_RETENTION_MONTHS: options.get(
                CONF_LOG_RETENTION_MONTHS,
                DEFAULT_LOG_RETENTION_MONTHS,
            ),
            CONF_LOG_FLUSH_MINUTES: options.get(
                CONF_LOG_FLUSH_MINUTES,
                DEFAULT_LOG_FLUSH_MINUTES,
            ),
        }

    async def async_step_init(self, user_input: Optional[Dict[str, Any]] = None) -> ConfigFlowResult:
        """Show the main menu."""
        return await self.async_step_menu(user_input)

    async def async_step_menu(self, user_input: Optional[Dict[str, Any]] = None) -> ConfigFlowResult:
        """Show the menu to add or edit TVs."""
        if user_input is not None:
            if user_input["action"] == "add_tv":
                return await self.async_step_add_tv()
            elif user_input["action"] == "edit_tv":
                return await self.async_step_pick_edit_tv()
            elif user_input["action"] == "delete_tv":
                return await self.async_step_delete_tv()
            elif user_input["action"] == "logging_settings":
                return await self.async_step_logging_settings()

        # Get list of existing TVs
        from .config_entry import list_tv_configs
        tvs = list_tv_configs(self.config_entry)
        
        options = {
            "logging_settings": "Logging settings",
            "add_tv": "Add a new TV",
        }
        if tvs:
            options["edit_tv"] = "Edit a TV"
            options["delete_tv"] = "Delete a TV"

        return self.async_show_form(
            step_id="menu",
            data_schema=vol.Schema({
                vol.Required("action"): vol.In(options)
            }),
        )

    async def async_step_logging_settings(
        self,
        user_input: Optional[Dict[str, Any]] = None,
    ) -> ConfigFlowResult:
        """Configure logging/retention settings."""

        defaults = self._logging_option_defaults()
        errors: Dict[str, str] = {}

        if user_input is not None:
            enabled = bool(user_input.get(CONF_LOGGING_ENABLED, defaults[CONF_LOGGING_ENABLED]))
            retention = user_input.get(CONF_LOG_RETENTION_MONTHS, defaults[CONF_LOG_RETENTION_MONTHS])
            flush = user_input.get(CONF_LOG_FLUSH_MINUTES, defaults[CONF_LOG_FLUSH_MINUTES])

            try:
                retention_int = int(retention)
                if not (LOG_RETENTION_MIN <= retention_int <= LOG_RETENTION_MAX):
                    raise ValueError
            except (TypeError, ValueError):
                errors[CONF_LOG_RETENTION_MONTHS] = "invalid_retention"
                retention_int = defaults[CONF_LOG_RETENTION_MONTHS]

            try:
                flush_int = int(flush)
                if not (LOG_FLUSH_MIN <= flush_int <= LOG_FLUSH_MAX):
                    raise ValueError
            except (TypeError, ValueError):
                errors[CONF_LOG_FLUSH_MINUTES] = "invalid_flush"
                flush_int = defaults[CONF_LOG_FLUSH_MINUTES]

            if not errors:
                new_options = dict(self.config_entry.options or {})
                new_options[CONF_LOGGING_ENABLED] = enabled
                new_options[CONF_LOG_RETENTION_MONTHS] = retention_int
                new_options[CONF_LOG_FLUSH_MINUTES] = flush_int

                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    options=new_options,
                )
                return self.async_create_entry(title="", data={})

        retention_choices = [str(value) for value in range(LOG_RETENTION_MIN, LOG_RETENTION_MAX + 1)]
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_LOGGING_ENABLED,
                    default=defaults[CONF_LOGGING_ENABLED],
                ): bool,
                vol.Required(
                    CONF_LOG_RETENTION_MONTHS,
                    default=str(defaults[CONF_LOG_RETENTION_MONTHS]),
                ): vol.In(retention_choices),
                vol.Required(
                    CONF_LOG_FLUSH_MINUTES,
                    default=defaults[CONF_LOG_FLUSH_MINUTES],
                ): vol.All(vol.Coerce(int), vol.Range(min=LOG_FLUSH_MIN, max=LOG_FLUSH_MAX)),
            }
        )

        return self.async_show_form(
            step_id="logging_settings",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_pick_edit_tv(self, user_input: Optional[Dict[str, Any]] = None) -> ConfigFlowResult:
        """Handle picking a TV to edit."""
        from .config_entry import list_tv_configs
        
        tvs = list_tv_configs(self.config_entry)
        if not tvs:
            return await self.async_step_menu()

        if user_input is not None:
            self._edit_tv_id = user_input["tv_id"]
            return await self.async_step_edit_tv()

        options = {tv_id: data.get("name", tv_id) for tv_id, data in tvs.items()}

        return self.async_show_form(
            step_id="pick_edit_tv",
            data_schema=vol.Schema({
                vol.Required("tv_id"): vol.In(options)
            }),
            description_placeholders={"count": str(len(tvs))}
        )

    async def async_step_delete_tv(self, user_input: Optional[Dict[str, Any]] = None) -> ConfigFlowResult:
        """Handle deleting a TV."""
        from .config_entry import list_tv_configs, remove_tv_config, get_tv_config
        from .frame_tv import delete_token
        
        tvs = list_tv_configs(self.config_entry)
        if not tvs:
            return await self.async_step_menu()

        if user_input is not None:
            tv_id = user_input["tv_id"]
            tv_config = get_tv_config(self.config_entry, tv_id)
            
            # Delete token first
            if tv_config and "ip" in tv_config:
                try:
                    await self.hass.async_add_executor_job(delete_token, tv_config["ip"])
                except Exception:
                    pass  # Best effort
            
            # Remove from config
            remove_tv_config(self.hass, self.config_entry, tv_id)
            
            # Refresh
            self._async_schedule_refresh()
            
            # Return to menu to see updated list
            return await self.async_step_menu()

        options = {tv_id: data.get("name", tv_id) for tv_id, data in tvs.items()}

        return self.async_show_form(
            step_id="delete_tv",
            data_schema=vol.Schema({
                vol.Required("tv_id"): vol.In(options)
            }),
            description_placeholders={"count": str(len(tvs))}
        )

    async def async_step_edit_tv(self, user_input: Optional[Dict[str, Any]] = None) -> ConfigFlowResult:
        """Handle editing an existing TV."""
        from .config_entry import get_tv_config, update_tv_config
        
        tv_id = getattr(self, "_edit_tv_id", None)
        if not tv_id:
            return await self.async_step_menu()
            
        current_config = get_tv_config(self.config_entry, tv_id)
        if not current_config:
            return await self.async_step_menu()

        errors: Dict[str, str] = {}

        if user_input is not None:
            host_input = user_input.get(CONF_HOST, "")
            name = (user_input.get(CONF_NAME) or "").strip()
            short_name = (user_input.get(CONF_SHORT_NAME) or "").strip()
            mac_input = user_input.get(CONF_MAC, "")
            freq = user_input.get(CONF_SHUFFLE_FREQUENCY, 30)
            motion_sensors = user_input.get(CONF_MOTION_SENSORS) or []
            light_sensor = user_input.get(CONF_LIGHT_SENSOR)
            min_lux = user_input.get(CONF_MIN_LUX, 0)
            max_lux = user_input.get(CONF_MAX_LUX, 1000)
            min_brightness = user_input.get(CONF_MIN_BRIGHTNESS, 1)
            max_brightness = user_input.get(CONF_MAX_BRIGHTNESS, 10)
            enable_dynamic_brightness = user_input.get(CONF_ENABLE_DYNAMIC_BRIGHTNESS, False)
            enable_motion_control = user_input.get(CONF_ENABLE_MOTION_CONTROL, False)
            enable_auto_shuffle = user_input.get(CONF_ENABLE_AUTO_SHUFFLE, False)
            motion_off_delay = user_input.get(CONF_MOTION_OFF_DELAY, 15)
            re_pair = user_input.get(CONF_REPAIR, False)

            try:
                host = validate_host(host_input)
            except ValueError:
                errors[CONF_HOST] = "invalid_host"
                host = host_input
            if not name:
                errors[CONF_NAME] = "name_required"

            normalized_mac = normalize_mac(mac_input)
            if not normalized_mac:
                errors[CONF_MAC] = "invalid_mac"

            try:
                frequency = int(freq)
                if frequency <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                errors[CONF_SHUFFLE_FREQUENCY] = "invalid_frequency"
                frequency = 0

            if not errors:
                # Check if IP changed
                old_ip = current_config.get("ip")
                ip_changed = old_ip != host

                # Update TV config (tags managed via services/add-on, not config flow)
                update_tv_config(self.hass, self.config_entry, tv_id, {
                    "name": name,
                    "short_name": short_name,
                    "ip": host,
                    "mac": normalized_mac,
                    "shuffle_frequency_minutes": frequency,
                    "enable_auto_shuffle": enable_auto_shuffle,
                    "motion_sensors": motion_sensors,
                    "light_sensor": light_sensor,
                    "min_lux": min_lux,
                    "max_lux": max_lux,
                    "min_brightness": min_brightness,
                    "max_brightness": max_brightness,
                    "enable_dynamic_brightness": enable_dynamic_brightness,
                    "enable_motion_control": enable_motion_control,
                    "motion_off_delay": motion_off_delay,
                })

                # Pair if requested OR if IP changed
                if re_pair or ip_changed:
                    token_dir = Path(self.config_entry.data[CONF_TOKEN_DIR])
                    token_dir.mkdir(parents=True, exist_ok=True)
                    token_path = token_dir / f"{safe_token_filename(host)}.token"
                    
                    # If IP changed, we might want to delete the old token? 
                    # For now, just ensure we pair with the new one.
                    
                    success = await self.hass.async_add_executor_job(
                        partial(pair_tv, host, token_path, mac=normalized_mac)
                    )
                    if not success:
                        errors["base"] = "pairing_failed"

                if not errors:
                    self._async_schedule_refresh()
                    return self.async_create_entry(title="", data={})

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=current_config.get("name", "")): str,
                vol.Optional(CONF_SHORT_NAME, default=current_config.get("short_name", "")): str,
                vol.Required(CONF_HOST, default=current_config.get("ip", "")): str,
                vol.Required(CONF_MAC, default=current_config.get("mac", "")): str,
                vol.Required(CONF_SHUFFLE_FREQUENCY, default=current_config.get("shuffle_frequency_minutes", 30)): vol.Coerce(int),
                vol.Optional(CONF_ENABLE_AUTO_SHUFFLE, default=current_config.get("enable_auto_shuffle", False)): bool,
                vol.Optional(CONF_MOTION_SENSORS, default=current_config.get("motion_sensors", [])): EntitySelector(
                    EntitySelectorConfig(domain="binary_sensor", device_class="motion", multiple=True)
                ),
                vol.Optional(CONF_LIGHT_SENSOR, default=current_config.get("light_sensor")): EntitySelector(
                    EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(CONF_ENABLE_DYNAMIC_BRIGHTNESS, default=current_config.get("enable_dynamic_brightness", False)): bool,
                vol.Optional(CONF_MIN_LUX, default=current_config.get("min_lux", 0)): vol.Coerce(int),
                vol.Optional(CONF_MAX_LUX, default=current_config.get("max_lux", 1000)): vol.Coerce(int),
                vol.Optional(CONF_MIN_BRIGHTNESS, default=current_config.get("min_brightness", 1)): vol.All(vol.Coerce(int), vol.Range(min=1, max=10)),
                vol.Optional(CONF_MAX_BRIGHTNESS, default=current_config.get("max_brightness", 10)): vol.All(vol.Coerce(int), vol.Range(min=1, max=10)),
                vol.Optional(CONF_ENABLE_MOTION_CONTROL, default=current_config.get("enable_motion_control", False)): bool,
                vol.Optional(CONF_MOTION_OFF_DELAY, default=current_config.get("motion_off_delay", 15)): vol.All(vol.Coerce(int), vol.Range(min=1, max=120)),
                vol.Optional(CONF_REPAIR, default=False): bool,
            }
        )

        return self.async_show_form(
            step_id="edit_tv",
            data_schema=schema,
            errors=errors,
            description_placeholders={"tv_name": current_config.get("name", "")}
        )

    async def async_step_add_tv(self, user_input: Optional[Dict[str, Any]] = None) -> ConfigFlowResult:
        """Handle adding a new TV."""
        errors: Dict[str, str] = {}
        
        # Preserve user input for re-rendering on error
        preserved_input = user_input or {}

        if user_input is not None:
            host_input = user_input.get(CONF_HOST, "")
            name = (user_input.get(CONF_NAME) or "").strip()
            short_name = (user_input.get(CONF_SHORT_NAME) or "").strip()
            mac_input = user_input.get(CONF_MAC, "")
            freq = user_input.get(CONF_SHUFFLE_FREQUENCY, 30)
            tags_input = user_input.get(CONF_TAGS, "")
            exclude_input = user_input.get(CONF_EXCLUDE_TAGS, "")
            motion_sensors = user_input.get(CONF_MOTION_SENSORS) or []
            light_sensor = user_input.get(CONF_LIGHT_SENSOR)
            min_lux = user_input.get(CONF_MIN_LUX, 0)
            max_lux = user_input.get(CONF_MAX_LUX, 1000)
            min_brightness = user_input.get(CONF_MIN_BRIGHTNESS, 1)
            max_brightness = user_input.get(CONF_MAX_BRIGHTNESS, 10)
            enable_dynamic_brightness = user_input.get(CONF_ENABLE_DYNAMIC_BRIGHTNESS, False)
            enable_motion_control = user_input.get(CONF_ENABLE_MOTION_CONTROL, False)
            enable_auto_shuffle = user_input.get(CONF_ENABLE_AUTO_SHUFFLE, False)
            motion_off_delay = user_input.get(CONF_MOTION_OFF_DELAY, 15)
            skip_pairing = user_input.get(CONF_SKIP_PAIRING, False)

            try:
                host = validate_host(host_input)
            except ValueError:
                errors[CONF_HOST] = "invalid_host"
                host = host_input
            if not name:
                errors[CONF_NAME] = "name_required"

            normalized_mac = normalize_mac(mac_input)
            if not normalized_mac:
                errors[CONF_MAC] = "invalid_mac"

            try:
                frequency = int(freq)
                if frequency <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                errors[CONF_SHUFFLE_FREQUENCY] = "invalid_frequency"
                frequency = 0

            tags = parse_tag_string(tags_input)
            exclude_tags = parse_tag_string(exclude_input)

            if not errors:
                tv_payload = {
                    "name": name,
                    "ip": host,
                    "mac": normalized_mac,
                    "tags": tags,
                    "notTags": exclude_tags,
                    "shuffle": {"frequencyMinutes": frequency},
                }

                if not skip_pairing:
                    token_dir = Path(self.config_entry.data[CONF_TOKEN_DIR])
                    token_dir.mkdir(parents=True, exist_ok=True)
                    token_path = token_dir / f"{safe_token_filename(host)}.token"
                    success = await self.hass.async_add_executor_job(
                        partial(pair_tv, host, token_path, mac=normalized_mac)
                    )
                    if not success:
                        errors["base"] = "pairing_failed"

                if not errors:
                    # Generate a new TV ID
                    from uuid import uuid4
                    tv_id = uuid4().hex
                    
                    # Create tagset structure for new TV
                    # Store tags/exclude_tags in a "primary" tagset
                    tagsets = {
                        "primary": {
                            "tags": tags,
                            "exclude_tags": exclude_tags,
                        }
                    }
                    
                    # Add TV to config entry (not metadata.json)
                    from .config_entry import add_tv_config
                    add_tv_config(self.hass, self.config_entry, tv_id, {
                        "name": name,
                        "short_name": short_name,
                        "ip": host,
                        "mac": normalized_mac,
                        "tagsets": tagsets,
                        "selected_tagset": "primary",
                        "shuffle_frequency_minutes": frequency,
                        "motion_sensors": motion_sensors,
                        "light_sensor": light_sensor,
                        "min_lux": min_lux,
                        "max_lux": max_lux,
                        "min_brightness": min_brightness,
                        "max_brightness": max_brightness,
                        "enable_auto_shuffle": enable_auto_shuffle,
                        "enable_dynamic_brightness": enable_dynamic_brightness,
                        "enable_motion_control": enable_motion_control,
                        "motion_off_delay": motion_off_delay,
                    })
                    
                    self._async_schedule_refresh()
                    return self.async_create_entry(
                        title=f"{name} added as TV for Frame Art Shuffler",
                        data={},
                    )

        # Use preserved input as defaults when re-rendering form with errors
        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=preserved_input.get(CONF_NAME, "")): str,
                vol.Optional(CONF_SHORT_NAME, default=preserved_input.get(CONF_SHORT_NAME, "")): str,
                vol.Required(CONF_HOST, default=preserved_input.get(CONF_HOST, "")): str,
                vol.Required(CONF_MAC, default=preserved_input.get(CONF_MAC, "")): str,
                vol.Optional(CONF_TAGS, default=preserved_input.get(CONF_TAGS, "")): str,
                vol.Optional(CONF_EXCLUDE_TAGS, default=preserved_input.get(CONF_EXCLUDE_TAGS, "")): str,
                vol.Required(CONF_SHUFFLE_FREQUENCY, default=preserved_input.get(CONF_SHUFFLE_FREQUENCY, 30)): vol.Coerce(int),
                vol.Optional(CONF_ENABLE_AUTO_SHUFFLE, default=preserved_input.get(CONF_ENABLE_AUTO_SHUFFLE, False)): bool,
                vol.Optional(CONF_MOTION_SENSORS, default=preserved_input.get(CONF_MOTION_SENSORS, [])): EntitySelector(
                    EntitySelectorConfig(domain="binary_sensor", device_class="motion", multiple=True)
                ),
                vol.Optional(CONF_LIGHT_SENSOR, default=preserved_input.get(CONF_LIGHT_SENSOR)): EntitySelector(
                    EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(CONF_ENABLE_DYNAMIC_BRIGHTNESS, default=preserved_input.get(CONF_ENABLE_DYNAMIC_BRIGHTNESS, False)): bool,
                vol.Optional(CONF_MIN_LUX, default=preserved_input.get(CONF_MIN_LUX, 0)): vol.Coerce(int),
                vol.Optional(CONF_MAX_LUX, default=preserved_input.get(CONF_MAX_LUX, 1000)): vol.Coerce(int),
                vol.Optional(CONF_MIN_BRIGHTNESS, default=preserved_input.get(CONF_MIN_BRIGHTNESS, 1)): vol.All(vol.Coerce(int), vol.Range(min=1, max=10)),
                vol.Optional(CONF_MAX_BRIGHTNESS, default=preserved_input.get(CONF_MAX_BRIGHTNESS, 10)): vol.All(vol.Coerce(int), vol.Range(min=1, max=10)),
                vol.Optional(CONF_ENABLE_MOTION_CONTROL, default=preserved_input.get(CONF_ENABLE_MOTION_CONTROL, False)): bool,
                vol.Optional(CONF_MOTION_OFF_DELAY, default=preserved_input.get(CONF_MOTION_OFF_DELAY, 15)): vol.All(vol.Coerce(int), vol.Range(min=1, max=120)),
                vol.Optional(CONF_SKIP_PAIRING, default=preserved_input.get(CONF_SKIP_PAIRING, False)): bool,
            }
        )
        return self.async_show_form(
            step_id="add_tv",
            data_schema=schema,
            errors=errors,
        )

    async def _async_pair_tv(self, host: str, token_path: Path, *, mac: str | None = None) -> bool:
        bound = partial(pair_tv, host, token_path, mac=mac)
        return await self.hass.async_add_executor_job(bound)

    def _async_schedule_refresh(self) -> None:
        domain_data = self.hass.data.get(DOMAIN)
        if not domain_data:
            return
        entry_data = domain_data.get(self.config_entry.entry_id)
        if not entry_data:
            return
        coordinator = entry_data.get("coordinator")
        if coordinator is not None:
            self.hass.async_create_task(coordinator.async_request_refresh())