# Analysis Inline Report

Date: 2026-11-13
Status: implemented, awaiting review

## 1. Goal

Users should be able to read the complete diagnostic report directly in the
main-window Analysis page. Exporting Markdown or JSON remains available but
is no longer required to read the report.

## 2. What changed

- Added a **Report overview** card at the top of the Analysis page:
  - game/target name;
  - duration;
  - frame count;
  - average FPS;
  - P95 frame time;
  - 1% Low FPS;
  - local anomaly count.
- Added a **complete diagnosis report** section. Every grouped finding is
  rendered directly with:
  - category and summary;
  - severity, confidence and claim level;
  - why the finding appears;
  - how certain it is;
  - what it does not tell the user;
  - what to try next;
  - group event count and a note when similar events were merged.
- Added a per-finding **Show evidence and metrics** expander containing the
  existing metric lines, raw engine evidence and caveats.
- Kept the existing finding list as a **Troubleshooting focus** selector for
  the C-4 guide. Each full-report block also has a button that selects the
  corresponding guide.
- Kept the anomaly table with all original events. Selecting a row expands
  a titled detail panel with CPU busy/wait, GPU busy/wait/latency/time and
  display latency.
- Kept Markdown/JSON export as a secondary action.

No diagnostic rules, capture pipeline, frame statistics or swap-chain
selection were changed.

## 3. Data reuse

The page continues to use one `diagnostics.analyze()` result:

```text
self.diagnostic_report
```

The overview uses `self.stats` and `len(report.events)`. The full report
uses:

```text
diagnostic_text.group_findings(report.findings)
diagnostic_text.finding_summary()
diagnostic_text.why_text()
diagnostic_text.limit_text()
diagnostic_text.advice_text()
diagnostic_text.certainty_text()
diagnostic_text.metric_lines()
```

The same helpers drive Markdown/JSON export, so the UI and exported report
do not diverge.

## 4. Negative number formatting

The event evidence template previously used a literal `+` before the value:

```text
CPU +{cpu:.1f} ms
```

A negative delta therefore rendered as `CPU +-0.4 ms`. The template now uses
Python's signed format:

```text
CPU {cpu:+.1f} ms
```

Positive values still show `+`, while negative values show a single `-`.

## 5. Tests

Focused new coverage:

- overview shows game, duration, frames, average FPS, P95, 1% Low and
  anomaly count;
- every grouped finding is rendered, including data-quality findings;
- grouped counts sum to the original finding count;
- severity/confidence/claim badges are present;
- per-finding evidence is collapsed by default and can be expanded;
- selected event detail includes extended CPU/GPU fields;
- `CPU +-0.4 ms` is prevented and `CPU -0.4 ms` is produced.

Full suite:

```text
Ran 504 tests

OK
```

## 6. GUI checks

Checked with the real grouped-diagnostics capture:

```text
D:\LagLensData\captures\douyin.exe_20261112_184509_333905.csv
```

- 6106 frames, 8 local anomalies, 2 finding groups (global CPU + grouped
  local CPU association).
- Overview showed `douyin.exe`, `136.49 s`, `6,106`, `44.7`, `27.91 ms`,
  `24.0 FPS`, `8`.
- Full report blocks and event detail rendered without horizontal scrolling.
- The page remained scrollable at 980x760 and simulated 125%/150% scaling;
  the horizontal scrollbar maximum stayed `0`.

Screenshots:

```text
captures/analysis_inline_en.png
captures/analysis_inline_report_en.png
captures/analysis_inline_events_en.png
captures/analysis_inline_zh_min.png
```

## 7. Affected files

- `frame_viewer.py`
- `diagnostic_text.py`
- `ui_theme.py`
- `locales/en.json`
- `locales/zh_CN.json`
- `tests/test_diagnostic_ui.py`
- `tests/test_diagnostic_grouping.py`
