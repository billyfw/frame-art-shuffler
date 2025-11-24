# Vendored Dependencies

## samsungtvws

This component includes a bundled ("vendored") copy of the `samsungtvws` library located in `custom_components/frame_art_shuffler/samsungtvws/`.

- **Current Version:** 3.0.3 (Snapshot from Nov 24, 2025)
- **Upstream Repository:** [xchwarze/samsung-tv-ws-api](https://github.com/xchwarze/samsung-tv-ws-api)

### Why?
Home Assistant's built-in `samsungtv` integration relies on an older version of this library. Python cannot load two versions of the same library simultaneously. If we rely on the system version, Home Assistant forces us to use the old one, which lacks critical features for modern Frame TVs (specifically `wait_for_response` and reliable chunked uploads).

By bundling the library inside our component package, we isolate it from the rest of Home Assistant, ensuring we always use the version that supports our features.

### How to Update
If Samsung releases a firmware update that breaks the API (e.g., authentication changes, protocol shifts), you should:

1. Check the [upstream repository](https://github.com/xchwarze/samsung-tv-ws-api) to see if they have fixed it.
2. If a fix exists, download the source code of the new version.
3. Replace the contents of `custom_components/frame_art_shuffler/samsungtvws/` with the new source code.
4. Verify that `frame_tv.py` imports still work correctly.
