# UI-4: Single-Window Navigation and Embedded Analysis

Date: 2026-11-13
Status: implementation complete, awaiting UI-4 review.

## 1. Summary

LagLens no longer opens a separate `FrameViewer` top-level window. The
main window now has four tabs:

```text
Hardware | Live Frames | Analysis | Settings
```

The Analysis page uses a `QStackedWidget`:

- empty state with Open CSV / Back to Live actions;
- embedded `FrameViewer` content.

All analysis entry points go through the same `show_analysis()` path:

- Analyze Last Capture;
- Recent Captures row click;
- automatic analysis after a completed capture;
- Open CSV.

No diagnostic rules, capture commands, frame statistics or analysis
algorithms were changed.

## 2. Embedded analysis

- `FrameViewer` gained an `embedded=True` mode used by the main window.
- In embedded mode:
  - no top-level window title/resize/minimum window size is applied;
  - the duplicated “LagLens · Frame Time Analysis” heading is hidden;
  - the existing internal `QScrollArea` remains the vertical scroller.
- The full analysis content remains available: frame chart, statistics,
  diagnostic summary, grouped event table, technical details, C-4 guide and
  Markdown/JSON export.

The Analysis page shows a compact header above the viewer:

```text
File: <capture name>                         Target: <process name>
```

## 3. Viewer lifecycle

`show_analysis()` now:

1. normalizes the CSV path;
2. if the same path is already loaded, switches back to the existing
   Analysis page without creating another viewer;
3. otherwise parses the capture and creates one embedded viewer;
4. disconnects the old viewer's re-check signal;
5. removes the old viewer from the layout, reparents it to `None` and calls
   `deleteLater()`;
6. installs the new viewer in the Analysis container;
7. updates the file/target header and switches to the Analysis tab.

Only one analysis viewer instance is parented at a time. Switching tabs does
not stop a running capture, clear an unsaved report or reset unrelated UI
state.

## 4. Re-check behavior

From the embedded analysis page, **Re-check with a new capture**:

- normalizes and prefills the target process in the existing Live page;
- checks whether that process is currently running;
- uses `status.recheck_ready` if it is running;
- uses `status.recheck_not_running` if it is not;
- switches to Live Frames;
- never starts capture automatically;
- never trusts or reuses an old PID.

## 5. Tests

New/extended regression coverage:

- all analysis entry points display in the main window;
- Analysis tab starts with an empty state;
- real embedded viewer is not a top-level window;
- same CSV reuses the loaded viewer;
- different CSV replaces the old viewer and leaves one layout child;
- automatic analysis switches to Analysis;
- Recent Captures opens Analysis;
- Re-check returns to Live and reports a missing running process;
- page switching does not stop a running worker;
- switching away and back preserves the same viewer and header;
- EN/ZH tab and analysis header localization;
- embedded viewer JSON export;
- event selection and chart linkage remain intact;
- Markdown/JSON report tests remain green.

Full suite:

```text
Ran 498 tests in 16.736s

OK
```

## 6. Screenshots

```text
captures/ui4_analysis_en.png
captures/ui4_analysis_zh.png
captures/ui4_analysis_min_zh.png
```

The screenshots show the main window with the Analysis tab selected, the
file/target header, and the embedded scrollable analysis content.

## 7. Layout / scaling

Checked:

- 1180×900 default window;
- 980×760 minimum window;
- simulated `QT_SCALE_FACTOR` 1.25 and 1.50 in EN/ZH.

At 980×760 and 150% simulated scaling:

```text
viewer viewport: 922 px
content width: 922 px
horizontal scrollbar maximum: 0
```

The C-4 step rows were changed from long-text checkboxes to
checkbox + wrapped-label rows so they no longer force a wide minimum layout.
The Analysis page scrolls vertically via the embedded viewer.

## 8. Boundaries

- No game window was launched, moved or automated.
- No UAC/elevation was triggered.
- No repository push or GitHub release was performed.
- Release-1 remains blocked on the fresh elevated ETW capture with the
  final packaged build.
