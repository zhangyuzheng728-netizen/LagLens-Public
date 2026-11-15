# UI-2 Implementation: Modern Design System

Date: 2026-11-12
Status: implementation complete, awaiting manual review.
Scope: design tokens and base component styling. UI-3 page layout is
not included.

## 1. Goal

Replace the remaining hard-coded, per-window dark styling with one
modern design system shared by the main window, analysis window and
process dialog. Keep the Qt stack, the UI-1 typography/high-DPI work
and all functional behavior.

Visual direction: restrained neutral dark surfaces, one teal accent,
clear hierarchy, subtle borders, consistent radii/spacing and complete
interaction states.

## 2. Design tokens

`ui_theme.py` is now the single source of truth.

### Colors

| Token | Value | Role |
|---|---|---|
| canvas | `#0B0D10` | window/page background |
| surface | `#14181F` | cards and panels |
| surface_raised | `#1A202B` | headers, hover rows, raised controls |
| overlay | `#222A36` | popups, tooltips, hover |
| border | `#29323E` | default 1px borders |
| border_strong | `#3A4656` | hover/focus borders |
| text_primary | `#F2F5F8` | body and KPI values |
| text_secondary | `#B6C0CD` | labels, muted copy |
| text_muted | `#8894A3` | disabled copy |
| accent | `#2DD4BF` | brand, selected tab, chart line, focus |
| accent_hover | `#5EEAD4` | accent hover |
| accent_pressed | `#14B8A6` | accent pressed |
| primary | `#0D9488` | primary button |
| primary_hover | `#0F9F94` | primary hover |
| primary_pressed | `#0B7C73` | primary pressed |
| success / warning / danger / info | `#34D399` / `#FBBF24` / `#F87171` / `#60A5FA` | semantic states |
| selection | `#173C39` | table selection |
| chart_grid / chart_axis / chart_line / chart_alert | `#2A3441` / `#8A97A8` / `#2DD4BF` / `#F87171` | chart palette |

KPI values are now primary text; teal is reserved for primary actions,
selection, brand and the frame-time line.

### Spacing

`SPACE = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32 }`

Applied to page margins, card padding, control spacing and section
gaps. Main window page margin is 24; cards use 16; control rows use 8;
section gaps use 12/16.

### Radii

`RADIUS = { sm: 6, md: 10, lg: 14, xl: 18, pill: 999 }`

- buttons/inputs: 10;
- cards/panels/tables: 14;
- small badges/tooltips: 6;
- dialogs: 18 (available for UI-3).

### Typography

UI-1 roles remain unchanged: display, heading, subheading, body, label,
caption, metric, mono; system-anchored point sizes; Segoe UI
Variable/YaHei fallbacks; tabular figures. UI-2 does not reintroduce
QSS font-size/family declarations.

## 3. Theme application

`ui_theme.ensure_application_theme()`:

- applies the UI-1 body font once;
- selects Qt's `Fusion` style for deterministic dark control rendering;
- installs a complete dark `QPalette` (window, base, text, buttons,
  highlight, tooltip, placeholder, disabled roles);
- installs one application-wide stylesheet generated from the tokens;
- is idempotent via an application property.

Per-window stylesheets were removed from:

- `main.py`
- `frame_viewer.py`
- `process_dialog.py`

The main window, analysis window and process dialog now inherit the same
theme. Page-specific visuals use object names (`card`, `chainPanel`,
`detailsPanel`, `reasonPanel`, `muted`, `warningLabel`) instead of
duplicated QSS.

## 4. Component coverage

### Buttons

- default secondary: raised surface, 1px border, 10px radius;
- primary variant: teal fill, white text, 600 weight;
- ghost variant: transparent, secondary text, hover surface;
- hover, pressed, focus and disabled states;
- `ui_theme.set_button_variant()` applies `variant=primary|secondary|
  ghost`.

Applied to:

- Start Monitoring: primary;
- Select (process dialog): primary;
- Stop / Analyze / Select Process / Browse / Open CSV: secondary;
- Refresh Processes and dialog Refresh: ghost.

### Inputs

- `QLineEdit`, `QComboBox`, `QSpinBox`, `QDoubleSpinBox` share surface,
  border, radius and padding;
- hover border, accent focus border, muted disabled state;
- selection colors;
- explicit combo chevron asset and dark popup with selected-row color.

### Tabs

- old full teal blocks replaced with quiet pill tabs;
- transparent background, secondary text, hover surface;
- selected tab uses raised surface + accent text.

### Tables

- surface background, raised alternate rows, 14px radius;
- header surface, secondary text, bottom border;
- row hover, dark-teal selection, accent focus border;
- font-aware row/header heights from UI-1.

### Checkboxes

- 20px rounded dark indicator with visible border;
- accent hover border;
- checked: accent fill + `assets/check.svg` check mark;
- disabled indicator state.

### Scrollbars, tooltips and menus

- dark 10px scrollbars with raised handles and hover state;
- dark tooltip surface and border;
- combo popup uses overlay surface and selection color;
- messages/dialog buttons inherit the same global theme.

### Charts

- chart grid, axis, line, alert and surface colors now come from
  `ui_theme.CHART`;
- no chart behavior or data logic changed.

## 5. Assets

- `assets/check.svg` — check mark for checked checkboxes;
- `assets/chevron-down.svg` — combo dropdown indicator.

No new runtime dependency was added.

## 6. Files changed

| File | Change |
|---|---|
| `ui_theme.py` | tokens, palette, global stylesheet, theme application and button variants |
| `main.py` | removed local stylesheet, uses tokens, button variants, token colors in live chart |
| `frame_viewer.py` | removed local stylesheet, object names, token colors in frame chart |
| `process_dialog.py` | removed local stylesheet, object names, button variants, token spacing |
| `tests/test_ui_theme.py` | 3 additional UI-2 tests (12 total UI theme tests) |
| `assets/check.svg`, `assets/chevron-down.svg` | check and combo indicators |

## 7. Verification

Full suite:

```text
Ran 324 tests in 14.321s

OK
```

312 pre-UI tests + 12 UI theme tests.

Screenshot matrix at native resolution (no image scaling):

- before UI-2: `ui2_before_100_*` (copied from UI-1 accepted state);
- after UI-2: `ui2_after_100_*` (English and Chinese);
- 125% and 150% display scaling via `QT_SCALE_FACTOR`:
  `ui2_after_125_*`, `ui2_after_150_*`;
- simulated 100% text scale: `ui2_after_text100_*`.

Covered pages: Live, Hardware, Settings, process dialog and analysis
window, in English and Chinese.

Visual checks:

- one neutral surface hierarchy across all windows;
- teal limited to actions/brand/chart/selection;
- KPI values use primary text;
- secondary/ghost/primary button hierarchy is visible;
- tables, headers, selection and scrollbars match the dark theme;
- checkboxes have visible unchecked, hover/focus, checked and disabled
  states;
- combo chevrons are visible;
- focus borders and hover states are defined for buttons and inputs;
- UI-1 font clarity and high-DPI behavior remain intact.

## 8. Explicit non-claims and limits

- 125%/150% display scaling was simulated with `QT_SCALE_FACTOR`, not a
  physical monitor scaling switch.
- 100% text scale was simulated with a 9pt application font; the
  current machine is actually at 182% Windows text scale.
- No physical multi-monitor DPR switch was tested.
- No real game capture was performed for UI-2 screenshots.
- Page-level hierarchy remains UI-3: empty Settings page, Hardware chart
  header placement, card proportions and navigation structure are not
  redesigned.
- The process dialog recommendation-signal column can still truncate;
  tooltip and reason panel remain the full-text path.
- Qt QSS has no transitions/shadows; the theme uses border/surface
  hierarchy instead.
- Native spin-box subcontrols remain Fusion-rendered with the dark
  palette; they are not custom-icon themed.
- The optional dark title bar was not changed.
- `assets/*.svg` must be included if the application is ever packaged
  as a frozen executable.
