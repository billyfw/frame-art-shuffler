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

1. When auto-shuffle runs, the integration queries the display log using **dual time windows**:
   - **Same-TV: 120 hours (5 days) default** — images shown on this TV via auto-shuffle
   - **Cross-TV: 72 hours (3 days) default** — images shown on any TV via auto-shuffle
2. The union of these sets becomes the "recent" images to avoid
3. If fresh images are available, one is selected randomly from the fresh pool
4. If all eligible images are recent (small pool or high shuffle frequency), the algorithm falls back to the full candidate pool

**Key design decisions:**

- **Dual time windows**: Different concerns need different horizons:
  - Same-TV: "I don't want to see the same image on this TV for almost a week"
  - Cross-TV: "I don't want to walk between rooms and see the same image for days"
- **Configurable windows**: Windows can be adjusted from 6 to 168 hours (7 days) via service call or the Frame Art Manager UI
- **Auto-shuffle only**: Manual displays (via button or service call) don't affect recency tracking. Only auto-scheduled shuffles are tracked and filtered
- **Soft preference**: Recency is preferred, not required. The algorithm never fails to select an image due to recency

### Configuring Recency Windows

Use the `frame_art_shuffler.set_recency_windows` service to adjust the time windows:

```yaml
service: frame_art_shuffler.set_recency_windows
data:
  same_tv_hours: 120   # 6-168 hours (default: 120)
  cross_tv_hours: 72   # 6-168 hours (default: 72)
```

The Frame Art Manager dashboard provides a visual interface with sliders and live preview of how window changes affect pool availability.

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
- **Tagset overrides**: The recency windows are off during an active tagset override. The user deliberately chose a different tagset, so the pool shouldn't be constrained by images from the previous tagset's recency window (shown under the everyday tagset in the last few days, about half an override's pictures would be held back). Since 0.6.2 an override goes through its pictures in rounds instead: see Override Rounds below.
- **Tagset changes (permanent)**: Only images in the new tagset that were previously shown are filtered

### Override Rounds (0.6.2)

From 2026-01-31 to 0.6.2 an override picked at random within the rolled tag, which was fine for an override of a few hours. Once the manager offered overrides of up to a week (2026-11-15), a Frame shuffling every 15 minutes through a set of about a hundred pictures showed one picture three times in four hours. Over a week such a Frame shows over 400 pictures from that set, so repeats are certain; the rounds space them evenly.

**The rule, per screen and per pool** (a tag's pool under tag weighting, every eligible picture otherwise; the tag itself is still rolled by weight first):

1. A picture shown in the current round is not picked again until every other picture in the pool has shown once; then the next round begins. Never the picture already on screen.
2. Two softer preferences, each dropped when it would leave nothing to pick: not one of the pool's last `pool_size // 2` showings, so a round does not open with the previous round's closing pictures; and not a picture another screen shows now.

**The history** is read from the display log at each pick (`DisplayLogManager.async_get_tagset_run`): this screen's shuffles, of any kind (the override's first, auto, the button), since the screen last showed a picture under another tagset. Pictures shown under the everyday tagset are therefore never counted, which is what the recency bypass protected. A session that names no tagset (a manual `display_image`, the screen-on session opened at startup) neither counts nor ends the run, and a screen-on session (the same picture resumed) does not count. The read includes the sessions not yet flushed and the picture on screen, so the round carries across a restart of Home Assistant; the log keeps 1 to 12 months, far longer than any override. Applying the same override again while it runs continues its rounds.

**Each screen keeps its own rounds.** One shared round would make each screen's own sequence uneven: a tablet shuffling every 10 minutes would use up most of each round, and the Frame would see its share at random. The "not what another screen shows now" preference covers the two screens in one room.

**Activity line:** `Shuffled to sunset.jpg (tag: beach, 3 of 24 this round)`, or `(3 of 102 this round)` without tag weighting. The pool-health trend still records nothing during an override (`recent_images` stays None there).

**Measured** against the second house's week-long override of 2026-11-14 (102 pictures in four tags weighted 7, 4, 4 and 0.6, a Frame every 15 minutes and a wall tablet every 10, both screens on 15.5 hours a day; a simulated week through this code, eight seeds): repeats within 4 hours on the Frame went from about 64 a week to about 3; each picture comes back after a median 21 hours in the 24-picture tag, 44 in the 31-picture tag and 58 in the 45-picture tag, at the shortest 5, 9 and 23 hours (at random: 30 minutes in each); both screens showed the same picture 0.1% of the time instead of 1.5%.

**Gaps:**
- A tag with two pictures still repeats within hours: the tag itself comes up at random (the 0.6-weight tag above, about 3 such repeats a week).
- Display logging off: no history, so an override picks as before 0.6.2.
- A session lost at shutdown (Known Failure Modes in `CLAUDE.md`) is a picture the round does not know was shown; it can come once more in that round.
- The pool is read at each pick: a picture added to the override's tags joins the current round, and one removed stops counting.

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

## Pool Health API

The integration exposes a REST API endpoint to monitor pool health — how many images are "fresh" vs. recently shown for each TV.

### Endpoint

```
GET /api/frame_art_shuffler/pool_health
```

Requires authentication (same as other HA APIs).

### Query Parameters (Optional)

Pass `same_tv_hours` and/or `cross_tv_hours` as query parameters to preview what pool health would look like with different window settings:

```
GET /api/frame_art_shuffler/pool_health?same_tv_hours=96&cross_tv_hours=48
```

### Response

```json
{
  "tvs": {
    "abc123...": {
      "name": "Fireplace",
      "pool_size": 500,
      "same_tv_recent": 300,
      "cross_tv_recent": 50,
      "total_recent": 350,
      "available": 150,
      "shuffle_frequency_minutes": 15,
      "same_tv_hours": 120,
      "cross_tv_hours": 72,
      "history": [
        {"timestamp": "2026-01-21T12:00:00Z", "pool_size": 500, "pool_available": 180},
        {"timestamp": "2026-01-21T12:15:00Z", "pool_size": 500, "pool_available": 179}
      ]
    }
  },
  "windows": {
    "same_tv_hours": 120,
    "cross_tv_hours": 72,
    "configured_same_tv_hours": 120,
    "configured_cross_tv_hours": 72
  }
}
```

### Field Definitions

| Field | Description |
|-------|-------------|
| `pool_size` | Total images in this TV's eligible pool (based on tagset) |
| `same_tv_recent` | Images shown on THIS TV within `same_tv_hours` |
| `cross_tv_recent` | Images shown on OTHER TVs within `cross_tv_hours` (excludes same-TV to avoid double-counting) |
| `total_recent` | Sum of `same_tv_recent` + `cross_tv_recent` |
| `available` | Images not recently shown, preferred for selection. `pool_size - total_recent` |
| `shuffle_frequency_minutes` | How often this TV shuffles (used to calculate variety hours) |
| `history` | Array of pool health snapshots over the last 7 days (recorded at each auto-shuffle) |

### History Field

The `history` array contains snapshots recorded each time auto-shuffle runs. Each entry has:
- `timestamp`: ISO 8601 timestamp of the shuffle
- `pool_size`: Total eligible images at that time
- `pool_available`: Fresh (non-recent) images available at that time

This data powers the 7-day trend sparkline in the Frame Art Manager UI.

### Variety Metric

The Frame Art Manager UI displays a **Variety** column calculated as:

```
Variety (hours) = available × (shuffle_frequency_minutes / 60)
```

This represents how many hours of unique shuffles are possible before the fresh pool is exhausted and sequences may start repeating.

| Variety | Status | Meaning |
|---------|--------|---------|
| 10+ hours | 🟢 Healthy | Good variety, patterns unlikely |
| 5-10 hours | 🟡 Moderate | Some repetition possible over a full day |
| <5 hours | 🔴 Low | Sequences will repeat; consider adding images |

### Use Cases

- **Monitoring**: Check if pool sizes are adequate for your shuffle frequency
- **Tuning**: Decide whether to adjust recency windows or add more images
- **Debugging**: Understand why certain images keep appearing

### Frame Art Manager Integration

The Frame Art Manager dashboard includes a "Pool Health" table that calls this API and displays the results in a user-friendly format.

## Future Enhancements

Potential improvements not implemented:

- [x] ~~Weighted random selection (avoid recently shown images)~~ — Implemented as recency preference
- [x] ~~Pool health monitoring~~ — Implemented via REST API
- [x] ~~Pool health history/sparkline~~ — 7-day trend tracked per shuffle
- [x] ~~Configurable recency windows~~ — Adjustable via service call (6-168 hours)
- [ ] Time-of-day based tag filtering
- [ ] Persistent notification on success/failure
- [ ] Upload progress indicator
- [ ] Batch shuffle multiple TVs
