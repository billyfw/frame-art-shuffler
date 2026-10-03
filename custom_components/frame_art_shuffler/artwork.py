"""Resized copies of library pictures for targets that load them over HTTP (wall tablets).

The library holds originals up to 15 MB and 4K wide; a wall tablet needs at most its own screen.
``render`` fits a picture inside ``MAX_SIZE`` as a JPEG, caches it beside the library and keeps the
cache to the ``CACHE_LIMIT`` most recently used files. Pure module: no Home Assistant imports.
"""

from __future__ import annotations

import io
import mimetypes
import os
import tempfile
from pathlib import Path

MAX_SIZE = (1920, 1200)  # a 16:10 wall tablet; a 16:9 picture comes out 1920 x 1080
JPEG_QUALITY = 85
CACHE_LIMIT = 300


def _guess_type(path: Path) -> str:
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def derivative_name(src: Path, max_size: tuple[int, int] = MAX_SIZE) -> str:
    """Cache file name: changes whenever the original's size or mtime changes."""
    st = src.stat()
    return f"{src.name}.{int(st.st_mtime)}.{st.st_size}.{max_size[0]}x{max_size[1]}.jpg"


def render(
    src: Path | str,
    cache_dir: Path | str | None,
    max_size: tuple[int, int] = MAX_SIZE,
    quality: int = JPEG_QUALITY,
) -> tuple[bytes, str]:
    """Return ``(bytes, content_type)`` for ``src`` fitted inside ``max_size``.

    Falls back to the original bytes when Pillow is missing or the file cannot be decoded, so a
    picture is always served. Never upscales.
    """
    src = Path(src)
    cache_path = Path(cache_dir) / derivative_name(src, max_size) if cache_dir is not None else None
    if cache_path is not None and cache_path.exists():
        try:
            os.utime(cache_path)  # most recently used
        except OSError:
            pass
        return cache_path.read_bytes(), "image/jpeg"

    try:
        from PIL import Image, ImageOps
    except ImportError:  # pragma: no cover - Pillow ships with Home Assistant
        return src.read_bytes(), _guess_type(src)

    try:
        with Image.open(src) as opened:
            image = ImageOps.exif_transpose(opened)
            image.thumbnail(max_size, Image.Resampling.LANCZOS)
            if image.mode != "RGB":
                rgba = image.convert("RGBA")
                flat = Image.new("RGB", rgba.size, (0, 0, 0))
                flat.paste(rgba, mask=rgba.getchannel("A"))
                image = flat
            buffer = io.BytesIO()
            image.save(buffer, "JPEG", quality=quality, optimize=True)
            data = buffer.getvalue()
    except Exception:  # pylint: disable=broad-except - an unreadable picture is served as it is
        return src.read_bytes(), _guess_type(src)

    if cache_path is not None:
        _write_cache(cache_path, data)
    return data, "image/jpeg"


def _write_cache(path: Path, data: bytes) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp, path)
        prune(path.parent)
    except OSError:
        pass


def prune(cache_dir: Path | str, limit: int = CACHE_LIMIT) -> int:
    """Keep the ``limit`` most recently used derivatives; return how many were removed."""
    files = []
    for path in Path(cache_dir).glob("*.jpg"):
        try:
            files.append((path.stat().st_mtime, path))
        except OSError:
            continue
    files.sort(reverse=True)
    removed = 0
    for _mtime, path in files[limit:]:
        try:
            path.unlink()
            removed += 1
        except OSError:
            pass
    return removed
