# CLAUDE.md

> **This repository is public.** Nothing identifying goes in it, in any commit: no person's name, no email
> address, no place name (the house ids used as configuration keys are the exception), no host or tailnet
> name, no device serial or MAC, no token. The owner's private repositories hold those facts and point here.
> `scripts/check_no_pii.py` scans the working tree and the whole history on every push (CI job `no-pii`); a
> finding in history means a rewrite and a force-push, done once on 2026-10-24 (commit identities, names and
> places). Commits here carry the owner's GitHub no-reply address.
> `scripts/frame_tv_cli.py`'s default MAC is a documentation placeholder since that rewrite; pass your TV's.

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Workflow Preferences

**Never commit or deploy without explicit user approval.** When you believe a task is complete, ask the user whether to:
- **Commit**: `git commit` (with a succinct, meaningful message) + `git push`
- **Commit and deploy**: `git commit` (with a succinct, meaningful message) + `git push` + `./scripts/dev_deploy.sh --restart`

**Deploy is fire-and-forget**: When running `dev_deploy.sh`, use `run_in_background: true` and don't wait for output. The script is reliable and takes ~45 seconds. Continue the conversation immediately after launching it.

**Times are shown in Central Time**, never UTC: convert timestamps before displaying them (logs view, upload log, replies to the owner).

## Project Overview

Frame Art Shuffler is a Home Assistant custom integration for managing Samsung Frame TVs. It handles art uploads, brightness control, gallery management, image shuffling with tag-based filtering, and activity logging. The integration coordinates with a separate Frame Art Manager add-on via a shared `metadata.json` file.

## Multi-home migration (2026-07, in progress)

The frame-art system is being restructured for a second house (the second house): the manager add-on
moves to a single central Fly.io instance, and **this integration gains a `library_sync`
module** that mirrors `library/` + `metadata.json` from GitHub over HTTPS (Trees/Contents/
LFS-batch APIs, read-only PAT, no git binary), plus a `sync_library` service the central
manager pokes after each push, a sync-status sensor, and a logs `HomeAssistantView`.
The authoritative spec is
`~/devprojects/ha-frame-art-manager/docs/MULTI_HOME_PLAN.md` (§4 is this repo's work) —
read it before starting Phase 2.

## Wall tablets and the private library (0.4.0, 2026-10-03)

A target is a Frame TV or a **wall tablet** (`kind`, `targets.py`): a tablet is never contacted,
its pick is served by its Artwork image entity, its "screen on" mirrors a showing entity, and its
tags work as for a TV (no include tags = every picture; the owner, 2026-10-04). New entries keep the library outside www (default
`/media/frame_art`) because HA publishes www at `/local/` without login: Madrone's www library
(metadata.json and the private pictures) answered through its Nabu Casa URL with no credentials
on 2026-10-03. Design and what did not change: `docs/TABLET_TARGETS.md`. the second house (ha-lau) is the
first house to run it (house2-tablets `docs/frame-art-plan.md`).

## Power control per TV (0.5.0, 2026-10-25)

Each TV target carries an explicit `power_control` (`targets.power_control`, default `remote_keys`), chosen in the
options flow and never inferred from a model or a token file: `remote_keys` is the old path (3 s `KEY_POWER` hold,
two Wake-on-LAN packets, unchanged), `ip_control` is Samsung IP Control over HTTPS port 1516 (`ip_control.py`), a
real standby and power-on, for Frames that ignore the hold (2024 on: the hold flips Art Mode and TV mode). Every
power call site passes the TV's method to `tv_on`/`tv_off`; pairing is the options flow's `ip_control` steps, and
the key sits beside the WebSocket token as `<address>.ipcontrol.token`. The TV needs IP Remote and Power On with
Mobile on, and Access Notification Off (on Always On it re-asks to allow the WebSocket after every real off).
Design, bench results and gaps: `docs/POWER_CONTROL.md`; `tests/test_ip_control.py`, `tests/test_power_control.py`,
`tests/test_power_control_flow.py`.

## Presence sensors and motion control (0.6.0, 2026-10-27)

Motion control's sensors may be `occupancy` or `presence` binary sensors as well as `motion` (the forms'
`MOTION_SENSOR_CLASSES`), and the screen stays on while any of them reads on: the off delay counts from the moment
every sensor reads clear (`_sensor_in_use`; the off callback starts over while one reads on, and a clear restarts a
pending countdown). Before, the countdown ran from each turn to on, so an occupancy sensor holding on (an mmWave
radar, someone sitting still) had the screen turned off one delay after they sat down, and the forms offered no
occupancy sensor at all. Unloading the entry now cancels pending countdowns (after a reload the old one fired
once). Design and gaps: `docs/MOTION_CONTROL.md`; tests `tests/test_motion_presence.py`.

## Commands

### Testing
```bash
# once: Home Assistant 2026.9 (the houses' version) through pytest-homeassistant-custom-component
uv venv --python 3.14 .venv && VIRTUAL_ENV=.venv uv pip install -r requirements_test.txt
.venv/bin/python -m pytest                              # all (pure + real-HA tests)
.venv/bin/python -m pytest tests/test_tablet_targets.py  # the integration inside HA
```
`pytest.ini` sets `asyncio_mode = auto` so the pure tests run beside HA's test plugin.

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
- `POWER_CONTROL.md` - Per-TV power control: remote keys or Samsung IP Control (0.5.0)
- `MOTION_CONTROL.md` - Motion control: wake, hold while a sensor reads on, off delay from the clear (0.6.0)
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

### Display swaps back 30 s after a shuffle, then the TV sticks on its Art Mode menu (2026 Frame, the second house Great Room, 2026-10-22)
Symptoms: every auto shuffle shows the right picture and the previous one returns about 30 s later;
`Uploaded art MY_F00xx but could not verify display; check TV manually` on every shuffle; then a shuffle
fails mid upload and every later one fails with `TV <ip> is unreachable (timeout)` while the TV sits lit on
its Art Mode menu (the menu also keeps the TV's own sleep timer from firing).

Two causes, both on the 2026 Frame (QN85LS03H, art API 6.0.0.0):

1. The swap: the TV answers `get_current_artwork` with the same stale id (`SAM-F0222`) whatever is on
   screen. Until 0.4.3 `_display_uploaded_art` took a failed readback for a failed display and fell back
   to selecting the gallery's last entry, which is the previous picture, and `_delete_other_images` then
   deleted everything but the new upload.
2. The menu: an upload larger than the panel (both wedges were 4032x2268 iPhone shots; every upload at
   or under 3840x2160 worked, eight for eight) hangs the TV's art app about 14 s into `send_image`. The
   TV drops to its Art Mode menu, the art channel answers nothing there (nor on the Smart Hub screen; a
   `KEY_RETURN` over the remote channel was accepted and changed nothing), and it stays that way for
   minutes to hours until the art app comes back by itself or the remote's power button relaunches it.
   The first guess, that the TV dropped because the picture on screen had been deleted, was wrong: the
   07:45 HST wedge happened with nothing deleted from the screen. 280 of the 665 library files were
   oversize on 2026-10-23, so this hit roughly every other shuffle. The maintained Samsung integration
   (TheFab21/ha-samsungtv-smart, `api/_image_prep.py`) caps every upload to the panel for the same
   reason, as Samsung's own app does.

What the TV actually says (read on that TV, 2026-10-23 07:25 HST): `get_current_artwork` answers
`{"content_id": "SAM-F0222", "category_id": "DEFAULT_CATEGORY", "content_type": "artstore"}` before and
after a select of a My Photos picture, so on this firmware that request reports the Art Store slot, not what
is on the panel. The reply to `select_image` is the truthful signal: `{"event": "select_image",
"content_id": "MY_F0011", "is_shown": "Yes", ...}`. The unfiltered `get_content_list` is the "recently
set" list first (each entry labelled `MY-C0008`, newest first) followed by My Photos (`MY-C0002`), so the
list's last entry is an arbitrary photo, never the newest upload (TheFab21's decompiled firmware notes,
`notes/T-PTMDDEUC/ART_APP_3.50.106.md`, say the same for the 2025 art app).

Fix (0.4.3): `_fit_to_panel` shrinks any upload larger than 3840x2160 to fit the panel (baseline JPEG,
quality 92, EXIF orientation applied; an image that already fits is sent byte for byte); the display
path only ever selects the uploaded image; the TV's reply to `select_image` (event `select_image` or the
`image_selected` broadcast, naming the content id, `is_shown` not "No") counts as confirmation and skips
the readback wait; two reads of an unmoving readback mean "trusted, unverified" (`None`, one info line)
instead of failure; the cleanup keeps the image the TV reports as current as well as the new one. The
vendored `select_image` returns the TV's reply for this (`docs/VENDORING.md`). Tests:
`tests/test_frame_tv.py` (FakeArt, generated images). Not covered: other decode failures the maintained
integration re-encodes for (CMYK, 16-bit, palette); none seen here, and a progressive JPEG displayed fine.

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

### TV unreachable after a power loss (September 2026, office TV)
Symptoms: `tv_on()` sends both WoL packets, then logs "Could not check TV state after
Wake-on-LAN: Unable to connect"; the HA box cannot ARP the TV at all; and the auto-motion path
logs `Screen on (woken by <sensor>)` on every motion although `binary_sensor.<tv>_screen_on`
never turns on (the activity line is written when the WoL send completes, not when the screen
comes on). Cause: a mains interruption leaves a Frame in a cold standby with its network off, so
there is nothing for WoL to reach. Only a local power-on (remote or the TV's button) fixes it;
FAS resumes by itself afterwards. Real incident 2026-09-15 (house power blip at 13:10 CDT; the
full timeline is in ha-config's CLAUDE.md, Frame section). Two log facts learned then: the REST
reply line with `"ip":"<tv ip>"` is the only reliable reachability marker, and the 10-second
`Screen status check failed for <ip>` debug line fires constantly on the 32" office model even
when it is working. Fixed 2026-09-16: the motion-wake path now verifies the screen with
`verify_screen_on()` (three REST polls, 4 s apart) and logs `Wake sent, no answer from TV
(<sensor>)` (event `motion_wake_failed`) when nothing answers, cancelling the off timer it had
optimistically started; `Screen on (woken by ...)` is only written when the TV really answered.
Not built on purpose: backing off the WoL re-sends (one packet per motion event is harmless).
The house side has a matching phone alert in ha-config (`alert_if_officeframe_stays_dark_through_motion`).

## Important Conventions

- Single-instance integration (only one config entry allowed)
- Token files stored in `tokens/` directory (gitignored, device-specific)
- Services raise `ServiceValidationError` for user-visible errors
- Custom exceptions: `FrameArtError` → `FrameArtConnectionError`, `FrameArtUploadError`
- Dashboard auto-regenerates when TVs change; requires `layout-card` frontend component
