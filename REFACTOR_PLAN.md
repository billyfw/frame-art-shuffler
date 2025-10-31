# Frame Art Shuffler Architecture Refactor Plan

## Current State (Hub Model - WRONG)
- **One integration entry** for a "home" (e.g., `madrone`)
- User adds TVs via **Options flow** (Add/Edit/Delete TV menu)
- Each TV becomes a device under the single integration entry
- Problem: **TVs don't appear as devices when added**, UI is confusing

## Target State (Per-Device Model - CORRECT)
- **One integration entry per TV** (standard Home Assistant pattern)
- User clicks "Add Integration" → Frame Art Shuffler → creates ONE TV
- Each TV is an independent entry with its own device
- Home selection happens via dropdown (prevents typos)

## User Flow (Target)

### Adding First TV
1. Click "Add Integration" → Frame Art Shuffler
2. **Step 1 (select_home)**: "Which home is this TV for?"
   - Text input for home name (e.g., `madrone`)
3. **Step 2 (configure_tv)**: Enter TV details
   - Name (e.g., "Office Frame TV")
   - IP address
   - MAC address
   - Tags (comma-separated, optional)
   - Exclude tags (comma-separated, optional)
   - Shuffle frequency (minutes)
4. **Pairing happens automatically** (with WOL wake)
5. Result: One device appears immediately

### Adding Subsequent TVs
1. Click "Add Integration" → Frame Art Shuffler
2. **Step 1 (select_home)**: "Which home is this TV for?"
   - **Dropdown** showing existing homes (`madrone`, etc.)
   - **Option**: "Create new home" → shows text input
3. **Step 2 (configure_tv)**: Enter TV details (same as above)
4. Result: Another device appears

### Editing a TV (Options Flow)
- Click gear icon on integration entry
- Edit: Name, IP, MAC, tags, shuffle frequency, **or change home**
- Can skip pairing if just changing metadata

### Reauth Flow
- Triggered when token expires/fails
- Re-pair with TV (uses existing TV data from entry)

## Technical Changes Required

### 1. Config Flow (`config_flow.py`)

#### Remove
- `single_instance_allowed` check
- Home claiming logic (`HomeAlreadyClaimedError`)
- `CONF_INSTANCE_ID`
- Entire options flow TV management (add/edit/delete TV actions)

#### Add/Change
- `async_step_select_home`: 
  - Check existing entries for homes
  - Show dropdown of existing homes + "Create new" option
  - Store selected/new home in flow state
- `async_step_configure_tv`:
  - TV details form (name, IP, MAC, tags, frequency)
  - Validate and pair TV
  - Create entry with:
    ```python
    {
        "home": "madrone",
        "tv_id": "<uuid>",
        "name": "Office Frame TV",
        "ip": "192.168.1.10",
        "mac": "aa:bb:cc:dd:ee:ff",
        "tags": ["landscape", "art"],
        "notTags": ["portrait"],
        "shuffle_frequency_minutes": 30
    }
    ```
  - Call `metadata.upsert_tv(home, tv_data)`
- Options flow becomes simple edit form (reuse configure_tv logic)

### 2. Coordinator (`coordinator.py`)

#### Current (per-home)
```python
class FrameArtCoordinator(DataUpdateCoordinator[list[dict[str, Any]]]):
    def __init__(self, hass, metadata_path, home):
        self._home = home
    
    async def _async_update_data(self):
        return await self.hass.async_add_executor_job(
            self._store.list_tvs, self._home
        )
```

#### Target (per-TV)
```python
class FrameArtCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(self, hass, metadata_path, home, tv_id):
        self._home = home
        self._tv_id = tv_id
    
    async def _async_update_data(self):
        return await self.hass.async_add_executor_job(
            self._store.get_tv, self._home, self._tv_id
        )
```

Returns single TV dict, not list.

### 3. Init (`__init__.py`)

#### Current
```python
async def async_setup_entry(hass, entry):
    home = entry.data[CONF_HOME]
    coordinator = FrameArtCoordinator(hass, metadata_path, home)
```

#### Target
```python
async def async_setup_entry(hass, entry):
    home = entry.data[CONF_HOME]
    tv_id = entry.data[CONF_TV_ID]
    coordinator = FrameArtCoordinator(hass, metadata_path, home, tv_id)
```

### 4. Sensor Platform (`sensor.py`)

#### Current
- Coordinator returns list of TVs
- Creates one entity per TV dynamically
- Creates "home" device as hub

#### Target
- Coordinator returns single TV dict
- Creates ONE sensor entity for THIS entry's TV
- Creates device directly (no hub concept)
- Device info:
  ```python
  DeviceInfo(
      identifiers={(DOMAIN, tv_id)},
      name=tv["name"],
      manufacturer="Samsung",
      model="Frame TV",
  )
  ```

### 5. Metadata (`metadata.py`)

#### Remove
- `claim_home()` method
- `HomeAlreadyClaimedError`
- `homes` dict from metadata structure

#### Keep
- `upsert_tv(home, tv_data)` - works same as before
- `get_tv(home, tv_id)` - works same as before
- `remove_tv(home, tv_id)` - called on entry removal
- `list_tvs(home)` - still useful for home dropdown

### 6. Constants (`const.py`)

#### Remove
- `CONF_INSTANCE_ID`

#### Keep everything else

### 7. Tests

#### Update
- `test_metadata.py`: Remove home claiming tests
- `test_flow_utils.py`: Should mostly work as-is
- Add new config flow tests for:
  - First TV (text input for home)
  - Second TV (dropdown selection)
  - Home creation
  - TV entry with all fields

## Data Migration

### Current metadata.json
```json
{
  "version": "1.0",
  "homes": {
    "madrone": {
      "instance_id": "abc123",
      "friendly_name": "madrone"
    }
  },
  "tvs": [
    {
      "id": "tv-uuid-1",
      "home": "madrone",
      "name": "Office TV",
      "ip": "192.168.1.10",
      "mac": "aa:bb:cc:dd:ee:ff",
      "tags": [],
      "notTags": [],
      "shuffle": {"shuffle_frequency_minutes": 30}
    }
  ],
  "images": {},
  "tags": []
}
```

### Target metadata.json
```json
{
  "version": "1.0",
  "tvs": [
    {
      "id": "tv-uuid-1",
      "home": "madrone",
      "name": "Office TV",
      "ip": "192.168.1.10",
      "mac": "aa:bb:cc:dd:ee:ff",
      "tags": [],
      "notTags": [],
      "shuffle": {"shuffle_frequency_minutes": 30}
    }
  ],
  "images": {},
  "tags": []
}
```

**No migration code needed** - just stop writing/reading `homes` dict. Old files with `homes` dict will be ignored, new files won't have it.

## Entry Data Structure

### Current
```python
{
    "home": "madrone",
    "instance_id": "abc123",
    "metadata_path": "/config/www/frame_art/metadata.json",
    "token_dir": "/config/frame_art_tokens"
}
```

### Target
```python
{
    "home": "madrone",
    "tv_id": "tv-uuid-1",
    "name": "Office Frame TV",
    "ip": "192.168.1.10",
    "mac": "aa:bb:cc:dd:ee:ff",
    "tags": ["landscape"],
    "notTags": ["portrait"],
    "shuffle_frequency_minutes": 30,
    "metadata_path": "/config/www/frame_art/metadata.json",
    "token_dir": "/config/frame_art_tokens"
}
```

All TV data stored in entry, synced to metadata on changes.

## Implementation Order

1. ✅ **Config flow refactor** (biggest change)
   - Remove single instance check
   - Add `async_step_select_home` (with existing homes dropdown)
   - Add `async_step_configure_tv` (TV details form + pairing)
   - Remove old options flow TV management
   - Keep simple options flow for editing THIS TV

2. ✅ **Coordinator update**
   - Change from per-home to per-TV
   - Return single dict instead of list

3. ✅ **Sensor platform update**
   - Remove dynamic entity creation
   - Create one entity per entry
   - Fix device info (no hub)

4. ✅ **Init update**
   - Pass tv_id to coordinator
   - Remove token directory reset logic (each entry manages own token)

5. ✅ **Metadata cleanup**
   - Remove claim_home
   - Remove HomeAlreadyClaimedError

6. ✅ **Tests update**
   - Fix existing tests
   - Add new flow tests

7. ✅ **Deploy and test**
   - Delete old `madrone` entry
   - Add new TV entry
   - Verify device appears
   - Add second TV with dropdown

## Key Files to Edit

- `custom_components/frame_art_shuffler/config_flow.py` (MAJOR)
- `custom_components/frame_art_shuffler/coordinator.py` (MODERATE)
- `custom_components/frame_art_shuffler/sensor.py` (MODERATE)
- `custom_components/frame_art_shuffler/__init__.py` (MINOR)
- `custom_components/frame_art_shuffler/metadata.py` (MINOR - remove claim_home)
- `custom_components/frame_art_shuffler/const.py` (TRIVIAL - remove CONF_INSTANCE_ID)
- `tests/test_metadata.py` (MINOR)

## Current Status

- ✋ **PAUSED** - User switching computers
- 📝 Plan documented
- 🔧 No code changes made yet
- ✅ Tests passing (17 passed)
- 📦 Current version: `0.1.0+dev20251031172824`

## Next Steps When Resuming

1. Start with config_flow.py refactor
2. Test each change with pytest
3. Use `./scripts/dev_deploy.sh --restart` to test in HA
4. Work through implementation order above
5. Estimated time: 30-45 minutes

## Context for Continuation

**What we're fixing:** Current integration uses a "hub" model where you create one entry for a home, then manage multiple TVs via options flow. TVs weren't appearing as devices. User wants standard HA pattern: one entry per TV, each TV is a device immediately visible.

**Key design decision:** Home selection via dropdown (after first TV) to prevent typos while keeping flexibility.

**Metadata compatibility:** Frame Art Manager add-on can still read the same metadata.json structure. We're just removing the `homes` dict that was used for instance claiming.
