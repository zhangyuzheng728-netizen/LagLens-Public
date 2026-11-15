# UI-1 Implementation: Clarity, Typography and High-DPI

Date: 2026-11-12
Status: implementation complete, awaiting manual review.
Scope: UI-1 only. UI-2 design-system work and UI-3 page layout are
not included.

## 1. What changed

### 1.1 System-anchored typography

New module: `ui_theme.py`.

- Reads the system UI point size from `QApplication.font()`.
- Applies a 10pt floor; it does not hard-code this machine's 15.75pt
  or the 182% Windows text scale.
- Sets the QApplication body font once, using a Qt family list:
  - `Segoe UI Variable Text`
  - `Segoe UI`
  - `Microsoft YaHei UI`
  - `Microsoft YaHei`
- Display/heading roles prefer `Segoe UI Variable Display`.
- PID/timing/table monospace roles use `Cascadia Mono` → `Consolas`.
- Metric and mono roles request OpenType tabular figures with
  `QFont.Tag("tnum")`.

Role scale (relative to the system base):

| Role | Multiplier | Purpose |
|---|---:|---|
| display | 1.5 | brand / analysis title |
| heading | 1.25 | page and dialog titles |
| subheading | 1.1 | reserved for UI-2 |
| body | 1.0 | normal UI text |
| label | 0.9 | field labels and table headers |
| caption | 0.8 | hints, status, chart axes |
| metric | 1.35 | KPI values |
| mono | 0.9 | PID, paths, timestamps |

The old global `font: 13px 'Segoe UI'` and all QSS `font-size` /
`font-family` declarations were removed from:

- `main.py`
- `frame_viewer.py`
- `process_dialog.py`

Per-widget fonts are now applied through `ui_theme.apply_font()`.
This keeps the text scale tied to the Windows/Qt system setting and
avoids synthetic 13px text on 125–200% displays.

### 1.2 High-DPI policy

- `ui_theme.configure_high_dpi()` explicitly selects Qt 6's
  `PassThrough` scale-factor rounding policy before `QApplication`.
- Qt 6's high-DPI scaling is already enabled; the app does **not**
  re-enable `AA_EnableHighDpiScaling` or manually scale widget
  coordinates by the device-pixel ratio.
- Offscreen pixmaps are not used for charts, so there is no
  low-resolution cache being enlarged.
- The chart geometry remains in logical coordinates; Qt scales the
  painter for the current screen.

### 1.3 Chart clarity

Both custom charts (`LiveChart`, `FrameChart`) now:

- set their own caption/tabular font instead of inheriting a QSS body
  font;
- enable `TextAntialiasing` explicitly;
- compute the Y-axis gutter from `QFontMetrics` instead of using a
  fixed 70px width;
- draw grid lines with antialiasing disabled, integer Y positions and
  cosmetic 1px pens;
- draw curves/dots with antialiasing and cosmetic pens;
- draw axis labels through `QRectF` alignment instead of fixed text
  baselines;
- keep the original data/point lists for click selection; no business
  logic or chart statistics changed.

### 1.4 Minimal layout fixes for larger text

Only fixes required to prevent clipping were made:

- the Live page actions and checkboxes are now on two rows;
- the analysis window content is wrapped in a scroll area with a
  dark, minimal scrollbar;
- larger default/minimum sizes:
  - main window 1180x840, minimum 980x720;
  - analysis window 1120x860, minimum 980x720;
  - process dialog 1180x820, minimum 980x640;
- process-dialog table row height and header height are font-aware;
- PID cells use the mono role.

No page-level redesign, navigation change, color-system change or
component restyle was performed. Those remain UI-2/UI-3.

## 2. Verification

### 2.1 Automated tests

New: `tests/test_ui_theme.py` (9 tests) covering:

- system point-size floor and role ordering;
- CJK fallback family stack;
- tabular figures for metric/mono roles;
- font-aware table row/header heights;
- chart caption role;
- chart rendering smoke tests without pixmap scaling;
- regression guard that no QSS pixel font declarations return.

Full suite:

```text
Ran 321 tests in 11.257s

OK
```

312 previous tests + 9 UI-1 tests.

### 2.2 Scale matrix

Current session:

- Windows text scale: **182%**
- QApplication default: Microsoft YaHei UI 15.75pt
- DPR: 1.0 on both screens
- display scaling tested: 100%, 125%, 150% via
  `QT_SCALE_FACTOR` (simulated display-scale changes, native DPR
  output, not a physical monitor switch)
- additional simulated 100% text scale: app font set to 9pt, theme
  floor yields 10pt body (marked simulated)

| Condition | Result | Screenshots |
|---|---|---|
| 100% display, current 182% text | pass, no clipping | `ui1_after_100_*` |
| 125% display, current 182% text | pass, no clipping | `ui1_after_125_*` |
| 150% display, current 182% text | pass, analysis scrolls | `ui1_after_150_*` |
| 100% display, simulated 100% text | pass, compact layout | `ui1_after_text100_*` |

Screenshots were captured with `QWidget.grab()` at native device
resolution and were not resized or upscaled. The after screenshots use
a larger default window because the text is now larger; the default
was increased so content does not clip. For a direct old-size
comparison, `ui1_after_same_100_*` uses the previous 1100x760 window
and intentionally shows the resulting clipping/scroll; it is not used
as the finished layout.

Before/after sets:

- `captures/ui1_before_100_live_en.png` vs
  `captures/ui1_after_100_live_en.png`
- `captures/ui1_before_100_live_zh.png` vs
  `captures/ui1_after_100_live_zh.png`
- `captures/ui1_before_100_settings_en.png` vs
  `captures/ui1_after_100_settings_en.png`
- `captures/ui1_before_100_dialog_en.png` vs
  `captures/ui1_after_100_dialog_en.png`
- `captures/ui1_before_100_analysis_en.png` vs
  `captures/ui1_after_100_analysis_en.png`
- 125% and 150% before/after live/dialog/analysis/settings sets;
- `captures/ui1_after_text100_*` (simulated text scale);
- `captures/ui1_after_100_analysis_en_bottom.png` (analysis scroll
  bottom, details and note visible).

### 2.3 Manual visual checks

- English and Chinese mixed text are readable; CJK falls back to
  Microsoft YaHei UI.
- Live page action labels no longer clip.
- Analysis window no longer overlaps chart, details and note; it
  scrolls at large text sizes.
- Process dialog buttons/notes/table rows fit; the signal column can
  still truncate and continues to rely on tooltip + selected-reason
  panel.
- Settings page is readable; page-level spacing remains UI-3 work.
- Chart axes and grid lines are crisp at 100/125/150; chart text is
  larger and pixel-aligned.

## 3. Remaining UI-1 limitations

- The page-level visual hierarchy is still the old layout: the
  hardware chart header placement, empty settings page, card
  proportions and navigation styling are UI-3.
- The recommendation-signal column still truncates long text; the
  full reason is available in the tooltip and selected-reason panel.
- No dark-title-bar change was made. It remains an optional UI-2/UI-3
  item.
- 125%/150% screenshots use Qt's `QT_SCALE_FACTOR` to simulate display
  scaling; they are not a physical monitor switch or a second-monitor
  test.
- The 100% text-scale screenshots are simulated with a 9pt application
  font; the current machine's actual Windows text scale is 182%.
- No real game capture was performed for UI-1; existing capture CSV
  and controlled process fixtures were used for analysis/dialog
  screenshots.
