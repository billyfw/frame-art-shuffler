# Tagsets Feature Implementation Plan

## Overview

Tagsets allow users to define named collections of include/exclude tags and assign them to TVs. A TV has a **selected** tagset (permanent) and optionally an **override** tagset (temporary, with expiry).

**Architecture:**
- **Integration** = database + engine (stores tagsets, manages timers, runs shuffle)
- **Add-on** = UI (displays/edits tagsets, calls integration services)

**Key Design Decision: GLOBAL tagsets**
- Tagsets are defined **once** at the integration level (not per-TV)
- Any tagset can be assigned to any TV
- Example: Create "everyday" tagset once, assign it to all 4 TVs
- TVs only store `selected_tagset` and `override_tagset` (names that reference global tagsets)

---

## Data Model

### Config Entry Structure (GLOBAL Tagsets)

```python
# Integration config entry data:
{
    # Global tagset definitions (shared by all TVs)
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
    
    # Per-TV configurations
    "tvs": {
        "tv_id_1": {
            "name": "Living Room Frame",
            "ip": "192.168.1.100",
            # ...other TV fields...
            
            # Tagset selection (references global tagsets by name)
            "selected_tagset": "everyday",      # permanent choice
            "override_tagset": null,            # temporary override
            "override_expiry_time": null,       # ISO timestamp when override expires
        },
        "tv_id_2": {
            "name": "Bedroom Frame",
            # ...
            "selected_tagset": "everyday",      # same tagset, different TV
            "override_tagset": "billybirthday", # can override independently
            "override_expiry_time": "2025-12-31T22:00:00Z",
        }
    }
}
```

### Effective Tags Resolution

```python
def get_effective_tags(entry: ConfigEntry, tv_id: str) -> tuple[list[str], list[str]]:
    """Return (include_tags, exclude_tags) for shuffle."""
    # Get global tagsets
    tagsets = entry.data.get("tagsets", {})
    
    if not tagsets:
        return ([], [])
    
    # Get TV's selected/override tagset name
    tv_config = entry.data.get("tvs", {}).get(tv_id, {})
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

Create or update a GLOBAL tagset definition. **No device_id needed.**

**Schema:**
```yaml
name: string           # required, tagset name
tags: list[string]     # required, include tags
exclude_tags: list[string]  # optional, default []
```

**Logic:**
1. Get current global tagsets from config entry
2. Add/update the named tagset
3. If this is the first tagset, auto-select it for all TVs that have no selection
4. Persist to config entry
5. Signal all TVs using this tagset to update sensors

**Errors:**
- Empty name
- Empty tags list

---

### 2. `frame_art_shuffler.delete_tagset`

Remove a GLOBAL tagset definition. **No device_id needed.**

**Schema:**
```yaml
name: string           # required, tagset name to delete
```

**Logic:**
1. Check deletion rules:
   - Cannot delete if it's the only tagset
   - Cannot delete if ANY TV has it as `selected_tagset`
   - Cannot delete if ANY TV has it as `override_tagset`
2. Remove from global tagsets dict
3. Persist to config entry

**Errors:**
- `cannot_delete_only_tagset`
- `tagset_in_use_by_tv` (list which TVs are using it)
- `tagset_not_found`

---

### 3. `frame_art_shuffler.select_tagset`

Assign a tagset to a specific TV (permanent selection). **Needs device_id.**

**Schema:**
```yaml
device_id: string      # required - which TV
name: string           # required, tagset name to select (or null to clear)
```

**Logic:**
1. Validate device_id → resolve to tv_id
2. Verify tagset exists in global tagsets (unless name is null)
3. Update TV's `selected_tagset` in config entry
4. Log activity

**Errors:**
- `tagset_not_found`

---

### 4. `frame_art_shuffler.override_tagset`

Apply a temporary tagset override to a specific TV. **Needs device_id.**

**Schema:**
```yaml
device_id: string         # required - which TV
name: string              # required, tagset name
duration_minutes: int     # required, must be > 0
```

**Logic:**
1. Validate device_id → resolve to tv_id
2. Verify tagset exists in global tagsets
3. Set TV's `override_tagset = name`
4. Calculate expiry and start timer
5. Persist to config entry

**Errors:**
- `tagset_not_found`
- `invalid_duration`

---

### 5. `frame_art_shuffler.clear_tagset_override`

Clear an active override for a specific TV. **Needs device_id.**

**Schema:**
```yaml
device_id: string      # required - which TV
```

**Logic:**
1. Validate device_id → resolve to tv_id
2. Cancel timer, clear TV's `override_tagset` and `override_expiry_time`
3. Persist to config entry

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

New installs start with empty global tagsets. User creates tagsets via add-on, then assigns to TVs.

### Existing Installs (Per-TV → Global Migration)

**Phase 3 will migrate existing per-TV tagsets to global tagsets.**

#### Automatic Migration Logic (in integration `__init__.py`)

```python
async def migrate_to_global_tagsets(hass, entry):
    """Migrate per-TV tagsets to global tagsets."""
    data = dict(entry.data)
    tvs = data.get("tvs", {})
    
    # Already migrated?
    if "tagsets" in data:
        return
    
    # Collect all unique tagsets from all TVs
    global_tagsets = {}
    for tv_id, tv_config in tvs.items():
        tv_tagsets = tv_config.get("tagsets", {})
        for name, tagset in tv_tagsets.items():
            if name not in global_tagsets:
                global_tagsets[name] = tagset
            # Note: if same name exists with different tags, first one wins
            # User can manually fix via add-on after migration
    
    # Move tagsets to global level
    data["tagsets"] = global_tagsets
    
    # Clean up per-TV tagset defs (keep only selection fields)
    for tv_id, tv_config in tvs.items():
        if "tagsets" in tv_config:
            del tvs[tv_id]["tagsets"]
        # Keep selected_tagset, override_tagset, override_expiry_time
    
    # Persist
    hass.config_entries.async_update_entry(entry, data=data)
    _LOGGER.info(f"Migrated {len(global_tagsets)} tagsets to global level")
```

#### Manual Migration (Alternative)

1. Stop Home Assistant
2. Edit `.storage/core.config_entries`
3. Move `tagsets` dict from inside each TV to the root `data` level
4. Start Home Assistant

---

## Add-on Implementation

### API Layer (`routes/ha.js`)

#### Endpoints for GLOBAL Tagsets

```javascript
// Get all global tagsets (no device_id needed)
GET /api/ha/tagsets

// Response:
{
  "tagsets": {
    "everyday": {"tags": [...], "exclude_tags": [...]},
    "billybirthday": {"tags": [...], "exclude_tags": [...]},
    ...
  }
}

// Create/update a global tagset (no device_id)
POST /api/ha/tagsets/upsert
{ name, tags, exclude_tags }
→ calls frame_art_shuffler.upsert_tagset

// Delete a global tagset (no device_id)
POST /api/ha/tagsets/delete
{ name }
→ calls frame_art_shuffler.delete_tagset
```

#### Endpoints for TV Tagset Assignments

```javascript
// Select tagset for a TV (needs device_id)
POST /api/ha/tagsets/select
{ device_id, name }
→ calls frame_art_shuffler.select_tagset

// Override tagset for a TV (needs device_id)
POST /api/ha/tagsets/override
{ device_id, name, duration_minutes }
→ calls frame_art_shuffler.override_tagset

// Clear override for a TV (needs device_id)
POST /api/ha/tagsets/clear-override
{ device_id }
→ calls frame_art_shuffler.clear_tagset_override
```

---

### UI Components

#### 1. Tagsets Tab (Advanced → Tagsets)

**Location:** First tab in Advanced section

**Sections:**

1. **Manage Tagsets** (GLOBAL - not per-TV)
   - Dropdown to select tagset to view/edit
   - Shows include/exclude tags for selected tagset
   - Edit button (opens modal)
   - Delete button (subtle text style)
   - New button (creates new global tagset)

2. **TV Tagset Assignments** (per-TV)
   - Card for each TV showing:
     - Selected tagset dropdown
     - Override status/expiry
     - Override button / Clear button

**Mockup:**
```
┌─────────────────────────────────────────────────────────────┐
│  MANAGE TAGSETS                                             │
├─────────────────────────────────────────────────────────────┤
│  Tagset: [everyday ▼]                           [+ New]     │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  everyday                                           │   │
│  │  Include: landscape, nature, family                 │   │
│  │  Exclude: (none)                                    │   │
│  │                                                     │   │
│  │  [Edit Tagset]                          Delete      │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  TV TAGSET ASSIGNMENTS                                      │
├─────────────────────────────────────────────────────────────┤
│  ┌──────────────────────────────┐ ┌──────────────────────┐  │
│  │ Living Room Frame            │ │ Bedroom Frame        │  │
│  │ Selected: [everyday ▼]       │ │ Selected: [everyday ▼│  │
│  │ Override: —                  │ │ Override: billybirthd│  │
│  │        [Apply Override]      │ │   (2h left)  [Clear] │  │
│  └──────────────────────────────┘ └──────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

#### 2. Gallery Tags Dropdown

**Add "Tagsets" section at top:**
```
Tags ▼
├── Tagsets
│   ├── everyday
│   ├── billybirthday
│   └── holidays
├── ──────────────
├── TVs
│   └── ...
├── All Tags
└── tags...
```

**Behavior:** Selecting a tagset filters to images matching that tagset's include tags (minus exclude tags).

---

#### 3. Stats Page Tags Dropdown

**Add "Tagsets" section:**
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

**Behavior:** Filters stats to images matching the selected tagset.

---

## Implementation Order

### Phase 1: Integration (frame-art-shuffler) ✅ COMPLETED (Per-TV)

Initial implementation with per-TV tagsets. All Phase 1 items completed:

1. ✅ Add constants to `const.py`
2. ✅ Add `get_effective_tags()` and `get_active_tagset_name()` helpers
3. ✅ Update `shuffle.py` to use `get_effective_tags()`
4. ✅ Add services: upsert, delete, select, override, clear_override
5. ✅ Add override expiry timer management
6. ✅ Add dedicated tagset sensors
7. ✅ Update config flow
8. ✅ Update dashboard and README

### Phase 2: Add-on UI (ha-frame-art-manager) ✅ COMPLETED (Per-TV)

Initial add-on implementation with per-TV tagsets:

1. ✅ API endpoints in `routes/ha.js` 
2. ✅ Tagsets tab with dropdown-based management
3. ✅ TV tagset assignment controls
4. 🔲 Gallery dropdown tagsets section (DEFERRED to Phase 4)
5. 🔲 Stats dropdown tagsets section (DEFERRED to Phase 4)

### Phase 3: Migrate to GLOBAL Tagsets ✅ COMPLETED

Successfully refactored both integration and add-on to use global tagsets:

#### Integration Changes (`frame-art-shuffler`) ✅

1. ✅ **`const.py`** - Added `CONF_TAGSETS` constant
2. ✅ **`config_entry.py`** - Updated helpers:
   - `get_global_tagsets(entry)` - Returns tagsets from entry root
   - `update_global_tagsets(hass, entry, tagsets)` - Persists global tagsets
   - `get_effective_tags(entry, tv_id)` - Resolves active tagset's tags for a TV
3. ✅ **`__init__.py`** - Updated services:
   - `upsert_tagset`: No device_id, writes to `entry.data["tagsets"]`
   - `delete_tagset`: No device_id, checks ALL TVs before allowing delete
   - `select_tagset`, `override_tagset`, `clear_tagset_override`: Keep device_id (per-TV)
   - Added `_async_migrate_tagsets_to_global()` for auto-migration
4. ✅ **`shuffle.py`** - Updated to use `get_effective_tags(entry, tv_id)`
5. ✅ **`sensor.py`** - Updated to:
   - Expose global tagsets in current_artwork attributes
   - Subscribe to dispatcher signals for real-time updates
6. ✅ **`services.yaml`** - Updated schemas (removed device_id from global operations)
7. ✅ **Migration logic** - Auto-migration runs in `async_setup_entry()`

#### Add-on Changes (`ha-frame-art-manager`) ✅

1. ✅ **`routes/ha.js`**:
   - Updated `/tvs` Jinja template to read global tagsets
   - Global CRUD endpoints don't require device_id
   - Pre-validation added for delete (see Lessons Learned)
2. ✅ **`public/js/app.js`**:
   - `populateTagsetDropdowns()` - No TV dropdown for tagset management
   - Single global tagset list stored in `allGlobalTagsets`
   - TV Assignments section remains per-TV
   - Immediate UI updates after CRUD operations

---

## Lessons Learned

### HA Supervisor API Strips Error Messages

**Problem:** When a service raises `ServiceValidationError`, Home Assistant Core properly returns the error message. However, the Supervisor API (which add-ons use to communicate with Core) **strips the message** and returns a generic `500 Internal Server Error - Server got itself in trouble`.

**Solution:** Pre-validate in the add-on backend before calling HA services. The add-on already has all the data needed (tagsets, TVs, assignments), so validation can happen in Node.js:

```javascript
// routes/ha.js - DELETE endpoint
router.post('/tagsets/delete', requireHA, async (req, res) => {
  const { name, tagsets, tvs } = req.body;  // Client sends current state
  
  // Pre-validation (since HA strips error messages)
  if (tagsets && tvs) {
    for (const tv of tvs) {
      if (tv.selected_tagset === name) {
        return res.status(400).json({ 
          error: 'Failed to delete tagset',
          details: `Cannot delete tagset '${name}': selected by ${tv.name}. Select a different tagset for that TV first.`
        });
      }
    }
  }
  
  // Then call HA service (will succeed since we pre-validated)
  await haRequest('POST', '/services/frame_art_shuffler/delete_tagset', { name });
});
```

The integration still has `ServiceValidationError` as a safety net, but the add-on provides the user-friendly error messages.

### Dispatcher Signals for Real-Time Updates

**Problem:** Sensor values weren't updating immediately after tagset changes. Users had to wait 60+ seconds for the next coordinator refresh.

**Solution:** Use HA's dispatcher system to signal sensors when tagsets change:

```python
# In service handler after updating tagsets:
async_dispatcher_send(hass, f"{DOMAIN}_tagset_updated_{entry.entry_id}")       # Global
async_dispatcher_send(hass, f"{DOMAIN}_tagset_updated_{entry.entry_id}_{tv_id}")  # Per-TV

# In sensor entity:
async def async_added_to_hass(self) -> None:
    # Subscribe to both global and TV-specific signals
    self._unsubscribe_global = async_dispatcher_connect(
        self.hass,
        f"{DOMAIN}_tagset_updated_{self._entry.entry_id}",
        self._handle_tagset_update
    )
    self._unsubscribe_tv = async_dispatcher_connect(
        self.hass,
        f"{DOMAIN}_tagset_updated_{self._entry.entry_id}_{self._tv_id}",
        self._handle_tagset_update
    )

@callback
def _handle_tagset_update(self) -> None:
    self.async_write_ha_state()
```

### CSS Class Collisions

**Problem:** The tagset modal used `.tag-checkbox` class, which collided with the existing filter dropdown's `.tag-checkbox` class. This caused JavaScript errors when the wrong checkboxes were selected.

**Solution:** Use unique class names: `.tagset-tag-checkbox` for the modal.

---

## Open Questions

1. ~~**Global tagsets vs per-TV tagsets?**~~ ✅ **DECIDED: GLOBAL** - Tagsets are defined once, assigned to TVs.

2. ~~**What if two TVs had different tagsets with same name during migration?**~~ ✅ **RESOLVED:** First one wins, log a warning. User can fix via add-on.

3. ~~**Should there be a "default" tagset for new TVs?**~~ ✅ **RESOLVED:** First tagset is auto-selected when TV has no selection and tagsets exist.

4. ~~**Tagset name validation?**~~ ✅ **IMPLEMENTED:** Non-empty, trimmed. No additional restrictions currently.

