"""Shuffle and upload helpers for Frame Art Shuffler.

This module centralizes all artwork uploads so we can enforce a per-TV
"only one upload at a time" guarantee. Any future feature that uploads an
image to a Frame TV **must** call :func:`async_guarded_upload` (either
directly or indirectly via :func:`async_shuffle_tv`) to ensure we never
run overlapping transfers for the same device.
"""
from __future__ import annotations

import functools
import json
import logging
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .activity import log_activity
from .config_entry import get_tv_config
from .const import DOMAIN
from .frame_tv import FrameArtError, set_art_on_tv_deleteothers

_LOGGER = logging.getLogger(__name__)

UploadWork = Callable[[], Awaitable[Any]]
SkipCallback = Callable[[], None]
StatusCallback = Callable[[str, str], None]


async def async_guarded_upload(
    hass: HomeAssistant,
    entry: Any,
    tv_id: str,
    action: str,
    work: UploadWork,
    on_skip: SkipCallback | None = None,
) -> Any:
    """Run an upload while preventing concurrent uploads for the same TV."""
    data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if not data:
        return await work()

    upload_flags: set[str] = data.setdefault("upload_in_progress", set())

    if tv_id in upload_flags:
        tv_config = get_tv_config(entry, tv_id) or {}
        tv_name = tv_config.get("name", tv_id)
        _LOGGER.info(
            "Skipping %s for %s: another upload is still running", action, tv_name
        )
        if on_skip:
            on_skip()
        return None

    upload_flags.add(tv_id)
    try:
        return await work()
    finally:
        upload_flags.discard(tv_id)


def _select_random_image(
    metadata_path: Path,
    include_tags: list[str],
    exclude_tags: list[str],
    current_image: str | None,
    tv_name: str,
) -> tuple[dict[str, Any] | None, int]:
    """Select a random eligible image for the given TV."""
    with open(metadata_path, "r", encoding="utf-8") as file:
        metadata = json.load(file)

    images = metadata.get("images", {})
    if not images:
        _LOGGER.warning("No images found in metadata for %s", tv_name)
        return None, 0

    eligible_images: list[dict[str, Any]] = []
    for filename, image_data in images.items():
        image_tags = set(image_data.get("tags", []))

        if include_tags and not any(tag in image_tags for tag in include_tags):
            continue
        if exclude_tags and any(tag in image_tags for tag in exclude_tags):
            continue

        image_data_with_name = {**image_data, "filename": filename}
        eligible_images.append(image_data_with_name)

    eligible_count = len(eligible_images)
    if not eligible_images:
        _LOGGER.warning(
            "No images matching tag criteria for %s (include: %s, exclude: %s)",
            tv_name,
            include_tags,
            exclude_tags,
        )
        return None, 0

    candidates = [img for img in eligible_images if img["filename"] != current_image]

    if not candidates:
        if eligible_count == 1:
            _LOGGER.info(
                "Only one image (%s) matches criteria for %s and it's already displayed."
                " No shuffle performed.",
                eligible_images[0]["filename"],
                tv_name,
            )
            return None, eligible_count
        _LOGGER.warning("No candidate images for %s after removing current image", tv_name)
        return None, eligible_count

    selected = random.choice(candidates)
    _LOGGER.info(
        "%s selected for TV %s from %d eligible images",
        selected["filename"],
        tv_name,
        eligible_count,
    )
    return selected, eligible_count


async def async_shuffle_tv(
    hass: HomeAssistant,
    entry: Any,
    tv_id: str,
    *,
    reason: str = "manual",
    skip_if_screen_off: bool = False,
    status_callback: StatusCallback | None = None,
) -> bool:
    """Shuffle a TV's artwork selection, enforcing the upload guard."""
    def _notify(status: str, message: str) -> None:
        if status_callback:
            status_callback(status, message)

    tv_config = get_tv_config(entry, tv_id)
    if not tv_config:
        _LOGGER.error("Cannot shuffle %s: TV config not found", tv_id)
        _notify("error", "TV config missing")
        return False

    tv_ip = tv_config.get("ip")
    if not tv_ip:
        _LOGGER.error("Cannot shuffle %s: missing IP address in config", tv_config.get("name", tv_id))
        _notify("error", "IP address missing")
        return False

    metadata_path = Path(entry.data.get("metadata_path", ""))
    if not metadata_path.exists():
        _LOGGER.error(
            "Cannot shuffle %s: metadata file not found at %s",
            tv_config.get("name", tv_id),
            metadata_path,
        )
        return False

    include_tags = tv_config.get("tags", [])
    exclude_tags = tv_config.get("exclude_tags", [])

    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    shuffle_cache = entry_data.setdefault("shuffle_cache", {})
    runtime_state = shuffle_cache.get(tv_id, {})
    current_image = runtime_state.get("current_image") or tv_config.get("current_image")
    tv_name = tv_config.get("name", tv_id)

    if skip_if_screen_off:
        status_cache = entry_data.get("tv_status_cache", {})
        screen_state = status_cache.get(tv_id, {}).get("screen_on")
        if screen_state is not True:
            if screen_state is False:
                message = "Shuffle skipped: screen is off"
            else:
                message = "Shuffle skipped: screen state unknown"
            log_activity(
                hass,
                entry.entry_id,
                tv_id,
                "shuffle_skipped",
                message,
            )
            _notify("skipped", message)
            return False

    try:
        selected_image, matching_count = await hass.async_add_executor_job(
            _select_random_image,
            metadata_path,
            include_tags,
            exclude_tags,
            current_image,
            tv_config.get("name", tv_id),
        )
    except Exception as err:  # pylint: disable=broad-except
        _LOGGER.error("Failed to select image for %s: %s", tv_name, err)
        _notify("error", f"Failed to select image: {err}")
        return False

    if not selected_image:
        return False

    image_filename = selected_image["filename"]
    image_path = metadata_path.parent / "library" / image_filename
    if not image_path.exists():
        _LOGGER.error(
            "Cannot shuffle %s: image file not found at %s",
            tv_name,
            image_path,
        )
        _notify("error", "Image file missing")
        return False

    image_matte = selected_image.get("matte")
    image_filter = selected_image.get("filter")
    if image_filter and isinstance(image_filter, str) and image_filter.lower() == "none":
        image_filter = None

    async def _perform_upload() -> bool:
        log_activity(
            hass,
            entry.entry_id,
            tv_id,
            "shuffle_initiated",
            f"Shuffling to {image_filename}...",
        )

        upload_func = functools.partial(
            set_art_on_tv_deleteothers,
            delete_others=True,
            matte=image_matte,
            photo_filter=image_filter,
        )

        await hass.async_add_executor_job(upload_func, tv_ip, str(image_path))

        timestamp = datetime.now(timezone.utc).isoformat()
        shuffle_cache[tv_id] = {
            "current_image": image_filename,
            "current_matte": image_matte,
            "current_filter": image_filter,
            "matching_image_count": matching_count,
            "last_shuffle_timestamp": timestamp,
        }

        log_activity(
            hass,
            entry.entry_id,
            tv_id,
            "shuffle",
            f"Shuffled to {image_filename}",
        )

        signal = f"{DOMAIN}_shuffle_{entry.entry_id}_{tv_id}"
        async_dispatcher_send(hass, signal)

        if coordinator := entry_data.get("coordinator"):
            await coordinator.async_set_active_image(tv_id, image_filename, is_shuffle=True)

        _notify("success", f"Shuffled to {image_filename}")
        return True

    def _on_skip() -> None:
        log_activity(
            hass,
            entry.entry_id,
            tv_id,
            "shuffle_skipped",
            "Shuffle skipped: upload already running",
        )
        _notify("skipped", "Another upload already running")

    try:
        result = await async_guarded_upload(
            hass,
            entry,
            tv_id,
            "shuffle",
            _perform_upload,
            _on_skip,
        )
    except FrameArtError as err:
        _LOGGER.error("Failed to upload %s to %s: %s", image_filename, tv_name, err)
        _notify("error", f"Upload failed: {err}")
        return False

    return bool(result)
