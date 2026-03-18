# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Workflow Preferences

**Never commit or deploy without explicit user approval.** When you believe a task is complete, ask the user whether to:
- **Commit**: `git commit` (with a succinct, meaningful message) + `git push`
- **Commit and deploy**: `git commit` (with a succinct, meaningful message) + `git push` + `./scripts/dev_deploy.sh --restart`

**Deploy is fire-and-forget**: When running `dev_deploy.sh`, use `run_in_background: true` and don't wait for output. The script is reliable and takes ~45 seconds. Continue the conversation immediately after launching it.

## Project Overview

Frame Art Shuffler is a Home Assistant custom integration for managing Samsung Frame TVs. It handles art uploads, brightness control, gallery management, image shuffling with tag-based filtering, and activity logging. The integration coordinates with a separate Frame Art Manager add-on via a shared `metadata.json` file.

## Commands

### Testing
```bash
source .venv/bin/activate
pytest                           # Run all tests
pytest tests/test_activity.py    # Run specific test file
pytest -v                        # Verbose output
```

### Development Deployment
```bash
./scripts/dev_deploy.sh          # Bump version, deploy to HA via SSH, reload
```

### Git Setup (one-time per machine)
```bash
./scripts/setup-git-hooks.sh     # Configure merge driver for manifest.json
```

### CLI for Manual TV Operations
```bash
python scripts/frame_tv_cli.py <TV_IP> upload <file> --brightness 5
python scripts/frame_tv_cli.py <TV_IP> status
python scripts/frame_tv_cli.py <TV_IP> brightness 5
```

## Architecture

### Core Components

- **`__init__.py`** - Integration setup, service registration, service handlers
- **`frame_tv.py`** - Samsung TV WebSocket client (synchronous; uses vendored samsungtvws)
- **`config_flow.py`** - UI flows for adding/editing/deleting TVs
- **`config_entry.py`** - Config storage helpers; access TV data via `get_tv_config(entry, tv_id)`
- **`shuffle.py`** - Shuffle engine with tag weighting (image-level or tag-level)
- **`activity.py`** - Event tracking and history sensor
- **`display_log.py`** - Display session logging with retention
- **`metadata.py`** - Shared metadata.json interface (syncs with Frame Art Manager add-on)
- **`dashboard.py`** - Auto-generates Lovelace dashboard YAML

### Entity Platforms

Each platform (`sensor.py`, `button.py`, `switch.py`, `number.py`, `binary_sensor.py`) follows HA patterns:
- `async_setup_entry()` for initialization
- Unique IDs: `{tv_id}_{entity_key}`
- All entities have `device_info` with DOMAIN identifier

### Key Patterns

**Async/Sync Bridge**: Frame TV WebSocket operations are synchronous. Run via:
```python
await hass.async_add_executor_job(frame_tv_function, args)
```

**Upload Concurrency**: Uploads use `async_guarded_upload()` to prevent overlapping operations per TV.

**Config Entry Data Structure**:
```python
entry.data["tvs"][tv_id]  # Per-TV config
entry.data["tagsets"]      # Global tagset definitions
```
Always `.copy()` nested dicts before calling `async_update_entry()`.

**Tagset Resolution**:
- TVs have `selected_tagset` (permanent) and `override_tagset` (temporary with expiry)
- Override takes precedence if not expired
- Tagset defines include/exclude tags for filtering during shuffle

**Tag Weighting** (in shuffle.py):
- `weighting_type: "image"` - All matching images equally likely
- `weighting_type: "tag"` - Tags weighted equally (or via tag_weights), then random image from selected tag
- Multi-tag images assigned to highest-weight matching tag

**Activity Events**: Log via `log_activity(hass, entry, tv_id, event_type, message, icon)`

### Data Flow

1. User config → Config Flow → Config Entry (HA storage)
2. TV operations → frame_tv.py → WebSocket to TV
3. Image metadata → metadata.json (shared with Frame Art Manager add-on)
4. Activity → Activity sensor + optional display log files

### Vendored Dependency

`samsungtvws` v3.0.3 is vendored in `custom_components/frame_art_shuffler/samsungtvws/` to avoid conflicts with HA's bundled version. See `docs/VENDORING.md`.

## Key Documentation

Feature design docs in `/docs/`:
- `TAGSETS_FEATURE.md` - Tagset system design
- `TAG_WEIGHTS_FEATURE.md` - Tag weighting algorithm
- `SHUFFLE_FEATURE.md` - Shuffle mechanics
- `TV_STATES.md` - Samsung Frame TV state machine
- `MATTE_BEHAVIOR.md` - Matte upload workarounds

## SSH Access to Home Assistant

Connect to the HA box for verification and debugging:

```bash
ssh ha                          # Connect to Home Assistant SSH add-on
```

**IMPORTANT**: Never perform destructive operations on the HA box (deleting files, modifying configs, restarting services, etc.) without explicit user permission. SSH access is primarily for read-only verification and debugging.

### Key Paths on HA Box
- **HA Config**: `/config/`
- **Integration**: `/config/custom_components/frame_art_shuffler/`
- **Display Logs**: `/config/frame_art/logs/events.json`
- **Display Summary**: `/config/frame_art/logs/summary.json`

### Debugging: Data Source Priority

When investigating TV behavior (what happened, when, why a TV is in a certain state):

1. **Check `events.json` FIRST** — this is the most reliable source for recent TV activity. It has timestamped display sessions with TV names, filenames, sources, and durations. It persists across HA restarts and log rotations.
2. **Then check HA logs via Supervisor API** — `curl -H "Authorization: Bearer $TOKEN" http://ha.mad:8123/api/hassio/core/logs`. There is no `home-assistant.log` file on disk (removed in HA 2025.11); logs are in the systemd journal.
3. **Don't rely on stale files** — there are no log files on disk to grep.

### Useful Commands
```bash
# Check display log events (BEST source for recent TV activity)
tail -100 /config/frame_art/logs/events.json

# Filter display log by TV name
grep 'fireplace' /config/frame_art/logs/events.json | tail -30

# HA logs are accessed via the Supervisor API (no log file on disk)
# Use the ha_logs MCP tool from the ha-config project, or:
curl -H "Authorization: Bearer $TOKEN" http://ha.mad:8123/api/hassio/core/logs
```

### Logging Configuration
The integration is set to debug level in `/config/configuration.yaml`:
```yaml
logger:
  logs:
    custom_components.frame_art_shuffler: debug
```

## Known Failure Modes

### Image shown twice / "I just saw this recently"
**Quick diagnosis**: Check if HA restarted shortly after the image was first shown.

1. `grep 'img-XXXX' /config/frame_art/logs/events.json` — if missing, session was never logged
2. Look for an HA restart within ~15 min of the first display

**Root cause**: When HA restarts, `async_finalize_active_sessions()` tries to flush the active
display session to disk via `hass.async_add_executor_job()`, but if the executor is already
shutting down, the write fails silently. The image never makes it into `events.json`, so
`get_recent_auto_shuffle_images()` treats it as "fresh" on the next shuffle.

**If this happens frequently**: investigate hardening `async_finalize_active_sessions()` to
not rely on the executor (e.g., synchronous write path during shutdown).

### HA Logging — No log file on disk (since HA 2025.11)

HA removed `home-assistant.log` for HAOS/Supervised installs.

**How to access logs programmatically:**
- Supervisor API: `GET /api/hassio/core/logs` (proxied through HA, uses Bearer token)
- The ha-config MCP server's `ha_logs` tool uses this endpoint
- WebSocket: `system_log/list` returns structured JSON of recent errors/warnings
- UI: Settings → System → Logs
- The old `/api/error_log` REST endpoint returns 404 (it was backed by the file)

## Historical Notes

### Fireplace TV WiFi-to-Wired Migration (March 2026)
Fireplace Frame TV (192.168.1.199) was switched from WiFi to wired ethernet. The integration's
config had the WiFi MAC; the wired MAC is different. Impact: `tv_on()` sent WoL to the wrong
MAC, so the TV couldn't be woken from standby. All IP-based operations (shuffles, tv_off,
brightness) worked fine since the IP didn't change.

**Fix**: Update MAC via config flow (Settings → Integrations → Frame Art Shuffler → Configure →
Edit TV → update MAC field). Direct file edit of `core.config_entries` doesn't work because HA
overwrites the file on shutdown with its in-memory state. Also needed: enable WoL for the wired
interface in TV settings.

**Config flow 500 error** encountered during fix: HA 2026.3.0 made `OptionsFlow.config_entry`
a read-only property. Our `__init__` was setting `self.config_entry = config_entry` which raised
`AttributeError`. Fixed by removing the `__init__` — HA provides `config_entry` automatically.

### samsungtv_smart Interference with WOL (March 2026)
The `samsungtv_smart` HA integration (HACS, by ollo69) caused WOL wake failures on the
office TV. It runs a background TCP ping to port 9197 **every 1 second** and opens WebSocket
connections when the ping succeeds. This prevented the TV from entering proper deep sleep,
making WOL unreliable (40% failure rate, requiring 2-3 attempts).

**Fix**: Removed the `samsungtv_smart` config entry for the office TV. FAS handles all
Frame TV operations directly. Also deleted the redundant `office_samsung_frame_tv_motion_control`
HA automation that had been using `media_player.office_frame` (already disabled, last triggered
Oct 2025).

**Key lesson**: If WOL becomes unreliable for a TV, check whether another integration
(samsungtv_smart, samsungtv, dlna_dmr, etc.) is maintaining connections to the same TV.
Two integrations polling the same TV on the same WebSocket port is a recipe for conflicts.

## Important Conventions

- Single-instance integration (only one config entry allowed)
- Token files stored in `tokens/` directory (gitignored, device-specific)
- Services raise `ServiceValidationError` for user-visible errors
- Custom exceptions: `FrameArtError` → `FrameArtConnectionError`, `FrameArtUploadError`
- Dashboard auto-regenerates when TVs change; requires `layout-card` frontend component
