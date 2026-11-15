# UI-3 Acceptance Record

Date: 2026-11-12
Scope: UI-3 page-level layout, responsive behavior and final visual
review.
Result: **PASS** (visual acceptance)

## User acceptance

The user completed the final visual acceptance and reported that the
UI now matches expectations.

## Delivered

- commit `4e7240f feat: refresh page layouts and responsive structure`;
- tag `ui-3-page-refresh`;
- Live page:
  - Capture card;
  - responsive KPI `CardGrid`;
  - chart card;
  - scrollable content with fixed status footer;
  - action/selection/options rows that do not force horizontal
    scrolling at 980px.
- Hardware page:
  - System metrics heading;
  - responsive 5/4/1 KPI grid;
  - chart card;
  - fixed footer actions.
- Settings page:
  - centered Appearance card;
  - centered Data & files card with selectable settings/capture paths;
  - language buddy and full translations.
- Analysis window:
  - Capture summary card;
  - Swap chain card;
  - Frame time card with threshold controls in the header;
  - Selected frame section;
  - scrollable content.
- Process dialog:
  - subtitle;
  - middle-elided path column with full tooltip;
  - existing explicit Select/no-auto-start behavior preserved.

## Verification

Full suite at UI-3 close:

```text
Ran 328 tests in 12.279s

OK
```

324 previous tests + 4 UI-3 tests.

Native-resolution screenshots (no image scaling):

- before UI-3: `ui3_before_100_*` (UI-2 accepted state);
- after UI-3: `ui3_after_100_*` (EN/ZH Live, Hardware, Settings,
  process dialog, analysis);
- 125%/150% display scaling: `ui3_after_125_*`, `ui3_after_150_*`;
- simulated 100% text scale: `ui3_after_text100_*`;
- 980px minimum window: `ui3_small_100_*`;
- analysis scrolled state: `ui3_after_100_analysis_en_bottom.png`.

## Phase UI summary

### UI-1 — accepted

- Removed the global 13px Segoe UI override.
- System-anchored point-size roles with a 10pt floor.
- Segoe UI Variable/YaHei family stack and tabular numerals.
- Explicit Qt 6 PassThrough high-DPI policy.
- Font-metric chart gutters, pixel-aligned grids, text antialiasing.
- Minimal scroll/clipping fixes.
- Acceptance: `docs/ACCEPTANCE_UI1.md`.

### UI-2 — accepted

- Centralized design tokens: colors, spacing, radii, chart palette.
- Fusion dark palette plus one global stylesheet.
- Unified buttons, inputs, tabs, tables, checkboxes, scrollbars,
  tooltips and focus/hover/pressed/disabled states.
- SVG check and combo-chevron assets.
- Acceptance: `docs/ACCEPTANCE_UI2.md`.

### UI-3 — accepted visually

- Page-level hierarchy and responsive layout.
- Capture/metric/chart cards, settings data cards, analysis sections
  and process-dialog subtitle.
- Scroll-based adaptation at large text and 125%/150% display scaling.
- Acceptance: this document.

## Remaining limitations (not real-hardware verified)

- 125%/150% display scaling and 100% text scale were simulated with Qt
  environment/font settings, not physical Windows display-setting
  changes.
- No physical multi-monitor DPR switch was tested.
- Live and analysis pages scroll vertically at the current 182%
  Windows text scale; this is intentional, not clipping.
- No real game capture was performed during UI-1/UI-2/UI-3 screenshot
  generation.
- Process-dialog paths can middle-elide in narrow windows; full paths
  remain in tooltips.
- Settings screenshots show the screenshot harness's temporary settings
  path, not the user's real settings file.
- Spin-box subcontrols remain Fusion-native.
- The optional dark title bar was not changed.
- `assets/check.svg` and `assets/chevron-down.svg` must be included when
  packaging a frozen executable.

## Next gate

Phase UI is visually accepted, but a real-game UI regression with
Palworld is still required before Phase C. The checklist is in
`docs/REGRESSION_CHECKLIST_PALWORLD_UI.md`.

Do not start Phase C until that regression completes.
