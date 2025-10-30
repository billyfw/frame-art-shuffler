# TV State Reference Guide

## Understanding TV States

Samsung Frame TVs have **two independent states**:

### 1. Screen State
- **On**: Screen is lit and displaying content
- **Off**: Screen is black (power saving mode)

### 2. Mode State  
- **Art Mode**: TV configured to display artwork
- **TV Mode**: TV configured for regular TV viewing (channels, apps, etc.)

## All Possible Combinations

| Screen | Mode | Description | `is_screen_on()` | `is_art_mode_enabled()` |
|--------|------|-------------|------------------|------------------------|
| **ON** | **Art** | 🖼️ Displaying artwork | ✅ True | ✅ True |
| **ON** | **TV** | 📺 Watching TV/apps | ✅ True | ❌ False |
| **OFF** | **Art** | 😴 Standby (art mode active) | ❌ False | ✅ True |
| **OFF** | **TV** | 💤 Fully off | ❌ False | ❌ False |

## Function Behavior

### `is_art_mode_enabled(ip)`
**What it checks**: Is the TV configured for art mode?  
**Use case**: "Can I upload artwork / change brightness?"

```python
# Returns True if art mode is enabled (screen may be on or off)
if is_art_mode_enabled(tv_ip):
    set_tv_brightness(tv_ip, 5)  # This will work
```

### `is_screen_on(ip)`
**What it checks**: Is the screen physically displaying something?  
**Use case**: "Is the TV visible / using power?"

```python
# Returns True only if screen is actively displaying
if is_screen_on(tv_ip):
    print("TV is on and visible")
else:
    print("TV screen is off (power saving)")
```

## Command Examples

### Scenario 1: Screen Off, Art Mode Active
```bash
$ python scripts/frame_tv_cli.py 192.168.1.249 screen-status
Screen is off (standby/power saving)

$ python scripts/frame_tv_cli.py 192.168.1.249 status  
Art mode is enabled

# Art operations still work!
$ python scripts/frame_tv_cli.py 192.168.1.249 brightness 5
Brightness set to 5
```

### Scenario 2: Screen On, TV Mode
```bash
$ python scripts/frame_tv_cli.py 192.168.1.249 screen-status
Screen is on (displaying content)

$ python scripts/frame_tv_cli.py 192.168.1.249 status
Art mode is not enabled

# Need to switch modes first
$ python scripts/frame_tv_cli.py 192.168.1.249 art-mode
TV switched to art mode
```

### Scenario 3: Complete Workflow
```bash
# Check states
$ python scripts/frame_tv_cli.py 192.168.1.249 screen-status
Screen is off (standby/power saving)

$ python scripts/frame_tv_cli.py 192.168.1.249 status
Art mode is not enabled

# Turn on and switch to art mode
$ python scripts/frame_tv_cli.py 192.168.1.249 on
Power on command sent

$ python scripts/frame_tv_cli.py 192.168.1.249 art-mode
TV switched to art mode

# Now both should be true
$ python scripts/frame_tv_cli.py 192.168.1.249 screen-status
Screen is on (displaying content)

$ python scripts/frame_tv_cli.py 192.168.1.249 status
Art mode is enabled
```

## Python Code Examples

### Check Both States
```python
from custom_components.frame_art_shuffler.frame_tv import (
    is_art_mode_enabled,
    is_screen_on,
    tv_on,
    set_art_mode,
)

tv_ip = "192.168.1.249"

# Comprehensive status check
screen_on = is_screen_on(tv_ip)
art_enabled = is_art_mode_enabled(tv_ip)

if screen_on and art_enabled:
    print("✅ Screen on, displaying artwork")
elif screen_on and not art_enabled:
    print("📺 Screen on, in TV mode")
elif not screen_on and art_enabled:
    print("😴 Screen off, art mode standby")
else:
    print("💤 Fully off")
```

### Smart Preparation
```python
# Ensure TV is ready for art operations
def prepare_tv_for_art(tv_ip: str, tv_mac: str):
    """Ensure TV is on and in art mode."""
    
    # Turn screen on if needed
    if not is_screen_on(tv_ip):
        print("Turning screen on...")
        tv_on(tv_ip, tv_mac)
        time.sleep(2)  # Give it a moment
    
    # Switch to art mode if needed
    if not is_art_mode_enabled(tv_ip):
        print("Switching to art mode...")
        set_art_mode(tv_ip)
        time.sleep(2)
    
    print("TV ready for art operations!")

# Use it
prepare_tv_for_art("192.168.1.249", "28:AF:42:18:64:08")
set_tv_brightness("192.168.1.249", 7)
```

## Backwards Compatibility

The old `is_tv_on()` function still works but is deprecated:
```python
# Old way (deprecated but works)
if is_tv_on(tv_ip):  # Checks art mode only
    ...

# New way (clearer)
if is_art_mode_enabled(tv_ip):  # Same behavior, clearer name
    ...

# Check screen separately
if is_screen_on(tv_ip):
    ...
```

## Common Patterns

### 1. "Wake up and show art"
```bash
python scripts/frame_tv_cli.py 192.168.1.249 on --mac 28:AF:42:18:64:08
python scripts/frame_tv_cli.py 192.168.1.249 art-mode
python scripts/frame_tv_cli.py 192.168.1.249 upload artwork.jpg
```

### 2. "Update art while screen is off"
```bash
# Works even with screen off if art mode is enabled!
python scripts/frame_tv_cli.py 192.168.1.249 upload artwork.jpg
python scripts/frame_tv_cli.py 192.168.1.249 brightness 5
```

### 3. "Turn off screen but keep art ready"
```bash
python scripts/frame_tv_cli.py 192.168.1.249 off
# Screen goes off, art mode stays enabled
# Art websocket still works for brightness/upload
```
