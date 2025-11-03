# Shuffle Image Feature

## Overview

Each Frame TV now has a "Shuffle Image" button that randomly selects and uploads an image from your `www/frame_art/` directory based on the TV's tag filtering preferences.

## How It Works

### Button Behavior

When you press the "Shuffle Image" button for a TV:

1. **Load images** from `metadata.json` in `/config/www/frame_art/`
2. **Filter by tags**:
   - Image must have at least one tag in the TV's `include_tags` (if any are set)
   - Image must NOT have any tag in the TV's `exclude_tags` (if any are set)
3. **Select randomly** from matching images, excluding the current image
4. **Upload** the selected image using `--delete-others` flag (removes all other images from TV)
5. **Update sensors** with the new image name and timestamp

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

Each TV gets two new sensors automatically created:

### `sensor.<tv_name>_last_shuffle_image`
- Shows the filename of the last shuffled image
- Example: `sunset_a3f2b1.jpg`
- Updates immediately when shuffle button is pressed

### `sensor.<tv_name>_last_shuffle_timestamp`
- Shows when the last shuffle occurred
- Device class: `timestamp` (displays as relative time in HA)
- Example: `2025-11-02T14:32:15.123456`
- Updates immediately when shuffle button is pressed

## State Storage

The integration tracks three pieces of state per TV in the config entry:

- `current_image`: Filename currently displayed (used to avoid re-selection)
- `last_shuffle_image`: Filename of last shuffle (for sensor)
- `last_shuffle_timestamp`: ISO timestamp of last shuffle (for sensor)

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

## No Pre-flight Checks

The button does **NOT** check if the TV screen is on or in art mode before uploading. It simply attempts the upload and lets `frame_tv.py` handle any connection errors naturally.

**Why:** Pre-flight checks using `is_screen_on()` and `is_art_mode_enabled()` might wake the TV from sleep, which is undesirable. Instead, we let the upload fail gracefully if the TV isn't ready.

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
4. Press "Shuffle Image" button in HA UI

### Dashboard Card
```yaml
type: entities
entities:
  - entity: button.living_room_shuffle_image
  - entity: sensor.living_room_last_shuffle_image
  - entity: sensor.living_room_last_shuffle_timestamp
```

### Automation
```yaml
automation:
  - alias: "Shuffle art every morning"
    trigger:
      - platform: time
        at: "08:00:00"
    action:
      - service: button.press
        target:
          entity_id: button.living_room_shuffle_image
```

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

- [ ] Weighted random selection (avoid recently shown images)
- [ ] Time-of-day based tag filtering
- [ ] Persistent notification on success/failure
- [ ] Upload progress indicator
- [ ] Batch shuffle multiple TVs
- [ ] Scheduled automatic shuffles (use HA automations for now)
