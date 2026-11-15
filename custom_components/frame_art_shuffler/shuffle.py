"""Shuffle and upload helpers for Frame Art Shuffler.

This module centralizes all artwork uploads so we can enforce a per-TV
"only one upload at a time" guarantee. Any future feature that uploads an
image to a Frame TV **must** call :func:`async_guarded_upload` (either
directly or indirectly via :func:`async_shuffle_tv`) to ensure we never
run overlapping transfers for the same device.
"""
from __future__ import annotations

import asyncio
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
from .config_entry import get_active_tagset_name, get_effective_tags, get_tag_weights, get_tv_config, get_weighting_type
from .const import DOMAIN
from .frame_tv import FrameArtError, set_art_on_tv_deleteothers
from .targets import is_tablet

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


def _build_tag_pools(
    images: dict[str, dict[str, Any]],
    include_tags: list[str],
    exclude_tags: list[str],
    tag_weights: dict[str, float],
) -> dict[str, list[dict[str, Any]]]:
    """Build per-tag image pools, assigning multi-tag images to highest-weight tag.
    
    Args:
        images: Dict of filename -> image data from metadata
        include_tags: Tags to include (from tagset)
        exclude_tags: Tags to exclude (from tagset)
        tag_weights: Dict of tag -> weight (missing = 1.0)
        
    Returns:
        Dict of tag -> list of eligible images for that tag
    """
    tag_pools: dict[str, list[dict[str, Any]]] = {tag: [] for tag in include_tags}
    
    for filename, image_data in images.items():
        image_tags = set(image_data.get("tags", []))
        
        # Skip if image has any exclude tag
        if exclude_tags and any(tag in image_tags for tag in exclude_tags):
            continue
        
        # Find which include tags this image matches
        matching_tags = [tag for tag in include_tags if tag in image_tags]
        
        if not matching_tags:
            continue
        
        # Assign to highest-weight tag (ties: first in tagset order, which is include_tags order)
        best_tag = max(matching_tags, key=lambda t: (tag_weights.get(t, 1.0), -include_tags.index(t)))
        
        image_with_name = {**image_data, "filename": filename}
        tag_pools[best_tag].append(image_with_name)
    
    return tag_pools


def _shown_this_round(history: list[str], pool: set[str]) -> set[str]:
    """Pictures of ``pool`` already shown in the current round of an override.

    ``history`` is every picture shuffled onto this screen since the override began,
    oldest first. A round ends when every picture in the pool has shown once, and the
    next round starts empty. Pictures outside the pool are ignored; one added to the
    pool during a round has simply not shown yet.
    """
    shown: set[str] = set()
    for filename in history:
        if filename in pool:
            shown.add(filename)
            if len(shown) == len(pool):
                shown = set()
    return shown


def _choose(
    candidates: list[dict[str, Any]],
    pool: set[str],
    recent_images: set[str] | None,
    round_history: list[str] | None,
    avoid: set[str] | None,
) -> tuple[dict[str, Any], int, bool, int | None]:
    """Pick one of ``candidates`` (the pool without the picture on screen).

    Outside an override (``round_history`` is None) this is the recency preference:
    a picture not in ``recent_images`` if there is one, else any candidate.

    During an override the pool is shown in rounds: a picture shown in the current
    round waits until every other picture in the pool has shown, and when a round
    is complete the next one begins. Two softer preferences follow, each dropped if
    it would leave nothing: not one of the pool's last ``len(pool) // 2`` showings
    (so a round's first pictures are not its predecessor's last ones), and not a
    picture another screen shows now (``avoid``).

    Returns (selected, fresh_count, used_fallback, round_position): ``fresh_count``
    counts the candidates preferred (not recent, or not yet shown this round);
    ``used_fallback`` is True when none were (all recent, or a new round began
    because only the picture on screen was left); ``round_position`` is the pick's
    place in its round (1 = the round's first), None outside an override.
    """
    if round_history is None:
        if recent_images:
            fresh = [img for img in candidates if img["filename"] not in recent_images]
        else:
            fresh = []
        if fresh:
            return random.choice(fresh), len(fresh), False, None
        return random.choice(candidates), 0, bool(recent_images), None

    shown = _shown_this_round(round_history, pool)
    fresh = [img for img in candidates if img["filename"] not in shown]
    new_round = not fresh
    if new_round:
        fresh = candidates

    spacing = len(pool) // 2
    pool_history = [filename for filename in round_history if filename in pool]
    last_shown = set(pool_history[-spacing:]) if spacing else set()
    spaced = [img for img in fresh if img["filename"] not in last_shown] or fresh
    apart = [img for img in spaced if img["filename"] not in (avoid or set())] or spaced

    position = 1 if new_round else len(shown) + 1
    return random.choice(apart), len(fresh), new_round, position


def _select_random_image(
    metadata_path: Path,
    include_tags: list[str],
    exclude_tags: list[str],
    tag_weights: dict[str, float],
    weighting_type: str,
    current_image: str | None,
    tv_name: str,
    recent_images: set[str] | None = None,
    round_history: list[str] | None = None,
    avoid: set[str] | None = None,
) -> tuple[dict[str, Any] | None, int, str | None, int, bool, int, int | None]:
    """Select a random eligible image.

    Two modes based on weighting_type:
    - "image": All eligible images weighted equally (original behavior)
    - "tag": Tags weighted (equal by default), then random image from selected tag

    Recency preference: If recent_images is provided, prefers images not in that set.
    Falls back to full candidate pool if all candidates are recent.

    Override rounds: If round_history is provided (the pictures shuffled onto this
    screen since its tagset override began, oldest first), the chosen pool (the tag's,
    or every eligible picture without tag weighting) is shown in rounds; see _choose.
    recent_images is then ignored.

    Args:
        metadata_path: Path to metadata.json
        include_tags: Tags to include (from tagset)
        exclude_tags: Tags to exclude (from tagset)
        tag_weights: Dict of tag -> weight (only used when weighting_type="tag")
        weighting_type: "image" or "tag"
        current_image: Currently displayed image filename (to exclude)
        tv_name: TV name for logging
        recent_images: Set of filenames recently shown (for recency preference)
        round_history: Pictures shown since the override began (override rounds)
        avoid: Pictures other screens show now (override rounds only)

    Returns:
        Tuple of (selected_image_dict, eligible_count, selected_tag_name, fresh_count,
        used_fallback, pool_size, round_position)
        - selected_image_dict: The chosen image, or None if no eligible images
        - eligible_count: Total number of eligible images
        - selected_tag_name: Only populated in "tag" weighting mode
        - fresh_count: Number of non-recent candidates (0 if recency not applied);
          during an override, the candidates not yet shown this round
        - used_fallback: True if recency preference couldn't be applied (all recent);
          during an override, True when a new round began early
        - pool_size: Pictures in the pool the pick came from (the tag's pool in "tag" mode)
        - round_position: The pick's place in its round, None outside an override
    """
    with open(metadata_path, "r", encoding="utf-8") as file:
        metadata = json.load(file)

    images = metadata.get("images", {})
    if not images:
        _LOGGER.warning("No images found in metadata for %s", tv_name)
        return None, 0, None, 0, False, 0, None

    # Handle case where no include tags means "all images" (image-weighted flat selection)
    if not include_tags:
        eligible_images: list[dict[str, Any]] = []
        for filename, image_data in images.items():
            image_tags = set(image_data.get("tags", []))
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
            return None, 0, None, 0, False, 0, None

        candidates = [img for img in eligible_images if img["filename"] != current_image]
        if not candidates:
            if eligible_count == 1:
                _LOGGER.info(
                    "Only one image (%s) matches criteria for %s and it's already displayed."
                    " No shuffle performed.",
                    eligible_images[0]["filename"],
                    tv_name,
                )
                return None, eligible_count, None, 0, False, 0, None
            _LOGGER.warning("No candidate images for %s after removing current image", tv_name)
            return None, eligible_count, None, 0, False, 0, None

        # Apply recency preference (or the override's rounds)
        pool = {img["filename"] for img in eligible_images}
        selected, fresh_count, used_fallback, round_position = _choose(
            candidates, pool, recent_images, round_history, avoid
        )

        _LOGGER.info(
            "%s selected for TV %s from %d eligible images (no tag filtering, %d fresh)",
            selected["filename"],
            tv_name,
            eligible_count,
            fresh_count,
        )
        return selected, eligible_count, None, fresh_count, used_fallback, len(pool), round_position

    # IMAGE-WEIGHTED MODE: All eligible images have equal probability
    if weighting_type == "image":
        eligible_images = []
        for filename, image_data in images.items():
            image_tags = set(image_data.get("tags", []))

            # Must have at least one include tag
            if not any(tag in image_tags for tag in include_tags):
                continue

            # Must not have any exclude tag
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
            return None, 0, None, 0, False, 0, None

        candidates = [img for img in eligible_images if img["filename"] != current_image]
        if not candidates:
            if eligible_count == 1:
                _LOGGER.info(
                    "Only one image (%s) matches criteria for %s and it's already displayed."
                    " No shuffle performed.",
                    eligible_images[0]["filename"],
                    tv_name,
                )
                return None, eligible_count, None, 0, False, 0, None
            _LOGGER.warning("No candidate images for %s after removing current image", tv_name)
            return None, eligible_count, None, 0, False, 0, None

        # Apply recency preference (or the override's rounds)
        pool = {img["filename"] for img in eligible_images}
        selected, fresh_count, used_fallback, round_position = _choose(
            candidates, pool, recent_images, round_history, avoid
        )

        _LOGGER.info(
            "%s selected for TV %s from %d eligible images (image-weighted, %d fresh)",
            selected["filename"],
            tv_name,
            eligible_count,
            fresh_count,
        )
        return selected, eligible_count, None, fresh_count, used_fallback, len(pool), round_position

    # TAG-WEIGHTED MODE: Select tag first (by weight), then random image from that tag
    # Build per-tag pools
    tag_pools = _build_tag_pools(images, include_tags, exclude_tags, tag_weights)

    # Calculate total eligible count (unique images across all pools)
    all_eligible = set()
    for pool in tag_pools.values():
        for img in pool:
            all_eligible.add(img["filename"])
    eligible_count = len(all_eligible)

    if eligible_count == 0:
        _LOGGER.warning(
            "No images matching tag criteria for %s (include: %s, exclude: %s)",
            tv_name,
            include_tags,
            exclude_tags,
        )
        return None, 0, None, 0, False, 0, None

    # Weighted tag selection with re-roll on empty
    remaining_tags = list(include_tags)  # Copy to avoid modifying original
    selected_tag: str | None = None
    candidates: list[dict[str, Any]] = []

    while remaining_tags and not candidates:
        # Calculate weights for remaining tags
        weights = [tag_weights.get(tag, 1.0) for tag in remaining_tags]
        total_weight = sum(weights)

        if total_weight <= 0:
            break

        # Weighted random selection
        roll = random.random() * total_weight
        cumulative = 0.0
        selected_tag = remaining_tags[0]  # Default fallback

        for tag, weight in zip(remaining_tags, weights):
            cumulative += weight
            if roll <= cumulative:
                selected_tag = tag
                break

        # Get candidates from selected tag's pool (excluding current image)
        pool = tag_pools.get(selected_tag, [])
        candidates = [img for img in pool if img["filename"] != current_image]

        if not candidates:
            if pool:
                # Pool has images but all are current_image
                _LOGGER.info(
                    "Tag '%s' rolled for %s but only contains current image, re-rolling",
                    selected_tag,
                    tv_name,
                )
            else:
                # Pool is empty
                _LOGGER.info(
                    "Tag '%s' rolled for %s but has 0 eligible images, re-rolling",
                    selected_tag,
                    tv_name,
                )
            remaining_tags.remove(selected_tag)
            selected_tag = None

    if not candidates:
        if eligible_count == 1:
            _LOGGER.info(
                "Only one image matches criteria for %s and it's already displayed."
                " No shuffle performed.",
                tv_name,
            )
            return None, eligible_count, None, 0, False, 0, None
        _LOGGER.warning("No candidate images for %s after weighted selection", tv_name)
        return None, eligible_count, None, 0, False, 0, None

    # Apply recency preference (or the override's rounds) within the selected tag's candidates
    pool = {img["filename"] for img in tag_pools.get(selected_tag, [])}
    selected, fresh_count, used_fallback, round_position = _choose(
        candidates, pool, recent_images, round_history, avoid
    )

    # Calculate percentage for logging
    total_weight = sum(tag_weights.get(t, 1.0) for t in include_tags)
    tag_pct = round((tag_weights.get(selected_tag, 1.0) / total_weight) * 100) if total_weight > 0 else 0

    _LOGGER.info(
        "%s selected for TV %s (tag: %s, %d%%) from %d eligible, %d fresh in tag",
        selected["filename"],
        tv_name,
        selected_tag,
        tag_pct,
        eligible_count,
        fresh_count,
    )
    return selected, eligible_count, selected_tag, fresh_count, used_fallback, len(pool), round_position


async def async_shuffle_tv(
    hass: HomeAssistant,
    entry: Any,
    tv_id: str,
    *,
    reason: str = "manual",
    skip_if_screen_off: bool = False,
    status_callback: StatusCallback | None = None,
    recent_images: set[str] | None = None,
    round_history: list[str] | None = None,
) -> bool:
    """Shuffle a TV's artwork selection, enforcing the upload guard.

    ``round_history`` (during a tagset override) is the list of pictures shuffled onto
    this screen since the override began, oldest first; the pick then follows the
    override's rounds (see ``_choose``) instead of the recency preference.
    """
    def _notify(status: str, message: str) -> None:
        if status_callback:
            status_callback(status, message)

    # Get TV name early for error logging (fallback to tv_id if not available)
    tv_config = get_tv_config(entry, tv_id)
    tv_name = tv_config.get("name", tv_id) if tv_config else tv_id

    try:
        return await _async_shuffle_tv_inner(
            hass, entry, tv_id, tv_config, tv_name, reason, skip_if_screen_off, _notify,
            recent_images, round_history,
        )
    except Exception as err:  # pylint: disable=broad-except
        _LOGGER.error("Shuffle failed for %s: %s", tv_name, err)
        log_activity(
            hass,
            entry.entry_id,
            tv_id,
            "shuffle_failed",
            f"Shuffle failed: {err}",
        )
        _notify("error", f"Shuffle failed: {err}")
        return False


async def _async_shuffle_tv_inner(
    hass: HomeAssistant,
    entry: Any,
    tv_id: str,
    tv_config: dict[str, Any] | None,
    tv_name: str,
    reason: str,
    skip_if_screen_off: bool,
    _notify: Callable[[str, str], None],
    recent_images: set[str] | None = None,
    round_history: list[str] | None = None,
) -> bool:
    """Inner implementation of shuffle - exceptions bubble up to caller."""
    if not tv_config:
        raise FrameArtError(f"TV config not found for {tv_id}")

    # A wall tablet is never contacted: its pick is recorded and read through its image entity.
    tablet = is_tablet(tv_config)
    tv_ip = tv_config.get("ip")
    if not tablet and not tv_ip:
        raise FrameArtError(f"Missing IP address in config for {tv_name}")

    metadata_path = Path(entry.data.get("metadata_path", ""))
    if not metadata_path.exists():
        raise FrameArtError(f"Metadata file not found at {metadata_path}")

    # Use effective tags (resolves tagsets from global tagsets)
    include_tags, exclude_tags = get_effective_tags(entry, tv_id)
    tag_weights = get_tag_weights(entry, tv_id)
    weighting_type = get_weighting_type(entry, tv_id)

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

    # During an override, the pictures the other screens show now (the rounds' last preference).
    avoid: set[str] | None = None
    if round_history is not None:
        avoid = set()
        for other_id, other_config in (entry.data.get("tvs") or {}).items():
            if other_id == tv_id:
                continue
            other_image = shuffle_cache.get(other_id, {}).get("current_image") or other_config.get("current_image")
            if other_image:
                avoid.add(other_image)

    (
        selected_image,
        matching_count,
        selected_tag,
        fresh_count,
        used_fallback,
        pool_size,
        round_position,
    ) = await hass.async_add_executor_job(
        _select_random_image,
        metadata_path,
        include_tags,
        exclude_tags,
        tag_weights,
        weighting_type,
        current_image,
        tv_name,
        recent_images,
        round_history,
        avoid,
    )

    if not selected_image:
        # No eligible images - this is not an error, just nothing to do
        return False

    image_filename = selected_image["filename"]
    image_path = metadata_path.parent / "library" / image_filename
    if not image_path.exists():
        raise FrameArtError(f"Image file missing: {image_filename}")

    image_matte = selected_image.get("matte")
    image_filter = selected_image.get("filter")
    if image_filter and isinstance(image_filter, str) and image_filter.lower() == "none":
        image_filter = None
    if tablet:
        # Mattes and filters are Frame TV features.
        image_matte = None
        image_filter = None

    async def _perform_upload() -> bool:
        upload_func = functools.partial(
            set_art_on_tv_deleteothers,
            delete_others=True,
            matte=image_matte,
            photo_filter=image_filter,
        )

        if not tablet:
            await hass.async_add_executor_job(upload_func, tv_ip, str(image_path))

        now = datetime.now(timezone.utc)
        timestamp = now.isoformat()
        shuffle_cache[tv_id] = {
            "current_image": image_filename,
            "current_matte": image_matte,
            "current_filter": image_filter,
            "matching_image_count": matching_count,
            "last_shuffle_timestamp": timestamp,
            "selected_tag": selected_tag,
        }

        # Build activity message with recency (or round) and tag info
        if round_position is not None:
            tag_part = f"tag: {selected_tag}, " if selected_tag else ""
            activity_msg = (
                f"Shuffled to {image_filename} ({tag_part}{round_position} of {pool_size} this round)"
            )
        elif selected_tag:
            if used_fallback:
                activity_msg = f"Shuffled to {image_filename} (tag: {selected_tag}, all in tag were recent)"
            elif fresh_count > 0:
                activity_msg = f"Shuffled to {image_filename} (tag: {selected_tag}, from {fresh_count} fresh in tag)"
            else:
                activity_msg = f"Shuffled to {image_filename} (tag: {selected_tag})"
        else:
            if used_fallback:
                activity_msg = f"Shuffled to {image_filename} (all {matching_count} eligible were recent, picked randomly)"
            elif fresh_count > 0:
                activity_msg = f"Shuffled to {image_filename} (from {fresh_count} fresh of {matching_count} eligible)"
            else:
                activity_msg = f"Shuffled to {image_filename}"

        log_activity(
            hass,
            entry.entry_id,
            tv_id,
            "shuffle",
            activity_msg,
        )

        signal = f"{DOMAIN}_shuffle_{entry.entry_id}_{tv_id}"
        async_dispatcher_send(hass, signal)

        if coordinator := entry_data.get("coordinator"):
            await coordinator.async_set_active_image(tv_id, image_filename, is_shuffle=True)

        display_log = entry_data.get("display_log")
        if display_log:
            tagset_name = get_active_tagset_name(entry, tv_id)
            # Pass pool stats for sparkline history (only for auto-shuffle with recency enabled)
            # Skip recording when recent_images is None (e.g., during tagset overrides)
            pool_size_arg = matching_count if reason == "auto" and recent_images is not None else None
            pool_available_arg = fresh_count if reason == "auto" and recent_images is not None else None
            display_log.note_display_start(
                tv_id=tv_id,
                tv_name=tv_name,
                filename=image_filename,
                tags=list(selected_image.get("tags", [])),
                source="shuffle",
                shuffle_mode=reason,
                started_at=now,
                tv_tags=include_tags if include_tags else None,
                matte=image_matte,
                photo_filter=image_filter,
                tagset_name=tagset_name,
                pool_size=pool_size_arg,
                pool_available=pool_available_arg,
            )

        _notify("success", f"Shuffled to {image_filename}")
        
        # Sync brightness after shuffle to ensure TV has correct brightness
        # This helps recover from cases where brightness was set but TV didn't apply it
        async_sync_brightness = entry_data.get("async_sync_brightness_after_shuffle")
        if async_sync_brightness and not tablet:
            try:
                await async_sync_brightness(tv_id)
            except Exception as err:
                # Don't fail the shuffle if brightness sync fails - it's logged separately
                _LOGGER.warning(f"Post-shuffle brightness sync failed for {tv_name}: {err}")
        
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

    max_attempts = 2
    retry_delay_seconds = 60

    for attempt in range(1, max_attempts + 1):
        try:
            result = await async_guarded_upload(
                hass,
                entry,
                tv_id,
                "shuffle",
                _perform_upload,
                _on_skip,
            )
            return bool(result)
        except (FrameArtError, Exception) as err:  # pylint: disable=broad-except
            if attempt < max_attempts:
                _LOGGER.warning(
                    "Shuffle attempt %d/%d failed for %s to %s: %s. Retrying in %ds...",
                    attempt,
                    max_attempts,
                    image_filename,
                    tv_name,
                    err,
                    retry_delay_seconds,
                )
                await asyncio.sleep(retry_delay_seconds)
            else:
                # Re-raise so outer handler logs it
                raise FrameArtError(
                    f"Upload failed for {image_filename} after {max_attempts} attempts: {err}"
                ) from err

    return False
