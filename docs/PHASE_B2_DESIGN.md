# Phase B-2 Design: Process-Selection Dialog

Date: 2026-11-12
Status: implementation complete, awaiting manual review.

## Scope

B-2 adds the approved independent process-selection dialog:

- keep the existing editable target combo and manual input;
- add a "Select Process…" button;
- support Recommended / All processes, live search and refresh;
- show process name, PID, window title, full path and recommendation
  signals;
- distinguish same-name processes at different paths;
- make clear that PresentMon targets by executable name, so a PID is
  for identification only;
- never select a row automatically, start a capture or switch the
  target silently.

B-2 does not wire successful-target memory into the main window and
does not add launcher/renderer guidance. Those remain B-3 work.

## Files

| File | Change |
|---|---|
| `process_dialog.py` | New `ProcessDialog` with Recommended/All, search, refresh, table and reason detail. |
| `main.py` | Keeps the editable combo; adds the button and `choose_process()`; only writes the selected name into the combo. |
| `locales/en.json`, `locales/zh_CN.json` | Dialog, reason and button texts in both languages. |
| `tests/test_process_dialog.py` | 18 dialog tests. |
| `tests/test_ui_i18n.py` | 3 main-window integration/localization tests. |

## Dialog behavior

### Data

- The dialog calls `process_catalog.collect_processes()` by default and
  accepts an injected `entries_provider` for tests.
- `process_catalog.rank_processes()` supplies scores and reason parts.
- Recommended mode keeps only `recommendation.recommended == True`.
- All mode shows every enumerated executable, sorted by name and PID.
- Search filters name, full path and window title in real time.
- Refresh re-enumerates, preserves a selection only when the same
  `(PID, normalized path)` still exists, and otherwise clears it.
- Provider or ranking failures show a localized error state instead of
  closing the dialog.

### Selection safety

- No row is selected when the dialog opens or after a normal refresh.
- `Select` is disabled until the user selects a row.
- `Select` only returns a `ProcessEntry`; it does not capture.
- Cancel leaves the main target unchanged.
- A double-click is intentionally not bound to accept, so selection is
  always an explicit button action.

### Name-based targeting

- The dialog always shows this note: PresentMon targets the executable
  name; PID is for identification only and does not select one
  specific instance.
- When the selected name is shared by more than one running process,
  a separate warning states how many other processes share it and that
  they may be captured together.
- Same-name rows remain distinguishable by PID, window title and full
  executable path.

### Recommendation reasons

The table shows compact recommendation signals. Selecting a row also
shows the complete reason in a detail panel, so a narrow column cannot
hide the explanation. Reason keys:

- `process.reason.remembered`
- `process.reason.remembered_short`
- `process.reason.window`
- `process.reason.visible`
- `process.reason.memory`
- `process.reason.system`

`process.reason.system` appears only in the all-processes view; system
paths are filtered out of the recommended view by B-1.

### Language switching

The dialog connects to `LanguageManager.language_changed` and rebuilds
its static texts, headers, reasons and placeholders without losing the
selected row. Both catalogs received matching keys and placeholders.

## Main-window change

- The editable combo and manual input remain.
- A `Select Process…` button opens the dialog.
- On acceptance, `choose_process()` calls
  `process_combo.setCurrentText(entry.name)` only.
- The start button is not triggered; no worker is created.
- The button has a tooltip stating that selection does not start a
  capture.

B-3 will pass `settings.successful_targets` into the dialog and call
`remember_capture_target()` after a successful capture.

## Verification

New tests: 21 (18 dialog + 3 main-window integration/localization).
Full suite: **290 tests passing** (269 previous + 21 new).

Covered behavior:

- columns, no default selection and disabled Select button;
- Recommended/All switching;
- live search by name, path and window title;
- empty filter and empty/failed provider states;
- selecting a row, selection preservation and disappearance on refresh;
- same-name collision warning;
- same-name/different-path rows with distinct PID and path;
- unavailable path and missing window title;
- explainable reason text and full selected reason;
- English/Chinese switching with selection preservation;
- main-window button localization, accept updates the combo, cancel
  keeps the target, and no capture starts.

GUI screenshots generated locally (not committed because `captures/`
is ignored):

- `captures/ui_b2_en_recommended.png`
- `captures/ui_b2_zh_recommended.png`
- `captures/ui_b2_en_all_collision.png`
- `captures/ui_b2_zh_all_collision.png`
- `captures/ui_b2_en_main.png`
- `captures/ui_b2_zh_main.png`

The dialog screenshots use a controlled fixture so the same-name
`Game.exe` paths and the collision warning are deterministic. The main
window screenshots were taken with the real `LagLens` window; no
capture was started.

## Known limits

- The table's recommendation-signal column can truncate long text; the
  selected reason panel and tooltip always show the complete text.
- The dialog is modal, so the main window is blocked while it is open.
- Recommendation is still a heuristic; "Recommended" is not a claim
  that the process is a game.
- The main-window target lock, settings memory, success recording and
  launcher/renderer guidance were added in B-3; see
  `docs/PHASE_B3_DESIGN.md`.

## Next step

- **B-3 (implemented):** settings memory, successful-capture recording,
  launcher/renderer guidance and the target lock. See
  `docs/PHASE_B3_DESIGN.md`.
