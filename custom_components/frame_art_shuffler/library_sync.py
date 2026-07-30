"""Mirror the frame_art library from GitHub over HTTPS (no git required).

Multi-home architecture (see ha-frame-art-manager/docs/MULTI_HOME_PLAN.md §4):
the central Frame Art Manager on Fly.io is the only writer to the
billyfw/frame_art repo; each house's HA mirrors `library/*` + `metadata.json`
to the local library directory using the GitHub REST + Git LFS batch APIs with
a read-only fine-grained PAT.

Design notes:
- Pure synchronous Python (stdlib only). Callers run `LibrarySyncer.run()` in
  an executor. One sync at a time is enforced by the caller.
- State file `<library_dir>/.library_sync_state.json` maps repo paths to their
  git blob SHAs (the SHA of the LFS *pointer* file — a valid change detector)
  and is updated after every file lands, so an interrupted first sync resumes.
- Ordering guarantee: all `library/` files land before `metadata.json` is
  replaced, so a shuffle never picks a metadata entry whose file is missing.
- Never touches `.git/`, `thumbs/`, `originals/`, tokens, or logs.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import ssl
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

_LOGGER = logging.getLogger(__name__)

try:  # HA ships certifi; fall back to system CAs elsewhere
    import certifi

    _SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:  # pragma: no cover - depends on environment
    _SSL_CONTEXT = ssl.create_default_context()

STATE_FILENAME = ".library_sync_state.json"
USER_AGENT = "frame-art-shuffler-library-sync/1.0"
API_BASE = "https://api.github.com"
LFS_BATCH_CHUNK = 50
DOWNLOAD_CHUNK_BYTES = 1024 * 1024
HTTP_TIMEOUT_S = 60
DOWNLOAD_TIMEOUT_S = 300
MAX_RETRIES = 3
RETRY_BACKOFF_S = 2.0

LIBRARY_PREFIX = "library/"
METADATA_FILENAME = "metadata.json"


class LibrarySyncError(Exception):
    """Raised when a sync run cannot complete."""


class LibraryAuthError(LibrarySyncError):
    """Raised on 401/403 — bad or expired token. Callers should notify."""


@dataclass
class LibrarySyncResult:
    """Outcome of one sync run."""

    commit: str
    skipped: bool = False  # True when already at the synced commit
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    adopted: list[str] = field(default_factory=list)
    downloaded_bytes: int = 0
    duration_s: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "commit": self.commit,
            "skipped": self.skipped,
            "added": len(self.added),
            "updated": len(self.updated),
            "deleted": len(self.deleted),
            "adopted": len(self.adopted),
            "downloaded_bytes": self.downloaded_bytes,
            "duration_s": round(self.duration_s, 2),
        }


def _parse_lfs_pointer(text: str) -> Optional[tuple[str, int]]:
    """Return (oid, size) if text is an LFS pointer, else None."""
    if not text.startswith("version https://git-lfs"):
        return None
    oid = None
    size = None
    for line in text.splitlines():
        if line.startswith("oid sha256:"):
            oid = line.split("sha256:", 1)[1].strip()
        elif line.startswith("size "):
            try:
                size = int(line.split(" ", 1)[1].strip())
            except ValueError:
                return None
    if oid and size is not None:
        return oid, size
    return None


class LibrarySyncer:
    """Mirrors library/ + metadata.json from a GitHub repo to a local dir."""

    def __init__(
        self,
        library_dir: Path,
        repo: str,
        branch: str,
        token: str,
        full_verify: bool = False,
        progress_cb: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._library_dir = Path(library_dir)
        self._repo = repo
        self._branch = branch
        self._token = token
        self._full_verify = full_verify
        self._progress_cb = progress_cb
        self._state_path = self._library_dir / STATE_FILENAME
        self._tmp_dir = self._library_dir / "library" / ".sync_tmp"

    # ------------------------------------------------------------- HTTP --

    def _request(
        self,
        url: str,
        headers: dict[str, str],
        data: Optional[bytes] = None,
        timeout: int = HTTP_TIMEOUT_S,
    ) -> bytes:
        """GET/POST with retry+backoff. Raises LibrarySyncError on failure."""
        last_err: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT, **headers})
                with urllib.request.urlopen(req, timeout=timeout, context=_SSL_CONTEXT) as resp:
                    return resp.read()
            except urllib.error.HTTPError as err:
                if err.code in (401, 403):
                    raise LibraryAuthError(
                        f"GitHub auth failed (HTTP {err.code}) for {url.split('?')[0]} — "
                        "check the library sync token (read-only Contents PAT)"
                    ) from err
                if err.code == 404:
                    raise LibrarySyncError(f"Not found (HTTP 404): {url.split('?')[0]}") from err
                last_err = err
            except (urllib.error.URLError, TimeoutError, OSError) as err:
                last_err = err
            time.sleep(RETRY_BACKOFF_S * (2**attempt))
        raise LibrarySyncError(f"Request failed after {MAX_RETRIES} attempts: {last_err}")

    def _api_headers(self, raw: bool = False) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github.raw+json" if raw else "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _api_json(self, path: str) -> Any:
        return json.loads(self._request(f"{API_BASE}{path}", self._api_headers()))

    def _api_raw(self, path: str) -> bytes:
        return self._request(f"{API_BASE}{path}", self._api_headers(raw=True))

    def _lfs_batch_download(self, objects: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """Resolve LFS oids to download actions. Returns {oid: action}."""
        # Verified 2026-07-29 against billyfw/frame_art: HTTP Basic with
        # x-access-token:<token> works on the LFS batch endpoint.
        basic = base64.b64encode(f"x-access-token:{self._token}".encode()).decode()
        body = json.dumps(
            {"operation": "download", "transfers": ["basic"], "objects": objects}
        ).encode()
        raw = self._request(
            f"https://github.com/{self._repo}.git/info/lfs/objects/batch",
            {
                "Authorization": f"Basic {basic}",
                "Accept": "application/vnd.git-lfs+json",
                "Content-Type": "application/vnd.git-lfs+json",
            },
            data=body,
        )
        actions: dict[str, dict[str, Any]] = {}
        for obj in json.loads(raw).get("objects", []):
            download = (obj.get("actions") or {}).get("download")
            if download:
                actions[obj["oid"]] = download
            else:
                _LOGGER.warning(
                    "LFS batch returned no download action for %s: %s",
                    obj.get("oid"),
                    obj.get("error"),
                )
        return actions

    # ------------------------------------------------------------ state --

    def _load_state(self) -> dict[str, Any]:
        try:
            return json.loads(self._state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"last_synced_commit": None, "files": {}}

    def _save_state(self, state: dict[str, Any]) -> None:
        tmp = self._state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=1), encoding="utf-8")
        os.replace(tmp, self._state_path)

    # ------------------------------------------------------------- sync --

    def _progress(self, message: str) -> None:
        _LOGGER.debug("library_sync: %s", message)
        if self._progress_cb:
            self._progress_cb(message)

    def _get_branch_tip(self) -> str:
        data = self._api_json(f"/repos/{self._repo}/branches/{self._branch}")
        return data["commit"]["sha"]

    def _get_tree(self, commit_sha: str) -> list[dict[str, Any]]:
        data = self._api_json(f"/repos/{self._repo}/git/trees/{commit_sha}?recursive=1")
        if data.get("truncated"):
            raise LibrarySyncError(
                "GitHub tree listing was truncated — repo too large for recursive "
                "tree API; per-directory paging needs to be implemented"
            )
        return [item for item in data.get("tree", []) if item.get("type") == "blob"]

    def _fetch_pointer(self, path: str, ref: str) -> tuple[Optional[tuple[str, int]], bytes]:
        """Fetch a repo file's raw content; parse as LFS pointer if it is one."""
        raw = self._api_raw(f"/repos/{self._repo}/contents/{path}?ref={ref}")
        if len(raw) < 512:
            try:
                pointer = _parse_lfs_pointer(raw.decode("utf-8"))
            except UnicodeDecodeError:
                pointer = None
        else:
            pointer = None
        return pointer, raw

    def _download_object(self, action: dict[str, Any], dest: Path, oid: str, size: int) -> None:
        """Stream a presigned LFS download to dest, verifying sha256 + size."""
        headers = {"User-Agent": USER_AGENT, **(action.get("header") or {})}
        req = urllib.request.Request(action["href"], headers=headers)
        digest = hashlib.sha256()
        written = 0
        self._tmp_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=self._tmp_dir, delete=False) as tmp:
            tmp_path = Path(tmp.name)
            try:
                with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT_S, context=_SSL_CONTEXT) as resp:
                    while True:
                        chunk = resp.read(DOWNLOAD_CHUNK_BYTES)
                        if not chunk:
                            break
                        digest.update(chunk)
                        tmp.write(chunk)
                        written += len(chunk)
            except Exception:
                tmp_path.unlink(missing_ok=True)
                raise
        if written != size or digest.hexdigest() != oid:
            tmp_path.unlink(missing_ok=True)
            raise LibrarySyncError(
                f"Integrity check failed for {dest.name}: "
                f"got {written} bytes / sha {digest.hexdigest()[:12]}…, "
                f"expected {size} bytes / sha {oid[:12]}…"
            )
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.replace(tmp_path, dest)

    def run(self) -> LibrarySyncResult:
        """Execute one sync. Blocking — run in an executor."""
        started = time.monotonic()
        state = self._load_state()

        tip = self._get_branch_tip()
        if tip == state.get("last_synced_commit") and not self._full_verify:
            return LibrarySyncResult(commit=tip, skipped=True, duration_s=time.monotonic() - started)

        self._progress(f"syncing to {tip[:10]}")
        tree = self._get_tree(tip)
        wanted = {
            item["path"]: item
            for item in tree
            if item["path"].startswith(LIBRARY_PREFIX) or item["path"] == METADATA_FILENAME
        }

        result = LibrarySyncResult(commit=tip)
        known: dict[str, Any] = state.get("files", {})
        to_fetch: list[str] = []

        for path, item in wanted.items():
            if path == METADATA_FILENAME:
                continue  # handled last
            entry = known.get(path)
            if entry and entry.get("blob_sha") == item["sha"] and not self._full_verify:
                continue
            to_fetch.append(path)

        # Resolve pointers (oid/size) for files we need. Adoption: an existing
        # local file whose size matches the pointer needs no download.
        pending: list[dict[str, Any]] = []
        for path in to_fetch:
            pointer, raw = self._fetch_pointer(path, tip)
            local = self._library_dir / path
            if pointer is None:
                # Non-LFS blob (unexpected under library/, but handle): write raw.
                local.parent.mkdir(parents=True, exist_ok=True)
                tmp = local.with_suffix(local.suffix + ".sync_tmp")
                tmp.write_bytes(raw)
                os.replace(tmp, local)
                known[path] = {"blob_sha": wanted[path]["sha"], "size": len(raw)}
                (result.updated if path in known else result.added).append(path)
                self._save_state({**state, "files": known})
                continue
            oid, size = pointer
            if (
                not self._full_verify
                and path not in known
                and local.exists()
                and local.stat().st_size == size
            ):
                known[path] = {"blob_sha": wanted[path]["sha"], "size": size, "oid": oid}
                result.adopted.append(path)
                self._save_state({**state, "files": known})
                continue
            pending.append(
                {"path": path, "oid": oid, "size": size, "blob_sha": wanted[path]["sha"]}
            )

        # Batched LFS downloads, state saved after each file (resumable).
        for i in range(0, len(pending), LFS_BATCH_CHUNK):
            chunk = pending[i : i + LFS_BATCH_CHUNK]
            actions = self._lfs_batch_download(
                [{"oid": p["oid"], "size": p["size"]} for p in chunk]
            )
            for p in chunk:
                action = actions.get(p["oid"])
                if not action:
                    raise LibrarySyncError(f"No LFS download action for {p['path']}")
                dest = self._library_dir / p["path"]
                is_update = p["path"] in known
                self._download_object(action, dest, p["oid"], p["size"])
                known[p["path"]] = {
                    "blob_sha": p["blob_sha"],
                    "size": p["size"],
                    "oid": p["oid"],
                }
                result.downloaded_bytes += p["size"]
                (result.updated if is_update else result.added).append(p["path"])
                self._save_state({**state, "files": known})
                self._progress(f"downloaded {p['path']}")

        # Deletions: tracked library files no longer in the tree.
        for path in [p for p in list(known) if p.startswith(LIBRARY_PREFIX) and p not in wanted]:
            (self._library_dir / path).unlink(missing_ok=True)
            known.pop(path, None)
            result.deleted.append(path)
            self._save_state({**state, "files": known})

        # metadata.json LAST — only after every library file has landed.
        meta_item = wanted.get(METADATA_FILENAME)
        if meta_item:
            meta_known = known.get(METADATA_FILENAME)
            if not meta_known or meta_known.get("blob_sha") != meta_item["sha"] or self._full_verify:
                raw = self._api_raw(f"/repos/{self._repo}/contents/{METADATA_FILENAME}?ref={tip}")
                json.loads(raw)  # refuse to install unparseable metadata
                dest = self._library_dir / METADATA_FILENAME
                tmp = dest.with_suffix(".sync_tmp")
                tmp.write_bytes(raw)
                os.replace(tmp, dest)
                known[METADATA_FILENAME] = {"blob_sha": meta_item["sha"], "size": len(raw)}
                result.updated.append(METADATA_FILENAME)

        state["files"] = known
        state["last_synced_commit"] = tip
        self._save_state(state)

        # Best-effort cleanup of the temp dir.
        try:
            if self._tmp_dir.exists() and not any(self._tmp_dir.iterdir()):
                self._tmp_dir.rmdir()
        except OSError:
            pass

        result.duration_s = time.monotonic() - started
        return result
