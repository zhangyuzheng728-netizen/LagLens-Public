# In-window report switcher

Status: implemented, automated tests passing. No new capture and no AI
request is made while switching.

## Why

Before this change the only ways to open another completed capture were the
Live Frames "recent captures" list, Analyze Last Capture, or Open CSV. Users
reading a long report had to leave the Analysis page to reach the history
list.

## Behavior

- The Analysis header has a **Switch report / 切换报告** button next to
  **Ask AI**.
- The button toggles an in-window panel above the report. It is not a
  separate window and it does not change the current report until the user
  opens a row.
- The panel reads the existing `settings.recent_captures` records; it does
  not create a second history store.
- Rows are sorted by `captured_at` descending. Each row shows:
  - program name (`target`, falling back to the CSV stem);
  - capture time (`captured_at`, falling back to session metadata);
  - duration from the session metadata (`ended_wall_ns - started_wall_ns`),
    or `--` for older captures without it;
  - data status from the session sidecar (frames, telemetry, network).
    Older captures without a session file show the legacy telemetry state.
- Opening a row validates the CSV, then reuses `show_analysis()`: charts,
  statistics, diagnostics, quality markers and the AI report context are all
  rebuilt from the selected file.
- Cancel, the toggled button and Escape-free dismissal keep the current
  report. A missing or damaged file shows the existing localized warning and
  leaves the current report untouched.
- Switching never starts PresentMon and never calls the AI provider.

## Identity and isolation

`FrameViewer.ai_report` carries the resolved `report_key` and the capture
`session_id`. The AI page is keyed by `report_key`, so switching reports does
not silently relink a conversation. Clicking **Ask AI** on the new report
opens that report's own session. A scenario change can refresh only the chat
whose `report_key` matches.

## Load race guard

`show_analysis()` increments `_analysis_generation` on every request. A load
result whose generation no longer matches is discarded instead of being
applied. The previous viewer's `recheck_requested` and `ai_context_changed`
signals are disconnected before it is deleted, so a late signal cannot update
the new report's chat context.

The current implementation still parses the CSV synchronously, so the guard
mainly protects future asynchronous/background loading work. Report loading
performance and background loading are the next phase.

## Known limits

- `validate_capture()` and `show_analysis()` each read the CSV. Large
  captures therefore pay two passes until the performance/caching phase.
- Duration and detailed status require a `<capture>.session.json`; older
  captures show the legacy status instead.
- The switcher lists the existing recent-capture limit (maximum 8).
