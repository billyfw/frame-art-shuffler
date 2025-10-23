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
- **Result**: Screen turns off, TV stays in art mode
- **Same as**: Samsung Smart TV integration's `media_player.turn_off` for Frame TVs

### Power On (`tv_on`)

```python
remote.send_key("KEY_POWER")
```

- Sends a single `KEY_POWER` press
- **Result**: Screen turns back on from screen-off state
- TV remains in art mode

## Why This Matters

Frame TVs have special power behavior:

1. **Art mode is a standby state** - the TV is "on" but in low power
2. **Short KEY_POWER press** - wakes screen from screen-off
3. **Long KEY_POWER hold (3s)** - turns screen off while maintaining art mode
4. **Other keys** (KEY_HOME, KEY_MENU) - fully wake the TV from art mode

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

# Test power on (screen should turn back on)
python scripts/frame_tv_cli.py 192.168.1.249 on

# Verify art mode still works
python scripts/frame_tv_cli.py 192.168.1.249 brightness 5
```

## Implementation History

- Initial implementation used `KEY_POWEROFF` / `KEY_POWER` fallback (didn't work correctly)
- Updated to use `hold_key("KEY_POWER", 3)` after discovering Frame-specific behavior in HA core
- Verified working with Samsung Frame TV (2024 model)
