# Phase UI Design: Modern Dark UI Refresh

Date: 2026-11-12
Status: design accepted; UI-1 and UI-2 accepted; UI-3 implemented,
awaiting final visual acceptance.
Scope: visual system, typography, high-DPI rendering and page layout.
No functional changes in this document. See
`docs/ACCEPTANCE_UI1.md`, `docs/UI1_IMPLEMENTATION.md`,
`docs/ACCEPTANCE_UI2.md`, `docs/UI2_IMPLEMENTATION.md` and
`docs/UI3_IMPLEMENTATION.md`.

## 1. Audit method

The audit combined:

- source inspection of `main.py`, `frame_viewer.py`,
  `process_dialog.py`, `settings.py` and `i18n.py`;
- review of the existing UI screenshots under `captures/`;
- a read-only PySide6 probe of the current Windows session
  (no settings written, no capture started);
- a read-only screenshot pass of the current Hardware tab.

Measured environment:

| Item | Value |
|---|---|
| Qt / PySide6 | Qt 6.12.0 / PySide6 6.12.0 |
| Style | `windows11` (available: `windows11`, `windowsvista`, `Windows`, `Fusion`) |
| High-DPI rounding policy | `PassThrough` (Qt default) |
| Current devicePixelRatio | 1.0 on both screens |
| Primary screen | 2560x1440, logical DPI 96, physical DPI ~108.8 |
| Secondary screen | 2560x1600, logical DPI 96, physical DPI ~189 |
| Windows text scale | **182%** (`HKCU\Software\Microsoft\Accessibility\TextScaleFactor`) |
| QApplication default font | **Microsoft YaHei UI 15.75pt** |
| Current QSS body font | **13px Segoe UI** (about 9.75pt) |
| Tabular-number support | `QFont.setFeature(QFont.Tag("tnum"), 1)` is available |

The last two rows are the central finding: the application asks Qt for a
system font of 15.75pt, then the stylesheet overrides it with a 13px
font. That is roughly 62% of the system text size on this machine.
Windows text scaling is effectively ignored by the QSS pixel sizes.

No functional code was changed and the 312-test suite was not rerun for
this design document.

## 2. Current UI problem list

### P0 — clarity and typography

**P0-1: Windows text scaling is overridden by pixel-based QSS.**

Evidence:

- system text scale is 182%;
- Qt resolves the default UI font as Microsoft YaHei UI 15.75pt;
- `main.py` applies `font: 13px 'Segoe UI'` to every `QWidget`;
- `frame_viewer.py` and `process_dialog.py` use `font-size: 14px`;
- muted text is 12px, while headings jump to 20/25/30px.

Impact:

- body text is much smaller than the user's Windows preference;
- CJK glyphs at 13px look thin and fuzzy, especially on high-physical-DPI
  screens;
- the same UI looks inconsistent across 100%, 125%, 150% and 200%
  scaling and across Windows text-size settings.

**P0-2: mixed font families.**

Latin text is forced to Segoe UI while Chinese falls back to Microsoft
YaHei UI. Latin, CJK and digits therefore have different x-heights,
weights and vertical alignment. The app's default font (Microsoft YaHei
UI) is not the font the QSS asks for. This makes mixed strings such as
`FPS 31.5 | 帧时间 20.81 ms` look uneven.

**P0-3: no tabular numerals.**

Live values, P50/P95/P99, PIDs and timings use proportional figures.
Numbers visibly change width while values update, which makes the UI
feel unstable and “cheap”. Qt 6.12 supports `tnum`, so this is fixable
without changing data.

### P0/P1 — chart rendering

**P0-4: grid lines and chart text are not pixel-aligned.**

`LiveChart` and `FrameChart`:

- enable `Antialiasing` for everything, including 1px horizontal grid
  lines drawn at fractional `y` coordinates;
- draw axis text with `QPainter.drawText` at integer coordinates using
  the widget's inherited font;
- do not request `TextAntialiasing` explicitly;
- use fixed 70px/25px gutters instead of text metrics;
- inherit 13px/14px body fonts.

Impact: grid lines look soft or “double”, axis labels are small, and the
chart looks lower-resolution than the rest of the UI. The effect gets
worse at fractional DPR because a 1px cosmetic line can land on a
half-pixel.

**P1-1: no explicit high-DPI policy in the app.**

Qt 6 currently defaults to `PassThrough`, and this session reports DPR
1.0. The app never sets the policy explicitly and has no test matrix for
125%/150%/200% or multi-monitor DPR changes. A future Qt/style change
could silently regress clarity.

**P1-2: analysis chart draws every frame.**

The Palworld acceptance capture has 11,385 frames. `FrameChart` draws
every point and every anomaly dot. This is correct today but leaves less
headroom for smoother rendering and higher-DPI redraws. Any optimization
must preserve the original point-to-frame mapping used by click
selection.

### P1 — design system and controls

**P1-3: partial QSS over a native Windows style.**

`windows11` provides native checkboxes, spin boxes, scrollbars, combo
popups and focus behavior, but the app styles only some of them. The
result mixes native light/neutral widgets with a dark stylesheet.
Examples: QCheckBox, QSpinBox, QScrollBar, QToolTip, QTableWidget
selection and QComboBox popup are not consistently tokenized.

**P1-4: inconsistent shape and spacing tokens.**

- border radius: 7px buttons/inputs, 10px analysis details, 12px cards;
- page margins: 22px main, 16px process dialog, 12px analysis spacing;
- card padding: 15px;
- colors are repeated as literals across three stylesheets;
- no hover/pressed/focus states for inputs, tables or tabs;
- no dark title-bar configuration (verify on the target Windows 11
  machine; do not assume the native title bar is dark).

**P1-5: teal is used for too many meanings.**

Teal currently means brand, value, chart line, selected tab, primary
button and focus. When everything is accented, nothing is. Metric values
should be primary text; teal should be reserved for primary actions,
selection and the chart line.

**P1-6: visual hierarchy is flat.**

- brand 30px;
- metric values 25px teal;
- section titles 20/25px;
- body 13/14px;
- muted labels 12px.

There is no 16–18px “section heading” role, no clear card header row and
no elevation hierarchy. Cards, page background and chart surfaces are
close in value, so the eye has few anchors.

### P1 — layout and responsiveness

**P1-7: fixed sizes and no scrolling.**

- main window 1100x760, minimum 900x650;
- analysis window starts at 1000x620;
- process dialog 1100x740, minimum 900x560;
- no `QScrollArea` around page content;
- hardware page puts five KPI cards in one row;
- settings page is a single language row followed by a large empty
  area;
- at 182% system text scale, the current 13px override hides the problem,
  but respecting the system size will require wrapping/scrolling.

**P1-8: process dialog table is visually dense.**

Five columns at 14px, 28px row height, a fixed 300px recommendation
column and long paths. The reason text is truncated; the full reason is
only in the tooltip/selected panel. This is functional but not
“modern product” density.

**P1-9: analysis window is a single long column.**

Summary, chain panel, chart, details and note all stack vertically with
small body text. There is little distinction between metadata, KPI
values and explanations. The chart is the visual center, but the
surrounding hierarchy does not support it.

**P1-10: title bar and window chrome.**

The app relies on the native title bar and does not explicitly request
Windows 11 immersive dark mode. On some Windows themes this produces a
light title bar above a near-black app. Verify on the target machine
before UI-2; fix with the DWM dark-mode attribute, not a frameless
window.

### P2 — polish

- no icons or visual affordances on primary actions;
- no empty states/illustrations for the settings or filtered table;
- no consistent focus ring for keyboard navigation;
- QSS has no transitions; hover feedback is abrupt;
- `font: 13px 'Segoe UI'` is a shorthand that overrides size, family
  and weight in one declaration, making overrides harder to reason
  about;
- the hardware chart card has a large empty area above the chart title
  in the current screenshot and the title does not read as a card
  header.

## 3. Design goals

1. **Readable first.** Respect the Windows text scale; crisp text at
   100%, 125%, 150%, 182% and 200%; no clipped labels.
2. **Calm, modern dark.** Neutral charcoal surfaces, one restrained
   accent, subtle borders and generous spacing; closer to Linear/ChatGPT
   than a traditional game overlay.
3. **Clear hierarchy.** Page title → section/card header → label →
   value → caption, with consistent typography and spacing.
4. **Stable numbers.** Tabular figures for live metrics, P-values,
   PIDs and timing tables.
5. **Native-feeling.** Keep keyboard behavior, focus visibility, file
   dialogs and Windows accessibility. Optimize presentation, not
   behavior.
6. **No functional drift.** All capture, analysis, i18n, settings and
   process-selection behavior stays the same. The 312-test suite must
   remain green after every sub-phase.

## 4. Typography proposal

### Base size and Windows text scaling

Anchor the type scale to the system UI font instead of hard-coded
pixels:

```python
system_pt = QApplication.font().pointSizeF()   # 15.75pt here
base_pt = max(10.0, system_pt)
```

Use point sizes for all role fonts. On this machine the base becomes
15.75pt; on a standard 100% Windows session with a 9pt system font the
base becomes 10pt. The 10pt floor keeps the app readable without
overriding an accessibility setting.

If the user later wants a denser layout, add an explicit
Compact/Comfortable setting; do not silently cap the system text size.

### Families

Use Qt family lists (not a single QSS family string):

| Role | Family stack | Fallback |
|---|---|---|
| UI text | `Segoe UI Variable Text` → `Segoe UI` → `Microsoft YaHei UI` | Windows 10 |
| Display / headings | `Segoe UI Variable Display` → `Segoe UI` → `Microsoft YaHei UI` | Windows 10 |
| CJK fallback | `Microsoft YaHei UI` → `Microsoft YaHei` | all |
| Monospace (PID/paths) | `Cascadia Mono` → `Consolas` | all |

Qt resolves CJK glyphs from the fallback family automatically. Set the
family list on a `QFont` and apply it through `QApplication.setFont` /
small role helpers; avoid `font-family` in QSS as the only mechanism.

### Roles

| Token | Multiplier | This machine (15.75pt base) | Use |
|---|---:|---:|---|
| Display | 1.6× | ~25.2pt | brand / page hero |
| Heading | 1.35× | ~21.3pt | page and dialog titles |
| Subheading | 1.15× | ~18.1pt | card headers |
| Body | 1.0× | 15.75pt | normal text |
| Label | 0.9× | ~14.2pt | field labels, table headers |
| Caption | 0.8× | ~12.6pt | hints, footnotes, axis labels |
| Metric | 1.35× | ~21.3pt | KPI values |
| Mono | 0.9× | ~14.2pt | PID, paths, timestamps |

Weights: 400 body, 500 labels/table headers, 600 headings/KPI values.
Use real DemiBold weights from the variable font; avoid synthetic bold.

Numbers: apply `QFont.Tag("tnum")` to KPI, table numeric and chart-axis
fonts. If the feature is unavailable, fall back to the same family
without failing.

Do not use QSS `font: 13px ...` or generic `QWidget { font-size: ... }`
again. QSS may still set color, padding and weight for specific
selectors, but the canonical family/size lives in `QFont` role helpers.

## 5. Color, spacing and shape tokens

### Palette

Keep the teal brand identity but use it sparingly.

| Token | Value | Use |
|---|---|---|
| `bg.canvas` | `#0B0D10` | window background |
| `bg.surface` | `#14181F` | cards, panels |
| `bg.surfaceRaised` | `#1A202B` | table headers, hover rows |
| `bg.overlay` | `#222A36` | popups, menus, tooltips |
| `border.subtle` | `#29323E` | card/table borders |
| `border.strong` | `#3A4656` | focused/selected borders |
| `text.primary` | `#F2F5F8` | body and KPI values |
| `text.secondary` | `#AFBAC8` | labels, descriptions |
| `text.muted` | `#788595` | captions, axis labels |
| `accent` | `#2DD4BF` | selected nav, chart line, focus |
| `accent.hover` | `#5EEAD4` | hover highlight |
| `accent.pressed` | `#14B8A6` | pressed/active |
| `primary` | `#0D9488` | primary button |
| `success` | `#34D399` | healthy/ready |
| `warning` | `#FBBF24` | collision/launcher warning |
| `danger` | `#F87171` | errors, anomaly dots |
| `info` | `#60A5FA` | neutral informational badge |
| `chart.grid` | `#2A3441` | chart grid lines |
| `chart.axis` | `#8A97A8` | chart labels |

Rules:

- KPI values use `text.primary`, not accent.
- Accent is for primary action, active navigation, selection and the
  frame-time line.
- Status colors always pair with text, never color alone.
- Body text must meet WCAG AA contrast on its surface; secondary text
  should remain above 4.5:1.

### Spacing

Use a 4px base scale:

`4 / 8 / 12 / 16 / 24 / 32`

- page padding: 24 (32 on wide screens);
- card padding: 16–20;
- section gap: 24;
- control height: 36–40 logical px (scaled with font);
- row gap: 8–12;
- table row height: 36–40 (font-aware).

### Shape

- radius 6: badges, small chips;
- radius 10: buttons, inputs, selects;
- radius 14: cards and chart panels;
- radius 18: dialogs;
- pill: status badges, segmented controls;
- border: 1px subtle; focus: 2px accent with a darker inner ring.

### Elevation

Prefer surface color + border over shadows. A single soft shadow is
acceptable for modal dialogs and menus, not for every card. Avoid many
`QGraphicsDropShadowEffect` instances for performance.

## 6. Page layout drafts

### Global shell

```text
┌──────────────────────────────────────────────────────────────┐
│ LagLens                         [Ready / Live status pill]  │
│ [ Hardware ] [ Live Frames ] [ Settings ]   (segmented nav) │
├──────────────────────────────────────────────────────────────┤
│ page content (scrollable)                                   │
│                                                              │
│                                                              │
├──────────────────────────────────────────────────────────────┤
│ status dot  status text · file size · elapsed                │
└──────────────────────────────────────────────────────────────┘
```

- Header: 56–64px; brand left, status pill right.
- Navigation: 36–40px segmented control, not full-width green tabs.
- Content: max-width not required for monitoring pages, but settings
  content should cap around 760px.
- Footer: one quiet status line with a colored dot.

### Live Frames

```text
Capture card
┌──────────────────────────────────────────────────────────────┐
│ Target process  [ douyin.exe            v ] [Select] [Refresh]│
│ PresentMon      [ E:\...\PresentMon.exe ]              [Browse]│
│ [Start monitoring] [Stop]  □ Auto-open  □ Low overhead  □ Exit │
└──────────────────────────────────────────────────────────────┘

KPI row
┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│ EST. PRESENT │ │ MEAN FRAME   │ │ PEAK FRAME   │ │ SPIKE        │
│ 31.5 FPS     │ │ 31.78 ms     │ │ 3021.93 ms   │ │ 45           │
└──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘

Chart card
┌──────────────────────────────────────────────────────────────┐
│ Live frame time                         last 60 samples      │
│ [chart]                                                      │
└──────────────────────────────────────────────────────────────┘
```

Notes:

- Capture card groups all input/actions; Start is the only primary
  button.
- Checkboxes become compact labeled toggles or well-spaced checks; no
  oversized native boxes.
- KPI values use tabular numerals; labels are caption-sized.
- Chart header has a small legend and no teal title.

### Hardware

- Five KPI cards in a responsive grid: 5 columns at wide width,
  3 + 2 at 900–1100, 2 columns when narrow.
- GPU chart card below, with a clear card header and axis units.
- The current huge empty chart area is reduced; chart should fill the
  card with sensible minimum height.

### Settings

```text
Settings
┌ Appearance ─────────────────────────────────────────────────┐
│ Language          [ Follow Windows language            v ]  │
│ Language changes apply immediately and are saved.           │
└─────────────────────────────────────────────────────────────┘

┌ About / Data (optional, read-only) ────────────────────────┐
│ Settings file    <data-dir>\LagLens.ini                 │
│ Captures         <repo>\captures           │
└─────────────────────────────────────────────────────────────┘
```

- Settings rows use a two-column layout with label + description on the
  left and the control on the right.
- Optional read-only “About/Data” card fills the empty page with useful
  context; it does not add behavior.
- Max content width ~760px; left-aligned, not stretched edge-to-edge.

### Analysis window

```text
┌ LagLens · Frame analysis                    [File name]      │
│ Capture summary: 1,523 frames · 49.24 s · douyin.exe          │
├──────────────────────────────────────────────────────────────┤
│ [FPS 31.5] [1% Low 1.1] [Mean 31.78 ms] [P95 36.18] [P99 ...]│
├──────────────────────────────────────────────────────────────┤
│ Swap chain [ Automatic (recommended) v ]   [high confidence] │
│ Why: ...                                                     │
├──────────────────────────────────────────────────────────────┤
│ [ frame-time chart ]                                         │
├──────────────────────────────────────────────────────────────┤
│ Selected frame details / hint                                │
└──────────────────────────────────────────────────────────────┘
```

- Add a KPI strip instead of a multi-line summary paragraph.
- Chain selector and confidence badge share the chart header.
- Details panel uses a surface card; footnote is caption-sized.
- Wrap the content in a scroll area; keep chart min-height ~320.

### Process dialog

```text
┌ Select target process ───────────────────────────────────────┐
│ Choose a running executable                                  │
│ [Recommended] [All processes]  [ Search name/path/title  ]  │
│ [Refresh]                                                    │
├──────────────────────────────────────────────────────────────┤
│ Process        PID    Window title     Path        Signals    │
│ ...                                                          │
├──────────────────────────────────────────────────────────────┤
│ ⚠ Same-name warning (when applicable)                        │
│ Selected reason: ...........................................  │
├──────────────────────────────────────────────────────────────┤
│ 3 of 120 processes                         [Cancel] [Select] │
└──────────────────────────────────────────────────────────────┘
```

- Segmented mode control, search with a leading icon, ghost Refresh.
- Table row height 36–40; signal column uses short chips or concise
  text; full signal text stays in the detail panel and tooltip.
- Keep the no-default-selection and explicit Select behavior.
- Keep the name-based-targeting note and collision warning prominent.

## 7. Technical decisions and trade-offs

### 7.1 Windows text scale vs fixed design

**Decision:** respect the system font size, with a 10pt floor. At 182%
this yields a 15.75pt body and a larger layout. Use scroll areas and
responsive grids rather than shrinking text.

Trade-off: more vertical space is required and some pages will scroll
at 900x650. That is preferable to overriding accessibility.

If a compact mode is desired later, expose it as an explicit preference;
do not silently cap Windows text scaling.

### 7.2 Point sizes vs pixel sizes

Use point sizes and role fonts. Pixels are physical-device-ish and do
not track Windows text scale. If a QSS size cannot be removed, use
`pt`, never `px`, and document why.

### 7.3 High-DPI policy

Set `QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
PassThrough)` explicitly before creating `QApplication`, even though Qt
6.12 currently defaults to it. Test at 100%, 125%, 150%, 200% and with
Windows text scale 100%, 150%, 182%. Test a secondary monitor with a
different physical DPI.

Do not manually scale `QPainter` coordinates by DPR for widget
painting: Qt already does that. Manual DPR math is only needed when
rendering into an offscreen `QPixmap`/`QImage`.

### 7.4 Chart rendering

- Set the chart painter font explicitly from the caption/mono role.
- Add `QPainter.RenderHint.TextAntialiasing`.
- Keep antialiasing for curves and dots.
- For 1px grid lines, either disable AA for the grid or align to
  half-pixels (`round(y) + 0.5`) and use a cosmetic pen.
- Compute the Y-axis gutter from `QFontMetrics`, not a fixed 70px.
- Draw axis labels with `QRectF` + alignment to avoid baseline drift.
- Consider min/max downsampling for 11k-frame analysis charts while
  preserving the original point list for click selection.
- Keep chart data and selection semantics unchanged.

### 7.5 Style engine: `windows11` vs `Fusion`

Current state is `windows11` plus partial QSS. Two options:

- **Keep windows11:** native animations and accessibility, but QSS
  coverage for checkboxes, spin boxes, scrollbars, tooltips and popups
  is incomplete and can vary by Windows build.
- **Switch to Fusion:** deterministic dark styling and easier token
  coverage, at the cost of some native Windows feel.

**Recommendation:** run a small UI-2 spike comparing both. Default to
Fusion if it gives materially more consistent dark controls; keep
native file dialogs, menus and DWM title-bar behavior. Do not switch
before the spike and screenshot review.

### 7.6 Dark title bar

Use the Windows DWM immersive-dark-mode attribute rather than a
frameless custom title bar. Frameless windows add drag, snap, resize,
accessibility and multi-monitor risk for little visual gain.

### 7.7 QSS limitations

Qt style sheets do not support CSS variables, transitions or box
shadows. Generate the global QSS from a Python token module, keep
per-widget styles minimal, and use `QPalette` for native pieces.
Avoid applying a new stylesheet per widget during live updates.

### 7.8 Icons

No new image dependency is required. Use text labels first. If icons
are added, use a tiny SVG line-icon set or `QStyle.StandardPixmap`,
with high-DPI variants. Do not mix emoji with line icons.

### 7.9 Tests and compatibility

- Keep all existing object names, widget attributes and text keys.
- Do not change capture, CSV, statistics, chain selection, settings or
  process-selection behavior.
- Preserve the 312-test baseline. UI changes may require test updates
  only for layout/object assumptions, never for behavior.
- Preserve runtime language switching and both catalogs.
- Add a screenshot harness at 100/125/150/182 text scale for UI-1/UI-3;
  use manual visual acceptance before any pixel-diff baseline.

## 8. UI-1 / UI-2 / UI-3 implementation plan

### UI-1 — clarity and typography (first)

Deliverables:

- explicit high-DPI setup before `QApplication`;
- a small theme/font module with system-anchored point sizes, family
  stacks, `tnum` numeric fonts and role helpers;
- remove generic pixel font declarations from `main.py`,
  `frame_viewer.py` and `process_dialog.py`;
- apply the same typography to the two custom charts;
- chart grid pixel alignment + text antialiasing + metric-based gutters;
- dark title bar if the current title bar is not already dark;
- screenshot matrix at 100/125/150/182 and test the secondary 189-DPI
  screen.

Acceptance:

- body text is visibly larger/clearer and respects Windows text scale;
- no clipping at 182% in the main window, process dialog or analysis
  window (scroll is allowed);
- chart labels and grid lines are crisp;
- numbers use tabular figures;
- 312 tests still pass;
- before/after screenshots in both languages.

### UI-2 — design system and controls

Deliverables:

- token module for colors, spacing, radii, typography and states;
- generated global QSS with component variants (primary/secondary/
  ghost/danger, inputs, combos, checkboxes, spin boxes, tabs/segmented
  control, table, tooltip, scrollbars, focus ring);
- remove hardcoded color/radius literals from the three windows;
- unify card/surface/border/elevation tokens;
- decide `windows11` vs `Fusion` after a spike;
- preserve current layouts (visual-only pass).

Acceptance:

- all controls look intentionally dark and consistent;
- hover/pressed/focus/disabled states are visible;
- contrast and keyboard focus pass manual checks;
- no light native artifacts in the main window/dialog;
- 312 tests still pass;
- screenshots at 100/125/150.

### UI-3 — page-level refresh and acceptance

Deliverables:

- global shell: header, status pill, segmented navigation, content
  scroll area, quiet footer;
- Live page: capture card, KPI grid, chart card, status;
- Hardware page: responsive KPI grid and chart card;
- Settings page: section cards and settings rows;
- Analysis window: KPI strip, chart/chain card, details card, scroll;
- Process dialog: segmented modes, search field, denser table, signal
  column, collision banner, reason detail, footer;
- responsive behavior at 900x650, 1100x760 and 1280x800;
- EN/ZH screenshots at 100/125/150/182 and manual acceptance checklist.

Acceptance:

- hierarchy matches the design goals: clear page title, card headers,
  readable body, stable numbers;
- no horizontal clipping or overlapping text;
- all existing functionality and keyboard behavior preserved;
- 312 tests still pass;
- final screenshot/manual acceptance before Phase UI is marked done.

## 9. Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Text scaling 182% makes pages overflow | High | High | system-anchored point sizes, scroll areas, responsive grids, test at 182% |
| Fractional DPR makes chart lines soft | Medium | High | cosmetic pens, pixel alignment, no AA for 1px grid, test 125/150/200 |
| Font availability differs on Windows 10/11 | Medium | Medium | family stacks with Segoe UI/YaHei/Cascadia fallbacks |
| QSS/native style conflicts | High | Medium | spike Fusion vs windows11; palette + targeted QSS; visual QA |
| Qt QSS lacks shadows/transitions | Certain | Low | surface/border hierarchy, one dialog shadow, no fake CSS |
| Chart redraw cost with 11k points | Medium | Medium | keep data; optional render downsampling; profile before/after |
| Layout changes break UI tests | Medium | High | preserve object names/attributes; update only layout assumptions; run 312 tests |
| Light title bar in dark app | Medium | Medium | DWM immersive dark mode; verify Windows 11 |
| Accent overuse / flat hierarchy | Medium | Medium | token rules: accent only for action/selection/chart |
| Localization length changes | Medium | Medium | test both languages at minimum width; elide + tooltip where needed |
| Font feature `tnum` unavailable | Low | Low | feature optional; same family fallback |
| Adding icons/assets | Low | Medium | no new dependency; tiny SVG/QStyle only after approval |

## 10. Decisions requested

1. **Respect Windows text scale at 182% (recommended)** even if some
   pages become scrollable, or cap the base at a smaller size for a
   denser layout?
2. **Keep teal as the brand accent (recommended)** with much less usage,
   or move to a neutral blue/purple accent?
3. **Fusion vs windows11:** approve a UI-2 spike and default to Fusion
   if it is materially more consistent?
4. **Settings page:** add an optional read-only “About / Data locations”
   card to fill the page, or keep the language card only?
5. **Icons:** text-only (recommended for this phase) or a minimal line
   icon set?

## 11. Current screenshots used for the audit

- `captures/ui_a2_en_settings.png`, `ui_a2_zh_settings.png`
- `captures/ui_a2_en_live.png`, `ui_a2_zh_live.png`
- `captures/ui_a3_en_analysis.png`, `ui_a3_zh_analysis.png`
- `captures/ui_b2_en_recommended.png`, `ui_b2_zh_recommended.png`
- `captures/ui_b2_en_all_collision.png`, `ui_b2_zh_all_collision.png`
- `captures/ui_b3_en_dialog.png`, `ui_b3_zh_dialog.png`
- `captures/ui_b3_en_launcher.png`, `ui_b3_zh_launcher.png`
- `captures/ui_b3_en_main_locked.png`, `ui_b3_zh_main_locked.png`
- `captures/ui_audit_en_hardware.png`,
  `captures/ui_audit_zh_CN_hardware.png`

These screenshots are audit evidence only; `captures/` remains ignored
by git.

## 12. Non-goals

- no changes to PresentMon capture, CSV validation, frame statistics,
  swap-chain selection or settings semantics;
- no new runtime dependency;
- no frameless window;
- no change to the 312-test behavior baseline;
- no Phase C work until the UI design is accepted.
