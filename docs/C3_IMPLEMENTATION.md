# C-3: Diagnostic UI and Reports

Date: 2026-11-12
Status: implementation complete, awaiting C-3 review.
Scope: integrate the C-2 diagnostic engine into the existing FrameViewer
with a player-readable summary, local stutter evidence, conservative
advice, QPC/telemetry status, and local JSON/Markdown reports. No C-2
rule changes, no capture-pipeline changes, no packaging or GitHub
release work.

## 1. Summary

- Added a **Diagnostic summary** card to `FrameViewer`.
- Findings show localized category, plain-language summary, severity,
  confidence and claim level.
- CPU, GPU, mixed, memory, presentation and insufficient-evidence
  findings are separately identified.
- Added a **local stutter events** list. Selecting an event:
  - highlights the frame on the existing chart;
  - shows the frame time, local baseline and local threshold;
  - shows the event frame's CPUBusy/GPUBusy/GPUWait values;
  - updates the existing selected-frame details.
- Added a **Time sync and telemetry** section:
  - QPC verified/unverified/legacy/unknown status;
  - sidecar sample count and complete/incomplete state;
  - whether frame-to-telemetry correspondence is trusted;
  - missing-field and untrusted-timebase reasons.
- Added localized, conservative **What to try next** suggestions. They
  are explicitly experiments, not confirmed causes.
- Added local **Markdown and JSON report export**. Reports use the
  capture basename only, not full paths or usernames.
- No telemetry sidecar still allows normal CSV analysis; the UI shows
  the missing-data reason.
- The capture summary now says **fixed-threshold stutters** and the
  diagnostic section is **local dynamic anomalies**, with an explicit
  note that the two counts are different.
- List heights shrink for small event/finding counts, and the evidence
  panel has a summary / Why / Evidence / Limitations hierarchy.
- Full suite: **433 tests in 13.820 s, OK**.

## 2. UI integration

### Diagnostic summary

The card is built in `FrameViewer` after the existing capture summary
and swap-chain panel, before the frame-time chart.

Each finding list item contains:

```text
localized category · localized finding summary
localized claim level · localized confidence
```

The detail panel below the list contains:

- the plain-language summary;
- why the engine reached the association;
- numeric evidence from the finding;
- the applicable limitation;
- the suggested next experiment.

Raw English engine evidence strings are not dumped into the localized
UI. The UI builds localized text from `Finding.metrics`, category
guidance and the code-to-text catalog. The underlying engine remains
unchanged.

### Stutter events and chart linkage

`DiagnosticReport.events` now exposes structured `DiagnosticEvent`
records:

```text
time, duration, local baseline, local threshold
window start/end, frame index, associated finding codes
```

Selecting an event sets the chart's selected marker and calls the
existing `show_details()` frame panel. The event detail adds the local
baseline, threshold and associated finding summary. Clicking a chart
point still updates the same selected-frame panel.

No frame-time statistics or chart calculations were changed.

### Fixed-threshold vs local dynamic anomalies

The capture summary label is now:

```text
Fixed-threshold stutters: ...
```

The diagnostic event section is:

```text
Local dynamic anomalies
```

A note under the section explicitly says that local dynamic anomalies
use a local baseline and can exist even when the fixed-threshold stutter
count is 0. This prevents the previous confusion where “Stutters: 0”
appeared above a non-empty local event list.

Local event/finding list heights are computed from their item count and
shrink when there are only one or two rows, removing the large blank
area in the small-event case.

The finding detail uses a clear hierarchy:

```text
bold finding summary
Why this appears: ...
Evidence
  • metric ...
Limitations: ...
```

Advice remains in its own section below, avoiding duplication.

### Time sync and telemetry

The card shows:

- QPC verified / unverified / legacy-relative / unknown;
- telemetry sample count;
- complete/incomplete sidecar;
- trusted or unavailable frame-to-telemetry alignment.

When telemetry is absent, untrusted or incomplete, the card explains
why memory/hardware association is not claimed. CSV analysis never
depends on the sidecar.

### Player-facing advice

Advice is selected by finding category:

- CPU: compare CPU-side load changes in the same scene;
- GPU: compare resolution/settings/frame-cap changes in the same scene;
- mixed: change one side at a time;
- memory: compare RAM/working-set changes in the same scene;
- presentation: check window mode, VSync/frame cap and refresh rate;
- data quality: enable QPC and complete telemetry/GPU fields;
- unknown: repeat with more evidence before attributing a cause.

Every advice section says these are experiments, not confirmed causes.
No game, driver or Windows setting is modified automatically.

## 3. Controlled A/B safety

C-2.2 already tightened metadata validation. For C-3, the engine default
is additionally conservative:

```text
DiagnosticConfig.allow_confirmed_by_control = False
```

Consequences:

- a normal `analyze()` call with `ControlExperiment` metadata does not
  emit `confirmed_by_control`;
- the rejection is visible in `control_rejections`;
- a future controlled-experiment validator can explicitly opt in;
- the FrameViewer never opts in and never exposes an A/B confirmation
  control;
- real Palworld findings remain `observed_association` or `likely`.

The UI labels `observed_association` as “Observed association” / “观察
到的关联”, never as a confirmed cause.

## 4. Report export

New pure module: `diagnostic_report.py`.

- **Markdown**: localized headings, capture information, findings,
  evidence, local events, limitations and advice.
- **JSON**: structured technical artifact with capture metadata and
  `DiagnosticReport.to_dict()`.
- **No full user paths**: only the CSV basename and target executable
  name are stored.
- **No username/environment paths** are added.
- PDF and cloud upload are intentionally out of scope.

The UI provides an **Export report…** button. The save dialog supports
`.md` and `.json`. The default path is next to the capture file, but the
report content itself contains only the basename.

## 5. Real Palworld demonstration

Screenshots:

- `captures/c3_diagnostics_en.png`
- `captures/c3_diagnostics_zh.png`

Source data: real QPC-capable Palworld capture
`Palworld-Win64-Shipping.exe_20261112_145654_215377.csv` with its C-1
sidecar. The capture has 615 frames and 39 telemetry samples.

The screenshot shows:

- capture summary unchanged;
- verified QPC timebase;
- 39 complete telemetry samples;
- mixed CPU/GPU pressure (`observed_association`, low confidence);
- one local stutter at 8.96 s / 42.57 ms;
- local baseline 15.55 ms, local threshold 31.10 ms;
- event frame CPUBusy 42.39 ms, GPUBusy 18.98 ms, GPUWait 1.72 ms;
- CPU-side local association (`observed_association`);
- conservative advice;
- “Target CPU samples are unusable” data-quality note for this
  historical pre-fix sidecar.

No confirmed cause is shown. The same capture is not used to claim a
real CPU or GPU root cause.

A post-fix QPC capture (`qpc_c22`) was used separately to confirm target
CPU sampling: target CPU median 64.6%, max 82.2%. At the user-visible
60 FPS target it produced `insufficient_evidence` (the capture was
running near 120 FPS); at a 120 FPS target it produced an observed CPU
candidate with target CPU context, still not confirmed.

### Minimum window and simulated scaling

The minimum window was checked at 980×760 with the full content in a
scroll area. Simulated `QT_SCALE_FACTOR` values 1.25 and 1.50 were run
for English and Chinese using the real QPC capture:

```text
EN 1.25: content 970×2791, screenshot generated
EN 1.50: content 970×2791, screenshot generated
ZH 1.25: content 970×2575, screenshot generated
ZH 1.50: content 970×2575, screenshot generated
```

No clipping or crash was observed; the diagnostic card remained
scrollable and readable. These are simulated scaling checks, not
physical 125%/150% monitor tests. The scaling screenshots are validation
artifacts under `<validation-data>` and are not committed.

## 6. Tests

New/changed tests:

- `tests/test_diagnostic_ui.py`:
  - summary/finding/event population;
  - fixed-threshold vs local dynamic anomaly wording;
  - compact list height for a single event;
  - rich-text evidence hierarchy;
  - event selection links chart marker, event evidence and frame details;
  - runtime EN/ZH switch localizes diagnostics;
  - no confirmed claim in normal UI;
  - Markdown/JSON export and path sanitization.
- `tests/test_diagnostics.py` report/report-export tests:
  - structured events and telemetry coverage;
  - localized path-safe Markdown;
  - structured path-safe JSON;
  - default confirmation disabled.
- Main-window analysis path preserves a QPC sidecar timebase before
  constructing FrameViewer, so the UI does not silently downgrade a
  verified QPC capture to legacy/inferred.
- Existing FrameViewer, i18n, statistics and chain-selection tests
  remain green.

Full suite:

```text
Ran 433 tests in 13.820s

OK
```

## 7. Known limitations

- The screenshots use a real capture but are static; simulated
  125%/150% and minimum-window checks passed, but physical monitor/DPI
  and full interactive manual acceptance are still required.
- The screenshot source sidecar predates the C-2.2 target CPU fix and
  therefore shows target CPU as unusable. This is intentional data
  quality reporting, not a UI error.
- JSON reports contain the engine's technical English evidence; the
  localized Markdown is the player-facing report.
- A/B confirmation remains disabled by default; no real controlled A/B
  validation exists.
- PDF export, packaging and GitHub release work are out of scope.
- The UI does not automatically modify game, driver or Windows settings.
