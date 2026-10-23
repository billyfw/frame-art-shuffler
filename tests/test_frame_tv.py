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


class FakeArt:
    """A Frame's art channel as the display path sees it: a gallery, a current-artwork readback and a
    select reply. readback_follows_select=False models the 2026 Frame, whose readback never moves."""

    def __init__(self, *, gallery, current, select_reply=None, select_error=None, readback_follows_select=True):
        self.gallery = list(gallery)
        self.current = current
        self.select_reply = select_reply
        self.select_error = select_error
        self.readback_follows_select = readback_follows_select
        self.selected: list[str] = []
        self.deleted: list[list[str]] = []
        self.current_reads = 0

    def available(self):
        return [{"content_id": cid, "category_id": "MY-C0002"} for cid in self.gallery]

    def get_current(self):
        self.current_reads += 1
        return {"content_id": self.current}

    def select_image(self, content_id, category=None, show=True):
        if self.select_error:
            raise self.select_error
        self.selected.append(content_id)
        if self.readback_follows_select:
            self.current = content_id
        return self.select_reply

    def delete_list(self, ids):
        self.deleted.append(list(ids))
        self.gallery = [cid for cid in self.gallery if cid not in ids]
        return True


def _quiet(monkeypatch):
    sleeps: list[float] = []
    waits: list[float] = []
    monkeypatch.setattr(frame_tv.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(frame_tv, "_wait_with_countdown", lambda seconds, msg: waits.append(seconds))
    return sleeps, waits


def test_display_confirmed_by_the_tvs_select_reply(monkeypatch):
    """Firmware that answers select_image with image_selected needs no readback and no wait."""
    sleeps, waits = _quiet(monkeypatch)
    art = FakeArt(
        gallery=["MY_F0010", "MY_F0011"],
        current="MY_F0010",
        readback_follows_select=False,
        select_reply={"event": "image_selected", "content_id": "MY_F0011", "is_shown": "Yes"},
    )
    assert frame_tv._display_uploaded_art(art, "MY_F0011", wait_after_upload=0, debug=False) is True
    assert art.selected == ["MY_F0011"]
    assert art.current_reads == 1  # the read before the select only
    assert waits == [] and sleeps == []


def test_display_confirmed_by_the_2026_frames_actual_reply(monkeypatch):
    """The reply read on the second house Great Room: the request's own event name, the content id, is_shown Yes."""
    sleeps, waits = _quiet(monkeypatch)
    reply = {"event": "select_image", "request_id": "x", "content_id": "MY_F0011", "category_id": None,
             "sub_category_id": None, "matte_id": "none", "portrait_matte_id": "none", "is_shown": "Yes"}
    art = FakeArt(gallery=["SAM-F0222", "MY_F0011"], current="SAM-F0222", readback_follows_select=False, select_reply=reply)
    assert frame_tv._display_uploaded_art(art, "MY_F0011", wait_after_upload=0, debug=False) is True
    assert art.selected == ["MY_F0011"] and waits == [] and sleeps == []


def test_display_does_not_trust_a_reply_that_says_not_shown(monkeypatch):
    sleeps, waits = _quiet(monkeypatch)
    reply = {"event": "select_image", "content_id": "MY_F0011", "is_shown": "No"}
    art = FakeArt(gallery=["MY_F0010", "MY_F0011"], current="MY_F0010", select_reply=reply)
    # the readback moves on this (healthy) TV, so verification still passes, by the readback
    assert frame_tv._display_uploaded_art(art, "MY_F0011", wait_after_upload=0, debug=False) is True
    assert waits == [frame_tv._POST_DISPLAY_VERIFY_DELAY]


def test_display_verified_by_the_readback_when_the_reply_says_nothing(monkeypatch):
    """A reply without a content id falls back to the readback, which moves on a normal Frame."""
    sleeps, waits = _quiet(monkeypatch)
    art = FakeArt(gallery=["MY_F0010", "MY_F0011"], current="MY_F0010", select_reply={"event": "image_selected"})
    assert frame_tv._display_uploaded_art(art, "MY_F0011", wait_after_upload=0, debug=False) is True
    assert art.selected == ["MY_F0011"]
    assert waits == [frame_tv._POST_DISPLAY_VERIFY_DELAY] and sleeps == []


def test_display_with_a_stale_readback_trusts_the_selection_and_picks_nothing_else(monkeypatch):
    """The 2026 Frame: the readback never moves. Two unchanged reads mean trust the select; the gallery's
    last entry is never selected instead (that fallback swapped the picture back every shuffle)."""
    sleeps, waits = _quiet(monkeypatch)
    art = FakeArt(
        gallery=["SAM-F0222", "MY_F0011", "MY_F0010"],
        current="SAM-F0222",
        readback_follows_select=False,
        select_reply={},
    )
    assert frame_tv._display_uploaded_art(art, "MY_F0011", wait_after_upload=0, debug=False) is None
    assert art.selected == ["MY_F0011", "MY_F0011"]
    assert "MY_F0010" not in art.selected
    assert sleeps == [frame_tv._DISPLAY_RETRY_DELAYS[1]]
    assert waits == [frame_tv._POST_DISPLAY_VERIFY_DELAY] * 2


def test_display_is_false_when_the_tv_refuses_every_select(monkeypatch):
    sleeps, waits = _quiet(monkeypatch)
    art = FakeArt(gallery=["MY_F0010"], current="MY_F0010", select_error=RuntimeError("busy"))
    assert frame_tv._display_uploaded_art(art, "MY_F0011", wait_after_upload=0, debug=False) is False
    assert art.selected == [] and art.deleted == []


def test_display_is_false_when_the_readback_moves_somewhere_else(monkeypatch):
    """A readback that moves but never to our image is a failed display, not a stale readback."""
    _quiet(monkeypatch)
    art = FakeArt(gallery=["MY_F0010", "MY_F0011", "MY_F0012"], current="MY_F0010", select_reply={})
    reads = iter(["MY_F0012", "MY_F0010", "MY_F0012"])
    art.get_current = lambda: {"content_id": next(reads)}
    art.readback_follows_select = False
    assert frame_tv._display_uploaded_art(art, "MY_F0011", wait_after_upload=0, debug=False) is False


def test_cleanup_keeps_the_new_image_and_what_the_tv_reports_as_current(monkeypatch):
    """Deleting the on-screen image dropped the second house Great Room Frame to its Art Mode menu."""
    _quiet(monkeypatch)
    art = FakeArt(gallery=["SAM-F0222", "MY_F0010", "MY_F0011", "MY_F0011"], current="MY_F0010")
    frame_tv._delete_other_images(art, "MY_F0011", debug=False)
    assert art.deleted == [["SAM-F0222"]]
    assert art.gallery == ["MY_F0010", "MY_F0011", "MY_F0011"]


def test_cleanup_deletes_the_rest_when_the_tv_agrees_on_the_current_image(monkeypatch):
    _quiet(monkeypatch)
    art = FakeArt(gallery=["MY_F0010", "MY_F0011", "MY_F0011"], current="MY_F0011")
    frame_tv._delete_other_images(art, "MY_F0011", debug=False)
    assert art.deleted == [["MY_F0010"]]


def test_cleanup_still_runs_when_the_readback_fails(monkeypatch):
    _quiet(monkeypatch)
    art = FakeArt(gallery=["MY_F0010", "MY_F0011"], current="MY_F0011")
    art.get_current = lambda: (_ for _ in ()).throw(RuntimeError("timeout"))
    frame_tv._delete_other_images(art, "MY_F0011", debug=False)
    assert art.deleted == [["MY_F0010"]]


def _image_bytes(width, height, fmt="JPEG", mode="RGB", **save):
    import io
    from PIL import Image

    img = Image.new(mode, (width, height), (200, 120, 40) if mode == "RGB" else (200, 120, 40, 255))
    out = io.BytesIO()
    img.save(out, format=fmt, **save)
    return out.getvalue()


def _size_of(payload):
    import io
    from PIL import Image

    with Image.open(io.BytesIO(payload)) as img:
        return img.size, img.format


def test_fit_to_panel_shrinks_an_iphone_shot_to_the_panel(monkeypatch):
    """4032x2268 wedged the 2026 Frame's art app twice; it goes out as 3840x2160 baseline JPEG."""
    monkeypatch.setattr(frame_tv, "_log_progress", lambda msg: None)
    payload, file_type = frame_tv._fit_to_panel(_image_bytes(4032, 2268), "JPEG")
    assert file_type == "JPEG"
    assert _size_of(payload) == ((3840, 2160), "JPEG")


def test_fit_to_panel_passes_a_fitting_image_through_byte_for_byte(monkeypatch):
    monkeypatch.setattr(frame_tv, "_log_progress", lambda msg: None)
    original = _image_bytes(3840, 2160)
    payload, file_type = frame_tv._fit_to_panel(original, "JPEG")
    assert payload is original and file_type == "JPEG"
    small_png = _image_bytes(1280, 720, fmt="PNG")
    payload, file_type = frame_tv._fit_to_panel(small_png, "PNG")
    assert payload is small_png and file_type == "PNG"


def test_fit_to_panel_keeps_a_portrait_image_inside_the_panel(monkeypatch):
    monkeypatch.setattr(frame_tv, "_log_progress", lambda msg: None)
    payload, _ = frame_tv._fit_to_panel(_image_bytes(3024, 4032), "JPEG")
    (w, h), _ = _size_of(payload)
    assert h == 2160 and w <= 3840


def test_fit_to_panel_turns_an_oversize_png_into_a_jpeg(monkeypatch):
    monkeypatch.setattr(frame_tv, "_log_progress", lambda msg: None)
    payload, file_type = frame_tv._fit_to_panel(_image_bytes(5712, 3213, fmt="PNG", mode="RGBA"), "PNG")
    assert file_type == "JPEG" and _size_of(payload) == ((3840, 2160), "JPEG")


def test_fit_to_panel_passes_unreadable_bytes_through(monkeypatch):
    monkeypatch.setattr(frame_tv, "_log_progress", lambda msg: None)
    payload, file_type = frame_tv._fit_to_panel(b"not an image", "JPEG")
    assert payload == b"not an image" and file_type == "JPEG"
