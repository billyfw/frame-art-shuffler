"""Helper utilities for Frame Art config flows."""

from __future__ import annotations

from pathlib import Path
import ipaddress
import re

HOSTNAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9-]{1,63})*$")


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


def pair_tv(host: str, token_path: Path) -> bool:
    """Attempt to pair with a TV, returning True on success."""

    try:
        from samsungtvws.remote import SamsungTVWS  # type: ignore import
    except Exception:  # pragma: no cover - import failure surfaces as False in tests
        return False

    try:
        remote = SamsungTVWS(
            host=host,
            name="FrameArtShuffler",
            port=8002,
            token_file=str(token_path),
        )
        remote.open()
        remote.close()
        return True
    except Exception:
        return False


__all__ = [
    "HOSTNAME_RE",
    "parse_tag_string",
    "pair_tv",
    "safe_token_filename",
    "validate_host",
]
