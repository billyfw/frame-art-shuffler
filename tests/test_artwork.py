"""Pure tests for the picture resizer and the target helpers (no Home Assistant needed)."""

from __future__ import annotations

import io
import os
import time
from pathlib import Path

from PIL import Image

from custom_components.frame_art_shuffler import artwork
from custom_components.frame_art_shuffler.targets import (
    is_tablet,
    public_library_url,
    resolve_library_file,
    target_kind,
)


def test_render_fits_the_tablet_and_caches(tmp_path):
    src = tmp_path / "big.jpg"
    Image.new("RGB", (4031, 2267), (1, 2, 3)).save(src, "JPEG")
    cache = tmp_path / "cache"
    data, ctype = artwork.render(src, cache)
    assert ctype == "image/jpeg"
    assert Image.open(io.BytesIO(data)).size == (1920, 1080)
    assert len(list(cache.glob("*.jpg"))) == 1
    again, _ = artwork.render(src, cache)
    assert again == data


def test_render_flattens_transparency_and_never_upscales(tmp_path):
    src = tmp_path / "small.png"
    Image.new("RGBA", (800, 600), (255, 0, 0, 0)).save(src, "PNG")
    data, ctype = artwork.render(src, None)
    out = Image.open(io.BytesIO(data))
    assert ctype == "image/jpeg" and out.mode == "RGB" and out.size == (800, 600)


def test_render_serves_an_unreadable_file_as_is(tmp_path):
    src = tmp_path / "broken.jpg"
    src.write_bytes(b"not a picture")
    data, ctype = artwork.render(src, tmp_path / "cache")
    assert data == b"not a picture" and ctype == "image/jpeg"


def test_prune_keeps_the_most_recent(tmp_path):
    for i in range(5):
        path = tmp_path / f"{i}.jpg"
        path.write_bytes(b"x")
        os.utime(path, (time.time() - 100 + i, time.time() - 100 + i))
    assert artwork.prune(tmp_path, limit=2) == 3
    assert sorted(p.name for p in tmp_path.glob("*.jpg")) == ["3.jpg", "4.jpg"]


def test_kind_defaults_to_tv():
    assert target_kind(None) == "tv"
    assert target_kind({"ip": "1.2.3.4"}) == "tv"
    assert target_kind({"kind": "something"}) == "tv"
    assert is_tablet({"kind": "tablet"})


def test_public_library_url(tmp_path):
    www = tmp_path / "config" / "www"
    assert public_library_url(www, www / "frame_art" / "metadata.json") == "/local/frame_art/library/"
    assert public_library_url(www, tmp_path / "media" / "frame_art" / "metadata.json") is None


def test_resolve_library_file_refuses_escapes(tmp_path):
    root = tmp_path / "frame_art"
    (root / "library").mkdir(parents=True)
    (root / "library" / "a.jpg").write_bytes(b"x")
    (root / "metadata.json").write_text("{}")
    meta = root / "metadata.json"
    assert resolve_library_file(meta, "a.jpg") == (root / "library" / "a.jpg").resolve()
    assert resolve_library_file(meta, "../metadata.json") is None
    assert resolve_library_file(meta, "missing.jpg") is None
    assert resolve_library_file(meta, None) is None
