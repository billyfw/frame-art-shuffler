# Frame TV Power Command Implementation

## Overview

This integration implements Frame TV-specific power commands that match the behavior of Home Assistant's Samsung Smart TV integration.

## How It Works

### Power Off (`tv_off`)

```python
remote.hold_key("KEY_POWER", 3)
```

- **Holds** the `KEY_POWER` button for **3 seconds**
- This is Frame TV-specific behavior (discovered from HA core `samsungtv` integration)
- **Result**: Screen turns off while TV stays in art mode
- **Same as**: Samsung Smart TV integration's `media_player.turn_off` for Frame TVs

### Power On (`tv_on`)

```python
_send_wake_on_lan("28:AF:42:18:64:08")
time.sleep(2)
# Done - no KEY_POWER sent
```

- Sends a Wake-on-LAN packet to wake the TV's network interface
- The TV wakes to its default state (typically art mode if that was last active)
- **Does NOT send KEY_POWER** to avoid unpredictable toggle behavior
- If you need to ensure art mode after waking, call `set_art_mode()` separately

### Switch to Art Mode (`set_art_mode`)

```python
remote.send_key("KEY_POWER")
```

- Sends a single `KEY_POWER` press (same as `tv_on`)
- **Result**: Switches TV from TV/app content to art mode
- **Works reliably** even when actively watching TV or using apps
- Discovered from Nick Waterton's `async_art_ensure_art_mode.py` example

## Why This Matters

Frame TVs have special power behavior:

1. **Art mode is a standby state** - the TV is "on" but in low power
2. **KEY_POWER press when showing content** - switches TV to art mode
3. **KEY_POWER hold (3s) when in art mode** - turns screen off while staying in art mode
4. **KEY_POWER press when screen off** - turns screen back on
5. **Other keys** (KEY_HOME, KEY_MENU) - fully wake the TV from art mode to normal TV operation

## Source Code Reference

From Home Assistant core `homeassistant/components/samsungtv/bridge.py`:

```python
async def _async_send_power_off(self) -> None:
    """Send power off command to remote."""
    if self._get_device_spec("FrameTVSupport") == "true":
        await self._async_send_commands(SendRemoteKey.hold("KEY_POWER", 3))
    else:
        await self._async_send_commands([SendRemoteKey.click("KEY_POWER")])
```

## Integration Modes

### Standalone Mode
- This integration handles all Frame TV control
- Users don't need Samsung Smart TV integration
- Simple, focused on art mode

### Hybrid Mode (Optional)
- Install both `frame_art_shuffler` + `samsungtv` integration
- Use Samsung integration for media_player features (volume, apps, channels)
- Use this integration for art-specific operations
- Both share the same token file - no additional authorization needed

## Testing

```bash
# Test power off (screen should turn off, TV stays in art mode)
python scripts/frame_tv_cli.py 192.168.1.249 off

# Test power on (Wake-on-LAN only)
python scripts/frame_tv_cli.py 192.168.1.249 on --mac 28:AF:42:18:64:08

# Verify art mode still works
python scripts/frame_tv_cli.py 192.168.1.249 brightness 5
```

## Implementation History

- Initial implementation used `KEY_POWEROFF` / `KEY_POWER` fallback (didn't work correctly)
- Updated to use `hold_key("KEY_POWER", 3)` after discovering Frame-specific behavior in HA core
- Verified working with Samsung Frame TV (2024 model)
