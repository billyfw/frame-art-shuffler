from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types

import pytest

MODULE_PATH = (
    Path(__file__).resolve().parent.parent
    / "custom_components"
    / "frame_art_shuffler"
    / "flow_utils.py"
)

spec = importlib.util.spec_from_file_location("flow_utils", MODULE_PATH)
assert spec and spec.loader  # for type checking
flow_utils = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = flow_utils
spec.loader.exec_module(flow_utils)

parse_tag_string = flow_utils.parse_tag_string
pair_tv = flow_utils.pair_tv
safe_token_filename = flow_utils.safe_token_filename
validate_host = flow_utils.validate_host


@pytest.mark.parametrize(
    "value,expected",
    [
        ("192.168.1.10", "192.168.1.10"),
        ("frame-tv.local", "frame-tv.local"),
        ("MyHost", "MyHost"),
    ],
)
def test_validate_host_accepts_valid_inputs(value: str, expected: str) -> None:
    assert validate_host(value) == expected


@pytest.mark.parametrize("value", ["", "invalid host", "???", "256.0.0.1"])
def test_validate_host_rejects_invalid_inputs(value: str) -> None:
    with pytest.raises(ValueError):
        validate_host(value)


def test_parse_tag_string_handles_commas_and_newlines() -> None:
    raw = "tag1, tag2\nTag3\n"
    assert parse_tag_string(raw) == ["tag1", "tag2", "Tag3"]


def test_safe_token_filename_sanitizes_characters() -> None:
    assert safe_token_filename("tv.example.com") == "tv_example_com"
    assert safe_token_filename("192.168.1.10") == "192_168_1_10"


def test_pair_tv_success(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    calls: dict[str, object] = {}

    class FakeRemote:
        def __init__(self, host: str, name: str, port: int, token_file: str, timeout: float) -> None:
            calls["init"] = {
                "host": host,
                "name": name,
                "port": port,
                "token_file": token_file,
                "timeout": timeout,
            }

        def open(self) -> None:  # pragma: no cover - trivial
            calls["opened"] = True

        def close(self) -> None:  # pragma: no cover - trivial
            calls["closed"] = True

    remote_module = types.SimpleNamespace(SamsungTVWS=FakeRemote)
    monkeypatch.setitem(sys.modules, "samsungtvws", types.SimpleNamespace(remote=remote_module))
    monkeypatch.setitem(sys.modules, "samsungtvws.remote", remote_module)

    token_path = tmp_path / "token"
    assert pair_tv("192.168.1.10", token_path) is True
    assert calls["init"]["host"] == "192.168.1.10"
    assert calls["init"]["port"] == 8002
    assert calls["init"]["token_file"] == str(token_path)
    assert calls["init"]["timeout"] == 12.0


def test_pair_tv_failure(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    class FakeRemote:
        def __init__(self, *args, **kwargs) -> None:
            raise RuntimeError("boom")

    remote_module = types.SimpleNamespace(SamsungTVWS=FakeRemote)
    monkeypatch.setitem(sys.modules, "samsungtvws", types.SimpleNamespace(remote=remote_module))
    monkeypatch.setitem(sys.modules, "samsungtvws.remote", remote_module)
    monkeypatch.setattr(flow_utils.time, "sleep", lambda x: None)

    token_path = tmp_path / "token"
    assert pair_tv("host", token_path) is False
