# UI-2 Acceptance Record

Date: 2026-11-12
Scope: UI-2 Modern Design System.
Result: **PASS**

## User acceptance

The user completed a visual acceptance and accepted the existing
Design Tokens, Fusion dark theme and base control system.

## Delivered

- commit `b93957d feat: add modern dark design system`;
- tag `ui-2-design-system`;
- centralized tokens in `ui_theme.py`:
  - colors, spacing, radii, chart palette;
  - typography roles from UI-1 remain the source of truth.
- Fusion style + dark QPalette + one global stylesheet;
- per-window stylesheets removed from main, analysis and process
  dialog;
- primary/secondary/ghost buttons with hover/pressed/focus/disabled;
- inputs, combos, tabs, tables, checkboxes, scrollbars, tooltips;
- SVG check and combo-chevron indicators;
- chart colors switched to design tokens.

## Verification

```text
Ran 324 tests in 14.321s

OK
```

312 previous tests + 12 UI theme tests.

Screenshots at native resolution, before (UI-1 state) and after
(UI-2):

- `ui2_before_100_*` vs `ui2_after_100_*` (EN/ZH);
- 125%/150% display scaling via `QT_SCALE_FACTOR`;
- simulated 100% text scale via a 9pt application font;
- Live, Hardware, Settings, process dialog and analysis window;
- analysis bottom/details: `ui2_after_100_analysis_en_bottom.png`.

Full notes: `docs/UI2_IMPLEMENTATION.md`.

## Explicit non-claims

- UI-3 page-level layout has not started yet.
- 125%/150% display scaling and 100% text scale are simulated, not
  physical Windows display-setting changes.
- No physical multi-monitor DPR switch was tested.
- No real game capture was performed for UI-2 screenshots.
- The optional dark title bar was not changed.
- Spin-box subcontrols remain Fusion-native.
- Recommendation-signal table text can still truncate; tooltip and
  reason panel provide the full text.
- SVG assets must be included if the app is packaged as a frozen
  executable.
