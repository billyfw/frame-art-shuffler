# Frame Art Shuffler (Home Assistant Integration)

This repository scaffolds a Home Assistant custom integration resp## Requirements

The integration depends on the [Nick Waterton fork of `samsungtvws`](https://github.com/NickWaterton/samsung-tv-ws-api) (version 3.0.3) for websocket-level control of Samsung TVs. This fork includes fixes for image uploads and improved art mode handling compared to the official PyPI release. Home Assistant will install this requirement automatically when the integration is loaded.

The official PyPI version (`samsungtvws` 2.7.2) has issues with image uploads ("Broken pipe" errors), while the Waterton fork handles uploads reliably. Both versions support brightness control and status queries.

## Important: TV Power States and Art Mode

Samsung Frame TVs have specific behavior regarding art mode and remote control commands:

- **Art Mode is Standby**: When the TV displays artwork, it's in a low-power standby state, not fully on
- **Power Off = Screen Off**: The `tv_off()` function holds `KEY_POWER` for 3 seconds, which turns the screen off while keeping the TV in art mode (matching the behavior of the Samsung Smart TV integration's `media_player.turn_off`)
- **Power On = Screen On**: The `tv_on()` function sends `KEY_POWER` to turn the screen back on. If the TV was in art mode, it returns to art mode. If it was in TV mode, it returns to TV mode.
- **Switching to Art Mode**: Use `set_art_mode()` to explicitly switch from TV mode to art mode when the TV is already powered on
- **Remote Keys Wake the TV**: Sending other remote control keys (like `KEY_HOME`, `KEY_MENU`) will fully wake the TV from art mode
- **Art Operations Don't Wake TV**: Operations like `set_tv_brightness()`, `set_art_on_tv_deleteothers()`, and `is_tv_on()` work with the art websocket and keep the TV in art mode

**Best Practice**: The power commands (`tv_on()`/`tv_off()`) are designed to match the Samsung Smart TV integration's behavior - they control the screen state without exiting art mode. If you want to manage artwork and brightness while keeping the TV in art mode, these functions work correctly. To fully wake the TV to normal operation, use other remote keys.

## Relationship to Samsung Smart TV Integration

This integration can work **standalone** or **alongside** the official Home Assistant Samsung Smart TV integration:

### Standalone Mode (Current Setup)
- Handles art uploads, brightness, and basic power control (screen on/off)
- Simpler, focused on art mode management
- Good if you only use your Frame TV for displaying art
- No additional integrations needed

### Hybrid Mode (Optional)
- Install both `frame_art_shuffler` and Home Assistant's built-in `samsungtv` integration
- Use `media_player.samsung_*` entities for full TV control (volume, channels, apps, sources)
- Use `frame_art_shuffler` services for art-specific features (upload, gallery management, brightness)
- Both integrations share the same token file, so TV authorization is automatic
- Good if you want full TV control + specialized art management

**Recommendation**: Start with standalone mode. If you later need volume control, app launching, or channel switching, add the Samsung Smart TV integration for those features while keeping this integration for art-focused operations.

This repository scaffolds a Home Assistant custom integration responsible for managing and rotating art on Samsung Frame TVs. The goal is to complement the existing `ha-config` Home Assistant deployment and the `ha-frame-art-manager` add-on.

## Integration layout

```
custom_components/frame_art_shuffler/
├── __init__.py          # Minimal Home Assistant setup hook
├── const.py             # Shared constants
├── frame_tv.py          # Helper functions for talking to Frame TVs
└── manifest.json        # Home Assistant integration metadata
```

Tokens granted by Samsung Frame TVs are stored per-host under `custom_components/frame_art_shuffler/tokens/` to keep authentication persistent across restarts and bundled with the add-on.

## Python helper interface

The integration exposes a small helper library (`frame_tv.py`) with the following synchronous functions:

- `set_art_on_tv_deleteothers(ip, artpath, delete_others=True)` – Upload an image, show it in art mode, and optionally delete every other art item on the TV.
- `set_tv_brightness(ip, brightness)` – Change art-mode brightness (validated range 1–50; Frame TVs historically accept 1–10 and 50).
- `is_tv_on(ip)` – Return `True` when art mode is reachable and the TV reports `on`.
- `tv_on(ip)` – Turn the screen on (wake from screen-off state) by sending `KEY_POWER`. The TV remains in art mode if it was previously in art mode.
- `tv_off(ip)` – Turn the screen off while staying in art mode by holding `KEY_POWER` for 3 seconds (matches Samsung Smart TV integration's `media_player.turn_off` behavior).
- `set_art_mode(ip)` – Switch the TV to art mode if it's currently in TV mode or another state. If already in art mode, this is a no-op.

All functions raise subclasses of `FrameArtError` when operations fail, allowing Home Assistant platforms or automations to handle retries and surface errors gracefully.

## Token Management

### Authorization Flow

The first time you connect to a Frame TV, the library will request authorization:

1. A popup appears on the TV screen asking to "Allow" or "Deny" the connection
2. Select "Allow" on the TV remote
3. A token file is automatically saved to `custom_components/frame_art_shuffler/tokens/<IP>.token`
4. Future connections reuse this token - no re-authorization needed

### Multi-Device Usage

- **Each machine pairs independently**: Your laptop, desktop, and Home Assistant instance each get their own token
- **Multiple pairings are supported**: TVs can have multiple paired clients simultaneously
- **Tokens don't conflict**: Authorizing on your laptop won't invalidate your HA token
- **Not shared across machines**: Token files are gitignored and device-specific

### Security Note

Token files are authentication credentials and should **not** be committed to version control. They are automatically excluded via `.gitignore`.

## Try it

### Python shell

Activate the project virtual environment if you have not already:

```bash
source .venv/bin/activate
```

Then open a Python shell (or create a script) and import the helpers:

```python
from custom_components.frame_art_shuffler.frame_tv import (
	FrameArtError,
	set_art_on_tv_deleteothers,
	set_tv_brightness,
	is_tv_on,
	tv_on,
	tv_off,
	set_art_mode,
)

TV_IP = "192.168.1.249"
IMAGE_PATH = "/path/to/artwork.jpg"

try:
	# Turn screen on if needed (e.g., from screen-off state)
	tv_on(TV_IP)

	# If TV was in TV mode, switch to art mode
	set_art_mode(TV_IP)

	# Check art-mode status
	if not is_tv_on(TV_IP):
		print("TV not in art mode yet")

	# Upload and display artwork, deleting the rest of the gallery
	content_id = set_art_on_tv_deleteothers(TV_IP, IMAGE_PATH, delete_others=True)
	print(f"Uploaded as {content_id}")

	# Adjust brightness (valid values: 1-10 or 50)
	set_tv_brightness(TV_IP, 5)

	# When finished, optionally turn the screen off (stays in art mode)
	tv_off(TV_IP)

except FrameArtError as err:
	print(f"Frame TV operation failed: {err}")
```

Tokens will be cached per TV under `custom_components/frame_art_shuffler/tokens/`, so repeat executions reuse earlier authorizations. Replace `TV_IP` and `IMAGE_PATH` with values that match your environment.

### Command line (CLI)

A lightweight CLI wrapper lives in `scripts/frame_tv_cli.py`. Ensure the virtual environment is active, then invoke it like this:

```bash
source .venv/bin/activate
python scripts/frame_tv_cli.py <TV_IP> <command> [options]
```

Available commands:

- `upload <file>` – Upload an image and display it. Flags:
	- `--keep-others` keeps existing artwork instead of deleting everything else.
	- `--matte MATTE_ID` applies a matte.
	- `--brightness VALUE` sets the art-mode brightness after upload (1–10 or 50).
	- `--skip-ensure-art` skips forcing art mode before upload.
	- `--debug` enables verbose logging similar to the development scripts.
- `on` – Turn screen on (wakes from screen-off state).
- `off` – Turn screen off (holds KEY_POWER for 3 seconds, stays in art mode).
- `art-mode` – Switch TV to art mode (if currently in TV mode or other state).
- `status` – Exit with code 0 if art mode is reachable, 1 otherwise.
- `brightness <value>` – Set the art-mode brightness (valid values: 1–10 or 50).

Example:

```bash
# Switch TV to art mode if it's in TV mode
python scripts/frame_tv_cli.py 192.168.1.249 art-mode

# Upload artwork with a matte
python scripts/frame_tv_cli.py 192.168.1.249 upload ~/Pictures/frame_art.jpg --matte flexible_apricot

# Set brightness
python scripts/frame_tv_cli.py 192.168.1.249 brightness 5

# Turn screen off (stays in art mode)
python scripts/frame_tv_cli.py 192.168.1.249 off
```

The CLI shares the same token cache directory, so you only need to approve the TV once per device.

## About the `.venv` directory

The `.venv/` folder in the project root is a Python virtual environment created for this repository. It bundles an isolated copy of the Python interpreter plus the packages this integration depends on (for example, `samsungtvws`). Activating it ensures commands use the right interpreter and libraries without affecting your system-wide Python installation or other projects.

- Activate: `source .venv/bin/activate` (the shell prompt will show the environment name).
- Deactivate: run `deactivate` or close the terminal.
- Any `pip install` performed while the environment is active will install into `.venv/` only.

Home Assistant will manage its own environment when it loads the integration, but using this local virtual environment keeps development and manual testing consistent.

## Requirements

The integration depends on [`samsungtvws` 2.7.2](https://pypi.org/project/samsungtvws/) for websocket-level control of Samsung TVs. That version matches the behaviour used by the legacy `frame_art_testdev` scripts and plays nicely with your TV’s token handshake. Home Assistant will install this requirement automatically when the integration is loaded, and the provided `.venv` is pinned to the same release. Helper utilities layer on a small shim to provide the brightness controls that newer forks expose.

## Next steps

- Wire the helper functions into Home Assistant platforms (e.g., services or coordinators).
- Sync configuration/state with the `ha-frame-art-manager` add-on.
- Extend documentation with usage recipes and troubleshooting notes once automation flows are in place.
