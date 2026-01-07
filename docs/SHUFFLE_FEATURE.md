# Shuffle Image Feature

## Overview

Each Frame TV now has an on-demand "Auto-Shuffle Now" button *and* an optional auto-shuffle scheduler. Both paths use the same guarded upload pipeline so a TV never receives overlapping transfers, and both honor the TV's tag filtering preferences.

## How It Works

### Button Behavior

When you press the "Auto-Shuffle Now" button for a TV:

1. **Load images** from `metadata.json` in `/config/www/frame_art/`
2. **Filter by tags**:
   - Image must have at least one tag in the TV's `include_tags` (if any are set)
   - Image must NOT have any tag in the TV's `exclude_tags` (if any are set)
3. **Select randomly** from matching images, excluding the current image
4. **Upload** the selected image using `--delete-others` flag (removes all other images from TV)
5. **Update sensors** with the new image name and timestamp

Note: Manual button presses do not apply recency preference (see below). For recency-aware selection, use auto-shuffle.

### Auto Shuffle Scheduler

When the "Auto-Shuffle Enable" switch is turned on for a TV (or the option is enabled in the config flow), Home Assistant starts a dedicated timer for that TV:

1. **Frequency** comes from the `Shuffle Frequency` number entity (minutes). Changing the number immediately restarts the timer.
2. **Power-aware**: the scheduler relies on the existing `tv_status_cache`. If the screen is off *or* the power state is unknown, the shuffle is skipped, logged, and the next run is scheduled without waking the panel.
3. **Guarded uploads**: every scheduled shuffle calls `async_shuffle_tv(..., skip_if_screen_off=True)` so it reuses the same per-TV upload lock as the manual button and the `display_image` service.
4. **Health checks**: timers should always stay in the future. If the next scheduled time ever drifts into the past, the integration logs an `auto_shuffle_error`, records it in Recent Activity, and immediately reschedules.
5. **Next run + persistence**: the `auto_shuffle_next` sensor (see below) exposes the upcoming timestamp, and the same value is persisted in the config entry so it survives Home Assistant restarts. On startup the timer restarts from the saved timestamp instead of starting over.

When auto-shuffle is enabled, the manual button also routes through the scheduler. Pressing it immediately runs `async_run_auto_shuffle`, logs the outcome, and then restarts the timer so the next run remains frequency minutes in the future.

### Recency Preference (Auto-Shuffle Only)

Auto-shuffle applies a **recency preference** to avoid showing images that were recently displayed on the same TV. This creates a more varied viewing experience without requiring strict rotation.

**How it works:**

1. When auto-shuffle runs, the integration queries the display log for images shown on this TV via auto-shuffle in the last **48 hours**
2. These "recent" images are deprioritized in favor of "fresh" images
3. If fresh images are available, one is selected randomly from the fresh pool
4. If all eligible images are recent (small pool or high shuffle frequency), the algorithm falls back to the full candidate pool

**Key design decisions:**

- **48-hour window**: Based on human perception—after ~48 hours, you've likely forgotten you saw an image recently
- **Auto-shuffle only**: Manual displays (via button or service call) don't affect recency tracking. Only auto-scheduled shuffles are tracked and filtered
- **Soft preference**: Recency is preferred, not required. The algorithm never fails to select an image due to recency
- **Per-TV tracking**: Each TV maintains its own recency window, so the same image can show on different TVs

**Activity log messages reflect recency:**

```
Shuffled to sunset.jpg (from 12 fresh of 25 eligible)
Shuffled to sunset.jpg (all 8 eligible were recent, picked randomly)
Shuffled to sunset.jpg (tag: Nature, from 5 fresh of 12 in tag)
Shuffled to sunset.jpg (tag: Nature, all 3 in tag were recent)
```

**Edge cases:**

- **Cold start / empty log**: All images are considered "fresh"
- **Logging disabled**: Recency preference is skipped, all images equally likely
- **Small image pools**: Will naturally fall back to full pool more often
- **Tagset changes**: Only images in the new tagset that were previously shown are filtered

### Logging

The button logs detailed information:

```
INFO: sunset.jpg selected for TV Living Room from possible set of images {beach.jpg, forest.jpg, sunset.jpg, mountains.jpg}
INFO: Uploading sunset.jpg to Living Room...
INFO: Successfully uploaded sunset.jpg to Living Room
```

### Edge Cases

#### No matching images
```
WARNING: No images matching tag criteria for Living Room (include: ['nature', 'warm'], exclude: ['people'])
```
Button does nothing.

#### Only one matching image (already displayed)
```
INFO: Only one image (current.jpg) matches criteria for Living Room and it's already displayed. No shuffle performed.
```
Button does nothing to avoid re-uploading the same image.

#### Multiple images but all except one are current
After filtering, if the only candidate is already displayed, the button will select another until finding one that isn't current. If impossible (only one image total), it logs and does nothing.

## Sensors

Each TV gets these shuffle-related sensors automatically created:

### `sensor.<tv_name>_last_shuffle_image`
- Shows the filename of the last shuffled image
- Example: `sunset_a3f2b1.jpg`
- Updates immediately when shuffle button is pressed

### `sensor.<tv_name>_last_shuffle_timestamp`
- Shows when the last shuffle occurred
- Device class: `timestamp` (displays as relative time in HA)
- Example: `2025-11-02T14:32:15.123456`
- Updates immediately when shuffle button is pressed

### `sensor.<tv_name>_auto_shuffle_next`
- Device class: `timestamp`
- Shows the exact UTC time the scheduler will attempt the next shuffle
- Returns `unknown` whenever auto-shuffle is disabled for that TV

## State Storage

The integration tracks four pieces of state per TV in the config entry:

- `current_image`: Filename currently displayed (used to avoid re-selection)
- `last_shuffle_image`: Filename of last shuffle (for sensor)
- `last_shuffle_timestamp`: ISO timestamp of last shuffle (for sensor)
- `next_shuffle_time`: ISO timestamp for the next scheduled auto shuffle (used to restore timers on restart)

These are persisted across HA restarts.

## Prerequisites

### Required Structure

```
/config/www/frame_art/
├── metadata.json          # Contains image metadata
├── image1.jpg
├── image2.jpg
└── ...
```

### metadata.json Format

```json
{
  "version": "1.0",
  "images": {
    "sunset_a3f2b1.jpg": {
      "tags": ["nature", "warm", "landscape"],
      "matte": "none",
      "filter": "none"
    },
    "beach_x7y9z3.jpg": {
      "tags": ["nature", "water", "blue"],
      "matte": "none",
      "filter": "none"
    }
  },
  "tvs": [],
  "tags": ["nature", "warm", "landscape", "water", "blue"]
}
```

## Tag Filtering Logic

### Include Tags (OR logic)
If TV has `include_tags: ["nature", "warm"]`:
- Image with `tags: ["nature", "landscape"]` ✅ Matches (has "nature")
- Image with `tags: ["warm", "sunset"]` ✅ Matches (has "warm")
- Image with `tags: ["people", "portrait"]` ❌ No match (has neither)

### Exclude Tags (AND NOT logic)
If TV has `exclude_tags: ["people", "bw"]`:
- Image with `tags: ["nature", "landscape"]` ✅ Matches (has neither exclude tag)
- Image with `tags: ["nature", "people"]` ❌ No match (has "people")
- Image with `tags: ["landscape", "bw"]` ❌ No match (has "bw")

### Combined Example
TV config:
```yaml
include_tags: ["nature", "art"]
exclude_tags: ["people"]
```

Image evaluation:
- `tags: ["nature", "landscape"]` ✅ Has "nature", no "people"
- `tags: ["art", "abstract"]` ✅ Has "art", no "people"
- `tags: ["nature", "people", "landscape"]` ❌ Has "people" (excluded)
- `tags: ["city", "urban"]` ❌ Missing both "nature" and "art"

## Upload Guard & Power Awareness

- Manual button presses and the `display_image` service both route through `async_guarded_upload`, guaranteeing only one upload per TV at a time.
- Auto shuffle uses the same helper *and* performs a cached power-state check. If the cached state is off/unknown, the scheduler logs a skip and never attempts to wake the panel.
- Because we rely on cached state instead of fresh REST polls, the TVs never receive extra wake pings just to see if a shuffle is needed.

## Error Handling

The button handles errors gracefully and logs them:

### Missing metadata.json
```
ERROR: Cannot shuffle Living Room: metadata file not found at /config/www/frame_art/metadata.json
```

### Image file not found
```
ERROR: Cannot shuffle Living Room: image file not found at /config/www/frame_art/sunset.jpg
```

### Upload failure
```
ERROR: Failed to upload sunset.jpg to Living Room: Unable to connect to TV 192.168.1.100
```

All errors are logged but do not crash the integration. The sensors remain at their previous values.

## Usage Examples

### Basic Shuffle
1. Add images to `/config/www/frame_art/`
2. Update `metadata.json` with image tags
3. Configure TV with include/exclude tags in HA
4. Press "Auto-Shuffle Now" button in HA UI

### Dashboard Card
```yaml
type: entities
entities:
  - entity: button.living_room_shuffle_image
  - entity: sensor.living_room_last_shuffle_image
  - entity: sensor.living_room_last_shuffle_timestamp
```

### Automation
You can still automate manual shuffles (e.g., specific tags at certain times) by calling the button, but most users will prefer enabling the built-in auto-shuffle switch so the integration tracks the schedule, skips when the TV is off, and exposes status sensors.

## Technical Details

### Execution Flow

1. **Button press** (async, HA event loop)
2. **Load TV config** (sync, from config entry)
3. **Select image** (sync, in executor thread)
   - Load `metadata.json`
   - Filter by tags
   - Random selection excluding current
4. **Upload image** (sync, in executor thread)
   - Call `set_art_on_tv_deleteothers()`
   - Handles retries internally
5. **Update config** (async, HA event loop)
6. **Refresh coordinator** (async, triggers sensor updates)

### Thread Safety

- Image selection runs in executor (blocking I/O)
- Upload runs in executor (blocking network I/O)
- Config updates run on event loop (atomic)
- Coordinator refresh is async-safe

### Performance

- Image selection: O(n) where n = total images
- Random selection: O(1) after filtering
- Upload time: 5-15 seconds depending on image size and network
- No polling or background tasks

## Future Enhancements

Potential improvements not implemented:

- [x] ~~Weighted random selection (avoid recently shown images)~~ — Implemented as recency preference (48-hour window)
- [ ] Time-of-day based tag filtering
- [ ] Persistent notification on success/failure
- [ ] Upload progress indicator
- [ ] Batch shuffle multiple TVs
