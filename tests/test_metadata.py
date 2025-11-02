from __future__ import annotations

from pathlib import Path
import importlib.util
import sys

import pytest

MODULE_PATH = (
    Path(__file__).resolve().parent.parent
    / "custom_components"
    / "frame_art_shuffler"
    / "metadata.py"
)

spec = importlib.util.spec_from_file_location("frame_art_metadata", MODULE_PATH)
assert spec and spec.loader  # for type checkers
metadata = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = metadata
spec.loader.exec_module(metadata)

MetadataStore = metadata.MetadataStore
TVNotFoundError = metadata.TVNotFoundError


@pytest.fixture()
def metadata_path(tmp_path: Path) -> Path:
    return tmp_path / "metadata.json"


def test_upsert_and_list_tv(metadata_path: Path) -> None:
    store = MetadataStore(metadata_path)

    tv = store.upsert_tv(
        {
            "name": "Living Room",
            "ip": "192.168.1.10",
            "mac": "aa:bb:cc:dd:ee:ff",
            "tags": ["family"],
            "notTags": [],
        },
    )

    tvs = store.list_tvs()
    assert len(tvs) == 1
    assert tvs[0]["name"] == "Living Room"
    assert tvs[0]["id"] == tv["id"]


def test_remove_tv(metadata_path: Path) -> None:
    store = MetadataStore(metadata_path)

    tv = store.upsert_tv({"name": "TV", "ip": "1.1.1.1", "mac": "aa:bb:cc:dd:ee:ff"})

    store.remove_tv(tv["id"])

    assert store.list_tvs() == []


def test_remove_tv_missing(metadata_path: Path) -> None:
    store = MetadataStore(metadata_path)

    with pytest.raises(TVNotFoundError):
        store.remove_tv("missing")
