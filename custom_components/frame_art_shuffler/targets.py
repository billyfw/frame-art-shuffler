"""Display targets: the Frame TVs and the wall tablets the shuffler drives.

A target is one entry in ``entry.data["tvs"]``; ``kind`` says what it is:

- ``tv`` (the default, and every target created before 0.4.0): a Samsung Frame TV reached by IP.
  A shuffle uploads the picture over the TV's WebSocket; its screen state is polled.
- ``tablet``: a wall tablet showing a dashboard. Nothing is ever sent to the device. A shuffle only
  records the pick, which the tablet's dashboard loads through the target's image entity, and its
  "screen on" mirrors an HA entity (the showing entity) that is on while the tablet shows art.
  A tablet with no include tags shows nothing: on a communal screen the tags are an allow-list.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .const import CONF_KIND, DOMAIN, KIND_TABLET, KIND_TV


def target_kind(tv_config: dict[str, Any] | None) -> str:
    """Return the target's kind, ``tv`` when absent or unknown."""
    kind = (tv_config or {}).get(CONF_KIND) or KIND_TV
    return kind if kind in (KIND_TV, KIND_TABLET) else KIND_TV


def is_tablet(tv_config: dict[str, Any] | None) -> bool:
    """True for a wall tablet target."""
    return target_kind(tv_config) == KIND_TABLET


def target_device_info(entry: Any, tv_id: str, name: str) -> Any:
    """Device info for a target's entities: a Frame TV, or a wall tablet."""
    from homeassistant.helpers.device_registry import DeviceInfo

    from .config_entry import get_tv_config

    if is_tablet(get_tv_config(entry, tv_id)):
        return DeviceInfo(
            identifiers={(DOMAIN, tv_id)},
            name=name,
            manufacturer="Frame Art Shuffler",
            model="Wall tablet",
        )
    return DeviceInfo(
        identifiers={(DOMAIN, tv_id)},
        name=name,
        manufacturer="Samsung",
        model="Frame TV",
    )


def library_root(metadata_path: Path | str) -> Path:
    """The folder holding metadata.json, library/ and the derivative cache."""
    return Path(metadata_path).parent


def library_dir(metadata_path: Path | str) -> Path:
    """The folder holding the pictures."""
    return library_root(metadata_path) / "library"


def public_library_url(www_dir: Path | str, metadata_path: Path | str) -> str | None:
    """The ``/local/...`` URL of the pictures when the library sits under HA's www folder.

    HA publishes www at /local/ to anyone who can reach it, with no login. None when the library
    lives elsewhere (the default for new entries, /media/frame_art).
    """
    try:
        rel = library_dir(metadata_path).resolve().relative_to(Path(www_dir).resolve())
    except ValueError:
        return None
    rel_text = rel.as_posix().strip("/")
    return f"/local/{rel_text}/" if rel_text else "/local/"


def resolve_library_file(metadata_path: Path | str, filename: str | None) -> Path | None:
    """The library file for ``filename``, or None if it is not a plain file inside the library.

    Guards the image entity and the tablet display path against names like ``../secrets.yaml``.
    """
    if not filename or not isinstance(filename, str):
        return None
    base = library_dir(metadata_path).resolve()
    candidate = (base / filename).resolve()
    try:
        candidate.relative_to(base)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None
