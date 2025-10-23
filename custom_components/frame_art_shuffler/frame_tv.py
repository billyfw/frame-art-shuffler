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
import time
from pathlib import Path
from typing import Any, Optional, cast

from samsungtvws import SamsungTVWS

from .const import DEFAULT_PORT, DEFAULT_TIMEOUT, TOKEN_DIR

_LOGGER = logging.getLogger(__name__)

_ART_MODE_ON = "on"
_UPLOAD_RETRIES = 3
_UPLOAD_RETRY_DELAY = 2
_INITIAL_UPLOAD_SETTLE = 6
_DISPLAY_RETRY_DELAYS = (0, 10, 15)
_POST_DISPLAY_VERIFY_DELAY = 8
_DELETE_SETTLE = 4
_BRIGHTNESS_VERIFY_DELAY = 1
_VALID_BRIGHTNESS = set(range(1, 11)) | {50}
_WARN_FILE_MB = 5
_LARGE_FILE_MB = 10
_POWER_COMMAND_RETRIES = 2
_POWER_RETRY_DELAY = 1


class FrameArtError(Exception):
    """Base error raised by the Frame TV helper."""


class FrameArtConnectionError(FrameArtError):
    """Raised when the TV can't be reached."""


class FrameArtUploadError(FrameArtError):
    """Raised when an upload or art operation fails."""


class _FrameTVSession:
    """Context manager that mirrors the helper scripts connection flow."""

    def __init__(self, ip: str) -> None:
        self.ip = ip
        self.token_path = _token_path(ip)
        self._remote = _build_client(ip, self.token_path)
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
    wait_after_upload: float = _INITIAL_UPLOAD_SETTLE,
    brightness: Optional[int] = None,
    debug: bool = False,
) -> str:
    """Upload art to the Frame TV, mirror test script behaviour, and return content_id."""

    file_path = Path(artpath).expanduser().resolve()
    if not file_path.exists():
        raise FrameArtUploadError(f"Art file not found: {file_path}")

    payload = file_path.read_bytes()
    _log_file_details(file_path, payload)

    file_type = _detect_file_type(file_path)

    # Upload with retries - recreate session on each attempt since connection may be broken
    response = None
    last_error: Optional[Exception] = None
    
    for attempt in range(_UPLOAD_RETRIES):
        if attempt:
            _LOGGER.info("Retrying upload attempt %s/%s", attempt + 1, _UPLOAD_RETRIES)
            time.sleep(_UPLOAD_RETRY_DELAY)
        
        try:
            with _FrameTVSession(ip) as session:
                art = session.art

                if ensure_art_mode and attempt == 0:  # Only check on first attempt
                    _ensure_art_mode(art, debug=debug)

                if brightness is not None and attempt == 0:  # Only set on first attempt
                    _set_brightness(art, brightness, debug=debug)

                # Upload with this fresh connection
                kwargs = {"file_type": file_type}
                if matte:
                    kwargs.update({"matte": matte, "portrait_matte": matte})
                response = art.upload(payload, **kwargs)
                
                # If we got here, upload succeeded - extract content_id and continue
                content_id = _extract_content_id(response)
                if debug:
                    _LOGGER.debug("Upload returned content_id=%s", content_id)

                time.sleep(wait_after_upload)

                displayed = _display_uploaded_art(
                    art,
                    content_id,
                    wait_after_upload=wait_after_upload,
                    debug=debug,
                )

                if not displayed:
                    _LOGGER.warning("Uploaded art %s but could not verify display; check TV manually", content_id)

                if delete_others:
                    _delete_other_images(art, content_id, debug=debug)

                return content_id
                
        except Exception as err:  # pylint: disable=broad-except
            last_error = err
            _LOGGER.warning("Upload attempt %s failed: %s", attempt + 1, err)
    
    # All retries exhausted
    raise FrameArtUploadError(f"Upload failed after {_UPLOAD_RETRIES} attempts: {last_error}")


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


def is_screen_on(ip: str) -> bool:
    """Return True when the TV screen is actually on and displaying content.
    
    This checks the TV's power state, not just art mode status.
    Note: This requires the REST API to be responsive, which may fail if the TV
    is in a low-power state or the screen is off.
    """
    
    token_path = _token_path(ip)
    try:
        remote = _build_client(ip, token_path)
        remote.open()
        
        # Try to get power status from the REST API
        # If we can connect and the TV responds, screen is likely on
        try:
            rest_api = remote._get_rest_api()  # type: ignore[attr-defined]
            device_info = rest_api.rest_device_info()
            
            # If we got device info, TV is responsive (screen likely on)
            remote.close()
            return device_info is not None
        except Exception:  # pylint: disable=broad-except
            # REST API not responsive - screen is likely off
            remote.close()
            return False
            
    except Exception as err:  # pylint: disable=broad-except
        _LOGGER.debug("Screen status check failed for %s: %s", ip, err)
        return False


# Backwards compatibility alias
def is_tv_on(ip: str) -> bool:
    """Deprecated: Use is_art_mode_enabled() instead.
    
    This function checks if art mode is enabled, not if the screen is on.
    For screen state, use is_screen_on().
    """
    return is_art_mode_enabled(ip)


def tv_on(ip: str) -> None:
    """Turn Frame TV screen back on (wake from screen-off state)."""

    token_path = _token_path(ip)
    last_error: Optional[Exception] = None
    
    for attempt in range(_POWER_COMMAND_RETRIES):
        if attempt > 0:
            _LOGGER.debug("Retrying tv_on attempt %s/%s", attempt + 1, _POWER_COMMAND_RETRIES)
            time.sleep(_POWER_RETRY_DELAY)
        
        try:
            remote = _build_client(ip, token_path)
            remote.open()
            remote.send_key("KEY_POWER")
            remote.close()
            return  # Success
        except Exception as err:  # pylint: disable=broad-except
            last_error = err
            _LOGGER.debug("tv_on attempt %s failed: %s", attempt + 1, err)
    
    # All retries exhausted
    raise FrameArtConnectionError(f"Failed to turn on TV screen {ip} after {_POWER_COMMAND_RETRIES} attempts: {last_error}") from last_error


def set_art_mode(ip: str) -> None:
    """Switch TV to art mode by sending KEY_POWER.
    
    When the TV is powered on and showing content (TV channels, apps, etc.), sending
    KEY_POWER will switch it to art mode. This is the reliable programmatic method
    discovered from the Nick Waterton examples.
    
    If the TV is already in art mode, this is a no-op.
    If the TV is off, this will turn it on (behavior depends on TV settings).
    """
    
    # First check if already in art mode
    with _FrameTVSession(ip) as session:
        try:
            status = session.art.get_artmode()
            _LOGGER.debug("Current art mode status for %s: %s", ip, status)
            
            if status == _ART_MODE_ON:
                _LOGGER.info("TV %s already in art mode", ip)
                return
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.debug("Could not check art mode status: %s", err)
            # Continue anyway and try to switch
    
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
            remote = _build_client(ip, token_path)
            remote.open()
            # For Frame TVs, hold KEY_POWER for 3 seconds to turn screen off while staying in art mode
            # This mimics the Samsung Smart TV integration's Frame-specific behavior
            remote.hold_key("KEY_POWER", 3)
            remote.close()
            return  # Success
        except Exception as err:  # pylint: disable=broad-except
            last_error = err
            _LOGGER.debug("tv_off attempt %s failed: %s", attempt + 1, err)
    
    # All retries exhausted
    raise FrameArtConnectionError(f"Failed to turn off TV screen {ip} after {_POWER_COMMAND_RETRIES} attempts: {last_error}") from last_error


def _display_uploaded_art(art, content_id: str, *, wait_after_upload: float, debug: bool) -> bool:
    # Method 1: try direct selection with retries mirroring the reference script
    for attempt, delay in enumerate(_DISPLAY_RETRY_DELAYS):
        if attempt and delay:
            _LOGGER.debug("Waiting %ss before retrying display", delay)
            time.sleep(delay)
        try:
            art.select_image(content_id, show=True)
        except Exception as err:  # pylint: disable=broad-except
            _LOGGER.debug("select_image failed on attempt %s: %s", attempt + 1, err)
            continue

        time.sleep(_POST_DISPLAY_VERIFY_DELAY)
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
    if not deletions:
        _LOGGER.debug("No other images to delete")
        return

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


def _build_client(ip: str, token_path: Path) -> SamsungTVWS:
    try:
        return SamsungTVWS(
            host=ip,
            port=DEFAULT_PORT,
            timeout=DEFAULT_TIMEOUT,
            token_file=str(token_path),
            name="SamsungTvRemote",
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
