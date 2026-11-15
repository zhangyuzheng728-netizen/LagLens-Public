# Palworld UI Regression Checklist

Date prepared: 2026-11-12
Purpose: verify the accepted Modern UI refresh with a real Palworld
session before Phase C starts.
Status: **not yet executed**.

## Scope

Validate that the new UI did not disturb:

- process selection and launcher/renderer guidance;
- live PresentMon/ETW monitoring;
- stopping a capture safely;
- CSV analysis and frame-detail interaction;
- successful executable-path memory and ranking;
- English/Chinese switching, scrolling and responsive layout.

This is a functional regression with the current UI, not a new feature
test.

## Preconditions

- [ ] LagLens repository is at `ui-3-accepted` or a later commit.
- [ ] Full automated suite is green (last known: 328 passing).
- [ ] Windows 11, current display scale recorded.
- [ ] Windows text scale recorded (current machine: 182%).
- [ ] PresentMon 2.6 path is valid and run as Administrator.
- [ ] No other ETW capture tool is running.
- [ ] D: or E: has enough free space; never delete existing captures.
- [ ] Back up `<data-dir>\LagLens.ini` before the run if the
      current successful-target memory must be preserved.
- [ ] Record the current `processes/successful_targets` contents.
- [ ] Palworld is installed and can be launched.

## Test cases

### 1. Process selection

- [ ] Launch LagLens and open `Select Process…`.
- [ ] Confirm the dialog shows no default row selection and Select is
      disabled until a row is chosen.
- [ ] Switch between Recommended and All processes.
- [ ] Search by executable name, path and window title.
- [ ] Use Refresh; confirm the dialog stays responsive and selection is
      cleared if the process disappeared.
- [ ] Confirm `Palworld-Win64-Shipping.exe` appears first in the
      recommended list when it is the remembered renderer.
- [ ] Confirm the historical-success reason is shown.
- [ ] If both `Palworld.exe` and `Palworld-Win64-Shipping.exe` are
      running, confirm the same-name/launcher guidance is understandable.
- [ ] Select the renderer and confirm only the target name changes; no
      capture starts automatically.
- [ ] Cancel once and confirm the previous target is unchanged.

Evidence: process-dialog screenshot, selected target name.

### 2. Live monitoring

- [ ] Click `Start Monitoring` with the renderer selected.
- [ ] Confirm the target combo, `Select Process…` and `Refresh
      Processes` are disabled while the worker runs.
- [ ] Confirm Stop becomes enabled and Start remains disabled.
- [ ] Confirm the Live page status changes to LIVE with frame count,
      elapsed time and file size.
- [ ] Confirm KPI cards update.
- [ ] Scroll to the chart and confirm the frame-time chart draws and
      remains readable.
- [ ] Switch EN → 中文 → EN and confirm the Live page, chart axes and
      status text follow the selected language.
- [ ] Resize the window to the minimum 980x760 and confirm there is no
      horizontal clipping; vertical scrolling is expected.

Evidence: live-page screenshot in both languages, window-size
screenshot, recorded frame count.

### 3. Stop capture

- [ ] Click `Stop Monitoring`.
- [ ] Confirm the UI does not freeze or close unexpectedly.
- [ ] Confirm the worker stops and PresentMon is no longer running.
- [ ] Confirm Start is re-enabled, Stop disabled, and target controls
      are re-enabled.
- [ ] Confirm the status reports the saved capture and the CSV exists.
- [ ] If using “Stop when target exits”, verify the target watcher
      stops only after the target was seen; this is optional if the
      normal stop path is already verified.

Evidence: stopped-state screenshot, CSV path, frame count.

### 4. CSV analysis

- [ ] Click `Analyze Last Capture`.
- [ ] Confirm the analysis window opens without error.
- [ ] Confirm the Capture summary, Swap chain, Frame time and Selected
      frame sections are visible in the new hierarchy.
- [ ] Confirm P50/P95/P99, 1% Low, stutters and frame counts are present.
- [ ] Click a chart point and confirm frame details appear.
- [ ] Change the stutter threshold manually and back to auto; confirm
      the chart, summary and stutter count update.
- [ ] Switch EN ↔ 中文 and confirm section titles, summary, chain reason
      and details are translated without losing the selected chain or
      frame.
- [ ] Scroll to the details/footnote; confirm there is no overlap.

Evidence: analysis top screenshot, selected-frame screenshot, both
languages.

### 5. Successful path memory

- [ ] After a genuinely usable CSV (`valid_frames > 0`), inspect
      `<data-dir>\LagLens.ini` → `processes/successful_targets`.
- [ ] Confirm the record contains only `path`, `executable` and
      `last_success`; no PID.
- [ ] Confirm the path is the verified Palworld renderer path.
- [ ] Reopen `Select Process…`.
- [ ] Confirm the renderer is still first and displays the historical
      success reason.
- [ ] Optional negative check: a zero-frame/failed capture must not add
      a new success record.
- [ ] Optional PID-reuse check is not practical in normal play; rely on
      automated tests and record that it was not manually exercised.

Evidence: settings JSON/INI snippet with path (redact user data if
needed), process-dialog screenshot.

### 6. Hardware and Settings pages

- [ ] Hardware: confirm GPU/CPU/VRAM/RAM/TEMP values update, the KPI
      grid reflows when the window narrows, and the GPU chart renders.
- [ ] Settings: confirm language selection changes text immediately.
- [ ] Confirm Settings shows the real current settings path and captures
      folder, not the screenshot harness temp path.
- [ ] Confirm paths are selectable/copyable.

Evidence: Hardware screenshot, Settings EN/ZH screenshot.

### 7. Exit and safety

- [ ] Stop the capture before closing LagLens.
- [ ] Close the app and confirm no PresentMon process remains.
- [ ] Reopen LagLens and confirm settings/language/successful-target
      memory survived.
- [ ] Do not delete captures or run destructive commands.

## Pass criteria

- No crash, hang or stuck PresentMon process.
- Target controls are locked only while a capture is running.
- Live and analysis UI are readable, scrollable and untruncated in the
  tested window sizes.
- CSV analysis produces the same statistics as before the UI refresh.
- Successful-target memory remains path-based, PID-free and correctly
  ranked.
- Both languages work at runtime.

## Evidence to record in the acceptance report

- display scale and Windows text scale;
- Palworld build/version and process names;
- frame count, duration, CSV path;
- settings memory record (path only);
- screenshots listed above;
- any deviation, with exact page, window size and language.

## Known constraints during the run

- 125%/150% display scaling is simulated via `QT_SCALE_FACTOR` unless
  the Windows display setting is actually changed; label it correctly.
- No physical multi-monitor DPR switch is required for this checklist,
  but note if it was not tested.
- The Live/Analysis pages scroll at 182% text scale; scrolling is
  expected.
- Narrow process-dialog paths may middle-elide; use tooltips for the
  full path.
- Phase C remains paused until this regression passes.
