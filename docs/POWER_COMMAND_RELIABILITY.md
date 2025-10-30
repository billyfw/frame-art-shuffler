# Power Command Reliability

## Issue: REST API Timing

Samsung Frame TVs occasionally have timing issues where the REST API endpoint used during client initialization is temporarily unavailable or slow to respond.

## Symptoms

```bash
$ python scripts/frame_tv_cli.py 192.168.1.249 off
Error: Unable to connect to TV 192.168.1.249: TV unreachable or feature not supported

$ python scripts/frame_tv_cli.py 192.168.1.249 status
TV is in art mode

$ python scripts/frame_tv_cli.py 192.168.1.249 off
Power off command sent  # Works now
```

## Root Cause

The `tv_on()` (after sending Wake-on-LAN) and `tv_off()` functions use the remote control interface, which requires initializing a `SamsungTVWS` client. During initialization, the library:

1. Connects to the REST API endpoint (`http://TV_IP:8001/api/v2/`)
2. Calls `get_model_year()` to determine TV capabilities
3. If the REST API doesn't respond quickly → initialization fails

**Why it's intermittent:**
- REST API may be in a low-power state
- TV just woke from sleep/screen-off
- Network interface settling after mode change
- Timing/race conditions

**Why subsequent attempts work:**
- The first connection "warms up" the REST API
- TV's network interface becomes fully active
- Caches/buffers are populated

## Solution: Automatic Retry

Added Wake-on-LAN support and retry logic to `tv_on()` plus retries for `tv_off()`:

```python
_POWER_COMMAND_RETRIES = 4  # Try up to 4 times
_POWER_RETRY_DELAY = 2      # Wait 2 seconds between retries

_send_wake_on_lan(mac_address)
time.sleep(_WOL_WAKE_DELAY)

for attempt in range(_POWER_COMMAND_RETRIES):
    if attempt > 0:
        time.sleep(_POWER_RETRY_DELAY)
    try:
        remote = _build_client(ip, token_path)
        remote.open()
        remote.send_key("KEY_POWER")  # or hold_key for off
        remote.close()
        return  # Success!
    except Exception as err:
        # Log and try again
        last_error = err
```

## Benefits

- **Transparent to user**: Retry happens automatically
- **Fast when working**: First attempt usually succeeds (no delay)
- **Reliable when flaky**: Second attempt catches timing issues
- **Logged for debugging**: Can see retry attempts in debug logs

## Alternative Considered: Longer Timeout

We could increase `DEFAULT_TIMEOUT` in `const.py`, but:
- ❌ Slows down all operations (even successful ones)
- ❌ Doesn't solve race conditions
- ❌ Makes failures take longer to report
- ✅ Retry is better: fast when working, resilient when needed

## Monitoring

With debug logging enabled:
```
DEBUG:tv_on attempt 1 failed: TV unreachable
DEBUG:Retrying tv_on attempt 2/2
DEBUG:tv_on succeeded on attempt 2
```

## Related: Art Operations Don't Have This Issue

Functions like `set_art_on_tv_deleteothers()`, `set_tv_brightness()`, and `is_tv_on()` use the art websocket directly (via `_FrameTVSession`) and don't hit the REST API during initialization, so they're not affected by this timing issue.
