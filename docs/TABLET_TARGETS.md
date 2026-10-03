# Tablet targets and the private library (0.4.0, 2026-10-03)

Why: Billy's wall tablets (the maui-tablets repo) are frame-art displays like the TVs: their own
tagset in the manager, the shuffler picking and rotating, display logs and analytics, the picture
shown full screen on the tablet's dashboard when nobody is using it. And a finding the same day:
an entry whose library sits in `www/frame_art` (every entry before 0.4.0) publishes
`metadata.json` (every filename and tag) and every picture at `/local/frame_art/` with no login,
on the LAN, the tailnet and the Nabu Casa remote URL (verified on Madrone, 2026-10-03).

## What changed

- **`kind`** on each target (`entry.data["tvs"][id]["kind"]`): `tv` when absent, `tablet` for
  the new kind (`targets.py`). Nothing is migrated; every existing target stays a TV.
- **Tablet shuffle** (`shuffle.py`): selection, recency, `shuffle_cache`, activity and display
  log as for a TV; no upload, no matte or filter, no brightness sync. No include tags means no
  pictures (an allow-list on a communal screen); the skip is logged once until tags appear.
- **Tablet screen state** (`binary_sensor.py`): mirrors the showing entity; off, missing or
  unavailable all count as not showing. Off closes the display-log session; on restarts the
  interval and picks at once unless the last pick is under 60 s old (then it reopens the
  session for the picture on screen). The TV poll skips tablets (no IP).
- **Artwork image entity** for every target (`image.py`): the current pick through HA's image
  proxy (rotating access tokens, logged-in users only), rendered by `artwork.py` as a JPEG fitted
  to 1920 x 1200 and cached in `<library root>/.derivatives/` (300 most recent), warmed right
  after each pick. File names are resolved inside the library only (`resolve_library_file`).
- **Library folder** (`config_flow.py`, user step): new entries choose it, default
  `/media/frame_art`. `entity_picture` on the current-artwork sensor and the generated dashboard
  use `/local/` only when the library really is under www (`public_library_url`); otherwise the
  dashboard shows the image entity.
- **Options flow**: "Add a wall tablet" and an edit form for tablets. Adding or editing a TV no
  longer wipes `entry.options` (the returned data becomes the options; `data={}` erased the
  library-sync token and the logging settings).
- **Device info** through `target_device_info` (model "Wall tablet" or "Frame TV").
- `display_image`: the library `filename` wins over `image_url` (the manager sends both; a
  library outside www has no `/local` URL). On a tablet it needs a library file.
- Auto-shuffle timers share one unload hook (a tablet restarts its timer every time it starts
  showing art; a hook per restart grew the unload list).
- Packaging: `hacs.json` at the repository root (it sat inside the component, where HACS does
  not look), manifest URLs to billyfw, version 0.4.0.

## Not changed

- Madrone's entry keeps its www library and its behaviour; moving it to `/media` (closing its
  exposure) is a separate decision: create the folder, move `library/`, `metadata.json` and the
  sync state, point `metadata_path` at it, restart.
- Cross-target recency: a fast-rotating tablet marks many pictures as recent for the TVs'
  cross-TV window (72 h by default, `set_recency_windows`). Watch it once a house has both.
