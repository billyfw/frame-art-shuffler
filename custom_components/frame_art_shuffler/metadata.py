"""Metadata management utilities for Frame Art Shuffler.

This module is responsible for reading and writing the shared
``metadata.json`` file that lives alongside the Frame Art Manager add-on.
It enforces the "home" scoping rules so multiple Home Assistant instances
can coexist while operating on the same library.

All helpers are intentionally synchronous; call them from the Home Assistant
event loop using ``hass.async_add_executor_job``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
import copy
import json
import os
import tempfile
import uuid


class MetadataError(Exception):
    """Base error raised for metadata operations."""


class HomeAlreadyClaimedError(MetadataError):
    """Raised when another integration instance already claimed a home."""


class TVNotFoundError(MetadataError):
    """Raised when a TV cannot be located in metadata."""


DEFAULT_METADATA = {
    "version": "1.0",
    "images": {},
    "tvs": [],
    "tags": [],
    "homes": {},
}


@dataclass(frozen=True)
class HomeClaim:
    """Represents the claim information for a home value."""

    home: str
    instance_id: str
    friendly_name: str
    is_new: bool


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _load_metadata(path: Path) -> Dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return copy.deepcopy(DEFAULT_METADATA)

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as err:
        raise MetadataError(f"Invalid metadata.json: {err}") from err

    if not isinstance(payload, dict):
        raise MetadataError("metadata.json must contain a JSON object")

    for key, default in DEFAULT_METADATA.items():
        if key in payload:
            continue
        if isinstance(default, (dict, list)):
            payload[key] = copy.deepcopy(default)
        else:
            payload[key] = default
    return payload


def _write_metadata(path: Path, data: Dict[str, Any]) -> None:
    _ensure_parent(path)
    # Write to a temporary file first to avoid corrupting metadata.json
    with tempfile.NamedTemporaryFile("w", dir=str(path.parent), delete=False, encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
        tmp_name = handle.name

    os.replace(tmp_name, path)


def _unique_list(items: Iterable[str]) -> List[str]:
    cleaned: List[str] = []
    seen = set()
    for item in items:
        if not item:
            continue
        candidate = item.strip()
        if not candidate:
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        cleaned.append(candidate)
    return cleaned


def _normalize_tv(home: str, tv: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(tv)
    normalized["home"] = home
    normalized["tags"] = _unique_list(normalized.get("tags", []))
    normalized["notTags"] = _unique_list(normalized.get("notTags", []))
    shuffle = normalized.get("shuffle") or {}
    if not isinstance(shuffle, dict):
        shuffle = {}
    normalized["shuffle"] = shuffle
    return normalized


def _add_tags_to_library(data: Dict[str, Any], *tag_sets: Iterable[str]) -> None:
    library = data.setdefault("tags", [])
    existing = set(library)
    for tags in tag_sets:
        for tag in tags:
            if tag and tag not in existing:
                library.append(tag)
                existing.add(tag)


class MetadataStore:
    """High-level helper around ``metadata.json``."""

    def __init__(self, metadata_path: Path) -> None:
        self._path = metadata_path

    @property
    def path(self) -> Path:
        return self._path

    # ---------------------------------------------------------------------
    # Home claim helpers
    # ---------------------------------------------------------------------
    def claim_home(self, home: str, instance_id: str, friendly_name: Optional[str] = None) -> HomeClaim:
        """Claim a home for this integration instance.

        Raises ``HomeAlreadyClaimedError`` if another instance already claimed
        the same home.
        """

        data = _load_metadata(self._path)
        homes = data.setdefault("homes", {})
        entry = homes.get(home)
        if entry:
            existing_id = entry.get("instance_id")
            if existing_id and existing_id != instance_id:
                raise HomeAlreadyClaimedError(
                    f"Home '{home}' is already claimed by another integration instance"
                )
            # Update friendly name for readability if provided
            if friendly_name:
                entry["friendly_name"] = friendly_name
            _write_metadata(self._path, data)
            return HomeClaim(home, instance_id, entry.get("friendly_name", home), is_new=False)

        homes[home] = {
            "instance_id": instance_id,
            "friendly_name": friendly_name or home,
        }
        _write_metadata(self._path, data)
        return HomeClaim(home, instance_id, friendly_name or home, is_new=True)

    # ------------------------------------------------------------------
    # TV access helpers
    # ------------------------------------------------------------------
    def list_tvs(self, home: str) -> List[Dict[str, Any]]:
        data = _load_metadata(self._path)
        return [tv for tv in data.get("tvs", []) if tv.get("home") == home]

    def generate_tv_id(self) -> str:
        return uuid.uuid4().hex

    def upsert_tv(self, home: str, tv: Dict[str, Any]) -> Dict[str, Any]:
        data = _load_metadata(self._path)
        tvs = data.setdefault("tvs", [])

        normalized = _normalize_tv(home, tv)
        tv_id = normalized.setdefault("id", self.generate_tv_id())

        updated = False
        for idx, existing in enumerate(tvs):
            if existing.get("id") == tv_id:
                tvs[idx] = {**existing, **normalized}
                updated = True
                break

        if not updated:
            tvs.append(normalized)

        _add_tags_to_library(data, normalized.get("tags", []), normalized.get("notTags", []))

        _write_metadata(self._path, data)
        return normalized

    def remove_tv(self, home: str, tv_id: str) -> None:
        data = _load_metadata(self._path)
        tvs = data.setdefault("tvs", [])
        remaining = [tv for tv in tvs if not (tv.get("home") == home and tv.get("id") == tv_id)]
        if len(remaining) == len(tvs):
            raise TVNotFoundError(f"TV {tv_id} not found for home {home}")
        data["tvs"] = remaining
        _write_metadata(self._path, data)

    def get_tv(self, home: str, tv_id: str) -> Dict[str, Any]:
        for tv in self.list_tvs(home):
            if tv.get("id") == tv_id:
                return tv
        raise TVNotFoundError(f"TV {tv_id} not found for home {home}")


def normalize_mac(mac: Optional[str]) -> Optional[str]:
    """Normalize MAC address to lowercase colon-separated form.

    Returns ``None`` when the input is invalid or empty.
    """

    if not mac or not isinstance(mac, str):
        return None

    cleaned = "".join(ch for ch in mac if ch in "0123456789abcdefABCDEF")
    if len(cleaned) != 12:
        return None
    pairs = [cleaned[i : i + 2] for i in range(0, 12, 2)]
    return ":".join(pair.lower() for pair in pairs)
