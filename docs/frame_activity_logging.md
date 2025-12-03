# Frame Activity Logging

## 1. Overview
The Frame Art Shuffler integration maintains a shared activity log that tracks how long each image is displayed on each TV. This log is stored in JSON files that the Frame TV Manager add-on can read to display analytics.

**Status:** ✅ Implemented (v0.5+)

## 2. Storage Layout
- **Root directory:** `/config/frame_art/logs/` (created automatically on setup)
- **Files:**

| File | Purpose |
|------|---------|
| `events.json` | Rolling array of raw session entries (trimmed by retention) |
| `summary.json` | Aggregated stats by TV/image/tag, regenerated on each flush |
| `pending.json` | Crash-recovery buffer, deleted after successful flush |

- **Permissions:** Integration writes; add-on reads only.

## 3. Data Flow

### Session Tracking
1. When a shuffle occurs, `note_display_start()` is called with:
   - `tv_id`, `tv_name` - which TV
   - `filename` - image being displayed
   - `tags` - image tags from metadata
   - `source` - "shuffle" (future: "manual", "automation")
   - `shuffle_mode` - reason for shuffle ("auto", "manual", etc.)
   - `started_at` - timestamp
   - `tv_tags` - the TV's configured include_tags (optional)

2. If `tv_tags` is provided, `matched_tags` is computed as the intersection of image tags and TV tags. This allows per-TV statistics to only count tags that are relevant to that TV's configuration.

3. The **previous** image's session is completed and queued for persistence.

4. Sessions are held in memory until the flush timer fires.

### Screen State Tracking
To accurately track viewing time, display sessions are automatically closed when the screen turns off and resumed when it turns on:

- **Screen Off**: When the screen turns off (motion timeout, remote, app, etc.), `note_screen_off()` is called to complete the current session. No viewing time accumulates while the screen is off.

- **Screen On**: When the screen turns on (motion detected, remote, app, etc.), `note_screen_on()` starts a new session for the same image that was showing.

This means the **same image can have multiple session entries** if the screen cycles on/off:
```json
[
  {"filename": "sunset.jpg", "started_at": "10:00", "completed_at": "10:15", "duration_seconds": 900, "source": "shuffle"},
  {"filename": "sunset.jpg", "started_at": "14:00", "completed_at": "14:30", "duration_seconds": 1800, "source": "screen_on"}
]
```

This design provides accurate viewing time statistics rather than wall-clock time between shuffles.

### Flush Cycle (default: every 5 minutes)
1. Read existing `events.json`
2. Append queued sessions
3. Trim events older than retention window
4. Write back atomically (temp file + rename)
5. Rebuild `summary.json` from trimmed events
6. Clear queue and delete `pending.json`

### Crash Recovery
- On each session record, `pending.json` is updated immediately
- On HA startup, `pending.json` is loaded back into the queue
- Ensures minimal data loss on unexpected restarts

## 4. Event Schema (`events.json`)
```json
[
  {
    "tv_id": "a9eef6ac436f482090e5e66ecbe88641",
    "tv_name": "Office Frame",
    "filename": "sunset-beach.jpg",
    "duration_seconds": 900,
    "completed_at": "2025-12-03T10:15:00+00:00",
    "started_at": "2025-12-03T10:00:00+00:00",
    "tags": ["nature", "landscape"],
    "matched_tags": ["nature"],
    "source": "shuffle",
    "shuffle_mode": "auto"
  }
]
```

### Field Notes
- **`tags`**: All tags assigned to the image in metadata
- **`matched_tags`**: Intersection of image tags with the TV's configured `include_tags`. May be `null` if the TV has no tag filter configured. Used for per-TV tag statistics.
- **`source`**: How the session started:
  - `"shuffle"` - Image was shuffled (auto or manual)
  - `"screen_on"` - Same image resumed after screen turned back on
  - `"display_image"` - Service call (future)
- **`shuffle_mode`**: Reason for shuffle (e.g., `"auto"`, `"manual"`). Only present when `source` is `"shuffle"`.

## 5. Summary Schema (`summary.json`)
```json
{
  "version": 1,
  "generated_at": "2025-12-03T10:15:00+00:00",
  "retention_months": 6,
  "logging_enabled": true,
  "flush_interval_minutes": 5,
  "totals": {
    "tracked_seconds": 12345,
    "event_count": 456
  },
  "tvs": {
    "tv_id_here": {
      "name": "Office Frame",
      "total_display_seconds": 12345,
      "event_count": 456,
      "share_of_tracked": 100.0,
      "per_image": [
        {"filename": "sunset.jpg", "seconds": 3600, "event_count": 4, "share": 29.17}
      ],
      "per_tag": [
        {"tag": "nature", "seconds": 5000, "event_count": 10, "share": 40.5}
      ]
    }
  },
  "images": {
    "sunset.jpg": {
      "tags": ["nature", "landscape"],
      "total_display_seconds": 3600,
      "event_count": 4,
      "per_tv": [
        {"tv_id": "abc123", "seconds": 3600, "event_count": 4, "share": 100.0}
      ]
    }
  },
  "tags": {
    "nature": {
      "total_display_seconds": 5000,
      "event_count": 10,
      "per_tv": [...],
      "top_images": [...]
    },
    "<none>": {
      "total_display_seconds": 1000,
      "event_count": 5,
      "per_tv": [...],
      "top_images": [...]
    }
  }
}
```

**Notes:**
- Images with no tags are tracked under the special tag `<none>`.
- The global `tags` section uses all image tags for comprehensive statistics.
- Per-TV `per_tag` arrays use `matched_tags` (intersection with TV's configured tags) when available, giving per-TV views only the tags relevant to that TV's filter configuration.

## 6. Configuration

### Integration Options Flow
Access via: **Settings → Devices & Services → Frame Art Shuffler → Configure → Logging settings**

| Setting | Range | Default | Description |
|---------|-------|---------|-------------|
| Enable logging | on/off | on | Master toggle |
| Retention window | 1-12 months | 6 | How long to keep events |
| Flush interval | 1-60 minutes | 5 | How often to write to disk |

### Services

| Service | Description |
|---------|-------------|
| `frame_art_shuffler.set_log_options` | Update logging settings programmatically |
| `frame_art_shuffler.flush_display_log` | Manually flush pending sessions to disk |
| `frame_art_shuffler.clear_display_log` | Delete all log data (events, summary, pending) |

#### `set_log_options` Example
```yaml
service: frame_art_shuffler.set_log_options
data:
  logging_enabled: true
  log_retention_months: 3
  log_flush_interval_minutes: 2
```

## 7. Add-on Integration Guide

### File Access
Mount `/config/frame_art/logs/` read-only in the add-on.

### Reading Summary
```python
import json
from pathlib import Path

summary_path = Path("/config/frame_art/logs/summary.json")
if summary_path.exists():
    with summary_path.open() as f:
        summary = json.load(f)
    
    # Check freshness
    generated_at = summary.get("generated_at")
    logging_enabled = summary.get("logging_enabled", False)
    
    # Get totals
    totals = summary.get("totals", {})
    total_hours = totals.get("tracked_seconds", 0) / 3600
    event_count = totals.get("event_count", 0)
    
    # Iterate TVs
    for tv_id, tv_data in summary.get("tvs", {}).items():
        print(f"{tv_data['name']}: {tv_data['total_display_seconds']/3600:.1f}h")
else:
    # No data yet - show message to user
    pass
```

### Calling Services (from add-on)
```bash
# Flush logs
curl -sS -X POST \
  -H "Authorization: Bearer $SUPERVISOR_TOKEN" \
  -H "Content-Type: application/json" \
  http://supervisor/core/api/services/frame_art_shuffler/flush_display_log

# Clear logs
curl -sS -X POST \
  -H "Authorization: Bearer $SUPERVISOR_TOKEN" \
  -H "Content-Type: application/json" \
  http://supervisor/core/api/services/frame_art_shuffler/clear_display_log

# Update settings
curl -sS -X POST \
  -H "Authorization: Bearer $SUPERVISOR_TOKEN" \
  -H "Content-Type: application/json" \
  http://supervisor/core/api/services/frame_art_shuffler/set_log_options \
  -d '{"log_retention_months": 3}'
```

### UI Recommendations
- **Refresh interval:** Poll summary every 60-120 seconds (flush is every 5 min by default)
- **Missing file:** Show "No activity data yet" message
- **Malformed file:** Show warning, don't crash
- **Display options:**
  - Total hours tracked
  - Event count
  - Last updated timestamp
  - Per-TV breakdown with percentages
  - Top tags
  - Top images (optional, can get large)

## 8. Dashboard Integration
The generated Lovelace dashboard includes a **Settings** tab (gear icon) that shows:
- Current logging status (enabled/disabled)
- Retention and flush settings
- Link to configure via integration options
- Activity summary (requires `sensor.frame_art_log_summary` - not yet implemented)
- **Clear All Logs** button with confirmation

## 9. Future Enhancements
- [ ] Add `sensor.frame_art_log_summary` entity to expose summary data to templates
- [ ] Per-month event files if `events.json` grows too large
- [ ] Binary sensor for log health/errors
- [ ] Export/download logs feature
- [ ] Incremental summary updates instead of full rebuild

---
*Last updated: December 2025*
