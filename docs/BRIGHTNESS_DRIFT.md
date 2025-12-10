# Brightness Drift Issue

## Summary

A rare intermittent issue where the TV appears dim after a shuffle despite logs showing brightness was successfully set to the expected value (e.g., 10).

## Symptoms

- TV screen appears visually dim after a shuffle
- Logs show "Brightness set to 10" with TV confirmation
- Manual brightness adjustment immediately fixes the issue
- No errors in logs
- TV's `brightness_sensor_setting` is confirmed `off` (no auto-brightness)

## Observed Instances

| Date | Time | Image | Expected | Actual (visual) | Notes |
|------|------|-------|----------|-----------------|-------|
| 2025-12-10 | ~11:54 | 3-copy-9965fbf7.jpg | 10 | Dim | Fixed by manual set to 4 then 10 |

## Investigation Findings

From the 2025-12-10 incident:
- `3-copy` shuffle started at 11:50:52
- Post-shuffle brightness sync set brightness to 10 at 11:51:24
- TV confirmed brightness = 10 at 11:51:27 (via `get_artmode_settings`)
- TV's `brightness_sensor_setting` = `off`
- No brightness commands between 11:51:27 and manual intervention at 11:55:52
- Previous shuffle (`img-6207` at 11:36) worked correctly with same brightness setting

## Mitigation Implemented

### 1. Delayed Verification with Auto-Correction

After each post-shuffle brightness sync:
1. Wait 5 seconds for TV to settle after image rendering
2. Query actual brightness from TV
3. If mismatch detected: log at WARNING level and re-set brightness
4. If match: log at DEBUG level

### 2. Logging Strategy

| Condition | Log Level | Message Pattern |
|-----------|-----------|-----------------|
| Normal verification | DEBUG | `Post-shuffle brightness verified for {tv}: {value}` |
| Drift detected | WARNING | `Brightness drift detected for {tv}: expected X, TV reports Y. Re-setting.` |
| Verification failed | DEBUG | `Post-shuffle brightness verification failed for {tv}: {error}` |

### How to Troubleshoot Future Occurrences

1. **Check HA logs** for WARNING level entries containing "Brightness drift"
2. **If no warning logged** but TV is dim, the drift happened after our 5-second check
3. **Use grep to find relevant entries:**
   ```bash
   ssh ha "grep -E 'Brightness drift|Post-shuffle brightness|shuffle.*selected' /config/home-assistant.log | grep 'YYYY-MM-DD HH:' | tail -50"
   ```
4. **Check TV's reported settings:**
   ```bash
   ssh ha "grep 'get_artmode_settings' /config/home-assistant.log | grep 'YYYY-MM-DD HH:' | tail -10"
   ```

## Possible Root Causes (Unconfirmed)

1. **Samsung firmware quirk** - TV accepts brightness command but doesn't apply it during image render transition
2. **Race condition** - New image rendering resets brightness before our verification
3. **WebSocket state** - TV confirms value but internal state differs
4. **Image-specific behavior** - Certain images may trigger different rendering paths

## Related Files

- `custom_components/frame_art_shuffler/__init__.py` - `async_sync_brightness_after_shuffle()`
- `custom_components/frame_art_shuffler/frame_tv.py` - `set_tv_brightness()`, `get_tv_brightness()`
- `custom_components/frame_art_shuffler/shuffle.py` - Calls brightness sync after upload

## Future Improvements to Consider

- Add configurable delay before brightness verification (currently 5s)
- Add option for multiple re-verification attempts
- Log brightness drift events to Recent Activity for visibility
