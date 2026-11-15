# UI-1 Acceptance Record

Date: 2026-11-12
Scope: UI-1 clarity, typography, high-DPI foundation and chart
rendering.
Result: **PASS**

## User acceptance

The user completed a visual acceptance and reported that the font
clarity in actual use improved noticeably.

## Delivered

- commit `eed3994 feat: improve UI clarity, typography and chart rendering`;
- tag `ui-1-clarity`;
- `ui_theme.py` with system-anchored point-size roles:
  display, heading, subheading, body, label, caption, metric, mono;
- Segoe UI Variable Text/Display with Microsoft YaHei UI fallback;
- tabular figures for metric and mono roles;
- Qt 6 `PassThrough` high-DPI policy set explicitly before QApplication;
- chart gutters computed from `QFontMetrics`;
- pixel-aligned 1px chart grids with cosmetic pens;
- explicit chart text antialiasing;
- font-aware process-dialog row/header heights;
- minimal clipping fixes:
  - Live actions and checkboxes on separate rows;
  - scrollable analysis content;
  - larger default/minimum window sizes.

## Verification

At UI-1 close:

```text
Ran 321 tests in 11.033s

OK
```

Screenshots were captured at native device resolution without image
scaling:

- 100% display + current 182% Windows text scale:
  `ui1_after_100_*`;
- 125% and 150% display scaling simulated via `QT_SCALE_FACTOR`:
  `ui1_after_125_*`, `ui1_after_150_*`;
- 100% text scale simulated with a 9pt application font:
  `ui1_after_text100_*`;
- old-size direct comparison:
  `ui1_after_same_100_*`.

English/Chinese Live, Hardware, Settings, process dialog and analysis
window were reviewed.

## Explicit non-claims

- 125%/150% display scaling was simulated with `QT_SCALE_FACTOR`, not a
  physical monitor scaling switch.
- 100% text scale was simulated with a smaller application font; the
  current machine is actually at 182% Windows text scale.
- No physical multi-monitor DPR switch was tested.
- No real game capture was performed for UI-1 screenshots.
- The optional dark title bar was not changed.

## Remaining for UI-2/UI-3

- UI-2: design tokens and unified control/state styling.
- UI-3: page-level layout and hierarchy refresh.
- Existing page-level issues remain: empty settings page, hardware
  chart header placement, card proportions and navigation styling.
