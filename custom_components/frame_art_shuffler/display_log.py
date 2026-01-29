"""Activity log manager for Frame Art display sessions."""
from __future__ import annotations

import asyncio
import calendar
import contextlib
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    CONF_LOG_FLUSH_MINUTES,
    CONF_LOG_RETENTION_MONTHS,
    CONF_LOGGING_ENABLED,
    DEFAULT_LOG_FLUSH_MINUTES,
    DEFAULT_LOG_RETENTION_MONTHS,
    DEFAULT_LOGGING_ENABLED,
    LOG_EVENTS_FILENAME,
    LOG_STORAGE_RELATIVE_PATH,
    LOG_SUMMARY_FILENAME,
    LOG_TAG_NONE,
)

_LOGGER = logging.getLogger(__name__)

SUMMARY_VERSION = 1
PENDING_FILENAME = "pending.json"
MIN_FLUSH_MINUTES = 1
MIN_RETENTION_MONTHS = 1
MAX_RETENTION_MONTHS = 12


@dataclass(slots=True)
class DisplaySession:
    """Single display session that can be persisted to disk."""

    tv_id: str
    tv_name: str
    filename: str
    duration_seconds: int
    completed_at: datetime
    started_at: datetime | None = None
    tags: list[str] = field(default_factory=list)
    source: str = "shuffle"
    shuffle_mode: str | None = None
    matched_tags: list[str] | None = None  # intersection with TV's configured tags
    matte: str | None = None
    photo_filter: str | None = None
    tagset_name: str | None = None  # active tagset name when this display occurred
    pool_size: int | None = None  # total images in pool at shuffle time
    pool_available: int | None = None  # fresh images available at shuffle time

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-friendly dict."""
        result = {
            "tv_id": self.tv_id,
            "tv_name": self.tv_name,
            "filename": self.filename,
            "duration_seconds": self.duration_seconds,
            "completed_at": self.completed_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "tags": self.tags,
            "source": self.source,
            "shuffle_mode": self.shuffle_mode,
            "matched_tags": self.matched_tags,
            "matte": self.matte,
            "photo_filter": self.photo_filter,
            "tagset_name": self.tagset_name,
        }
        # Only include pool stats if present (for auto-shuffle events)
        if self.pool_size is not None:
            result["pool_size"] = self.pool_size
        if self.pool_available is not None:
            result["pool_available"] = self.pool_available
        return result

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DisplaySession":
        """Create a DisplaySession from stored JSON."""
        completed = _parse_timestamp(payload.get("completed_at"))
        started = _parse_timestamp(payload.get("started_at"))
        if completed is None:
            raise ValueError("completed_at timestamp missing from stored session")
        return cls(
            tv_id=payload.get("tv_id", "unknown"),
            tv_name=payload.get("tv_name", "Frame TV"),
            filename=payload.get("filename", "unknown"),
            duration_seconds=int(payload.get("duration_seconds", 0)),
            completed_at=completed,
            started_at=started,
            tags=list(payload.get("tags", [])),
            source=payload.get("source", "shuffle"),
            shuffle_mode=payload.get("shuffle_mode"),
            matched_tags=payload.get("matched_tags"),
            matte=payload.get("matte"),
            photo_filter=payload.get("photo_filter"),
            tagset_name=payload.get("tagset_name"),
            pool_size=payload.get("pool_size"),
            pool_available=payload.get("pool_available"),
        )


@dataclass(slots=True)
class _ActiveDisplay:
    """Tracks the image currently on-screen for a TV."""

    filename: str
    tags: list[str]
    started_at: datetime
    source: str
    shuffle_mode: str | None
    tv_name: str
    matched_tags: list[str] | None = None  # intersection with TV's configured tags
    matte: str | None = None
    photo_filter: str | None = None
    tagset_name: str | None = None  # active tagset name when this display started
    pool_size: int | None = None  # total images in pool at shuffle time
    pool_available: int | None = None  # fresh images available at shuffle time


class DisplayLogManager:
    """Coordinates buffered logging, periodic flush, and summary output."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._hass = hass
        self._entry = entry
        self._base_path = Path(hass.config.path(LOG_STORAGE_RELATIVE_PATH))
        self._events_path = self._base_path / LOG_EVENTS_FILENAME
        self._summary_path = self._base_path / LOG_SUMMARY_FILENAME
        self._pending_path = self._base_path / PENDING_FILENAME

        self._enabled = _coerce_bool(
            entry.options.get(CONF_LOGGING_ENABLED, DEFAULT_LOGGING_ENABLED)
        )
        self._retention_months = _clamp(
            int(entry.options.get(CONF_LOG_RETENTION_MONTHS, DEFAULT_LOG_RETENTION_MONTHS)),
            MIN_RETENTION_MONTHS,
            MAX_RETENTION_MONTHS,
        )
        self._flush_minutes = max(
            MIN_FLUSH_MINUTES,
            int(entry.options.get(CONF_LOG_FLUSH_MINUTES, DEFAULT_LOG_FLUSH_MINUTES)),
        )

        self._queue: list[DisplaySession] = []
        self._flush_unsub: Callable[[], None] | None = None
        self._pending_save_task: asyncio.Task[None] | None = None
        self._active_sessions: dict[str, _ActiveDisplay] = {}
        self._ready = False

    async def async_setup(self) -> None:
        """Prepare storage and start the periodic flush timer."""
        if self._ready:
            return
        self._ready = True

        if not self._enabled:
            _LOGGER.debug("Display logging disabled for entry %s", self._entry.entry_id)
            return

        await self._hass.async_add_executor_job(
            lambda: self._base_path.mkdir(parents=True, exist_ok=True)
        )
        await self._load_pending_buffer()
        self._schedule_flush_timer()

    async def async_shutdown(self) -> None:
        """Cancel callbacks and flush any pending events."""
        self._cancel_flush_timer()
        if self._pending_save_task:
            await asyncio.shield(self._pending_save_task)
        await self.async_finalize_active_sessions()

    def update_settings(
        self,
        *,
        enabled: bool | None = None,
        retention_months: int | None = None,
        flush_minutes: int | None = None,
    ) -> None:
        """Update runtime settings from options flow changes."""
        prev_enabled = self._enabled
        prev_interval = self._flush_minutes

        if enabled is not None:
            self._enabled = _coerce_bool(enabled)
        if retention_months is not None:
            self._retention_months = _clamp(
                int(retention_months), MIN_RETENTION_MONTHS, MAX_RETENTION_MONTHS
            )
        if flush_minutes is not None:
            self._flush_minutes = max(MIN_FLUSH_MINUTES, int(flush_minutes))

        if not self._ready:
            return

        if prev_enabled and not self._enabled:
            self._cancel_flush_timer()
            self._active_sessions.clear()
        elif not prev_enabled and self._enabled:
            self._schedule_flush_timer()
        elif self._enabled and prev_interval != self._flush_minutes:
            self._schedule_flush_timer()

    def note_display_start(
        self,
        *,
        tv_id: str,
        tv_name: str,
        filename: str,
        tags: list[str],
        source: str,
        shuffle_mode: str | None = None,
        started_at: datetime | None = None,
        tv_tags: list[str] | None = None,
        matte: str | None = None,
        photo_filter: str | None = None,
        tagset_name: str | None = None,
        pool_size: int | None = None,
        pool_available: int | None = None,
    ) -> None:
        """Update the active display state and capture the previous session.

        Args:
            tv_id: The TV's unique identifier.
            tv_name: Human-readable TV name.
            filename: The image filename being displayed.
            tags: All tags on the image.
            source: How the display was triggered (e.g., "shuffle").
            shuffle_mode: The shuffle mode used (e.g., "random").
            started_at: Override timestamp (defaults to now).
            tv_tags: The TV's configured include_tags. If provided, matched_tags
                will be computed as the intersection of image tags and TV tags.
                This allows per-TV statistics to only count tags relevant to that TV.
            matte: The matte style applied to the image (e.g., "flexible_warm").
            photo_filter: The photo filter applied to the image.
            tagset_name: The name of the active tagset when this display started.
            pool_size: Total images in the pool at shuffle time (for pool health tracking).
            pool_available: Fresh images available at shuffle time (for pool health tracking).
        """
        if not self._ready or not self._enabled:
            self._active_sessions.pop(tv_id, None)
            return

        now = started_at or datetime.now(timezone.utc)
        previous = self._active_sessions.get(tv_id)
        if previous:
            self._record_completed_session(tv_id, previous, now)

        # Compute intersection of image tags and TV's configured tags
        matched_tags: list[str] | None = None
        if tv_tags is not None and tags:
            matched_tags = [t for t in tags if t in tv_tags]

        self._active_sessions[tv_id] = _ActiveDisplay(
            filename=filename,
            tags=list(tags or []),
            started_at=now,
            source=source,
            shuffle_mode=shuffle_mode,
            tv_name=tv_name,
            matched_tags=matched_tags,
            matte=matte,
            photo_filter=photo_filter,
            tagset_name=tagset_name,
            pool_size=pool_size,
            pool_available=pool_available,
        )

    def note_screen_off(
        self,
        *,
        tv_id: str,
        tv_name: str,
        ended_at: datetime | None = None,
    ) -> None:
        """Record end of display session when screen turns off.

        Completes the current active session (if any) and clears it so no time
        accumulates while the screen is off. The same image may generate multiple
        session entries if the screen cycles on/off.

        Args:
            tv_id: The TV's unique identifier.
            tv_name: Human-readable TV name (for logging).
            ended_at: Override timestamp (defaults to now).
        """
        if not self._ready or not self._enabled:
            self._active_sessions.pop(tv_id, None)
            return

        active = self._active_sessions.pop(tv_id, None)
        if not active:
            return

        now = ended_at or datetime.now(timezone.utc)
        self._record_completed_session(tv_id, active, now)
        _LOGGER.debug(
            "Display log: Closed session for %s on %s (screen off)",
            active.filename,
            tv_name,
        )

    def note_screen_on(
        self,
        *,
        tv_id: str,
        tv_name: str,
        filename: str | None = None,
        tags: list[str] | None = None,
        tv_tags: list[str] | None = None,
        started_at: datetime | None = None,
        matte: str | None = None,
        photo_filter: str | None = None,
        tagset_name: str | None = None,
    ) -> None:
        """Resume display tracking when screen turns on.

        If the same image is still showing (no shuffle), this starts a new session
        segment for that image. If filename is not provided and there's no active
        session, this is a no-op.

        Args:
            tv_id: The TV's unique identifier.
            tv_name: Human-readable TV name.
            filename: The image currently displayed (if known).
            tags: Image tags (if known).
            tv_tags: TV's configured include_tags for matched_tags computation.
            started_at: Override timestamp (defaults to now).
            matte: The matte style applied to the image (e.g., "flexible_warm").
            photo_filter: The photo filter applied to the image.
            tagset_name: The name of the active tagset when this display started.
        """
        if not self._ready or not self._enabled:
            return

        # Discard any existing session - if the screen is turning on, any existing
        # session is orphaned (e.g., created by a shuffle that completed after
        # screen-off). We intentionally do NOT record it since the duration would
        # include time when the screen was off.
        existing = self._active_sessions.pop(tv_id, None)
        if existing:
            _LOGGER.warning(
                "Display log: Discarding orphaned session for %s on %s "
                "(started %s, not recording)",
                existing.filename,
                tv_name,
                existing.started_at.isoformat(),
            )

        # If we don't know what image is showing, can't start tracking
        if not filename:
            _LOGGER.debug(
                "Display log: Screen on for %s but no image info, skipping",
                tv_name,
            )
            return

        now = started_at or datetime.now(timezone.utc)

        # Compute intersection of image tags and TV's configured tags
        matched_tags: list[str] | None = None
        if tv_tags is not None and tags:
            matched_tags = [t for t in tags if t in tv_tags]

        self._active_sessions[tv_id] = _ActiveDisplay(
            filename=filename,
            tags=list(tags or []),
            started_at=now,
            source="screen_on",  # Mark source as screen resumption
            shuffle_mode=None,
            tv_name=tv_name,
            matched_tags=matched_tags,
            matte=matte,
            photo_filter=photo_filter,
            tagset_name=tagset_name,
        )
        _LOGGER.debug(
            "Display log: Started new session for %s on %s (screen on)",
            filename,
            tv_name,
        )

    def record_session(self, session: DisplaySession) -> None:
        """Queue a new display session for persistence."""
        if not self._ready or not self._enabled:
            return

        self._queue.append(session)
        self._ensure_pending_write()

    async def async_flush(self, *, force: bool = False) -> None:
        """Persist queued events and rebuild the summary snapshot."""
        if not self._ready:
            return

        if not self._enabled and not force:
            return

        if not self._queue and not force:
            return

        payload = [session.to_dict() for session in self._queue]

        try:
            await self._hass.async_add_executor_job(
                self._persist_to_disk,
                payload,
                force,
            )
        except Exception:  # pragma: no cover - defensive logging
            _LOGGER.exception("Failed to flush Frame Art display log for %s", self._entry.entry_id)
            return

        self._queue.clear()
        await self._hass.async_add_executor_job(self._remove_pending_copy)

    async def _load_pending_buffer(self) -> None:
        sessions = await self._hass.async_add_executor_job(self._read_pending_file)
        if sessions:
            self._queue.extend(sessions)
            _LOGGER.debug(
                "Restored %s pending display sessions for entry %s",
                len(sessions),
                self._entry.entry_id,
            )

    def _ensure_pending_write(self) -> None:
        if self._pending_save_task and not self._pending_save_task.done():
            return
        self._pending_save_task = self._hass.async_create_task(self._async_write_pending())

    async def _async_write_pending(self) -> None:
        payload = [session.to_dict() for session in self._queue]
        try:
            await self._hass.async_add_executor_job(
                self._atomic_write_json,
                self._pending_path,
                payload,
            )
        except Exception:  # pragma: no cover - disk issues are rare
            _LOGGER.exception("Failed to persist pending Frame Art sessions for %s", self._entry.entry_id)

    def _persist_to_disk(self, new_sessions: list[dict[str, Any]], force: bool) -> None:
        self._base_path.mkdir(parents=True, exist_ok=True)
        existing_events = self._read_events_file()
        if new_sessions:
            existing_events.extend(new_sessions)

        trimmed_events = self._trim_events(existing_events)
        if not force and not new_sessions and len(trimmed_events) == len(existing_events):
            return

        self._atomic_write_json(self._events_path, trimmed_events)
        summary = self._build_summary(trimmed_events)
        self._atomic_write_json(self._summary_path, summary)

    def _read_events_file(self) -> list[dict[str, Any]]:
        if not self._events_path.exists():
            return []
        try:
            with self._events_path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            return list(data) if isinstance(data, list) else []
        except Exception:
            _LOGGER.exception("Failed to read Frame Art event log; recreating %s", self._events_path)
        return []

    def _read_pending_file(self) -> list[DisplaySession]:
        if not self._pending_path.exists():
            return []
        try:
            with self._pending_path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            sessions = [DisplaySession.from_dict(item) for item in payload or []]
            return sessions
        except Exception:
            _LOGGER.warning("Pending Frame Art log file corrupt; discarding %s", self._pending_path)
            self._pending_path.unlink(missing_ok=True)
            return []

    def _trim_events(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        cutoff = self._retention_cutoff()
        if not cutoff:
            return events

        trimmed: list[dict[str, Any]] = []
        for event in events:
            completed = _parse_timestamp(event.get("completed_at"))
            if not completed:
                continue
            if completed >= cutoff:
                trimmed.append(event)
        return trimmed

    def _build_summary(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        totals_seconds = 0
        totals_events = 0
        tvs: dict[str, Any] = {}
        images: dict[str, Any] = {}
        tags: dict[str, Any] = {}

        for event in events:
            duration = int(event.get("duration_seconds", 0))
            totals_seconds += max(duration, 0)
            totals_events += 1

            tv_id = event.get("tv_id", "unknown")
            tv_entry = tvs.setdefault(
                tv_id,
                {
                    "name": event.get("tv_name", tv_id),
                    "total_display_seconds": 0,
                    "event_count": 0,
                    "per_image": {},
                    "per_tag": {},
                },
            )
            tv_entry["total_display_seconds"] += duration
            tv_entry["event_count"] += 1

            filename = event.get("filename", "unknown")
            image_entry = images.setdefault(
                filename,
                {
                    "tags": event.get("tags", []),
                    "total_display_seconds": 0,
                    "event_count": 0,
                    "per_tv": {},
                },
            )
            image_entry["total_display_seconds"] += duration
            image_entry["event_count"] += 1

            normalized_tags = event.get("tags") or [LOG_TAG_NONE]
            for tag in normalized_tags:
                tag_entry = tags.setdefault(
                    tag,
                    {
                        "total_display_seconds": 0,
                        "event_count": 0,
                        "per_tv": {},
                        "top_images": {},
                    },
                )
                tag_entry["total_display_seconds"] += duration
                tag_entry["event_count"] += 1

                per_tv = tag_entry["per_tv"].setdefault(
                    tv_id,
                    {"seconds": 0, "event_count": 0},
                )
                per_tv["seconds"] += duration
                per_tv["event_count"] += 1

                top_images = tag_entry["top_images"].setdefault(
                    filename,
                    {"seconds": 0, "event_count": 0},
                )
                top_images["seconds"] += duration
                top_images["event_count"] += 1

            per_image = tv_entry["per_image"].setdefault(
                filename,
                {"seconds": 0, "event_count": 0},
            )
            per_image["seconds"] += duration
            per_image["event_count"] += 1

            # For per-TV tag stats, use matched_tags (intersection with TV's
            # configured tags) if available, otherwise fall back to all tags.
            # This gives per-TV views only the tags relevant to that TV.
            tv_tag_list = event.get("matched_tags")
            if tv_tag_list is None:
                tv_tag_list = normalized_tags
            else:
                tv_tag_list = tv_tag_list or [LOG_TAG_NONE]

            for tag in tv_tag_list:
                per_tag = tv_entry["per_tag"].setdefault(
                    tag,
                    {"seconds": 0, "event_count": 0},
                )
                per_tag["seconds"] += duration
                per_tag["event_count"] += 1

            per_tv = image_entry["per_tv"].setdefault(
                tv_id,
                {"seconds": 0, "event_count": 0},
            )
            per_tv["seconds"] += duration
            per_tv["event_count"] += 1

        summary = {
            "version": SUMMARY_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "retention_months": self._retention_months,
            "logging_enabled": self._enabled,
            "flush_interval_minutes": self._flush_minutes,
            "totals": {
                "tracked_seconds": totals_seconds,
                "event_count": totals_events,
            },
            "tvs": self._format_tv_summary(tvs, totals_seconds),
            "images": self._format_image_summary(images),
            "tags": self._format_tag_summary(tags),
        }
        return summary

    def _format_tv_summary(self, tvs: dict[str, Any], total_seconds: int) -> dict[str, Any]:
        formatted: dict[str, Any] = {}
        for tv_id, data in tvs.items():
            formatted[tv_id] = {
                "name": data["name"],
                "total_display_seconds": data["total_display_seconds"],
                "event_count": data["event_count"],
                "share_of_tracked": _percent(data["total_display_seconds"], total_seconds),
                "per_image": _collapse_dict(
                    data["per_image"],
                    "filename",
                    data["total_display_seconds"],
                ),
                "per_tag": _collapse_dict(
                    data["per_tag"],
                    "tag",
                    data["total_display_seconds"],
                ),
            }
        return formatted

    def _format_image_summary(self, images: dict[str, Any]) -> dict[str, Any]:
        formatted: dict[str, Any] = {}
        for filename, data in images.items():
            formatted[filename] = {
                "tags": data["tags"],
                "total_display_seconds": data["total_display_seconds"],
                "event_count": data["event_count"],
                "per_tv": _collapse_dict(
                    data["per_tv"],
                    "tv_id",
                    data["total_display_seconds"],
                ),
            }
        return formatted

    def _format_tag_summary(self, tags: dict[str, Any]) -> dict[str, Any]:
        formatted: dict[str, Any] = {}
        for tag, data in tags.items():
            formatted[tag] = {
                "total_display_seconds": data["total_display_seconds"],
                "event_count": data["event_count"],
                "per_tv": _collapse_dict(
                    data["per_tv"],
                    "tv_id",
                    data["total_display_seconds"],
                ),
                "top_images": _collapse_dict(
                    data["top_images"],
                    "filename",
                    data["total_display_seconds"],
                ),
            }
        return formatted

    def _schedule_flush_timer(self) -> None:
        self._cancel_flush_timer()
        if not self._enabled:
            return

        interval = timedelta(minutes=self._flush_minutes)

        async def _handle_interval(now: datetime) -> None:
            await self.async_flush()

        self._flush_unsub = async_track_time_interval(
            self._hass,
            _handle_interval,
            interval,
        )

    def _cancel_flush_timer(self) -> None:
        if self._flush_unsub:
            self._flush_unsub()
            self._flush_unsub = None

    def _remove_pending_copy(self) -> None:
        with contextlib.suppress(FileNotFoundError):
            os.remove(self._pending_path)

    def _atomic_write_json(self, path: Path, payload: Any) -> None:
        temp_path = path.with_suffix(".tmp")
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        os.replace(temp_path, path)

    def _retention_cutoff(self) -> datetime:
        now = datetime.now(timezone.utc)
        months = _clamp(self._retention_months, MIN_RETENTION_MONTHS, MAX_RETENTION_MONTHS)
        return _subtract_months(now, months)

    async def async_finalize_active_sessions(self) -> None:
        """Close out any in-progress sessions and flush to disk."""
        if not self._ready or not self._enabled:
            self._active_sessions.clear()
            return

        if not self._active_sessions:
            await self.async_flush(force=True)
            return

        now = datetime.now(timezone.utc)
        for tv_id, active in list(self._active_sessions.items()):
            self._record_completed_session(tv_id, active, now)
        self._active_sessions.clear()
        await self.async_flush(force=True)

    async def async_clear_logs(self) -> None:
        """Delete all log files and clear in-memory state."""
        # Clear in-memory state
        self._queue.clear()
        self._active_sessions.clear()

        # Delete log files
        def _delete_files() -> None:
            for path in [self._events_path, self._summary_path, self._pending_path]:
                with contextlib.suppress(FileNotFoundError):
                    os.remove(path)

        await self._hass.async_add_executor_job(_delete_files)
        _LOGGER.info("Display logs cleared for entry %s", self._entry.entry_id)

    def get_recent_auto_shuffle_images(
        self,
        tv_id: str | None = None,
        hours: int = 72,
    ) -> set[str]:
        """Get filenames of images shown via auto-shuffle in the last N hours.

        Used by the shuffle algorithm to prefer images that haven't been
        shown recently, improving perceived variety.

        Args:
            tv_id: TV identifier to filter by. If None, returns images from all TVs.
            hours: Lookback window (default 72)

        Returns:
            Set of filenames shown via auto-shuffle within the window.
            Returns empty set if logging is disabled or no events found.
        """
        if not self._ready or not self._enabled:
            return set()

        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        events = self._read_events_file()
        recent: set[str] = set()

        for event in events:
            # Filter by TV (skip filter if tv_id is None to get all TVs)
            if tv_id is not None and event.get("tv_id") != tv_id:
                continue

            # Filter by auto-shuffle source
            if event.get("source") != "shuffle":
                continue
            if event.get("shuffle_mode") != "auto":
                continue

            # Filter by time window
            completed = _parse_timestamp(event.get("completed_at"))
            if not completed or completed < cutoff:
                continue

            filename = event.get("filename")
            if filename:
                recent.add(filename)

        return recent

    def get_pool_health(
        self,
        tv_id: str,
        pool_filenames: set[str],
        same_tv_hours: int = 72,
        cross_tv_hours: int = 36,
    ) -> dict[str, Any]:
        """Calculate pool health metrics for a TV.

        Returns intuitive buckets for understanding pool availability:
        - same_tv_recent: Images shown on THIS TV within same_tv_hours
        - cross_tv_recent: Images shown on OTHER TVs within cross_tv_hours
          (excludes images already counted in same_tv_recent to avoid double-counting)
        - total_recent: Sum of same_tv_recent + cross_tv_recent
        - available: pool_size - total_recent

        Args:
            tv_id: TV identifier
            pool_filenames: Set of filenames in the TV's eligible pool (based on tagset)
            same_tv_hours: Same-TV recency window (default 72)
            cross_tv_hours: Cross-TV recency window (default 36)

        Returns:
            Dict with pool_size, same_tv_recent, cross_tv_recent, total_recent,
            available, same_tv_hours, cross_tv_hours
        """
        if not self._ready or not self._enabled:
            return {
                "pool_size": len(pool_filenames),
                "same_tv_recent": 0,
                "cross_tv_recent": 0,
                "total_recent": 0,
                "available": len(pool_filenames),
                "same_tv_hours": same_tv_hours,
                "cross_tv_hours": cross_tv_hours,
            }

        # Get recent images for this TV
        same_tv_recent = self.get_recent_auto_shuffle_images(
            tv_id=tv_id, hours=same_tv_hours
        )

        # Get recent images for ALL TVs (includes this TV)
        all_tv_recent = self.get_recent_auto_shuffle_images(
            tv_id=None, hours=cross_tv_hours
        )

        # Filter to only images in the pool
        same_tv_in_pool = same_tv_recent & pool_filenames
        all_tv_in_pool = all_tv_recent & pool_filenames

        # Cross-TV recent = images on other TVs, excluding this TV's images
        # (to avoid double-counting with same_tv_recent)
        cross_tv_in_pool = all_tv_in_pool - same_tv_in_pool

        # Total recent = union (same as same_tv + cross_tv since they're now mutually exclusive)
        total_recent = len(same_tv_in_pool) + len(cross_tv_in_pool)
        available = len(pool_filenames) - total_recent

        return {
            "pool_size": len(pool_filenames),
            "same_tv_recent": len(same_tv_in_pool),
            "cross_tv_recent": len(cross_tv_in_pool),
            "total_recent": total_recent,
            "available": available,
            "same_tv_hours": same_tv_hours,
            "cross_tv_hours": cross_tv_hours,
        }

    def get_pool_health_history(
        self,
        tv_id: str,
        hours: int = 24,
    ) -> list[dict[str, Any]]:
        """Get historical pool health data from recorded shuffle events.

        Returns pool_available and pool_size at each auto-shuffle event within
        the time window. This data is recorded at shuffle time, so it reflects
        the actual pool state when each shuffle occurred.

        Args:
            tv_id: TV identifier
            hours: Lookback window (default 24)

        Returns:
            List of dicts with timestamp, pool_size, pool_available, sorted oldest first.
            Returns empty list if logging is disabled or no events found.
        """
        if not self._ready or not self._enabled:
            return []

        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        events = self._read_events_file()
        history: list[dict[str, Any]] = []

        for event in events:
            # Filter by TV
            if event.get("tv_id") != tv_id:
                continue

            # Filter by auto-shuffle source
            if event.get("source") != "shuffle":
                continue
            if event.get("shuffle_mode") != "auto":
                continue

            # Filter by time window (use started_at if available, else completed_at)
            timestamp_str = event.get("started_at") or event.get("completed_at")
            timestamp = _parse_timestamp(timestamp_str)
            if not timestamp or timestamp < cutoff:
                continue

            # Only include events with pool data
            pool_size = event.get("pool_size")
            pool_available = event.get("pool_available")
            if pool_size is None or pool_available is None:
                continue

            history.append({
                "timestamp": timestamp.isoformat(),
                "pool_size": pool_size,
                "pool_available": pool_available,
            })

        # Sort by timestamp, oldest first
        history.sort(key=lambda x: x["timestamp"])
        return history

    def _record_completed_session(
        self,
        tv_id: str,
        active: _ActiveDisplay,
        completed_at: datetime,
    ) -> None:
        duration = int((completed_at - active.started_at).total_seconds())
        if duration <= 0:
            duration = 1

        session = DisplaySession(
            tv_id=tv_id,
            tv_name=active.tv_name,
            filename=active.filename,
            duration_seconds=duration,
            completed_at=completed_at,
            started_at=active.started_at,
            tags=active.tags,
            source=active.source,
            shuffle_mode=active.shuffle_mode,
            matched_tags=active.matched_tags,
            matte=active.matte,
            photo_filter=active.photo_filter,
            tagset_name=active.tagset_name,
            pool_size=active.pool_size,
            pool_available=active.pool_available,
        )
        self.record_session(session)


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "on", "yes"}
    return bool(value)


def _clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, value))


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(value)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.astimezone(timezone.utc)
    except Exception:
        return None


def _collapse_dict(
    source: dict[str, dict[str, int]],
    key_field: str,
    total_seconds: int | None,
) -> list[dict[str, Any]]:
    if total_seconds is None:
        total_seconds = sum(item.get("seconds", 0) for item in source.values())
    items: list[dict[str, Any]] = []
    for key, metrics in source.items():
        seconds = metrics.get("seconds", 0)
        record = {
            key_field: key,
            "seconds": seconds,
            "event_count": metrics.get("event_count", 0),
            "share": _percent(seconds, total_seconds),
        }
        items.append(record)
    items.sort(key=lambda item: item.get("seconds", 0), reverse=True)
    return items


def _percent(part: int, whole: int) -> float:
    if whole <= 0:
        return 0.0
    return round((part / whole) * 100, 2)


def _subtract_months(dt: datetime, months: int) -> datetime:
    year = dt.year
    month = dt.month - months
    while month <= 0:
        month += 12
        year -= 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)