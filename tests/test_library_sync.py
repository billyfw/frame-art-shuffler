"""Tests for library_sync (multi-home GitHub mirror). Pure module, no HA."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest

MODULE_PATH = (
    Path(__file__).resolve().parent.parent
    / "custom_components"
    / "frame_art_shuffler"
    / "library_sync.py"
)

spec = importlib.util.spec_from_file_location("frame_art_library_sync", MODULE_PATH)
assert spec and spec.loader
library_sync = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = library_sync
spec.loader.exec_module(library_sync)

LibrarySyncer = library_sync.LibrarySyncer
LibrarySyncError = library_sync.LibrarySyncError
LibraryAuthError = library_sync.LibraryAuthError

TIP = "c0ffee" * 6 + "beef1234"


def _pointer(content: bytes) -> tuple[str, bytes]:
    oid = hashlib.sha256(content).hexdigest()
    text = (
        "version https://git-lfs.github.com/spec/v1\n"
        f"oid sha256:{oid}\n"
        f"size {len(content)}\n"
    )
    return oid, text.encode()


def _blob_sha(data: bytes) -> str:
    # Not a real git sha — any stable unique string works as a change detector.
    return "blob-" + hashlib.sha256(data).hexdigest()[:20]


class FakeRepo:
    """In-memory GitHub double serving API + LFS + downloads for a Syncer."""

    def __init__(self, files: dict[str, bytes], metadata: dict) -> None:
        self.files = dict(files)  # repo path -> real content bytes
        self.metadata_raw = json.dumps(metadata).encode()
        self.ops: list[str] = []  # ordered log of served operations
        self.corrupt_downloads = False

    # -- wiring -----------------------------------------------------------
    def attach(self, syncer: LibrarySyncer, monkeypatch) -> None:
        monkeypatch.setattr(syncer, "_request", self._request)
        monkeypatch.setattr(
            library_sync.urllib.request, "urlopen", self._urlopen
        )

    # -- request routing ----------------------------------------------------
    def _request(self, url: str, headers, data=None, timeout=0) -> bytes:
        if "/branches/" in url:
            self.ops.append("tip")
            return json.dumps({"commit": {"sha": TIP}}).encode()
        if "/git/trees/" in url:
            self.ops.append("tree")
            tree = [
                {"path": path, "type": "blob", "sha": _blob_sha(content)}
                for path, content in self.files.items()
            ]
            tree.append(
                {
                    "path": "metadata.json",
                    "type": "blob",
                    "sha": _blob_sha(self.metadata_raw),
                }
            )
            tree.append({"path": "thumbs/ignored.jpg", "type": "blob", "sha": "x"})
            tree.append({"path": ".gitattributes", "type": "blob", "sha": "y"})
            return json.dumps({"tree": tree, "truncated": False}).encode()
        if "/contents/metadata.json" in url:
            self.ops.append("fetch:metadata.json")
            return self.metadata_raw
        if "/contents/" in url:
            path = url.split("/contents/", 1)[1].split("?")[0]
            self.ops.append(f"pointer:{path}")
            _, pointer_bytes = _pointer(self.files[path])
            return pointer_bytes
        if url.endswith("/info/lfs/objects/batch"):
            self.ops.append("lfs-batch")
            requested = json.loads(data.decode())["objects"]
            objects = [
                {
                    "oid": obj["oid"],
                    "size": obj["size"],
                    "actions": {"download": {"href": f"https://dl.fake/{obj['oid']}"}},
                }
                for obj in requested
            ]
            return json.dumps({"objects": objects}).encode()
        raise AssertionError(f"unexpected request: {url}")

    # -- presigned download double ------------------------------------------
    def _urlopen(self, req, timeout=0, context=None):
        href = req.full_url if hasattr(req, "full_url") else req
        oid = href.rsplit("/", 1)[1]
        for content in self.files.values():
            if hashlib.sha256(content).hexdigest() == oid:
                self.ops.append(f"download:{oid[:8]}")
                payload = b"CORRUPT!" if self.corrupt_downloads else content
                return _FakeResponse(payload)
        raise AssertionError(f"unknown download oid: {oid}")


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, n=-1):
        return super().read(n)


@pytest.fixture()
def library_dir(tmp_path: Path) -> Path:
    d = tmp_path / "frame_art"
    (d / "library").mkdir(parents=True)
    return d


def _make(library_dir: Path, repo: FakeRepo, monkeypatch, **kwargs) -> LibrarySyncer:
    syncer = LibrarySyncer(
        library_dir=library_dir,
        repo="billyfw/frame_art",
        branch="main",
        token="test-token",
        **kwargs,
    )
    repo.attach(syncer, monkeypatch)
    return syncer


FILES = {
    "library/a.jpg": b"image-a-bytes" * 100,
    "library/b.png": b"image-b-bytes" * 200,
}
METADATA = {"version": "1.0", "tags": ["x"], "images": {"a.jpg": {}, "b.png": {}}}


def test_fresh_sync_downloads_files_then_metadata(library_dir, monkeypatch):
    repo = FakeRepo(FILES, METADATA)
    result = _make(library_dir, repo, monkeypatch).run()

    assert sorted(result.added) == sorted(FILES)
    assert (library_dir / "library/a.jpg").read_bytes() == FILES["library/a.jpg"]
    assert (library_dir / "library/b.png").read_bytes() == FILES["library/b.png"]
    assert json.loads((library_dir / "metadata.json").read_text()) == METADATA

    state = json.loads((library_dir / ".library_sync_state.json").read_text())
    assert state["last_synced_commit"] == TIP
    assert set(state["files"]) == set(FILES) | {"metadata.json"}

    # ordering guarantee: metadata fetched after every download completed
    meta_idx = repo.ops.index("fetch:metadata.json")
    download_idxs = [i for i, op in enumerate(repo.ops) if op.startswith("download:")]
    assert download_idxs and meta_idx > max(download_idxs)
    # thumbs/.gitattributes never fetched
    assert not any("thumbs" in op or "gitattributes" in op for op in repo.ops)


def test_noop_when_commit_unchanged(library_dir, monkeypatch):
    repo = FakeRepo(FILES, METADATA)
    _make(library_dir, repo, monkeypatch).run()
    repo.ops.clear()

    result = _make(library_dir, repo, monkeypatch).run()
    assert result.skipped is True
    assert repo.ops == ["tip"]  # nothing but the tip check


def test_adoption_of_existing_files_skips_download(library_dir, monkeypatch):
    # Simulate the Madrone case: files already on disk (old git checkout).
    for path, content in FILES.items():
        dest = library_dir / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)

    repo = FakeRepo(FILES, METADATA)
    result = _make(library_dir, repo, monkeypatch).run()

    assert sorted(result.adopted) == sorted(FILES)
    assert result.added == []
    assert not any(op.startswith("download:") for op in repo.ops)
    assert not any(op == "lfs-batch" for op in repo.ops)


def test_deletion_removes_file_and_state(library_dir, monkeypatch):
    repo = FakeRepo(FILES, METADATA)
    _make(library_dir, repo, monkeypatch).run()

    del repo.files["library/b.png"]
    repo.metadata_raw = json.dumps(
        {"version": "1.0", "tags": [], "images": {"a.jpg": {}}}
    ).encode()
    global TIP
    monkeypatch.setattr(library_sync, "time", library_sync.time)  # no-op keep import
    # new tip so the run isn't skipped
    new_tip = "d00d" * 10
    monkeypatch.setattr(
        FakeRepo,
        "_request",
        _tip_swapped_request(new_tip),
    )

    result = _make(library_dir, repo, monkeypatch).run()
    assert result.deleted == ["library/b.png"]
    assert not (library_dir / "library/b.png").exists()
    state = json.loads((library_dir / ".library_sync_state.json").read_text())
    assert "library/b.png" not in state["files"]
    assert (library_dir / "library/a.jpg").exists()


def _tip_swapped_request(new_tip):
    original = FakeRepo._request

    def wrapper(self, url, headers, data=None, timeout=0):
        if "/branches/" in url:
            self.ops.append("tip")
            return json.dumps({"commit": {"sha": new_tip}}).encode()
        return original(self, url, headers, data=data, timeout=timeout)

    return wrapper


def test_integrity_failure_blocks_metadata_update(library_dir, monkeypatch):
    repo = FakeRepo(FILES, METADATA)
    repo.corrupt_downloads = True

    with pytest.raises(LibrarySyncError):
        _make(library_dir, repo, monkeypatch).run()

    # Nothing installed: no corrupted file, no metadata, no synced commit.
    assert not (library_dir / "library/a.jpg").exists()
    assert not (library_dir / "metadata.json").exists()
    if (library_dir / ".library_sync_state.json").exists():
        state = json.loads((library_dir / ".library_sync_state.json").read_text())
        assert state.get("last_synced_commit") != TIP


def test_auth_error_is_distinct(library_dir, monkeypatch):
    syncer = LibrarySyncer(
        library_dir=library_dir, repo="r/r", branch="main", token="bad"
    )

    def raise_auth(url, headers, data=None, timeout=0):
        import urllib.error

        raise LibraryAuthError("GitHub auth failed (HTTP 401)")

    monkeypatch.setattr(syncer, "_request", raise_auth)
    with pytest.raises(LibraryAuthError):
        syncer.run()
