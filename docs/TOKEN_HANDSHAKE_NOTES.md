# Samsung Frame TV Token Handshake Notes

## Summary of Findings (October 22, 2025)

After extensive testing, we've identified the correct token handshake pattern for Samsung Frame TVs and resolved several issues.

## Token Storage Pattern

### Working Pattern
- **One token file per TV**: `{IP_ADDRESS}.token` (e.g., `192.168.1.249.token`)
- **Location**: `custom_components/frame_art_shuffler/tokens/`
- **Content**: 8-byte token string saved by samsungtvws library
- **Reuse**: Same token works for both remote control and art mode operations

### Connection Flow
```python
# Create connection with token_file parameter
tv = SamsungTVWS(host=IP, port=8002, token_file=token_path, timeout=90)

# For remote control operations (power, keys)
tv.open()
tv.send_key("KEY_POWER")

# For art mode operations (brightness, upload, display)
art = tv.art()  # Creates separate art websocket
art.get_brightness()
art.set_brightness(5)
```

## Key Discoveries

### 1. Art Mode vs Remote Control
- **Art mode = standby**: TV displays artwork in low-power state
- **Remote keys wake TV**: Sending `KEY_HOME`, `KEY_MENU`, etc. will turn TV fully on
- **Art operations preserve mode**: Brightness, upload, display operations keep TV in art mode

### 2. Token Handshake
- **First connection**: TV shows "Allow" prompt, user must approve
- **Token saved automatically**: samsungtvws library saves token when approved
- **Subsequent connections**: Token read from file, no TV prompt needed
- **Single token**: Same token file works for both remote and art websockets

### 3. Handshake Without Waking TV
```python
# ✓ CORRECT: Opens connections without waking TV
tv = SamsungTVWS(host=IP, port=8002, token_file=token_path)
tv.open()  # May prompt for approval, but doesn't wake TV
art = tv.art()  # Second prompt if needed, also doesn't wake
art.get_brightness()  # Works in art mode

# ✗ WRONG: These wake the TV from art mode
tv.open()
tv.send_key("KEY_HOME")  # Wakes TV!
tv.send_key("KEY_MENU")  # Wakes TV!
```

### 4. Type Coercion Bug
- **Issue**: Library's `art.get_brightness()` returns string `"5"` not int `5`
- **Fix**: Use `int(art.get_brightness())` instead of `cast(int, ...)`
- **Impact**: Comparison `"5" == 5` failed, causing false errors

## Integration Implementation

### Session Pattern
```python
class _FrameTVSession:
    def __init__(self, ip: str):
        self.token_path = _token_path(ip)
        self._remote = _build_client(ip, self.token_path)
        self._art = self._remote.art()  # Art from same connection
```

### Brightness Helper
```python
def _get_brightness_value(art: Any) -> int:
    if hasattr(art, "get_brightness"):
        return int(art.get_brightness())  # Force int conversion
    # Fallback to raw JSON request...
```

### Power Commands (Separate from Art)
```python
def tv_on(ip: str, mac_address: str):
  _send_wake_on_lan(mac_address)
  token_path = _token_path(ip)
  remote = _build_client(ip, token_path)
  try:
    remote.open()
    remote.send_key("KEY_POWERON")
  finally:
    remote.close()
```

## Testing Results

### ✓ Working Commands
```bash
# Brightness control (stays in art mode)
python3 scripts/frame_tv_cli.py 192.168.1.249 brightness 8
# Output: Brightness set to 8

# Status check
python3 scripts/frame_tv_cli.py 192.168.1.249 status
# Output: TV is in art mode

# Testdev script
cd frame_art_testdev
python3 test_connection.py --brightness 10
# Output: SUCCESS! ... ✓ Everything works! TV stayed in art mode.
```

### Token Verification
```bash
# Token exists and has content
ls -lh custom_components/frame_art_shuffler/tokens/192.168.1.249.token
# -rw-r--r--  8B Oct 22 09:10

# Same token works in testdev
ls -lh frame_art_testdev/frame_tv_token.txt
# -rw-r--r--  8B Oct 22 09:10
```

## Troubleshooting Guide

### TV Timeout Errors
- **Symptom**: `{'event': 'ms.channel.timeOut'}`
- **Causes**:
  1. TV not responding (needs power cycle)
  2. TV in wrong mode (fully on instead of art mode)
  3. Network issues
- **Solution**: Power cycle TV, verify art mode, check network

### Token Not Saved
- **Symptom**: No token file after approval
- **Causes**:
  1. Didn't click "Allow" on TV
  2. Connection closed before token write
  3. File permission issues
- **Solution**: Ensure user clicks Allow, wait 5+ seconds after approval

### TV Wakes from Art Mode
- **Symptom**: TV turns fully on when using integration
- **Cause**: Code is calling `remote.send_key()` with wake keys
- **Solution**: Only use art operations for brightness/upload; avoid remote keys

### Type Comparison Failures
- **Symptom**: `"TV reported brightness 5 after setting 5"` but it's an error
- **Cause**: String vs int comparison
- **Solution**: Use `int()` conversion in `_get_brightness_value()`

## Best Practices

1. **Token Management**
   - One token file per TV IP
   - Store with integration for bundling
   - 8 bytes is normal size
   - Reuse across restarts

2. **Art Mode Preservation**
   - Use art operations for brightness, upload, display
   - Avoid remote control keys when in art mode
   - Don't call `tv.open()` + `send_key()` for art operations

3. **Connection Pattern**
   - Let library handle token auth automatically
   - Don't manually call `.open()` for art operations
   - Use same token for remote and art websockets

4. **Type Safety**
   - Always convert library responses to expected types
   - Don't rely on `cast()` for runtime conversion
   - Use explicit `int()`, `str()`, etc.

## Library Versions

- **samsungtvws**: Nick Waterton fork version 3.0.3
- **Source**: `git+https://github.com/NickWaterton/samsung-tv-ws-api.git`
- **Rationale**: 
  - Official PyPI version 2.7.2 has broken pipe errors on image uploads
  - Waterton fork 3.0.3 handles uploads reliably
  - Fork includes native brightness methods (`get_brightness()`, `set_brightness()`)
  - After TV reset, handshakes work correctly with both versions
  - Upload functionality only works with the fork
- **Note**: The testdev scripts use this fork from system Python, which is why uploads work there but failed with PyPI 2.7.2

## Related Files

- `custom_components/frame_art_shuffler/frame_tv.py` - Main helper implementation
- `scripts/frame_tv_cli.py` - CLI wrapper
- `frame_art_testdev/test_connection.py` - Legacy test script (reference)
- `README.md` - Integration documentation

## Handshake Logic Update (November 24, 2025)

### The "Handshake First" Requirement
We discovered a critical behavior difference between the **Remote Control Channel** (`samsung.remote.control`) and the **Art Mode Channel** (`com.samsung.art-app`):

1.  **Remote Control Channel**: Supports the initial handshake. If no token is provided (or `token=None`), it triggers the "Allow" prompt on the TV and returns a new token upon approval.
2.  **Art Mode Channel**: **Does NOT** support the initial handshake. If you attempt to connect without a valid token, the TV simply disconnects the client immediately (often resulting in `ms.channel.timeOut` or `ms.channel.clientDisconnect`).

### The Fix
To ensure robust connections in new environments (like a fresh HA install or a new TV IP) where a token file does not yet exist:

1.  **Check for Token**: The code first checks if a token file exists for the target IP.
2.  **Handshake via Remote**: If the token is missing, the code **must** first open a connection to the **Remote Control Channel**. This triggers the pairing process.
3.  **Save Token**: Once the handshake completes and the token is saved to disk, the Remote connection is closed.
4.  **Connect to Art**: The code then proceeds to open the **Art Mode Channel** using the newly acquired token.

This logic is implemented in `_FrameTVSession.__init__` in `frame_tv.py`.

### Client Name
We also updated the client name from `SamsungTvRemote` to `FrameArtShuffler` to ensure a clean session ID and avoid conflicts with other integrations.
