# UI-3 Implementation: Page-Level Layout Refresh

Date: 2026-11-12
Status: implementation complete, awaiting final UI acceptance.
Scope: page hierarchy, responsive layout and final screenshot review.
No business logic changes.

## 1. Goals

UI-3 applies the accepted UI-1 typography and UI-2 design system to
the actual pages:

- main Live page: capture card, metric section, chart card;
- Hardware page: responsive metric grid and chart card;
- Settings page: appearance/data cards instead of a mostly empty page;
- Analysis window: summary card, chain card, frame-time card and
  selected-frame section;
- process dialog: subtitle and narrow-window polish;
- responsive scrolling at large text, 125%/150% display scaling and
  the 980px minimum window.

## 2. Main window shell and Live page

- The main page content is now inside a vertical `QScrollArea`; the
  status/disclaimer footer stays visible outside the scroll area.
- The Live page is structured as:
  1. **Capture** card with title, short description, process picker,
     PresentMon path, action row, selection row and options row;
  2. **Live metrics** section with a responsive `CardGrid`;
  3. **Live Frame Time** chart card with a proper card header.
- `Select Process…` and `Refresh Processes` moved to their own row so
  they no longer force horizontal scrolling at 980px or 182% text.
- `Start Monitoring` remains the only primary button.
- Process/PresentMon labels now use `setBuddy()` for keyboard focus.
- `CardGrid` reflows KPI cards by available width (5/4/2 columns at
  tested sizes).

## 3. Hardware page

- Added a **System metrics** section heading.
- Five KPI cards use `CardGrid`:
  - 5 columns on wide windows;
  - 4 + 1 at the 980px minimum;
  - further reflow at narrower simulated widths.
- The GPU chart is now a proper card with a header.
- Status and “Open Frame Analysis CSV” remain in a fixed footer.
- Hardware page content scrolls independently from the footer.

## 4. Settings page

- Content is centered in a fixed 780px column.
- Two cards:
  - **Appearance** — language selector with description and buddy;
  - **Data & files** — read-only settings-file and captures-folder
    paths in mono/caption typography, selectable and full-width.
- Long paths no longer wrap at the drive letter; they fit on one line
  at the supported window widths and retain a full tooltip.
- No settings behavior changed.

## 5. Analysis window

- Content remains scrollable.
- New hierarchy:
  - `Capture summary` card with the existing summary and metric help;
  - `Swap chain` card (existing chain panel);
  - `Frame time` card with threshold controls in the card header;
  - `Selected frame` section with the details panel;
  - footnote.
- Existing `summary`, `metrics_help`, `chart`, `chain_*`, `details` and
  threshold attributes are preserved, so the existing statistics and
  i18n tests remain valid.
- Section titles are translated and retranslated at runtime.

## 6. Process dialog

- Added a subtitle clarifying that recommendations are hints.
- Path column uses a middle-elide delegate so drive and executable name
  stay visible in narrow dialogs; the reason column keeps right elision
  so its beginning stays readable.
- Existing table, warning, reason panel and footer behavior unchanged.
- No auto-select, auto-start or silent target switching.

## 7. Responsive and accessibility behavior

- Main/Hardware/Settings pages use scroll areas with fixed footers.
- `CardGrid` reflows by width; tested at 1180, 900 and 500px in unit
  tests.
- Small-window screenshots at 980x760 main, 980x640 dialog and
  980x720 analysis show no horizontal viewport clipping.
- Large text and 125%/150% display scaling show vertical scrolling
  instead of overlapping/clipped content.
- Labels use buddy relationships for target/PresentMon/language.
- Existing tab order and keyboard behavior are preserved.
- English and Chinese runtime switching covers the new section titles.

## 8. Tests

New UI-3 tests (4):

- `CardGrid` reflow at 1180/900/500px;
- Live/Hardware/Settings section titles and data locations, both
  languages;
- analysis section titles, both languages;
- process-dialog subtitle localization.

Full suite:

```text
Ran 328 tests in 12.279s

OK
```

324 previous tests + 4 UI-3 tests.

## 9. Screenshots

All screenshots are native resolution; no image upscaling.

- Before UI-3: `ui3_before_100_*` (copied from the UI-2 accepted state,
  1180x840 main).
- After UI-3 at 100% display, current 182% text:
  - `ui3_after_100_live_en/zh.png`
  - `ui3_after_100_hardware_en.png`
  - `ui3_after_100_settings_en/zh.png`
  - `ui3_after_100_dialog_en/zh.png`
  - `ui3_after_100_analysis_en/zh.png`
  - `ui3_after_100_analysis_en_bottom.png`
- 125%/150% display scaling via `QT_SCALE_FACTOR`:
  `ui3_after_125_*`, `ui3_after_150_*`.
- Simulated 100% text scale:
  `ui3_after_text100_*`.
- 980px minimum-window set:
  `ui3_small_100_*`.

UI-3 main window default is 1180x900; the before UI-2 window was
1180x840. The after screenshots are not enlarged copies of before.

## 10. Explicit non-claims and limits

- 125%/150% display scaling was simulated with `QT_SCALE_FACTOR`, not
  a physical monitor scaling switch.
- 100% text scale was simulated with a 9pt application font; the
  machine is actually at 182% Windows text scale.
- No physical multi-monitor DPR switch was tested.
- No real game capture was performed for UI-3 screenshots; the same
  existing CSV and controlled process fixtures were used.
- Live page and analysis window scroll vertically at 182% text; this is
  intentional and keeps text from being clipped.
- Settings screenshots intentionally show the screenshot harness's
  temporary settings path, not the user's real settings file.
- Process-dialog path text can still be middle-elided in narrow windows;
  tooltips provide the full path.
- The optional dark title bar was not changed.
- Phase C remains paused.
