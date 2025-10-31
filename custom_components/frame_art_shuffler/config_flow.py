"""Config flow for the Frame Art Shuffler integration."""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any, Dict, Optional
import uuid

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_MAC, CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_EXCLUDE_TAGS,
    CONF_HOME,
    CONF_INSTANCE_ID,
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
    HomeAlreadyClaimedError,
    MetadataStore,
    TVNotFoundError,
    normalize_mac,
)
from .notify import async_notify_addon_tv_change

CONF_SKIP_PAIRING = "skip_pairing"

ACTION_ADD_TV = "add_tv"
ACTION_EDIT_TV = "edit_tv"
ACTION_DELETE_TV = "delete_tv"


@dataclass
class _OptionsFlowState:
    mode: Optional[str] = None
    selected_tv_id: Optional[str] = None


def _default_metadata_path(hass: HomeAssistant) -> Path:
    return Path(hass.config.path(DEFAULT_METADATA_RELATIVE_PATH))


def _default_token_dir(hass: HomeAssistant) -> Path:
    return Path(hass.config.path(TOKEN_DIR_NAME))


class FrameArtConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Frame Art Shuffler."""

    VERSION = 1

    def __init__(self) -> None:
        self._home: Optional[str] = None
        self._instance_id: Optional[str] = None
        self._metadata_path: Optional[Path] = None
        self._token_dir: Optional[Path] = None
        self._reauth_entry: Optional[config_entries.ConfigEntry] = None
        self._reauth_tv_id: Optional[str] = None

    async def async_step_user(self, user_input: Optional[Dict[str, Any]] = None) -> FlowResult:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        errors: Dict[str, str] = {}

        if user_input is not None:
            home = (user_input.get(CONF_HOME) or "").strip()
            if not home:
                errors[CONF_HOME] = "home_required"
            else:
                metadata_path = _default_metadata_path(self.hass)
                token_dir = _default_token_dir(self.hass)
                instance_id = uuid.uuid4().hex
                store = MetadataStore(metadata_path)
                try:
                    await self.hass.async_add_executor_job(
                        store.claim_home, home, instance_id, home
                    )
                except HomeAlreadyClaimedError:
                    errors[CONF_HOME] = "home_claimed"
                except Exception:  # pragma: no cover - unexpected file errors
                    errors["base"] = "metadata_error"
                else:
                    self._home = home
                    self._instance_id = instance_id
                    self._metadata_path = metadata_path
                    self._token_dir = token_dir
                    data = {
                        CONF_HOME: home,
                        CONF_INSTANCE_ID: instance_id,
                        CONF_METADATA_PATH: str(metadata_path),
                        CONF_TOKEN_DIR: str(token_dir),
                    }
                    return self.async_create_entry(
                        title=f"Frame Art ({home})",
                        data=data,
                    )

        schema = vol.Schema({vol.Required(CONF_HOME): str})
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
        home = entry.data[CONF_HOME]

        try:
            tv = await self.hass.async_add_executor_job(store.get_tv, home, tv_id)
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
    """Options flow for managing TVs within the claimed home."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry
        self._state = _OptionsFlowState()

    @property
    def _home(self) -> str:
        return self.config_entry.data[CONF_HOME]

    @property
    def _metadata_path(self) -> Path:
        return Path(self.config_entry.data[CONF_METADATA_PATH])

    def _store(self) -> MetadataStore:
        return MetadataStore(self._metadata_path)

    async def _list_tvs(self) -> list[dict[str, Any]]:
        return await self.hass.async_add_executor_job(self._store().list_tvs, self._home)

    async def async_step_init(self, user_input: Optional[Dict[str, Any]] = None) -> FlowResult:
        tvs = await self._list_tvs()
        with_tvs = bool(tvs)
        actions = {ACTION_ADD_TV: "Add TV"}
        if with_tvs:
            actions[ACTION_EDIT_TV] = "Edit TV"
            actions[ACTION_DELETE_TV] = "Delete TV"

        if user_input is not None:
            action = user_input.get("action")
            if action == ACTION_ADD_TV:
                self._state.mode = ACTION_ADD_TV
                return await self.async_step_add_tv()
            if action == ACTION_EDIT_TV and with_tvs:
                self._state.mode = ACTION_EDIT_TV
                return await self.async_step_select_tv()
            if action == ACTION_DELETE_TV and with_tvs:
                self._state.mode = ACTION_DELETE_TV
                return await self.async_step_select_tv()
            if action == "finish":
                return self.async_create_entry(title="", data={})

        schema = vol.Schema(
            {
                vol.Required("action", default=ACTION_ADD_TV): vol.In(actions),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)

    async def async_step_select_tv(self, user_input: Optional[Dict[str, Any]] = None) -> FlowResult:
        tvs = await self._list_tvs()
        if not tvs:
            return self.async_abort(reason="no_tvs")

        choices = {tv["id"]: f"{tv.get('name', 'Unnamed')} ({tv.get('ip', '?')})" for tv in tvs}

        if user_input is not None:
            tv_id = user_input.get(CONF_TV_ID)
            if tv_id in choices:
                self._state.selected_tv_id = tv_id
                if self._state.mode == ACTION_EDIT_TV:
                    return await self.async_step_edit_tv()
                return await self.async_step_confirm_delete()

        schema = vol.Schema({vol.Required(CONF_TV_ID): vol.In(choices)})
        return self.async_show_form(step_id="select_tv", data_schema=schema)

    async def async_step_confirm_delete(self, user_input: Optional[Dict[str, Any]] = None) -> FlowResult:
        tv_id = self._state.selected_tv_id
        if not tv_id:
            return self.async_abort(reason="unknown_tv")

        if user_input is not None:
            if user_input.get("confirm"):
                store = self._store()
                await self.hass.async_add_executor_job(store.remove_tv, self._home, tv_id)
                await async_notify_addon_tv_change(
                    self.hass,
                    event="deleted",
                    home=self._home,
                    tv={"id": tv_id},
                )
                self._async_schedule_refresh()
            return self.async_create_entry(title="", data={})

        schema = vol.Schema({vol.Required("confirm", default=False): bool})
        return self.async_show_form(
            step_id="confirm_delete",
            data_schema=schema,
            description_placeholders={"tv_id": tv_id},
        )

    async def async_step_add_tv(self, user_input: Optional[Dict[str, Any]] = None) -> FlowResult:
        return await self._handle_tv_form(user_input, is_edit=False)

    async def async_step_edit_tv(self, user_input: Optional[Dict[str, Any]] = None) -> FlowResult:
        return await self._handle_tv_form(user_input, is_edit=True)

    async def _handle_tv_form(self, user_input: Optional[Dict[str, Any]], *, is_edit: bool) -> FlowResult:
        tv: Optional[Dict[str, Any]] = None
        if is_edit:
            tv_id = self._state.selected_tv_id
            if not tv_id:
                return self.async_abort(reason="unknown_tv")
            store = self._store()
            try:
                tv = await self.hass.async_add_executor_job(store.get_tv, self._home, tv_id)
            except Exception:  # pragma: no cover - unexpected read error
                return self.async_abort(reason="unknown_tv")
        else:
            tv_id = None

        errors: Dict[str, str] = {}

        if user_input is not None:
            host_input = user_input.get(CONF_HOST, "")
            name = (user_input.get(CONF_NAME) or "").strip()
            mac_input = user_input.get(CONF_MAC)
            freq = user_input.get(CONF_SHUFFLE_FREQUENCY, 0)
            tags_input = user_input.get(CONF_TAGS, "")
            exclude_input = user_input.get(CONF_EXCLUDE_TAGS, "")
            skip_pairing = user_input.get(CONF_SKIP_PAIRING, False)

            try:
                host = validate_host(host_input)
            except ValueError:
                errors[CONF_HOST] = "invalid_host"
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
                    "id": tv_id,
                    "name": name,
                    "ip": host,
                    "mac": normalized_mac,
                    "tags": tags,
                    "notTags": exclude_tags,
                    "shuffle": {CONF_SHUFFLE_FREQUENCY: frequency},
                }

                if not skip_pairing:
                    token_dir = Path(self.config_entry.data[CONF_TOKEN_DIR])
                    token_dir.mkdir(parents=True, exist_ok=True)
                    token_path = token_dir / f"{safe_token_filename(host)}.token"
                    success = await self._async_pair_tv(host, token_path, mac=normalized_mac)
                    if not success:
                        errors["base"] = "pairing_failed"

                if not errors:
                    store = self._store()
                    updated_tv = await self.hass.async_add_executor_job(
                        store.upsert_tv,
                        self._home,
                        tv_payload,
                    )
                    await async_notify_addon_tv_change(
                        self.hass,
                        event="updated" if tv_id else "created",
                        home=self._home,
                        tv=updated_tv,
                    )
                    self._async_schedule_refresh()
                    return self.async_create_entry(title="", data={})

        defaults = {
            CONF_NAME: tv.get("name") if tv else "",
            CONF_HOST: tv.get("ip") if tv else "",
            CONF_MAC: tv.get("mac") if tv else "",
            CONF_TAGS: ", ".join(tv.get("tags", [])) if tv else "",
            CONF_EXCLUDE_TAGS: ", ".join(tv.get("notTags", [])) if tv else "",
            CONF_SHUFFLE_FREQUENCY: tv.get("shuffle", {}).get(CONF_SHUFFLE_FREQUENCY, 30)
            if tv
            else 30,
            CONF_SKIP_PAIRING: True if tv else False,
        }

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default=defaults[CONF_NAME]): str,
                vol.Required(CONF_HOST, default=defaults[CONF_HOST]): str,
                vol.Required(CONF_MAC, default=defaults[CONF_MAC]): str,
                vol.Optional(CONF_TAGS, default=defaults[CONF_TAGS]): str,
                vol.Optional(CONF_EXCLUDE_TAGS, default=defaults[CONF_EXCLUDE_TAGS]): str,
                vol.Required(CONF_SHUFFLE_FREQUENCY, default=defaults[CONF_SHUFFLE_FREQUENCY]): vol.Coerce(int),
                vol.Optional(CONF_SKIP_PAIRING, default=defaults[CONF_SKIP_PAIRING]): bool,
            }
        )
        return self.async_show_form(
            step_id="edit_tv" if is_edit else "add_tv",
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