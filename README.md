# Frame Art Shuffler (Home Assistant Integration)

This repository scaffolds a Home Assistant custom integration resp## Requirements

The integration depends on the [Nick Waterton fork of `samsungtvws`](https://github.com/NickWaterton/samsung-tv-ws-api) (version 3.0.3) for websocket-level control of Samsung TVs. This fork includes fixes for image uploads and improved art mode handling compared to the official PyPI release. Home Assistant will install this requirement automatically when the integration is loaded.

The official PyPI version (`samsungtvws` 2.7.2) has issues with image uploads ("Broken pipe" errors), while the Waterton fork handles uploads reliably. Both versions support brightness control and status queries.

### Dashboard Dependency (Optional)

The auto-generated dashboard uses [`layout-card`](https://github.com/thomasloven/lovelace-layout-card) for responsive mobile layout (3 columns on desktop → 1 column on mobile). Install via HACS:

1. Open **HACS → Frontend → Explore & Download Repositories**
2. Search for "layout-card" and install it
3. Restart Home Assistant

Without `layout-card`, the dashboard will show an error. You can still use all integration features by creating your own dashboard with the exposed entities.

## Important: TV Power States and Art Mode

Samsung Frame TVs have specific behavior regarding art mode and remote control commands:

- **Art Mode is Standby**: When the TV displays artwork, it's in a low-power standby state, not fully on
- **Power Off = Screen Off**: The `tv_off()` function holds `KEY_POWER` for 3 seconds, which turns the screen off while keeping the TV in art mode (matching the behavior of the Samsung Smart TV integration's `media_player.turn_off`)
- **Power On = Wake via WOL**: The `tv_on(ip, mac_address)` function broadcasts a Wake-on-LAN packet to wake the TV's network interface. The TV will wake to its default state (typically art mode if that was the last active mode). This function intentionally does NOT send KEY_POWER to avoid unpredictable toggle behavior.
- **Switching to Art Mode**: Use `set_art_mode()` to switch from TV mode to art mode programmatically. This function sends KEY_POWER to the TV, which switches it to art mode when the TV is showing content. This is reliable and works even when actively watching TV or using apps.
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
- `is_art_mode_enabled(ip)` – Return `True` when art mode is enabled (screen may be on or off).
- `is_screen_on(ip)` – Return `True` when the screen is actually on and displaying content.
- `tv_on(ip, mac_address)` – Wake the TV's network interface via Wake-on-LAN. The TV wakes to its default state. Does not send KEY_POWER to avoid toggle issues.
- `tv_off(ip)` – Turn the screen off while staying in art mode by holding `KEY_POWER` for 3 seconds (matches Samsung Smart TV integration's `media_player.turn_off` behavior).
- `set_art_mode(ip)` – Switch the TV to art mode by sending KEY_POWER. Works reliably even when TV is actively playing content. If already in art mode, this is a no-op.

**Note**: `is_tv_on(ip)` is deprecated but kept for backwards compatibility. Use `is_art_mode_enabled(ip)` instead.

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
	is_art_mode_enabled,
	is_screen_on,
	tv_on,
	tv_off,
	set_art_mode,
)

TV_IP = "192.168.1.249"
TV_MAC = "28:AF:42:18:64:08"
IMAGE_PATH = "/path/to/artwork.jpg"

try:
	# Check if screen is on
	if not is_screen_on(TV_IP):
		tv_on(TV_IP, TV_MAC)  # Wake via WOL
		time.sleep(3)  # Give TV time to wake
	
	# Ensure we're in art mode
	if not is_art_mode_enabled(TV_IP):
		set_art_mode(TV_IP)
	
	# Ensure we're in art mode
	if not is_art_mode_enabled(TV_IP):
		set_art_mode(TV_IP)

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
- `on --mac <MAC>` – Wake the TV via Wake-on-LAN (does not send KEY_POWER).
- `off` – Turn screen off (holds KEY_POWER for 3 seconds, stays in art mode).
- `art-mode` – Switch TV to art mode (if currently in TV mode or other state).
- `status` – Check if art mode is enabled. Exit code 0 if enabled, 1 otherwise.
- `screen-status` – Check if screen is on (displaying content). Exit code 0 if on, 1 if off.
- `brightness <value>` – Set the art-mode brightness (valid values: 1–10 or 50).

Example:

```bash
# Check if screen is on
python scripts/frame_tv_cli.py 192.168.1.249 screen-status

# Check if art mode is enabled
python scripts/frame_tv_cli.py 192.168.1.249 status

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

## HACS installation

You can install the integration manually via HACS while it’s under active development:

1. In Home Assistant, open **HACS → Integrations → Custom repositories**.
3. Search for “Frame Art Shuffler” in the HACS Integrations list and install it.
4. Restart Home Assistant to load the integration.
5. Go to **Settings → Devices & Services → Add Integration** and pick **Frame Art Shuffler**.
6. Enter a unique Home name.


### Developing without publishing a release

When you want to iterate on the integration without cutting a new GitHub release, copy (or symlink) the component straight into your Home Assistant config directory. The helper script `scripts/dev_deploy.sh` automates these steps by bumping the manifest to a unique `+dev` version, syncing the files over SSH, and reloading the config entry. To run it with defaults (Home Assistant at `homeassistant.local`):

```bash
./scripts/dev_deploy.sh
```

To perform the process manually instead:

1. Stop Home Assistant or ensure you can restart it after copying files.
2. From the HA host, create the custom-component folder if it doesn't exist:
	```bash
	mkdir -p /config/custom_components
	```
3. Copy this repository’s `custom_components/frame_art_shuffler` folder into `/config/custom_components/` (or create a symlink if you mount the repo on the HA host).
4. If HACS already installed the integration, open **HACS → Integrations**, select Frame Art Shuffler, and choose **Reinstall** with the *local* version checkbox so HACS tracks your working copy.
5. Restart Home Assistant. The updated Python files load immediately; no release or version bump is required while you are testing locally.

Tips:

- When iterating rapidly, set `version` in `manifest.json` to something like `0.1.0-dev` so you can distinguish local builds in the UI.
- Use the Home Assistant developer tools → **Reload** helpers for quick retests (or call `homeassistant.reload_config_entry` with the Frame Art Shuffler entry ID) after editing code.
- Keep `metadata.json` and `frame_art_shuffler/tokens/` backed up so a failed experiment doesn't lose your art library or pairing tokens.

### Git Setup (One-Time Per Machine)

After cloning the repo on a new machine, run:

```bash
./scripts/setup-git-hooks.sh
```

This configures a custom git merge driver that auto-resolves `manifest.json` version conflicts by keeping the higher version. Without this, you'll get merge conflicts when `dev_deploy.sh` has bumped the version on different machines.

### Managing TVs via Options flow

After creating the integration entry, Home Assistant registers a dedicated device and status sensor for each TV (state shows the IP address with tags and metadata exposed as attributes). You can monitor these to verify metadata updates without waiting for future control entities.

Open **Configure** on the integration card to manage TVs:

- **Add TV**: Provide name, IP/hostname, MAC address, and shuffle frequency. The flow automatically pairs the TV to create a token file in the configured token directory. Disable pairing only if you already copied tokens manually.
- **Edit TV**: Update settings; future automation can react.
- **Delete TV**: Removes the TV from the integration.

If token pairing ever breaks (for example, after clearing the TV's authorized devices), open the integration entry and choose **Re-authenticate**; the flow recreates the token file while preserving metadata.

### Dashboard Setup (Optional)

The integration generates a Lovelace dashboard YAML file with controls and status for all configured Frame TVs. The dashboard is generated automatically when you add TVs, but you need to manually register it in your `configuration.yaml` to make it appear in the sidebar.

Add this to your `configuration.yaml`:

```yaml
lovelace:
  mode: storage
  dashboards:
    frame-art-shuffler:
      mode: yaml
      title: Frame Art Shuffler
      icon: mdi:television-ambient-light
      show_in_sidebar: true
      filename: custom_components/frame_art_shuffler/dashboards/frame_tv_manager.yaml
```

Then restart Home Assistant. The "Frame Art Shuffler" dashboard will appear in the sidebar with:

- **Per-TV Controls**: Brightness sliders, shuffle buttons, TV on/off buttons
- **Status Sensors**: Art mode, motion detection, screen state
- **Activity History**: Recent events (brightness changes, motion events, shuffle actions) with timestamps

**Note**: The dashboard YAML file is regenerated automatically whenever you add, edit, or remove TVs via the integration's options flow. Your `configuration.yaml` reference just points to the file—you don't need to update it when TV configuration changes.

## Testing checklist

1. Install via HACS and create the integration entry with a new Home name.
2. In the Options flow, add a TV and confirm a token file appears under `config/frame_art_shuffler/tokens/`.
3. Edit the TV in the options flow and confirm the settings update.
4. Delete the TV and verify it is removed.
5. Watch the Home Assistant logs for pairing success or errors (`Logger: custom_components.frame_art_shuffler`).

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
