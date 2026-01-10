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
- **HA Log**: `/config/home-assistant.log`
- **Display Logs**: `/config/frame_art/logs/events.json`
- **Display Summary**: `/config/frame_art/logs/summary.json`

### Useful Commands
```bash
# View recent integration logs
grep 'frame_art_shuffler' /config/home-assistant.log | tail -50

# Watch logs in real-time (for shuffle events)
tail -f /config/home-assistant.log | grep -E '(shuffle|selected|fresh)'

# Check display log events
tail -100 /config/frame_art/logs/events.json

# Restart Home Assistant
ha core restart
```

### Logging Configuration
The integration is set to debug level in `/config/configuration.yaml`:
```yaml
logger:
  logs:
    custom_components.frame_art_shuffler: debug
```

## Important Conventions

- Single-instance integration (only one config entry allowed)
- Token files stored in `tokens/` directory (gitignored, device-specific)
- Services raise `ServiceValidationError` for user-visible errors
- Custom exceptions: `FrameArtError` → `FrameArtConnectionError`, `FrameArtUploadError`
- Dashboard auto-regenerates when TVs change; requires `layout-card` frontend component
