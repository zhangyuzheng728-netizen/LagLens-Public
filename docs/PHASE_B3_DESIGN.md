# Phase B-3 Design: Settings Memory, Success Recording and Launcher Guidance

Date: 2026-11-12
Status: implementation complete, awaiting final Phase B acceptance.

## Scope

B-3 completes the Phase B integration:

- feed `settings.successful_targets` into the process dialog so
  previously captured games rank first;
- record a successful capture only when the CSV contains usable frames;
- suggest a likely renderer for a suspected launcher without switching
  the target silently;
- lock the target controls while a capture worker is running;
- finish English/Chinese texts and runtime language switching;
- keep the complete reason tooltip on the recommendation column.

No changes were made to the PresentMon capture pipeline, frame
statistics or swap-chain selection.

## Settings memory in the dialog

`LagLens.choose_process()` reads `settings.successful_targets` and
passes the records to `ProcessDialog(remembered_targets=...)`.
`process_catalog.rank_processes()` already gives an exact path match
+100 points, so a previously successful game sorts above ordinary
visible-window applications.

The dialog only reads memory. It does not write settings; writes happen
after a successful capture (below).

## Success recording

`LagLens._remember_success()` is called from `on_capture_completed()`
only inside the existing `info.ok` branch. `info.ok` means the CSV has
at least one valid frame and no validation error, so damaged, empty or
failed captures never produce a success record.

The recorder:

1. reads every valid `ProcessID` from the CSV;
2. enumerates running processes;
3. accepts a PID only if it still names the expected executable, has
   an accessible path, and existed by the capture cutoff;
4. stores only the verified executable path in
   `processes/successful_targets`.

### PID-reuse protection

`remember_capture_target(..., created_before=...)` verifies that the
process `create_time` is not later than the capture cutoff plus a
5-second tolerance. The cutoff comes from the capture CSV's last
modification time. A PID reused after the capture therefore cannot be
mistaken for the process that produced frames. If `create_time` is
unavailable, the path is not recorded when a cutoff is supplied.

If the game exits immediately after capture, its path cannot be
verified and is intentionally not guessed from the name.

## Launcher / renderer guidance

The existing `similar_process_names()` remains the detection source.
B-3 adds `process_catalog.renderer_hint()`:

- a target with no visible top-level window is a suspected launcher;
- if the target already has a visible window, no warning is shown;
- otherwise the similar process with a visible window, then the
  largest memory use, is suggested;
- the hint is text only. The target is never changed automatically.

`confirm_similar_target()` now shows "Possible renderer: ..." when a
suggestion exists. The failure message also suggests a renderer when a
zero-frame capture has similar processes running.

## Target lock during capture

`LagLens.set_target_controls_enabled()` disables the editable target
combo, the process-picker button and the refresh button when a worker
starts. `on_worker_finished()` re-enables them after the worker has
really stopped. `choose_process()` and `refresh_processes()` also
return early while a worker is running, so a programmatic call cannot
desynchronize the UI from the running capture.

## i18n and tooltips

- New dialog/launcher/success texts exist in both catalogs with
  matching placeholders.
- The dialog still re-renders on `language_changed` without losing the
  selected row.
- The recommendation-signal table cell keeps a full-text tooltip; the
  selected-reason panel also shows the complete text.

## Verification

New tests: 22 (13 catalog/ranking/launcher/PID-reuse, 1 dialog
tooltip, 8 main-window integration). Full suite:

```text
Ran 312 tests in 9.094s

OK
```

Covered behavior:

- settings memory reaches the dialog;
- valid capture calls the recorder with settings, target, CSV and a
  cutoff;
- damaged CSV and failed capture do not call the recorder;
- PID reuse after the capture is rejected; old processes are accepted;
- launcher hint chooses a visible/larger-memory renderer;
- suspected launcher shows a suggestion; visible renderer skips the
  warning; no suggestion uses the fallback message;
- target controls and picker actions are blocked while a worker runs
  and restored when it finishes;
- reason column tooltip contains the complete reason;
- both catalogs keep identical keys/placeholders.

## Screenshots

- `captures/ui_b3_en_dialog.png`, `ui_b3_zh_dialog.png`: remembered
  target at the top, full selected reason.
- `captures/ui_b3_en_launcher.png`, `ui_b3_zh_launcher.png`: launcher
  warning with "Possible renderer".
- `captures/ui_b3_en_main_locked.png`, `ui_b3_zh_main_locked.png`:
  target/choose/refresh controls disabled in a synthetic live state.

The dialog uses a controlled process fixture for deterministic paths.
The locked main-window screenshots set the live status and disable the
controls directly; they are UI-state captures, not a real ETW capture.
No real game capture was performed for B-3.

## Known limits

- Success memory requires the process to still be running and its
  creation time to be verifiable. Immediate exit means no record.
- PID reuse inside the 5-second timestamp tolerance is theoretically
  possible but extremely unlikely; the CSV cutoff is the primary guard.
- Launcher detection relies on visible top-level windows. A hidden or
  unusual full-screen process may be treated as a launcher.
- The recommendation-signal column can still truncate; the tooltip and
  selected-reason panel show the complete text.
- Phase C (metric explanations, reference ranges and target FPS) is
  still pending.
