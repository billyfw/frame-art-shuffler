"""Tagset overrides go through their pictures in rounds (0.6.2).

During an override the recency windows stay off (they would carry the everyday tagset's
history into the override and hold back its pictures, the reason they were turned off in
January 2026). Instead each pool (a tag's, or every eligible picture without tag weighting)
is shown in rounds on each screen: nothing repeats until every picture in the pool has
shown, counted from the screen's own shuffles since the override began, as the display log
records them.
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.frame_art_shuffler import shuffle as shuffle_module
from custom_components.frame_art_shuffler.const import DOMAIN, LOG_EVENTS_FILENAME, LOG_STORAGE_RELATIVE_PATH
from custom_components.frame_art_shuffler.display_log import DisplayLogManager
from custom_components.frame_art_shuffler.shuffle import (
    _choose,
    _select_random_image,
    _shown_this_round,
)

PKG = "custom_components.frame_art_shuffler"

# Three tags of different sizes; "sea-1" also carries "hills" and goes to the heavier "sea".
LIBRARY = {
    **{f"sea-{i}.jpg": ["sea"] for i in range(1, 6)},
    **{f"hills-{i}.jpg": ["hills"] for i in range(1, 5)},
    **{f"bird-{i}.jpg": ["bird"] for i in range(1, 3)},
    "sea-1.jpg": ["sea", "hills"],
    "private-1.jpg": ["sea", "private"],
}
TAGSET = {
    "tags": ["sea", "hills", "bird"],
    "exclude_tags": ["private"],
    "tag_weights": {"sea": 5.0, "hills": 3.0, "bird": 1.0},
    "weighting_type": "tag",
}
POOLS = {
    "sea": {f"sea-{i}.jpg" for i in range(1, 6)},
    "hills": {f"hills-{i}.jpg" for i in range(1, 5)},
    "bird": {"bird-1.jpg", "bird-2.jpg"},
}


def _metadata(tmp_path: Path, library: dict[str, list[str]] = LIBRARY) -> Path:
    path = tmp_path / "metadata.json"
    images = {name: {"tags": tags, "matte": "none", "filter": "None"} for name, tags in library.items()}
    path.write_text(json.dumps({"version": "1.0", "images": images, "tvs": [], "tags": []}))
    return path


def _picks(metadata: Path, tagset: dict, count: int, *, seed: int, history=None, avoid=None):
    """Run `count` override picks, feeding each back as the screen's history."""
    random.seed(seed)
    history = list(history or [])
    current = history[-1] if history else None
    picks = []
    for _ in range(count):
        selected, _eligible, tag, _fresh, fallback, pool_size, position = _select_random_image(
            metadata,
            tagset["tags"],
            tagset.get("exclude_tags", []),
            tagset.get("tag_weights", {}),
            tagset.get("weighting_type", "image"),
            current,
            "Test",
            None,
            history,
            avoid,
        )
        current = selected["filename"]
        history.append(current)
        picks.append({"file": current, "tag": tag, "position": position, "pool": pool_size, "fallback": fallback})
    return picks


# --- the round bookkeeping ---------------------------------------------------------------


def test_a_round_ends_when_every_picture_has_shown():
    pool = {"a", "b", "c"}
    assert _shown_this_round([], pool) == set()
    assert _shown_this_round(["a", "b"], pool) == {"a", "b"}
    assert _shown_this_round(["a", "b", "a", "c"], pool) == set()  # a, b, c: the round is complete
    assert _shown_this_round(["a", "b", "c", "b"], pool) == {"b"}  # the next round has begun


def test_pictures_outside_the_pool_are_ignored_and_new_ones_join_the_round():
    assert _shown_this_round(["a", "x", "b", "y"], {"a", "b", "c"}) == {"a", "b"}
    # "d" joined the pool after a, b and c had shown: the round waits for it.
    assert _shown_this_round(["a", "b", "c"], {"a", "b", "c", "d"}) == {"a", "b", "c"}


# --- picks during an override --------------------------------------------------------------


@pytest.mark.parametrize("seed", range(5))
def test_no_picture_repeats_until_its_whole_tag_has_shown(tmp_path, seed):
    picks = _picks(_metadata(tmp_path), TAGSET, 300, seed=seed)
    for tag, pool in POOLS.items():
        sequence = [p for p in picks if p["tag"] == tag]
        assert len(sequence) > 3 * len(pool)
        for start in range(0, len(sequence) - len(pool) + 1, len(pool)):
            one_round = sequence[start:start + len(pool)]
            assert {p["file"] for p in one_round} == pool  # each picture once
            assert [p["position"] for p in one_round] == list(range(1, len(pool) + 1))
            assert all(p["pool"] == len(pool) for p in one_round)
            assert not any(p["fallback"] for p in one_round)


@pytest.mark.parametrize("seed", range(5))
def test_a_round_does_not_open_with_the_last_round_s_closing_pictures(tmp_path, seed):
    picks = _picks(_metadata(tmp_path), TAGSET, 300, seed=seed)
    for tag, pool in POOLS.items():
        files = [p["file"] for p in picks if p["tag"] == tag]
        for index, name in enumerate(files):
            later = files[index + 1:]
            if name in later:
                assert later.index(name) + 1 > len(pool) // 2, (tag, index)


def test_the_picture_on_screen_is_never_picked_again(tmp_path):
    two = {"bird-1.jpg": ["bird"], "bird-2.jpg": ["bird"]}
    picks = _picks(_metadata(tmp_path, two), {"tags": ["bird"]}, 12, seed=1)
    files = [p["file"] for p in picks]
    assert all(a != b for a, b in zip(files, files[1:]))


# Without tag weighting a tagset of "hills" alone takes every picture tagged hills, sea-1 too.
HILLS = POOLS["hills"] | {"sea-1.jpg"}


def test_the_count_starts_with_the_override_not_before(tmp_path):
    """Pictures the everyday tagset showed are not in the override's history and do not hold it back."""
    picks = _picks(_metadata(tmp_path), {"tags": ["hills"]}, 5, seed=3, history=[])
    assert {p["file"] for p in picks} == HILLS
    assert [p["position"] for p in picks] == [1, 2, 3, 4, 5]


def test_a_picture_another_screen_shows_now_waits_if_it_can(tmp_path):
    metadata = _metadata(tmp_path)
    hills = {"tags": ["hills"]}
    for seed in range(20):
        first = _picks(metadata, hills, 1, seed=seed, avoid={"hills-2.jpg"})
        assert first[0]["file"] != "hills-2.jpg"
    # Left last in its round, it is shown all the same.
    last = _picks(metadata, hills, 1, seed=0, history=["hills-1.jpg", "sea-1.jpg", "hills-3.jpg", "hills-4.jpg"],
                  avoid={"hills-2.jpg"})
    assert last[0]["file"] == "hills-2.jpg" and last[0]["position"] == 5


def test_without_tag_weighting_the_whole_set_is_one_round(tmp_path):
    picks = _picks(_metadata(tmp_path), {"tags": ["sea", "hills", "bird"], "exclude_tags": ["private"]}, 22, seed=4)
    everything = set().union(*POOLS.values())
    assert {p["file"] for p in picks[:11]} == everything
    assert {p["file"] for p in picks[11:]} == everything
    assert [p["position"] for p in picks[:11]] == list(range(1, 12))
    assert all(p["tag"] is None and p["pool"] == 11 for p in picks)


def test_only_the_picture_on_screen_left_starts_a_new_round():
    """The last unshown picture is on screen (put there by a manual display): a new round begins."""
    candidates = [{"filename": "a"}, {"filename": "b"}]  # "c" is on screen
    random.seed(0)
    selected, fresh, new_round, position = _choose(candidates, {"a", "b", "c"}, None, ["a", "b"], None)
    assert new_round and position == 1 and selected["filename"] in ("a", "b") and fresh == 2


# --- the everyday rule is unchanged --------------------------------------------------------


def test_outside_an_override_the_recency_preference_is_unchanged():
    candidates = [{"filename": name} for name in ("a", "b", "c")]
    for seed in range(10):
        random.seed(seed)
        selected, fresh, fallback, position = _choose(candidates, {"a", "b", "c"}, {"a", "b"}, None, None)
        assert (selected["filename"], fresh, fallback, position) == ("c", 1, False, None)
    random.seed(0)
    selected, fresh, fallback, position = _choose(candidates, {"a", "b", "c"}, {"a", "b", "c"}, None, None)
    assert fresh == 0 and fallback and position is None
    selected, fresh, fallback, position = _choose(candidates, {"a", "b", "c"}, None, None, None)
    assert fresh == 0 and not fallback and position is None
    # recent_images is ignored when rounds apply, and the avoid set only applies to rounds
    selected, fresh, fallback, position = _choose(candidates, {"a", "b", "c"}, set(), None, {"a", "b"})
    assert position is None


def test_outside_an_override_the_same_random_draws_give_the_same_picks(tmp_path):
    """Byte for byte: the selector consumes the random stream exactly as before 0.6.2."""
    metadata = _metadata(tmp_path)
    recent = {"sea-2.jpg", "hills-1.jpg"}
    random.seed(11)
    got = [
        _select_random_image(metadata, TAGSET["tags"], TAGSET["exclude_tags"], TAGSET["tag_weights"], "tag",
                             "sea-3.jpg", "Test", recent)[0]["filename"]
        for _ in range(30)
    ]
    in_metadata_order = list(json.loads(metadata.read_text())["images"])
    random.seed(11)
    expected = []
    for _ in range(30):
        # the 0.6.1 algorithm, inlined: a tag by weight, then a fresh picture in it
        roll = random.random() * 9.0
        tag = "sea" if roll <= 5.0 else "hills" if roll <= 8.0 else "bird"
        candidates = [name for name in in_metadata_order if name in POOLS[tag] and name != "sea-3.jpg"]
        fresh = [name for name in candidates if name not in recent]
        expected.append(random.choice(fresh) if fresh else random.choice(candidates))
    assert got == expected


# --- the history, from the display log -----------------------------------------------------


@pytest.fixture
async def display_log(hass, tmp_path):
    # Each test its own log: the test harness's config folder is shared by every test.
    hass.config.config_dir = str(tmp_path)
    entry = MockConfigEntry(domain=DOMAIN, data={"tvs": {}, "tagsets": {}}, options={})
    entry.add_to_hass(hass)
    log = DisplayLogManager(hass, entry)
    await log.async_setup()
    yield log
    await log.async_shutdown()


async def _session(log: DisplayLogManager, minute: int, filename: str, tagset: str | None, source="shuffle", tv="tv1"):
    started = datetime(2026, 11, 14, 18, 0, tzinfo=timezone.utc) + timedelta(minutes=minute)
    if source == "screen_on":
        log.note_screen_on(tv_id=tv, tv_name=tv, filename=filename, started_at=started, tagset_name=tagset)
    else:
        log.note_display_start(tv_id=tv, tv_name=tv, filename=filename, tags=[], source=source,
                               shuffle_mode="auto" if source == "shuffle" else None, started_at=started,
                               tagset_name=tagset)


async def test_the_run_is_read_from_the_log_queue_and_screen(display_log):
    log = display_log
    await _session(log, 0, "home-1.jpg", "everyday")
    await _session(log, 15, "trip-1.jpg", "trip")          # the override begins
    await _session(log, 15, "other-tv.jpg", "trip", tv="tv2")
    await _session(log, 30, "trip-2.jpg", "trip")
    await log.async_flush(force=True)                       # stored
    await _session(log, 40, "manual.jpg", None, source="manual")   # names no tagset: neutral
    await _session(log, 45, "trip-3.jpg", "trip")           # queued, not yet flushed
    await _session(log, 60, "trip-4.jpg", "trip")           # on screen now
    assert await log.async_get_tagset_run("tv1", "trip") == ["trip-1.jpg", "trip-2.jpg", "trip-3.jpg", "trip-4.jpg"]
    assert await log.async_get_tagset_run("tv2", "trip") == ["other-tv.jpg"]


async def test_a_screen_on_resumption_does_not_count_and_another_tagset_ends_the_run(display_log):
    log = display_log
    await _session(log, 0, "trip-1.jpg", "trip")
    await _session(log, 15, "home-1.jpg", "everyday")       # the last override ended
    await _session(log, 30, "trip-2.jpg", "trip")           # a new one began
    log.note_screen_off(tv_id="tv1", tv_name="tv1")
    await _session(log, 50, "trip-2.jpg", None, source="screen_on")    # startup's resumed session
    await _session(log, 55, "trip-2.jpg", "trip", source="screen_on")  # resumed, same picture
    await _session(log, 60, "trip-3.jpg", "trip")
    assert await log.async_get_tagset_run("tv1", "trip") == ["trip-2.jpg", "trip-3.jpg"]


async def test_no_display_log_means_no_rounds(hass, tmp_path):
    hass.config.config_dir = str(tmp_path)
    entry = MockConfigEntry(domain=DOMAIN, data={"tvs": {}, "tagsets": {}}, options={"logging_enabled": False})
    entry.add_to_hass(hass)
    log = DisplayLogManager(hass, entry)
    await log.async_setup()
    assert await log.async_get_tagset_run("tv1", "trip") is None


# --- inside Home Assistant: a wall tablet under an override, across a restart ---------------

TABLET_ID = "tablet0001"
SHOWING = "input_boolean.wall_showing"
TRIP = [f"trip-{i}.jpg" for i in range(1, 8)]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def no_tv_calls():
    with patch(f"{PKG}.shuffle.set_art_on_tv_deleteothers", MagicMock(side_effect=AssertionError("upload"))), \
            patch(f"{PKG}.frame_tv.is_screen_on", MagicMock(return_value=False)), \
            patch(f"{PKG}.async_generate_dashboard", AsyncMock(return_value=False)):
        yield


async def _setup_tablet(hass: HomeAssistant, tmp_path: Path) -> MockConfigEntry:
    hass.config.config_dir = str(tmp_path)  # this test's own display log
    assert await async_setup_component(hass, "input_boolean", {"input_boolean": {"wall_showing": {"name": "Wall showing"}}})
    root = tmp_path / "media" / "frame_art"
    (root / "library").mkdir(parents=True)
    library = {**{name: ["trip"] for name in TRIP}, **{f"home-{i}.jpg": ["home"] for i in range(1, 5)}}
    images = {}
    for name, tags in library.items():
        Image.new("RGB", (64, 36), (20, 90, 160)).save(root / "library" / name, "JPEG")
        images[name] = {"tags": tags, "matte": "none", "filter": "None"}
    (root / "metadata.json").write_text(json.dumps({"version": "1.0", "images": images, "tvs": [], "tags": []}))
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Frame Art Shuffler",
        data={
            "metadata_path": str(root / "metadata.json"),
            "token_dir": str(tmp_path / "tokens"),
            "tvs": {TABLET_ID: {
                "id": TABLET_ID, "kind": "tablet", "name": "Wall Test", "short_name": "Wall",
                "showing_entity": SHOWING, "selected_tagset": "everyday",
                "shuffle_frequency_minutes": 5, "enable_auto_shuffle": True,
            }},
            "tagsets": {
                "everyday": {"tags": ["home", "trip"], "exclude_tags": []},
                "trip": {"tags": ["trip"], "exclude_tags": []},
            },
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await hass.services.async_call("input_boolean", "turn_on", {"entity_id": SHOWING}, blocking=True)
    await hass.async_block_till_done()
    return entry


def _on_screen(hass: HomeAssistant, entry: MockConfigEntry) -> str:
    return hass.data[DOMAIN][entry.entry_id]["shuffle_cache"][TABLET_ID]["current_image"]


async def _auto_shuffle(hass: HomeAssistant, entry: MockConfigEntry) -> str:
    await hass.data[DOMAIN][entry.entry_id]["async_run_auto_shuffle"](TABLET_ID)
    await hass.async_block_till_done()
    return _on_screen(hass, entry)


async def test_an_override_goes_through_its_set_in_rounds_across_a_restart(hass, tmp_path, no_tv_calls):
    entry = await _setup_tablet(hass, tmp_path)
    for _ in range(6):  # the everyday tagset shows trip pictures too; they must not hold the override back
        await _auto_shuffle(hass, entry)

    messages: list[str] = []
    real_log_activity = shuffle_module.log_activity

    def _capture(hass_, entry_id, tv_id, event_type, message=None, icon=None):
        if event_type == "shuffle":
            messages.append(message)
        return real_log_activity(hass_, entry_id, tv_id, event_type, message, icon)

    with patch(f"{PKG}.shuffle.log_activity", _capture):
        await hass.services.async_call(
            DOMAIN, "override_tagset", {"device_id": _device_id(hass, entry), "name": "trip", "duration_minutes": 600},
            blocking=True,
        )
        await hass.async_block_till_done()
        shown = [_on_screen(hass, entry)]
        for _ in range(2):
            shown.append(await _auto_shuffle(hass, entry))

        # A restart in the middle of the round: the round comes back from the display log.
        assert await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        reloaded_log = hass.data[DOMAIN][entry.entry_id]["display_log"]
        assert await reloaded_log.async_get_tagset_run(TABLET_ID, "trip") == shown
        for _ in range(4):
            shown.append(await _auto_shuffle(hass, entry))
        assert sorted(shown) == TRIP  # seven pictures, seven different, across the restart

        next_round = await _auto_shuffle(hass, entry)
        assert next_round not in shown[-3:]  # a round does not open with the last one's closing pictures

    assert messages[0] == f"Shuffled to {shown[0]} (1 of 7 this round)"
    assert messages[6] == f"Shuffled to {shown[6]} (7 of 7 this round)"
    assert messages[7] == f"Shuffled to {next_round} (1 of 7 this round)"

    # The pool-health trend stays out of overrides.
    display_log = hass.data[DOMAIN][entry.entry_id]["display_log"]
    await display_log.async_finalize_active_sessions()
    events_file = Path(hass.config.path(LOG_STORAGE_RELATIVE_PATH)) / LOG_EVENTS_FILENAME
    events = [json.loads(line) for line in events_file.read_text().splitlines()]
    during = [e for e in events if e.get("tagset_name") == "trip"]
    before = [e for e in events if e.get("tagset_name") == "everyday" and e.get("shuffle_mode") == "auto"]
    assert during and all("pool_size" not in e for e in during)
    assert before and all("pool_size" in e for e in before)


def _device_id(hass: HomeAssistant, entry: MockConfigEntry) -> str:
    from homeassistant.helpers import device_registry as dr
    return dr.async_get(hass).async_get_device_by_identifier((DOMAIN, TABLET_ID), entry.entry_id).id
