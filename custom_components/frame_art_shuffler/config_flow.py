"""Config flow for the Frame Art Shuffler integration."""

from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import Any, Dict, Optional

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_MAC, CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_EXCLUDE_TAGS,
    CONF_METADATA_PATH,
    CONF_SHUFFLE_FREQUENCY,
    CONF_TAGS,
    CONF_TOKEN_DIR,
    CONF_TV_ID,
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

    async def async_step_user(self, user_input: Optional[Dict[str, Any]] = None) -> FlowResult:
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

    async def async_step_reauth(self, data: Dict[str, Any]) -> FlowResult:
        entry_id = self.context.get("entry_id")
        self._reauth_tv_id = data.get(CONF_TV_ID)
        if not entry_id or not self._reauth_tv_id:
            return self.async_abort(reason="reauth_failed")

        entry = self.hass.config_entries.async_get_entry(entry_id)
        if entry is None:
            return self.async_abort(reason="reauth_failed")

        self._reauth_entry = entry
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: Optional[Dict[str, Any]] = None) -> FlowResult:
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

    async def async_step_init(self, user_input: Optional[Dict[str, Any]] = None) -> FlowResult:
        """Show the Add TV form directly."""
        return await self.async_step_add_tv(user_input)

    async def async_step_add_tv(self, user_input: Optional[Dict[str, Any]] = None) -> FlowResult:
        """Handle adding a new TV."""
        errors: Dict[str, str] = {}
        
        # Preserve user input for re-rendering on error
        preserved_input = user_input or {}

        if user_input is not None:
            host_input = user_input.get(CONF_HOST, "")
            name = (user_input.get(CONF_NAME) or "").strip()
            mac_input = user_input.get(CONF_MAC, "")
            freq = user_input.get(CONF_SHUFFLE_FREQUENCY, 30)
            tags_input = user_input.get(CONF_TAGS, "")
            exclude_input = user_input.get(CONF_EXCLUDE_TAGS, "")
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
                    store = self._store()
                    updated_tv = await self.hass.async_add_executor_job(
                        store.upsert_tv,
                        tv_payload,
                    )
                    self._async_schedule_refresh()
                    return self.async_create_entry(title="", data={})

        # Use preserved input as defaults when re-rendering form with errors
        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=preserved_input.get(CONF_NAME, "")): str,
                vol.Required(CONF_HOST, default=preserved_input.get(CONF_HOST, "")): str,
                vol.Required(CONF_MAC, default=preserved_input.get(CONF_MAC, "")): str,
                vol.Optional(CONF_TAGS, default=preserved_input.get(CONF_TAGS, "")): str,
                vol.Optional(CONF_EXCLUDE_TAGS, default=preserved_input.get(CONF_EXCLUDE_TAGS, "")): str,
                vol.Required(CONF_SHUFFLE_FREQUENCY, default=preserved_input.get(CONF_SHUFFLE_FREQUENCY, 30)): vol.Coerce(int),
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