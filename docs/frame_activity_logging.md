# Frame Activity Logging Plan

## 1. Goals
- Provide a durable, shared log the Home Assistant integration maintains and the Frame TV Manager add-on reads.
- Support aggregated insights by TV, image, and tag while also storing up to six months of raw display events for troubleshooting or recompute needs.
- Keep writes lightweight and resilient to HA restarts; real-time precision is not required.

## 2. Storage Layout
- Root directory: `/config/frame_art/logs` (created on setup if missing).
- Files:
  - `summary.json` – current aggregate snapshot (by TV/image/tag, plus metadata).
  - `events.json` – rolling array of raw session entries covering the configured retention window (default 6 months).
  - `pending.json` (optional) – transient buffer persisted between flush intervals so short-term data survives restarts.
- Permissions: integration writes/reads; add-on reads only.

## 3. Data Capture Workflow
1. **Event observation**: hook into shuffle/display lifecycle so every time a TV finishes displaying an image (e.g., at the 15-minute shuffle tick) we record: timestamp, TV device name, image filename, duration seconds, list of tags (union of integration and file metadata), and optional additional context (source, shuffle mode).
2. **In-memory queue**: append new event records to an in-memory list.
3. **Flush timer**: every 2–5 minutes (configurable), the integration attempts to persist queued events:
   - Read `events.json` (if present) and append queued events.
   - Trim array to the retention window (based on timestamps and user-configured months).
   - Write back using atomic temp-file + rename.
   - Recompute `summary.json` from the trimmed events (see Section 4).
   - Clear the in-memory queue and delete `pending.json`.
4. **Restart behavior**: on HA startup, load `pending.json` (if it exists) into the queue so unsaved events survive unexpected restarts. If `pending.json` becomes corrupted, log an error and discard (user loses those minutes but system continues).

## 4. Summary Generation
- Each flush rebuilds aggregates to keep math simple and robust.
- Snapshot structure:
  ```json
  {
    "version": 1,
    "generated_at": "2025-12-02T09:15:00Z",
    "retention_months": 6,
    "logging_enabled": true,
    "flush_interval_minutes": 5,
    "tvs": { ... },
    "images": { ... },
    "tags": { ... },
    "totals": {
      "tracked_seconds": 12345,
      "event_count": 456
    }
  }
  ```
- Aggregations:
  - **TVs**: keyed by FAS TV device name; each entry stores `total_display_seconds`, `event_count`, `per_image` array, and `per_tag` array.
  - **Images**: keyed by filename (or hash if duplicates possible); includes `tags`, `total_display_seconds`, `per_tv` array.
  - **Tags**: keyed by tag slug; includes `total_display_seconds`, `per_tv` array, and optional top images. When an image has zero tags, record an explicit tag value `<none>` so dashboards can surface untagged usage.
- Percentages are computed relative to each section’s totals (e.g., per TV percentages sum to 100%).
- Keep numeric precision modest (two decimals) to limit file size.

## 5. Retention & Rotation
- User-configurable retention between 1 and 12 months, default 6.
- Implementation trims `events.json` on every flush by discarding entries older than `now - retention_window`.
- When the user shortens retention via UI, immediately prune events beyond the new window and regenerate summary at the next flush (or trigger an on-demand flush). When the user lengthens retention, only future data is captured; older data is gone.
- Optional enhancement: when file size exceeds a ceiling (e.g., 20 MB), warn the user that more data is being stored than expected.

## 6. Error Handling & Observability
- Wrap every flush in try/except. On failure:
  - Leave `pending.json` intact so queued events retry on next interval.
  - Log error to Home Assistant logger with stack trace.
  - Create/update a persistent notification for the owner ("Frame Art logging failed: <details>").
  - Expose a binary sensor or diagnostic entity (`sensor.frame_art_log_status`) that flips to `error` until the next successful flush.
- Include metrics (optional) such as number of events per flush or last flush timestamp for diagnostics.

## 7. Configuration & Dashboard UI
- Integration options flow:
  - Toggle logging on/off.
  - Retention length (months, default 6).
  - Flush interval (advanced, default 5 minutes).
- Dashboard (Frame TV Manager add-on) gear page:
  - Display the contents of `summary.json` in a collapsible/raw viewer for debugging.
  - Show metadata (last update timestamp, retention window).
  - Provide retention selector and toggle; when changed, call `frame_art_shuffler.set_log_options` to update config and trigger a flush.
  - Clarify that raw event file is not shown due to size but underpins the summary.

## 8. Access Path for Add-on
- Add-on should mount `/config/frame_art/logs` read-only.
- Expected files:
  - `summary.json` – parse once per UI refresh.
  - `events.json` – optional (if add-on needs deeper analytics later).
- Because this directory is outside `www`, it isn’t web-exposed; only HA core/add-on can access it.

## 9. Future Enhancements (Nice-to-haves)
- Switch to per-month event files if `events.json` rewrites become costly.
- Provide HA service to dump/export logs for manual inspection.
- Add CLI script in `scripts/` to pretty-print aggregates or validate schema.
- Consider incremental summary updates instead of full rebuild once data volume grows.

## 10. Add-on Integration Touchpoints
- **Service contract**: invoke `POST /api/services/frame_art_shuffler/set_log_options` (Supervisor token auth) with payload fields `logging_enabled`, `log_retention_months`, and/or `log_flush_interval_minutes`. Omit keys you are not changing. Example:
  ```bash
  curl -sS -X POST \
    -H "Authorization: Bearer $SUPERVISOR_TOKEN" \
    -H "Content-Type: application/json" \
    http://supervisor/core/api/services/frame_art_shuffler/set_log_options \
    -d '{
      "logging_enabled": true,
      "log_retention_months": 6,
      "log_flush_interval_minutes": 5
    }'
  ```
- **Summary fields**: the add-on UI should read `summary.json` and surface `generated_at`, `retention_months`, `logging_enabled`, `flush_interval_minutes`, plus tables for `tvs`, `images`, `tags`, and `totals.tracked_seconds`/`totals.event_count`.
- **Error handling**: if `summary.json` is missing or malformed, show a warning that the integration needs at least one flush cycle after enabling logging.
- **Scheduling**: recommend refreshing the summary view every 60–120 seconds; flush interval defaults to 5 minutes, so more frequent polling is unnecessary.

---
This plan is the foundation for both the integration implementation and the add-on display work. Update this document as schema or workflows evolve.
