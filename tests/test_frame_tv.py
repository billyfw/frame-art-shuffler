"""Tests for the post-wake screen verification in frame_tv."""
from unittest.mock import patch

from custom_components.frame_art_shuffler import frame_tv


def test_verify_screen_on_retries_then_succeeds():
    """A TV that answers on the second poll counts as awake, after one delay."""
    sleeps: list[float] = []
    with patch.object(frame_tv.time, "sleep", lambda s: sleeps.append(s)), patch.object(
        frame_tv, "is_screen_on", side_effect=[False, True]
    ) as check:
        assert frame_tv.verify_screen_on("10.0.0.1") is True
    assert check.call_count == 2
    assert sleeps == [4.0]


def test_verify_screen_on_gives_up_after_attempts():
    """A TV that never answers (cold standby after a power loss) is reported as not on."""
    sleeps: list[float] = []
    with patch.object(frame_tv.time, "sleep", lambda s: sleeps.append(s)), patch.object(
        frame_tv, "is_screen_on", return_value=False
    ) as check:
        assert frame_tv.verify_screen_on("10.0.0.1", attempts=3, delay=4.0) is False
    assert check.call_count == 3
    assert sleeps == [4.0, 4.0]


def test_verify_screen_on_fast_path_no_sleep():
    """An immediate answer needs no delay."""
    with patch.object(frame_tv.time, "sleep") as sleep, patch.object(
        frame_tv, "is_screen_on", return_value=True
    ):
        assert frame_tv.verify_screen_on("10.0.0.1") is True
    sleep.assert_not_called()
