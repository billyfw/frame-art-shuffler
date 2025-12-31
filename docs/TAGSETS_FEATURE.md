# Tagsets Feature Implementation Plan

## Overview

Tagsets allow users to define named collections of include/exclude tags and assign them to TVs. A TV has a **selected** tagset (permanent) and optionally an **override** tagset (temporary, with expiry).

**Architecture:**
- **Integration** = database + engine (stores tagsets, manages timers, runs shuffle)
- **Add-on** = UI (displays/edits tagsets, calls integration services)

---

## Data Model

### TV Config Entry Structure

```python
tvs[tv_id] = {
    # ...existing fields (name, ip, mac, etc.)...
    
    # Legacy fields (kept for backward compat, used if no tagsets defined)
    "tags": ["landscape", "nature"],
    "exclude_tags": [],
    
    # NEW: Tagsets
    "tagsets": {
        "everyday": {
            "tags": ["landscape", "nature", "family"],
            "exclude_tags": []
        },
        "billybirthday": {
            "tags": ["birthday", "billy", "cake"],
            "exclude_tags": []
        },
        "holidays": {
            "tags": ["christmas", "winter"],
            "exclude_tags": ["summer"]
        }
    },
    "selected_tagset": "everyday",      # permanent choice (nullable if no tagsets)
    "override_tagset": null,            # temporary override (null when inactive)
    "override_expiry_time": null,       # ISO timestamp when override expires
}
```

### Effective Tags Resolution

```python
def get_effective_tags(tv_config: dict) -> tuple[list[str], list[str]]:
    """Return (include_tags, exclude_tags) for shuffle."""
    tagsets = tv_config.get("tagsets", {})
    
    # No tagsets = no tags (requires migration for existing installs)
    if not tagsets:
        return ([], [])
    
    # Use override if active, else selected
    active_name = tv_config.get("override_tagset") or tv_config.get("selected_tagset")
    if not active_name or active_name not in tagsets:
        # Fallback: use first tagset or empty
        active_name = next(iter(tagsets), None)
        if not active_name:
            return ([], [])
    
    tagset = tagsets[active_name]
    return (
        tagset.get("tags", []),
        tagset.get("exclude_tags", [])
    )
```

---

## Integration Services

### 1. `frame_art_shuffler.upsert_tagset`

Create or update a tagset definition.

**Schema:**
```yaml
device_id: string      # required
name: string           # required, tagset name
tags: list[string]     # required, include tags
exclude_tags: list[string]  # optional, default []
```

**Logic:**
1. Validate device_id → resolve to tv_id
2. Get current tagsets from config entry
3. Add/update the named tagset
4. If this is the first tagset, set `selected_tagset` to this name
5. Call `update_tv_config()` to persist

**Errors:**
- Invalid device_id
- Empty name
- Empty tags list (must have at least one tag?)

---

### 2. `frame_art_shuffler.delete_tagset`

Remove a tagset definition.

**Schema:**
```yaml
device_id: string      # required
name: string           # required, tagset name to delete
```

**Logic:**
1. Validate device_id → resolve to tv_id
2. Check deletion rules:
   - Cannot delete if it's the only tagset
   - Cannot delete if it's the `selected_tagset`
   - Cannot delete if it's the `override_tagset`
3. Remove from tagsets dict
4. Call `update_tv_config()` to persist

**Errors:**
- `cannot_delete_only_tagset`
- `cannot_delete_selected_tagset`
- `cannot_delete_active_override`
- `tagset_not_found`

---

### 3. `frame_art_shuffler.select_tagset`

Permanently switch which tagset a TV uses.

**Schema:**
```yaml
device_id: string      # required
name: string           # required, tagset name to select
```

**Logic:**
1. Validate device_id → resolve to tv_id
2. Verify tagset exists
3. Update `selected_tagset` in config entry
4. Log activity: "Tagset changed to 'holidays'"
5. Optionally trigger a shuffle? (or let next scheduled shuffle use it)

**Errors:**
- `tagset_not_found`

---

### 4. `frame_art_shuffler.override_tagset`

Apply a temporary tagset override with required expiry.

**Schema:**
```yaml
device_id: string         # required
name: string              # required, tagset name
duration_minutes: int     # required, must be > 0
```

**Logic:**
1. Validate device_id → resolve to tv_id
2. Verify tagset exists
3. Set `override_tagset = name`
4. Calculate expiry: `now + duration_minutes`
5. Set `override_expiry_time`
6. Start/restart expiry timer (one-shot, like motion_off pattern)
7. Persist to config entry (so it survives restart)
8. Log activity: "Tagset override 'billybirthday' applied for 4h"
9. Signal sensors to update

**Errors:**
- `tagset_not_found`
- `invalid_duration` (must be > 0)

---

### 5. `frame_art_shuffler.clear_tagset_override`

Clear an active override early, reverting to selected tagset.

**Schema:**
```yaml
device_id: string      # required
```

**Logic:**
1. Validate device_id → resolve to tv_id
2. Cancel any pending expiry timer
3. Set `override_tagset = null`
4. Set `override_expiry_time = null`
5. Persist to config entry
6. Log activity: "Tagset override cleared"
7. Signal sensors to update

**Errors:**
- (none, clearing when no override is a no-op)

---

## Timer Management

### Override Expiry Timer

Pattern: Same as `motion_off_timer` in `__init__.py`

```python
# Storage
override_expiry_timers: dict[str, Callable[[], None]] = {}

def cancel_override_expiry_timer(tv_id: str) -> None:
    if tv_id in override_expiry_timers:
        override_expiry_timers[tv_id]()
        del override_expiry_timers[tv_id]

def start_override_expiry_timer(tv_id: str, expiry_time: datetime) -> None:
    cancel_override_expiry_timer(tv_id)
    
    async def async_expiry_callback(_now: Any) -> None:
        # Clear override
        update_tv_config(hass, entry, tv_id, {
            "override_tagset": None,
            "override_expiry_time": None,
        })
        log_activity(hass, entry.entry_id, tv_id, "tagset_override_expired", 
                     "Tagset override expired, reverted to selected tagset")
        # Signal sensors
        async_dispatcher_send(hass, f"{DOMAIN}_tagset_updated_{entry.entry_id}_{tv_id}")
    
    unsubscribe = async_track_point_in_time(hass, async_expiry_callback, expiry_time)
    override_expiry_timers[tv_id] = unsubscribe
    entry.async_on_unload(unsubscribe)
```

### Startup Restoration

On integration load, for each TV:
1. Check if `override_expiry_time` is set
2. If in the past → clear the override
3. If in the future → start timer for remaining duration

---

## Sensors / Entities

### Implemented: Dedicated Tagset Sensors

Each TV now has dedicated sensors for tagset status:

- **`sensor.<tv>_selected_tagset`** - Name of the permanent tagset (e.g., "everyday")
- **`sensor.<tv>_override_tagset`** - Name of active override, or "none" if no override
- **`sensor.<tv>_override_expiry`** - Timestamp when override expires (datetime sensor)
- **`sensor.<tv>_tags_combined`** - Displays effective tags resolved from active tagset: `[+] tag1, tag2 / [-] excluded`

### Tagset Data in Current Artwork Attributes

The `sensor.<tv>_current_artwork` sensor also exposes tagset info as attributes:
```yaml
tagsets: ["everyday", "billybirthday", "holidays"]
selected_tagset: "everyday"
override_tagset: "billybirthday"  # or null
override_expiry_time: "2025-12-31T18:00:00Z"  # or null
active_tagset: "billybirthday"  # resolved active tagset name
```

The add-on can read these attributes to display and manage tagsets.

---

## Text Entities - REMOVED

Text entities (`text.<tv>_tags_include` and `text.<tv>_tags_exclude`) have been removed from the integration. Tags are now managed exclusively through:

1. **Services** - `upsert_tagset`, `select_tagset`, `override_tagset`, etc.
2. **Add-on UI** - Calls the services to manage tagsets

This simplifies the architecture and ensures tagset management is centralized.

---

## Migration Path

### New Installs

New TV additions automatically create a "primary" tagset with the user-provided tags during config flow. No migration needed.

### Existing Installs

**Existing installs require manual migration.** The integration no longer uses legacy `tags`/`exclude_tags` fields - it only reads from the `tagsets` structure.

#### Manual Migration Steps

1. **Stop Home Assistant:**
   ```bash
   ssh ha 'ha core stop'
   ```

2. **Edit `.storage/core.config_entries`:**
   - Find the `frame_art_shuffler` entry
   - For each TV in `data.tvs`, convert:
     ```json
     {
       "tags": ["landscape", "nature"],
       "exclude_tags": ["winter"]
     }
     ```
     To:
     ```json
     {
       "tagsets": {
         "primary": {
           "tags": ["landscape", "nature"],
           "exclude_tags": ["winter"]
         }
       },
       "selected_tagset": "primary"
     }
     ```

3. **Start Home Assistant:**
   ```bash
   ssh ha 'ha core start'
   ```

**Important:** Do NOT modify the config file while HA is running - it will be overwritten on the next write cycle.

### First Tagset Creation via Add-on

When user creates their first tagset via add-on after migration:
1. Add-on calls `upsert_tagset`
2. Integration creates/updates the tagset
3. User can then select which tagset to use

---

## Add-on Implementation

### API Layer (`routes/ha.js`)

#### New Endpoints (convenience wrappers)

```javascript
// Get tagsets for a TV (reads from sensor attributes via template)
GET /api/ha/tagsets?device_id=xxx

// Response:
{
  "tagsets": {
    "everyday": {"tags": [...], "exclude_tags": [...]},
    ...
  },
  "selected_tagset": "everyday",
  "override_tagset": null,
  "override_expiry_time": null
}
```

#### Service Calls

```javascript
// Upsert tagset
POST /api/ha/tagsets/upsert
{ device_id, name, tags, exclude_tags }
→ calls frame_art_shuffler.upsert_tagset

// Delete tagset  
POST /api/ha/tagsets/delete
{ device_id, name }
→ calls frame_art_shuffler.delete_tagset

// Select tagset
POST /api/ha/tagsets/select
{ device_id, name }
→ calls frame_art_shuffler.select_tagset

// Override tagset
POST /api/ha/tagsets/override
{ device_id, name, duration_minutes }
→ calls frame_art_shuffler.override_tagset

// Clear override
POST /api/ha/tagsets/clear-override
{ device_id }
→ calls frame_art_shuffler.clear_tagset_override
```

---

### UI Components

#### 1. Tags Tab (Advanced → Tags)

**Location:** New tab in Advanced section, before Settings

**Sections:**
1. **Manage Tagsets** - CRUD for tagset definitions
2. **TV Tagset Assignments** - Per-TV selected/override status
3. **Manage Tags** - Existing tag management (moved from Settings)

**Mockup:**
```
┌─────────────────────────────────────────────────────────────┐
│  MANAGE TAGSETS                                    [+ New]  │
├─────────────────────────────────────────────────────────────┤
│  everyday         landscape, nature, family         [Edit]  │
│  billybirthday    birthday, billy, cake            [Edit]  │
│  holidays         christmas, winter                [Edit]  │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  TV TAGSET ASSIGNMENTS                                      │
├─────────────────────────────────────────────────────────────┤
│  Living Room Frame                                          │
│    Selected: [everyday ▼]                                   │
│    Override: —                          [Apply Override]    │
│                                                             │
│  Bedroom Frame                                              │
│    Selected: [everyday ▼]                                   │
│    Override: billybirthday (2h 15m left)      [Clear]      │
└─────────────────────────────────────────────────────────────┘

───────────────────────────────────────────────────────────────

┌─────────────────────────────────────────────────────────────┐
│  MANAGE TAGS                                                │
│  (existing tag rename/delete/merge UI)                      │
└─────────────────────────────────────────────────────────────┘
```

**Modals:**
- **Edit/New Tagset:** Name field, tags multi-select, exclude tags multi-select, Save/Delete buttons
- **Apply Override:** Tagset dropdown, duration picker (30m, 1h, 2h, 4h, 8h, custom), Apply button

---

#### 2. Gallery Tags Dropdown

**Current:**
```
Tags ▼
├── TVs
│   └── ...
├── All Tags
└── tags...
```

**New:**
```
Tags ▼
├── Tagsets
│   ├── everyday
│   ├── billybirthday
│   └── holidays
├── TVs
│   └── ...
├── All Tags
└── tags...
```

**Behavior:** Selecting a tagset filters to images matching that tagset's include tags (minus exclude tags).

---

#### 3. Stats Page Tags Dropdown

**Current:**
```
Filter ▼
├── All
└── tags...
```

**New:**
```
Filter ▼
├── Tagsets
│   ├── everyday
│   ├── billybirthday
│   └── holidays
├── ──────────────
├── All
└── tags...
```

**Behavior:** Filters stats to images with tags in the selected tagset.

---

## Implementation Order

### Phase 1: Integration (frame-art-shuffler) ✅ COMPLETED

All Phase 1 items have been implemented and tested:

1. ✅ Add constants to `const.py` - `CONF_TAGSETS`, `CONF_SELECTED_TAGSET`, `CONF_OVERRIDE_TAGSET`, `CONF_OVERRIDE_EXPIRY_TIME`
2. ✅ Add `get_effective_tags()` and `get_active_tagset_name()` helpers to `config_entry.py`
3. ✅ Update `shuffle.py` to use `get_effective_tags()`
4. ✅ Add services in `__init__.py`:
   - `upsert_tagset`
   - `delete_tagset`
   - `select_tagset`
   - `override_tagset`
   - `clear_tagset_override`
5. ✅ Add override expiry timer management
6. ✅ Add startup restoration for pending overrides
7. ✅ Add dedicated tagset sensors:
   - `sensor.<tv>_selected_tagset` - Shows permanent tagset name
   - `sensor.<tv>_override_tagset` - Shows "none" or override name
   - `sensor.<tv>_override_expiry` - Timestamp when override expires
8. ✅ Update `tags_combined` sensor to use `get_effective_tags()`
9. ✅ Add `services.yaml` entries for all 5 tagset services
10. ✅ Remove text entities (tags now managed via services only)
11. ✅ Update config flow:
    - Add TV: Creates initial "primary" tagset with user-provided tags
    - Edit TV: No tag fields (tags managed via add-on/services)
12. ✅ Update dashboard to show tagset sensors
13. ✅ Update README with tagsets documentation

**Data Migration:** Existing installs must manually migrate via SSH (stop HA → edit config → start HA) to convert legacy `tags`/`exclude_tags` to tagsets structure.

### Phase 2: Add-on (ha-frame-art-manager) - TODO

#### API Layer (`routes/ha.js`)

1. **GET endpoint** - Fetch tagsets for a TV:
   ```javascript
   GET /api/ha/tagsets?device_id=xxx
   // Read from sensor state_attr(sensor.<tv>_current_artwork, 'tagsets')
   ```

2. **Service wrapper endpoints:**
   - `POST /api/ha/tagsets/upsert` → calls `frame_art_shuffler.upsert_tagset`
   - `POST /api/ha/tagsets/delete` → calls `frame_art_shuffler.delete_tagset`
   - `POST /api/ha/tagsets/select` → calls `frame_art_shuffler.select_tagset`
   - `POST /api/ha/tagsets/override` → calls `frame_art_shuffler.override_tagset`
   - `POST /api/ha/tagsets/clear-override` → calls `frame_art_shuffler.clear_tagset_override`

#### UI Components

1. **Tags Tab** (new tab in Advanced section):
   - Manage Tagsets section: CRUD for tagset definitions
   - TV Tagset Assignments section: Per-TV selected/override status with dropdowns
   - Move existing tag management (rename/delete/merge) into this tab

2. **Gallery Dropdown** - Add "Tagsets" section at top:
   - Selecting a tagset filters to images matching that tagset's tags

3. **Stats Dropdown** - Add "Tagsets" section:
   - Filter stats by tagset

#### Implementation Steps

1. [ ] Add API endpoints in `routes/ha.js`
2. [ ] Create Tags tab component with tagset CRUD
3. [ ] Add TV tagset assignment controls (select/override)
4. [ ] Update Gallery dropdown with tagset filter option
5. [ ] Update Stats dropdown with tagset filter option
6. [ ] End-to-end testing

---

## Open Questions

1. **Should creating a tagset trigger a shuffle?** Probably not, let next scheduled shuffle use it.

2. **Should selecting a different tagset trigger a shuffle?** Maybe optional parameter?

3. **What happens if user edits `selected_tagset` tags while override is active?** Works fine, changes take effect when override expires.

4. **Global tagsets vs per-TV tagsets?** Current design is per-TV. Global would add complexity but allow "apply billybirthday to all TVs." Could add later.

5. **Tagset name validation?** Probably: non-empty, alphanumeric + underscore + hyphen, max length 50.
