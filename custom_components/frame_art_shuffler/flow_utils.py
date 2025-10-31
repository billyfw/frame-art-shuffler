"""Helper utilities for Frame Art config flows."""

from __future__ import annotations

from pathlib import Path
import ipaddress
import logging
import re
import time

HOSTNAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9-]{1,63})*$")

_LOGGER = logging.getLogger(__name__)


def safe_token_filename(host: str) -> str:
    """Return a filesystem-safe token filename derived from host."""

    return re.sub(r"[^A-Za-z0-9]+", "_", host)


def parse_tag_string(value: str) -> list[str]:
    """Parse comma or newline separated tags into a cleaned list."""

    if not value:
        return []
    bits = re.split(r"[\n,]", value)
    return [item.strip() for item in bits if item.strip()]


def validate_host(value: str) -> str:
    """Validate an IP address or hostname string for config flow input."""

    candidate = (value or "").strip()
    if not candidate:
        raise ValueError
    try:
        ipaddress.ip_address(candidate)
        return candidate
    except ValueError:
        if re.fullmatch(r"[0-9:\.]+", candidate):
            raise ValueError
        if HOSTNAME_RE.fullmatch(candidate):
            return candidate
    raise ValueError


def pair_tv(
    host: str,
    token_path: Path,
    *,
    mac: str | None = None,
    wake: bool = True,
    attempts: int = 2,
    timeout: float = 12.0,
    retry_delay: float = 4.0,
) -> bool:
    """Attempt to pair with a TV, returning True on success.

    The helper can optionally wake the TV via Wake-on-LAN before attempting to
    open the websocket pairing channel. It retries a limited number of times
    so failures surface quickly in the UI.
    """

    try:
        from samsungtvws.remote import SamsungTVWS  # type: ignore import
    except Exception as err:  # pragma: no cover - import failure surfaces as False in tests
        _LOGGER.debug("Unable to import samsungtvws for pairing: %s", err)
        return False

    if wake and mac:
        try:
            from .frame_tv import tv_on  # pylint: disable=import-outside-toplevel
        except Exception as err:  # pragma: no cover - import failure surfaces as False in tests
            _LOGGER.debug("Unable to import wake helper for %s: %s", host, err)
        else:
            try:
                tv_on(host, mac)
            except Exception as err:  # pragma: no cover - best effort wake
                _LOGGER.debug("Wake-on-LAN for %s failed: %s", host, err)

    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        if attempt > 1:
            time.sleep(retry_delay)

        try:
            remote = SamsungTVWS(
                host=host,
                name="FrameArtShuffler",
                port=8002,
                token_file=str(token_path),
                timeout=timeout,
            )
        except Exception as err:
            last_error = err
            _LOGGER.debug("Failed to initialise SamsungTVWS for %s: %s", host, err)
            continue

        try:
            remote.open()
            return True
        except Exception as err:
            last_error = err
            _LOGGER.debug("Pairing attempt %s/%s for %s failed: %s", attempt, attempts, host, err)
        finally:
            try:
                remote.close()
            except Exception:  # pragma: no cover - best effort cleanup
                pass

    if last_error:
        _LOGGER.debug("Pairing failed for %s: %s", host, last_error)
    return False


__all__ = [
    "HOSTNAME_RE",
    "parse_tag_string",
    "pair_tv",
    "safe_token_filename",
    "validate_host",
]
