# UX-4: Capture Workflow and First-Use Help

Date: 2026-11-12
Status: implementation complete, awaiting combined UX-4 review.
Scope: finishing the remaining UX-4 workflow tasks. No diagnostic engine,
capture command or raw frame-calculation change was made.

## 1. Summary

- Completed automatic analysis after a valid, fully written capture.
- Added a recent-captures list (up to 8 records) stored in the existing INI
  settings file; no database was introduced.
- Added a non-blocking first-use quick-start card with three steps, a
  dismiss action, and a permanent **Quick start** button to reopen it.
- Tightened the plain-language copy:
  - missing telemetry does not imply PresentMon CPU/GPU frame timing is
    unavailable;
  - untrusted time alignment never claims reliable hardware/sample-to-frame
    matching;
  - `observed_association` remains strictly separate from
    `confirmed_by_control`.
- Full suite: **472 tests in 21.479 s, OK**.

## 2. Automatic analysis after capture

The existing `Auto-open analysis` checkbox remains the user control.

Flow:

1. Capture worker finishes writing the CSV.
2. `validate_capture()` checks the file, not just PresentMon's exit code.
3. A successful, complete capture is recorded as the last valid capture.
4. The main window stores a pending auto-analysis path.
5. The actual `FrameViewer` opens only after the worker has fully finished
   and telemetry has been stopped/closed.
6. If the user opens the same capture first, `show_analysis()` raises the
   existing visible viewer instead of creating a duplicate.

Auto-opening requires all of:

```text
Auto-open analysis enabled
valid_frames >= 2
info.complete (no trailing partial row or bad field rows)
no CaptureResult.error
window not closing
```

Empty files, damaged CSVs, unusual exits, incomplete final rows and
cancelled captures leave the pending path empty. The user can still open a
valid last capture manually.

## 3. Recent captures

### Storage

Settings key:

```text
captures/recent
```

Value: JSON array in the existing `LagLens.ini`. No database or new
dependency.

Each record contains:

```text
path, name, target, captured_at, frames, telemetry
```

Safety rules:

- maximum 8 records;
- duplicate paths are removed;
- malformed records and corrupt JSON fall back to an empty list;
- the stored path is never executed.

### UI

The Live Frames tab has a **Recent captures** card below the capture card.
Each row shows:

```text
capture file name
target · time · frame count · optional file/telemetry status
```

Clicking a row opens the normal analysis window.

Safe degradation:

- missing file: row is marked `file missing`; click shows a localized
  warning and does not crash;
- damaged/empty CSV: click validates the file first and shows a localized
  warning;
- missing telemetry sidecar: row is marked `no telemetry`, but analysis
  still opens and the C-3/C-4 missing-telemetry explanation is shown.

The list is refreshed after successful capture and after runtime language
changes.

## 4. First-use quick start

- A card at the top of Live Frames shows three steps:
  1. choose the running game process;
  2. start monitoring, play the same scene, stop;
  3. review the plain diagnosis and follow the guide.
- It can be dismissed with **Got it, start using LagLens / 知道了，开始使用**.
- Dismissal is saved as `ui/onboarding_seen`; the card does not reappear on
  future launches.
- A **Quick start / 快速上手** ghost button remains next to the capture
  controls, so the card can be reopened at any time.
- The card is non-modal and never blocks capture or normal use.

## 5. Copy checks

- Missing telemetry now says PresentMon frame-level CPU/GPU timing is still
  available; only the extra hardware samples cannot be tied to individual
  frames.
- Untrusted time alignment says to treat hardware/frame links as
  approximate and warns against treating a specific slow frame as reliably
  matched to a hardware sample.
- Observed association still uses "possible link, not a confirmed cause"
  language.
- CPU/GPU busy evidence still explicitly does not prove faulty or weak
  hardware.
- Markdown/JSON behavior and the technical-details disclosure from the
  accepted plain-language task are unchanged.

## 6. Tests

Added or extended:

- `tests/test_settings.py`:
  - recent-capture round trip and sanitising;
  - 8-record limit;
  - corrupt recent JSON fallback;
  - onboarding-seen persistence.
- `tests/test_capture.py`:
  - auto-analysis waits for worker finish;
  - disabled auto-analysis stays closed;
  - empty/incomplete/abnormal captures do not auto-open;
  - same-path duplicate open reuses a visible viewer;
  - successful capture populates recent list and opens from a row;
  - missing/damaged recent files warn safely;
  - missing-sidecar recent entry still opens;
  - first-use card dismissal and reopen;
  - onboarding and recent-list runtime EN/ZH switching.

Full suite:

```text
Ran 472 tests in 21.479s

OK
```

## 7. Real-data operation validation

Validation artifact: `<validation-data>\ux4_workflow_verify.py`.

The shell in this session was **not elevated**
(`capture_core.is_elevated() == False`), so PresentMon could not create a
fresh ETW session. The production UI paths were exercised with a real
Palworld QPC capture produced earlier on this machine:

```text
Palworld-Win64-Shipping.exe_20261112_145654_215377.csv
615 frames, 9.86 s, 39 telemetry samples
```

Observed results:

```text
onboarding_visible True
onboarding_steps 3
recent_count 3
recent_missing_marked True
recent_no_telemetry_marked True
recent_viewer_active True
onboarding_seen True
onboarding_hidden True
onboarding_reopened True
pending_auto_analysis <validation-data>\qpc_live_2\Palworld-Win64-Shipping.exe_20261112_145654_215377.csv
viewer_visible_before_finished False
auto_viewer_active True
active_analysis_path <validation-data>\qpc_live_2\Palworld-Win64-Shipping.exe_20261112_145654_215377.csv
```

This confirms:

- a real capture row opens the analysis window;
- the completion path records a pending auto-analysis path;
- the viewer does not open before the worker-finished step;
- the viewer opens after worker completion and reads the real sidecar;
- onboarding dismissal and reopening work;
- missing and no-telemetry rows are marked safely.

A fresh ETW capture still needs an elevated manual run; it is not claimed as
already performed here.

## 8. Screenshots

Committed:

```text
captures/ux4_live_onboarding_en.png
captures/ux4_live_onboarding_zh.png
captures/ux4_auto_analysis_en.png
```

The Live screenshots show the quick-start card, capture controls, recent
captures, and a missing-file/no-telemetry row. The auto-analysis screenshot
shows the real capture opened through the production completion path.

## 9. DPI / minimum-window checks

Checked at 980×760 with simulated `QT_SCALE_FACTOR` 1.25 and 1.50 in EN/ZH:

```text
EN 1.25: content 922×1613
EN 1.50: content 922×1613
ZH 1.25: content 922×1585
ZH 1.50: content 922×1585
```

No clipping or crash was observed; the Live page remains scrollable.
These are simulated scaling checks, not physical monitor/DPI tests.

## 10. Limitations

- No new ETW capture was possible without an elevated shell in this
  session; real captured data from an earlier run was replayed through the
  production UI paths instead.
- Recent records store local capture paths and are not synced anywhere.
- Quick-start dismissal is per settings file; deleting the INI shows it
  again.
- No database, cloud sync, automatic A/B comparison or new diagnostic rules
  were added.
- Release-1 packaging and GitHub publication were not started.
