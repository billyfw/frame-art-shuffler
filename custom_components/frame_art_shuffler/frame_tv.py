"""Helper utilities for interacting with Samsung Frame TVs.

This module provides art-focused functions for Frame TV control:
- set_art_on_tv_deleteothers: Upload and display artwork, manage gallery
- set_tv_brightness: Adjust art mode brightness (1-10, or 50 for max)
- is_art_mode_enabled: Check if TV is in art mode (screen may be on/off)
- is_screen_on: Check if screen is actually displaying content
- tv_on/tv_off: Screen power control (stays in art mode)
- set_art_mode: Switch TV to art mode (from TV mode or other state)

Power commands use the same KEY_POWER hold behavior as the Samsung Smart TV
integration to turn the screen off while maintaining art mode.
"""
from __future__ import annotations

import json
import logging
import re
import socket
import time
import random
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, cast

# VENDORING NOTE:
# We import a local vendored copy of samsungtvws (v3.0.3) to avoid conflicts
# with Home Assistant's built-in outdated version.
# If functionality breaks due to TV firmware updates, check the upstream repo:
# https://github.com/xchwarze/samsung-tv-ws-api
try:
    from . import samsungtvws
    from .samsungtvws.remote import SamsungTVWS
    from .samsungtvws.helper import get_ssl_context
except ImportError:
    import samsungtvws
    from samsungtvws.remote import SamsungTVWS
    from samsungtvws.helper import get_ssl_context

from .const import DEFAULT_PORT, DEFAULT_TIMEOUT

_LOGGER = logging.getLogger(__name__)

TOKEN_DIR = Path(__file__).resolve().parent / "tokens"

_ART_MODE_ON = "on"
_UPLOAD_RETRIES = 3
_UPLOAD_RETRY_DELAY = 2
_INITIAL_UPLOAD_SETTLE = 6
_DISPLAY_RETRY_DELAYS = (0, 10, 15)
_POST_DISPLAY_VERIFY_DELAY = 8
_DELETE_SETTLE = 4
_BRIGHTNESS_VERIFY_DELAY = 1
_VALID_BRIGHTNESS = set(range(1, 11)) | {50}
_WARN_FILE_MB = 10
_LARGE_FILE_MB = 15
_MAX_UPLOAD_BYTES = 20 * 1024 * 1024
_POWER_COMMAND_RETRIES = 4
_POWER_RETRY_DELAY = 2
_POWER_COMMAND_TIMEOUT = 8
_SCREEN_CHECK_TIMEOUT = 6
_WOL_BROADCAST_IP = "255.255.255.255"
_WOL_BROADCAST_PORT = 9
_WOL_WAKE_DELAY = 2

# Use a dedicated directory for integration data to keep /config clean
# This matches the structure we want for tokens as well
DATA_DIR = Path("/config/frame_art_shuffler")
PROGRESS_LOG_FILE = DATA_DIR / "upload.log"


def _log_progress(msg: str) -> None:
    """Log message to the shared progress file."""
    _LOGGER.info(msg)
    try:
        # Ensure directory exists
        if not PROGRESS_LOG_FILE.parent.exists():
            # Only try to create if we are in a writable environment like /config
            if str(PROGRESS_LOG_FILE).startswith("/config"):
                PROGRESS_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

        # Only write if parent dir exists
        if PROGRESS_LOG_FILE.parent.exists():
            timestamp = datetime.now().strftime("%H:%M:%S")
            with open(PROGRESS_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(f"[{timestamp}] {msg}\n")
    except Exception:
        pass


def _clear_progress() -> None:
    """Clear the progress log file."""
    try:
        if PROGRESS_LOG_FILE.parent.exists():
            with open(PROGRESS_LOG_FILE, "w", encoding="utf-8") as f:
                f.write("")
    except Exception:
        pass


class FrameArtError(Exception):
    """Base error raised by the Frame TV helper."""


class FrameArtConnectionError(FrameArtError):
    """Raised when the TV can't be reached."""


class FrameArtUploadError(FrameArtError):
    """Raised when an upload or art operation fails."""


def set_token_directory(path: Path) -> None:
    """Override the token storage directory used by SamsungTVWS."""

    global TOKEN_DIR  # noqa: PLW0603 - module-level configuration mutation is intentional
    TOKEN_DIR = path
    TOKEN_DIR.mkdir(parents=True, exist_ok=True)


class _FrameTVSession:
    """Context manager that mirrors the helper scripts connection flow."""

    def __init__(self, ip: str, timeout: Optional[float] = None) -> None:
        self.ip = ip
        self.token_path = _token_path(ip)
        self._remote = _build_client(ip, self.token_path, timeout=timeout)

        # Ensure we have a valid token by performing a handshake on the remote channel
        # if the token file is missing. The art channel does not support initial handshake.
        if not self.token_path.exists():
            _LOGGER.info("No token found for %s, attempting handshake via remote control channel...", ip)
            try:
                self._remote.open()
                self._remote.close()
                _LOGGER.info("Handshake successful, token saved.")
            except Exception as err:
                _LOGGER.warning("Handshake attempt failed: %s", err)
                # We continue anyway, as art() might handle it or we want to bubble the error later

        self._art = cast(Any, self._remote.art())

    @property
    def art(self) -> Any:
        return self._art

    def close(self) -> None:
        for conn in (self._art, self._remote):
            try:
                conn.close()
            except Exception:  # pragma: no cover - best effort cleanup
                pass

    def __enter__(self) -> "_FrameTVSession":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        self.close()


def set_art_on_tv_deleteothers(
    ip: str,
    artpath: str,
    *,
    delete_others: bool = False,
    ensure_art_mode: bool = True,
    matte: Optional[str] = None,
    photo_filter: Optional[str] = None,
    wait_after_upload: float = _INITIAL_UPLOAD_SETTLE,
    brightness: Optional[int] = None,
    debug: bool = False,
) -> str:
    """Upload art to the Frame TV, mirror test script behaviour, and return content_id."""

    _clear_progress()
    _log_progress(f"Starting process for {ip}...")

    file_path = Path(artpath).expanduser().resolve()
    if not file_path.exists():
        raise FrameArtUploadError(f"Art file not found: {file_path}")

    payload = file_path.read_bytes()
    _log_file_details(file_path, payload)

    file_type = _detect_file_type(file_path)
    file_size = len(payload)

    if file_size > _MAX_UPLOAD_BYTES:
        size_mb = file_size / (1024 * 1024)
        raise FrameArtUploadError(
            f"Art file {file_path.name} is {size_mb:.2f} MB; maximum supported size is 5.00 MB"
        )

    # Fail fast: Check if TV is reachable with a short timeout before starting the heavy upload process
    # This prevents the UI from hanging for minutes if the TV is off.
    try:
        _log_progress(f"Checking connectivity to {ip}...")
        with _FrameTVSession(ip, timeout=4) as session:
            # Perform a lightweight operation to verify connection.
            # We don't care about the actual return value (True/False); we just want to confirm
            # that the TV received the request and responded, proving it is network-reachable.
            session.art.get_artmode()
    except Exception as err:
        _log_progress(f"Connection failed: TV appears to be off or unreachable.")
        raise FrameArtConnectionError(f"TV {ip} is unreachable (timeout): {err}") from err

    # Upload with retries - recreate session on each attempt since connection may be broken
    response = None
    last_error: Optional[Exception] = None
    content_id: Optional[str] = None
    
    for attempt in range(_UPLOAD_RETRIES):
        if attempt:
            _LOGGER.info("Retrying upload attempt %s/%s", attempt + 1, _UPLOAD_RETRIES)
            time.sleep(_UPLOAD_RETRY_DELAY)
        
        try:
            # Use 120s timeout for upload to handle large files/slow networks
            with _FrameTVSession(ip, timeout=120) as session:
                art = session.art

                if ensure_art_mode and attempt == 0:  # Only check on first attempt
                    _ensure_art_mode(art, debug=debug)

                if brightness is not None and attempt == 0:  # Only set on first attempt
                    _set_brightness(art, brightness, debug=debug)

                # Get current image count before upload
                images_before = None
                try:
                    _log_progress("Checking Art Mode connection and listing current images...")
                    images_before = art.available()
                    ids = [img.get('content_id') for img in images_before] if images_before else []
                    count = len(images_before) if images_before else 0

                    # TV firmware often reports the active image twice (once as active, once as available).
                    # If we see exactly 2 identical IDs, report it as 1 image to avoid user confusion.
                    if count == 2 and len(ids) == 2 and ids[0] == ids[1]:
                        count = 1

                    _log_progress(f"Art Mode connection OK. Images on TV: {count} {ids}")
                except Exception as err:  # pylint: disable=broad-except
                    _LOGGER.warning("Could not list images (Art Mode connection issue?): %s", err)
                    # If we can't list images, upload will likely fail too, but we'll try anyway
                    # as per original logic, but logged as warning now.

                # Upload with this fresh connection
                kwargs = {"file_type": file_type}
                if matte is not None:
                    kwargs["matte"] = matte
                    _log_progress(f"Uploading with matte: {matte}")
                
                try:
                    _log_progress(f"Uploading image to {ip} (attempt {attempt + 1}/{_UPLOAD_RETRIES})...")
                    
                    # Use our custom chunked upload instead of the library's default upload
                    # to avoid hangs on large files/slow networks
                    content_id = _upload_chunked(
                        art, 
                        payload, 
                        file_type=file_type, 
                        matte=kwargs.get("matte"),
                        portrait_matte=kwargs.get("portrait_matte")
                    )
                    
                    _log_progress(f"Upload successful, content_id={content_id}")
                    if debug:
                        _LOGGER.debug("Upload returned content_id=%s", content_id)
                    
                    break  # Success, exit retry loop
                    
                except Exception as upload_err:  # pylint: disable=broad-except
                    error_msg = str(upload_err)
                    _LOGGER.warning("Upload attempt %s failed with error: %s", attempt + 1, error_msg)
                    
                    # Check if this is a timeout
                    is_timeout = "timeout" in error_msg.lower() or "timed out" in error_msg.lower()
                    
                    if is_timeout:
                        _LOGGER.info("Upload attempt %s timed out - checking if image appeared on TV...", attempt + 1)
                        
                        # Try to check if the upload actually succeeded despite timeout
                        timeout_recovered = False
                        try:
                            time.sleep(6)  # Give TV more time to finish processing
                            images_after = art.available()
                            
                            if images_after and images_before is not None:
                                # Check if a new image appeared by comparing counts
                                count_before = len(images_before)
                                count_after = len(images_after)
                                
                                if count_after > count_before:
                                    # New image(s) appeared! Find the new one by comparing lists
                                    before_ids = {img.get('content_id') for img in images_before}
                                    new_images = [img for img in images_after if img.get('content_id') not in before_ids]
                                    
                                    if new_images:
                                        # Found new image(s), take the first one
                                        content_id = new_images[0].get('content_id')
                                        _LOGGER.info("Upload timed out but new image appeared on TV (content_id=%s)", content_id)
                                        timeout_recovered = True
                                        break  # Success, exit retry loop
                                    
                                    # Fallback: if count increased but can't identify which, use newest
                                    _LOGGER.warning("Count increased but couldn't identify new image, using newest")
                                    content_id = images_after[-1].get('content_id')
                                    if content_id:
                                        timeout_recovered = True
                                        break
                                else:
                                    _LOGGER.warning("Upload timed out and no new image appeared - upload actually failed")
                            
                            # If we don't have before count, try to find by comparing with after
                            elif images_after:
                                _LOGGER.info("Upload timed out, no before count available, using newest image...")
                                content_id = images_after[-1].get('content_id')
                                _LOGGER.warning("Upload timed out, using newest image as best guess (content_id=%s)", content_id)
                                if content_id:
                                    timeout_recovered = True
                                    break
                            else:
                                _LOGGER.warning("Upload timed out and TV has no images")
                            
                        except Exception as check_err:  # pylint: disable=broad-except
                            _LOGGER.warning("Could not check TV gallery after timeout: %s", check_err)
                        
                        # If timeout recovery failed, this was a real failure - will retry
                        if not timeout_recovered:
                            last_error = upload_err
                            if attempt < _UPLOAD_RETRIES - 1:
                                _LOGGER.info("Upload actually failed (not just timeout), will retry...")
                            else:
                                _LOGGER.error("Upload failed after %s attempts", _UPLOAD_RETRIES)
                                raise
                    else:
                        # Not a timeout - some other error, will retry
                        last_error = upload_err
                        if attempt < _UPLOAD_RETRIES - 1:
                            _LOGGER.warning("Upload attempt %s failed: %s", attempt + 1, upload_err)
                        else:
                            # Last attempt, will raise below
                            raise
                        
        except Exception as err:  # pylint: disable=broad-except
            last_error = err
            if attempt == _UPLOAD_RETRIES - 1:
                # Last attempt failed
                break
    
    # Check if we got a content_id (either from successful upload or timeout recovery)
    if not content_id:
        raise FrameArtUploadError(f"Upload failed after {_UPLOAD_RETRIES} attempts: {last_error}")
    
    # We have a content_id, continue with display
    try:
        with _FrameTVSession(ip) as session:
            art = session.art
            
            _wait_with_countdown(wait_after_upload, "Waiting for TV to process upload")

            displayed = _display_uploaded_art(
                art,
                content_id,
                wait_after_upload=wait_after_upload,
                debug=debug,
            )

            if not displayed:
                _LOGGER.warning("Uploaded art %s but could not verify display; check TV manually", content_id)
            else:
                _log_progress(f"Art {content_id} successfully displayed on {ip}")

            # Apply photo filter if specified
            if photo_filter is not None and photo_filter.lower() not in ("none", ""):
                try:
                    _log_progress(f"Applying photo filter '{photo_filter}' to {ip}")
                    if debug:
                        _LOGGER.debug("Applying photo filter '%s' to content_id=%s", photo_filter, content_id)
                    art.set_photo_filter(content_id, photo_filter)
                    _log_progress(f"Photo filter '{photo_filter}' applied successfully")
                    if debug:
                        _LOGGER.debug("Successfully applied photo filter '%s'", photo_filter)
                except Exception as filter_err:  # pylint: disable=broad-except
                    _LOGGER.warning("Failed to apply photo filter '%s': %s", photo_filter, filter_err)

            if delete_others:
                _log_progress("Cleaning up old images from TV memory...")
                _delete_other_images(art, content_id, debug=debug)

            _log_progress(f"Upload complete for {ip} (content_id={content_id})")
            
            # Wait briefly so the user can see the success message, then clear
            time.sleep(5)
            _clear_progress()
            
            return content_id
    except Exception as err:  # pylint: disable=broad-except
        # Upload worked but post-processing failed
        _LOGGER.error("Upload succeeded (content_id=%s) but post-processing failed: %s", content_id, err)
        raise FrameArtUploadError(f"Upload succeeded but failed to display/cleanup: {err}") from err


def set_tv_brightness(ip: str, brightness: int) -> None:
    """Set the art-mode brightness following the reference script behaviour."""

    if brightness not in _VALID_BRIGHTNESS:
        raise ValueError("Brightness must be 1-10 for normal or 50 for max")

    with _FrameTVSession(ip) as session:
        art = session.art
        
        # Set brightness directly without pre-checking current value
        # (TV can be slow/unresponsive to brightness queries)
        _set_brightness_value(art, brightness)
        time.sleep(_BRIGHTNESS_VERIFY_DELAY)

        # Try to verify, but don't fail if verification times out
        try:
            confirmed = _get_brightness_value(art)
            if confirmed != brightness:
                _LOGGER.warning(
                    "TV reported brightness %s after setting %s (may be stale)",
                    confirmed, brightness
                )
            else:
                _LOGGER.info("Brightness set to %s on %s", confirmed, ip)
        except Exception as err:  # pylint: disable=broad-except
            # Verification failed but set command was sent
            _LOGGER.info("Brightness command sent to %s (verification timed out)", ip)


def is_art_mode_enabled(ip: str) -> bool:
    """Return True when the TV reports art mode is active (screen may be on or off)."""

    with _FrameTVSession(ip) as session:
        try:
            status = session.art.get_artmode()
            _LOGGER.debug("Art mode status for %s: %s", ip, status)
            return status == _ART_MODE_ON
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.debug("Art mode check failed for %s: %s", ip, err)
            return False


def is_screen_on(ip: str, timeout: Optional[float] = None) -> bool:
    """Return True when the TV screen is actually on and displaying content.

    This checks the TV's power state, not just art mode status.
    Note: This requires the REST API to be responsive, which may fail if the TV
    is in a low-power state or the screen is off.
    """

    token_path = _token_path(ip)
    remote: Optional[SamsungTVWS] = None
    try:
        remote = _build_client(ip, token_path, timeout=timeout)
        remote.open()

        rest_api = remote._get_rest_api()  # type: ignore[attr-defined]
        try:
            power_state = rest_api.rest_power_state()
            return bool(power_state)
        except Exception:  # pylint: disable=broad-except
            device_info = rest_api.rest_device_info()
            state = (
                str(device_info.get("device", {}).get("PowerState", "")).lower()
                if isinstance(device_info, dict)
                else ""
            )
            if state in {"on", "off"}:
                return state == "on"
            return bool(device_info)

    except Exception as err:  # pylint: disable=broad-except
        _LOGGER.debug("Screen status check failed for %s: %s", ip, err)
        return False
    finally:
        if remote is not None:
            try:
                remote.close()
            except Exception:  # pragma: no cover - best effort cleanup
                pass


# Backwards compatibility alias
def is_tv_on(ip: str) -> bool:
    """Deprecated: Use is_art_mode_enabled() instead.
    
    This function checks if art mode is enabled, not if the screen is on.
    For screen state, use is_screen_on().
    """
    return is_art_mode_enabled(ip)


def tv_on(ip: str, mac_address: str) -> bool:
    """Wake Frame TV via Wake-on-LAN.
    
    Samsung Frame TVs require a two-stage Wake-on-LAN approach with significant delay:
    
    1. First WOL wakes the network interface, but the TV enters a "network awake, 
       screen off" standby state where the screen remains black.
    
    2. The TV needs 12+ seconds to fully transition into this network-awake state
       before it will respond to commands.
    
    3. Second WOL (sent after the delay) actually turns on the screen and displays 
       art mode.
    
    CRITICAL: The 12-second delay between WOL packets is required. Testing showed that
    shorter delays (2s, 5s) do not work - the TV must fully enter the network-awake 
    state before the second WOL will turn on the screen. This mimics the reliable 
    behavior of manually running the WOL command twice from the CLI with natural 
    human delay between commands.
    
    This function intentionally does NOT send KEY_POWER to avoid toggle issues where
    the TV might switch from art mode to TV content mode unexpectedly.
    
    Returns True when Wake-on-LAN was sent successfully. For diagnostic purposes,
    logs the TV's screen and art mode state after waking.
    
    If you need to ensure the TV is in art mode after waking, call set_art_mode()
    separately.
    """

    # First WOL: Wake network interface
    _send_wake_on_lan(mac_address)
    _LOGGER.info("Wake-on-LAN packet sent to %s (first - waking network)", mac_address)
    
    # CRITICAL: Wait for TV to fully enter network-awake state
    # This delay was determined through testing - shorter delays (2s, 5s) do not work.
    # The TV needs this time to transition from "fully off" to "network awake, screen off"
    # before the second WOL packet will successfully turn on the screen.
    time.sleep(12)
    
    # Second WOL: Turn on screen
    _send_wake_on_lan(mac_address)
    _LOGGER.info("Wake-on-LAN packet sent to %s (second - turning on screen)", mac_address)
    
    # Give TV time to fully wake up and display art
    time.sleep(3)
    
    # Check state for diagnostic purposes (don't take action based on it)
    try:
        screen_on = is_screen_on(ip, timeout=_SCREEN_CHECK_TIMEOUT)
        art_enabled = is_art_mode_enabled(ip)
        _LOGGER.info(
            "TV %s state after Wake-on-LAN: screen_on=%s, art_mode=%s",
            ip, screen_on, art_enabled
        )
    except Exception as err:  # pylint: disable=broad-except
        _LOGGER.debug("Could not check TV state after Wake-on-LAN: %s", err)
    
    return True
def set_art_mode(ip: str) -> None:
    """Switch TV to art mode by sending KEY_POWER.
    
    When the TV is powered on and showing content (TV channels, apps, etc.), sending
    KEY_POWER will switch it to art mode. This is the reliable programmatic method
    discovered from the Nick Waterton examples.
    
    If the TV is already in art mode, this is a no-op.
    If the TV is off, this will turn it on (behavior depends on TV settings).
    
    Note: KEY_POWER is a toggle, so we must verify current state before sending it.
    If we cannot determine the current state, we do not send the command to avoid
    accidentally toggling out of art mode.
    """
    
    # First check if already in art mode
    # KEY_POWER is a toggle, so we MUST know the current state
    with _FrameTVSession(ip) as session:
        try:
            status = session.art.get_artmode()
            _LOGGER.debug("Current art mode status for %s: %s", ip, status)
            
            if status == _ART_MODE_ON:
                _LOGGER.info("TV %s already in art mode", ip)
                return
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.warning("Could not verify art mode status for %s: %s. Not sending KEY_POWER to avoid toggling out of art mode.", ip, err)
            # Do NOT continue - KEY_POWER is a toggle so we need to know current state
            raise FrameArtUploadError(f"Cannot determine art mode status for {ip}, refusing to send KEY_POWER") from err
    
    # Send KEY_POWER to switch to art mode
    token_path = _token_path(ip)
    try:
        remote = _build_client(ip, token_path)
        remote.open()
        remote.send_key("KEY_POWER")
        remote.close()
        _LOGGER.info("Sent KEY_POWER to switch %s to art mode", ip)
        
        # Give TV time to switch
        time.sleep(3)
        
        # Verify it worked
        with _FrameTVSession(ip) as session:
            new_status = session.art.get_artmode()
            if new_status == _ART_MODE_ON:
                _LOGGER.info("TV %s successfully switched to art mode", ip)
            else:
                _LOGGER.warning("TV %s may not have switched to art mode (status: %s)", ip, new_status)
                
    except Exception as err:  # pylint: disable=broad-except
        raise FrameArtUploadError(f"Failed to switch {ip} to art mode: {err}") from err


def tv_off(ip: str) -> None:
    """Power off Frame TV screen while staying in art mode (hold KEY_POWER for 3 seconds)."""

    token_path = _token_path(ip)
    last_error: Optional[Exception] = None
    
    for attempt in range(_POWER_COMMAND_RETRIES):
        if attempt > 0:
            _LOGGER.debug("Retrying tv_off attempt %s/%s", attempt + 1, _POWER_COMMAND_RETRIES)
            time.sleep(_POWER_RETRY_DELAY)
        
        try:
            remote = _build_client(ip, token_path, timeout=_POWER_COMMAND_TIMEOUT)
            remote.open()
            # For Frame TVs, hold KEY_POWER for 3 seconds to turn screen off while staying in art mode
            # This mimics the Samsung Smart TV integration's Frame-specific behavior
            remote.hold_key("KEY_POWER", 3)
            remote.close()
            return
        except Exception as err:  # pylint: disable=broad-except
            last_error = err
            _LOGGER.debug("tv_off attempt %s failed: %s", attempt + 1, err)
    
    # All retries exhausted
    raise FrameArtConnectionError(f"Failed to turn off TV screen {ip} after {_POWER_COMMAND_RETRIES} attempts: {last_error}") from last_error


def _send_wake_on_lan(mac_address: str) -> None:
    """Broadcast a Wake-on-LAN packet to wake the Frame TV network interface."""

    cleaned = re.sub(r"[^0-9A-Fa-f]", "", mac_address)
    if len(cleaned) != 12:
        raise FrameArtConnectionError(f"Invalid MAC address for Wake-on-LAN: {mac_address}")

    payload = bytes.fromhex("FF" * 6 + cleaned * 16)

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.sendto(payload, (_WOL_BROADCAST_IP, _WOL_BROADCAST_PORT))
    except OSError as err:
        raise FrameArtConnectionError(f"Failed to send Wake-on-LAN packet to {mac_address}: {err}") from err


def _display_uploaded_art(art, content_id: str, *, wait_after_upload: float, debug: bool) -> bool:
    # Method 1: try direct selection with retries mirroring the reference script
    for attempt, delay in enumerate(_DISPLAY_RETRY_DELAYS):
        if attempt and delay:
            _LOGGER.debug("Waiting %ss before retrying display", delay)
        try:
            art.select_image(content_id, show=True)
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.debug("select_image failed on attempt %s: %s", attempt + 1, err)
            continue

        _wait_with_countdown(_POST_DISPLAY_VERIFY_DELAY, "Image selected. Verifying display")
        if _verify_current_art(art, content_id, debug=debug):
            return True

    # Method 2: fallback to selecting the newest image from the gallery
    try:
        gallery = art.available() or []
    except Exception as err:  # pylint: disable=broad-except
        _LOGGER.debug("Fetching available art failed: %s", err)
        gallery = []

    if gallery:
        newest = gallery[-1].get("content_id")
        if newest:
            try:
                art.select_image(newest, show=True)
                time.sleep(_POST_DISPLAY_VERIFY_DELAY)
                return _verify_current_art(art, newest, debug=debug)
            except Exception as err:  # pylint: disable=broad-except
                _LOGGER.debug("Fallback select_image failed: %s", err)

    return False


def _verify_current_art(art, expected_content_id: str, *, debug: bool) -> bool:
    try:
        current = art.get_current()
        current_id = current.get("content_id", "unknown")
        if debug:
            _LOGGER.debug("Current art: %s (expected %s)", current_id, expected_content_id)
        return current_id == expected_content_id
    except Exception as err:  # pylint: disable=broad-except
        _LOGGER.debug("Could not verify current art: %s", err)
        return False


def _delete_other_images(art, keep_content_id: str, *, debug: bool) -> None:
    try:
        available = art.available() or []
    except Exception as err:  # pylint: disable=broad-except
        raise FrameArtUploadError(f"Could not enumerate TV gallery: {err}") from err

    deletions = [item.get("content_id") for item in available if item.get("content_id") and item.get("content_id") != keep_content_id]
    
    # Log what we are keeping to help debug duplicate issues
    kept = [item.get("content_id") for item in available if item.get("content_id") == keep_content_id]
    if len(kept) > 1:
        _log_progress(f"Warning: Found {len(kept)} copies of active image {keep_content_id}. Keeping all to avoid accidental deletion.")
    
    if not deletions:
        _LOGGER.debug("No other images to delete")
        return

    _log_progress(f"Deleting {len(deletions)} old images: {deletions}")
    art.delete_list(deletions)
    if debug:
        _LOGGER.debug("Deleted %s old images", len(deletions))
    time.sleep(_DELETE_SETTLE)


def _set_brightness(art, brightness: int, *, debug: bool) -> None:
    try:
        current = _get_brightness_value(art)
        if debug:
            _LOGGER.debug("Current brightness before set: %s", current)
    except Exception:
        current = None

    _set_brightness_value(art, brightness)
    time.sleep(_BRIGHTNESS_VERIFY_DELAY)

    try:
        confirmed = _get_brightness_value(art)
    except Exception as err:  # pylint: disable=broad-except
        raise FrameArtUploadError(f"Unable to verify brightness after setting {brightness}: {err}") from err

    if confirmed != brightness:
        raise FrameArtUploadError(
            f"Expected brightness {brightness} but TV reported {confirmed}"
        )

    _LOGGER.info("Brightness set to %s", confirmed)


def _ensure_art_mode(art, *, debug: bool) -> None:
    try:
        status = art.get_artmode()
        if debug:
            _LOGGER.debug("Art mode status: %s", status)
    except Exception as err:  # pylint: disable=broad-except
        _LOGGER.debug("Unable to read art mode status: %s", err)
        return

    if status == _ART_MODE_ON:
        return

    try:
        art.set_artmode(True)
        time.sleep(_INITIAL_UPLOAD_SETTLE)
        status = art.get_artmode()
    except Exception as err:  # pylint: disable=broad-except
        raise FrameArtUploadError(f"Unable to enable art mode: {err}") from err

    if status != _ART_MODE_ON:
        raise FrameArtUploadError(f"TV art mode still {status}, expected {_ART_MODE_ON}")


def _log_file_details(file_path: Path, payload: bytes) -> None:
    size_mb = len(payload) / (1024 * 1024)
    _LOGGER.info("Preparing upload of %s (%.2f MB)", file_path.name, size_mb)

    if size_mb > _LARGE_FILE_MB:
        _LOGGER.warning(
            "File %.2f MB is large; Samsung Frame TVs may timeout. Consider resizing to < %.1f MB",
            size_mb,
            _WARN_FILE_MB,
        )
    elif size_mb > _WARN_FILE_MB:
        _LOGGER.info("File %.2f MB; expect longer upload times", size_mb)


def _detect_file_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "JPEG"
    if suffix == ".png":
        return "PNG"
    return "JPEG"


def _extract_content_id(response) -> str:
    if isinstance(response, str):
        return response
    if isinstance(response, dict) and "content_id" in response:
        return response["content_id"]
    raise FrameArtUploadError("Upload response did not contain a content_id")


def _token_path(ip: str) -> Path:
    TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    safe_ip = ip.replace(":", "_")
    return TOKEN_DIR / f"{safe_ip}.token"


def _build_client(ip: str, token_path: Path, timeout: Optional[float] = None) -> SamsungTVWS:
    try:
        return SamsungTVWS(
            host=ip,
            port=DEFAULT_PORT,
            timeout=timeout if timeout is not None else DEFAULT_TIMEOUT,
            token_file=str(token_path),
            name="FrameArtShuffler",
        )
    except Exception as err:  # pylint: disable=broad-except
        raise FrameArtConnectionError(f"Unable to connect to TV {ip}: {err}") from err


def _get_brightness_value(art: Any) -> int:
    if hasattr(art, "get_brightness"):
        return int(art.get_brightness())

    try:
        response = art._send_art_request(  # type: ignore[attr-defined]
            {"request": "get_brightness"},
            wait_for_event="d2d_service_message",
        )
    except Exception as err:  # pylint: disable=broad-except
        raise FrameArtUploadError(f"Unable to read brightness: {err}") from err

    if not response:
        raise FrameArtUploadError("TV did not return a brightness response")

    try:
        raw = response.get("data")
        payload = json.loads(raw) if isinstance(raw, str) else raw or {}
        
        # Handle case where payload might not have 'value' key
        if "value" not in payload:
            _LOGGER.debug(f"Brightness response missing 'value' key. Response: {response}, Payload: {payload}")
            raise FrameArtUploadError(f"Brightness response missing 'value' field")
        
        return int(payload["value"])  # type: ignore[index]
    except FrameArtUploadError:
        raise  # Re-raise our own errors
    except Exception as err:  # pylint: disable=broad-except
        raise FrameArtUploadError(f"Malformed brightness payload: {err}") from err


def _set_brightness_value(art: Any, brightness: int) -> None:
    if hasattr(art, "set_brightness"):
        art.set_brightness(brightness)
        return

    try:
        art._send_art_request(  # type: ignore[attr-defined]
            {"request": "set_brightness", "value": brightness}
        )
    except Exception as err:  # pylint: disable=broad-except
        raise FrameArtUploadError(f"Unable to set brightness {brightness}: {err}") from err


def delete_token(ip: str) -> None:
    """Delete the token file for the given IP address."""
    token_path = _token_path(ip)
    if token_path.exists():
        try:
            token_path.unlink()
            _LOGGER.info("Deleted token file for %s", ip)
        except OSError as err:
            raise FrameArtError(f"Failed to delete token file for {ip}: {err}") from err
    else:
        _LOGGER.info("No token file found for %s", ip)


def _upload_chunked(
    art: Any,
    payload: bytes,
    file_type: str,
    matte: Optional[str] = None,
    portrait_matte: Optional[str] = None,
) -> str:
    """Upload image in chunks to avoid timeouts/hangs on large files."""
    file_size = len(payload)
    date = datetime.now().strftime("%Y:%m:%d %H:%M:%S")
    
    # 1. Send 'send_image' request to get connection info
    # Generate a unique request_id for this transaction
    req_id = str(uuid.uuid4())
    
    # Log session details
    _LOGGER.debug("Starting chunked upload. Session ID (art_uuid): %s, Request ID: %s", art.art_uuid, req_id)
    _LOGGER.debug("Image Date: %s, File Size: %s", date, file_size)
    
    request_data = {
        "request": "send_image",
        "file_type": file_type,
        "request_id": req_id,
        "id": art.art_uuid,
        "conn_info": {
            "d2d_mode": "socket",
            "connection_id": random.randrange(4 * 1024 * 1024 * 1024),
            "id": art.art_uuid,
        },
        "image_date": date,
        "matte_id": matte or 'none',
        "portrait_matte_id": portrait_matte or 'none',
        "file_size": file_size,
    }
    
    _LOGGER.debug("Sending send_image request for chunked upload: %s", json.dumps(request_data))
    data = art._send_art_request(request_data, wait_for_event="ready_to_use")
    if not data:
        raise FrameArtUploadError("TV did not return ready_to_use event")
        
    conn_info = json.loads(data["conn_info"])
    
    # 2. Prepare Header
    header = json.dumps({
        "num": 0,
        "total": 1,
        "fileLength": file_size,
        "fileName": "dummy",
        "fileType": file_type,
        "secKey": conn_info["key"],
        "version": "0.0.1",
    })
    
    # 3. Connect to secondary socket
    art_socket_raw = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    art_socket_raw.settimeout(30)  # Ensure this socket also has a timeout
    
    if conn_info.get('secured', False):
        art_socket = get_ssl_context().wrap_socket(art_socket_raw)
    else:
        art_socket = art_socket_raw
        
    try:
        _LOGGER.debug("Connecting to upload socket %s:%s...", conn_info["ip"], conn_info["port"])
        art_socket.connect((conn_info["ip"], int(conn_info["port"])))
        
        # 4. Send Header
        art_socket.send(len(header).to_bytes(4, "big"))
        art_socket.send(header.encode("ascii"))
        
        # 5. Send Payload in Chunks
        CHUNK_SIZE = 64 * 1024  # 64KB chunks
        total_sent = 0
        _LOGGER.info("Starting chunked upload (%s bytes, chunk size %s)...", file_size, CHUNK_SIZE)
        
        while total_sent < file_size:
            chunk = payload[total_sent : total_sent + CHUNK_SIZE]
            art_socket.send(chunk)
            total_sent += len(chunk)
            # Optional: very brief sleep to allow network buffers to drain if needed
            # time.sleep(0.001)
            
        _LOGGER.info("Chunked upload finished sending %s bytes", total_sent)
            
    except Exception as err:
        _LOGGER.error("Error during chunked upload transmission: %s", err)
        raise FrameArtUploadError(f"Chunked upload transmission failed: {err}") from err
    finally:
        art_socket.close()
        
    # 6. Wait for confirmation
    _LOGGER.debug("Waiting for image_added confirmation...")
    response = art.wait_for_response("image_added")
    
    if not response or "content_id" not in response:
        raise FrameArtUploadError("Upload finished but no content_id returned")
        
    return response["content_id"]


def _wait_with_countdown(seconds: float, msg: str) -> None:
    """Wait for specified seconds while logging a countdown inline."""
    _LOGGER.info(f"{msg} ({seconds}s)")
    
    # Ensure directory exists
    try:
        if not PROGRESS_LOG_FILE.parent.exists():
            if str(PROGRESS_LOG_FILE).startswith("/config"):
                PROGRESS_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    # If we can't write to file, just sleep
    if not PROGRESS_LOG_FILE.parent.exists():
        time.sleep(seconds)
        return

    try:
        timestamp = datetime.now().strftime("%H:%M:%S")
        with open(PROGRESS_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {msg} ")
            f.flush()
            
            remaining = int(seconds)
            while remaining > 0:
                f.write(f"{remaining}... ")
                f.flush()
                time.sleep(1)
                remaining -= 1
            
            f.write("Done.\n")
    except Exception:
        # Fallback if file operations fail
        time.sleep(seconds)
