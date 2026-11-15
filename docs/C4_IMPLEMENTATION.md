# C-4: Guided Troubleshooting

Date: 2026-11-12
Status: implementation complete, awaiting C-4 review.
Scope: add a lightweight, localized step-by-step troubleshooting guide to
the existing FrameViewer diagnostic card and provide a re-check entry that
reuses the normal live-capture flow. No diagnostic-rule changes, no
capture-architecture changes, no automatic A/B comparison, no network or
cloud features, and no packaging or GitHub release work.

## 1. Summary

- Added a **Step-by-step troubleshooting** section after the existing
  conservative advice in the diagnostic card.
- Selecting a finding shows the guide for its category:
  - CPU;
  - GPU;
  - mixed CPU/GPU;
  - memory;
  - presentation;
  - data quality.
- Every guide has four concrete, safe steps. The engine's `unknown`
  category reuses the data-quality guide.
- Each step has a checkbox. A progress label shows
  `done/total steps completed` and updates immediately.
- **Reset steps** clears only the selected category.
- Completion state is kept in memory per category, so switching between
  findings of different categories does not lose checked steps.
- **Re-check with a new capture** emits the target application name to
  the main window. The main window selects that target and switches to
  the existing Live Frames tab, but does not start a capture.
- The guide note explicitly asks the user to change only one variable at
  a time and repeat the same game scene. It also states that the guide
  never modifies game, driver or Windows settings.
- Finding text continues to describe `observed_association` as an
  observation, never as a confirmed cause.
- Legacy CSV files without telemetry still show guides and re-check
  normally.
- Full suite: **444 tests in 14.380 s, OK**.

## 2. How to use it

1. Open a capture in the existing analysis window.
2. Select a finding in **Findings**.
3. Read the matching **Step-by-step troubleshooting** guide.
4. Change only one game, driver or Windows variable yourself.
5. Capture the same scene again and compare the new result.
6. Check off completed steps as you go; use **Reset steps** to start the
   selected category again.
7. Use **Re-check with a new capture** to return to the Live Frames tab
   with the target prefilled. Start the capture manually when ready.

The guide does not change any setting on the user's behalf. It is a
checklist and a shortcut back to the normal capture controls.

## 3. UI behavior

### Guide content

Each category has four steps:

| Category | Focus |
|---|---|
| CPU | Background CPU load, repeatable capture, CPU metrics, one CPU-side change |
| GPU | One GPU setting, repeatable capture, GPU metrics, frame cap/VSync |
| Mixed | Baseline, one CPU-side change, one GPU-side change, inconclusive handling |
| Memory | Baseline RAM/working set, memory-heavy app or texture setting, repeat capture, comparison |
| Presentation | Window mode, VSync, frame cap, displayed-frame ratio and latency |
| Data quality | QPC, telemetry sidecar, GPU fields, capture duration and coverage |

Guides are text-only and use the existing `diagnostic_text` translation
infrastructure. The diagnostic engine remains language-neutral and
unchanged.

### Progress and reset

- State is stored in `FrameViewer._guide_states` as a per-category list
  of booleans.
- Selecting another finding rebuilds the visible checkboxes from the
  stored state for that category.
- **Reset steps** clears only the currently selected category.
- A category with zero steps (for example, no finding is selected) hides
  the checkboxes and disables reset.
- Progress text is localized, for example:
  - `2/4 steps completed`
  - `已完成 2/4 步`

### Re-check flow

`FrameViewer` exposes a new signal:

```python
recheck_requested = Signal(str)
```

The button emits the target application name derived from the capture's
`Application` column. `LagLens.prepare_recheck()` then:

1. normalizes the target name;
2. fills the existing process combo;
3. switches to the existing Live Frames tab;
4. shows the localized `status.recheck_ready` message;
5. raises/activates the main window.

It deliberately does **not** call `start_capture()`, start telemetry, or
change PresentMon/QPC settings. The existing capture controls remain the
only way to start a new capture.

If a legacy CSV has no usable `Application` value, the re-check button
is disabled; the guide itself still works.

## 4. Localization

New keys live under:

```text
analysis.diagnostics.guide.*
status.recheck_ready
```

Both `locales/en.json` and `locales/zh_CN.json` contain the same keys.
Runtime language switching rebuilds the visible guide through the
existing `retranslate()` diagnostic refresh, preserving per-category
checkbox state.

## 5. Tests

Added or extended tests in:

- `tests/test_diagnostic_ui.py`:
  - guide steps are shown for the selected finding;
  - four steps, progress and enabled re-check button;
  - checkbox progress and reset;
  - per-category state persistence and selected-category reset;
  - `unknown` uses the data-quality guide;
  - all categories have 3–5 non-empty steps;
  - runtime EN/ZH guide localization;
  - re-check signal carries the capture target;
  - legacy capture without telemetry still offers the guide.
- `tests/test_capture.py`:
  - `prepare_recheck()` fills the target and switches to the Live tab
    without starting capture;
  - empty target is ignored;
  - the real main-window handler updates the process combo and status;
  - `show_analysis()` connects the viewer's re-check signal to the main
    window handler.

Full suite:

```text
Ran 444 tests in 14.380s

OK
```

## 6. Screenshots and scaling checks

Real Palworld QPC capture:

```text
Palworld-Win64-Shipping.exe_20261112_145654_215377.csv
615 frames, 9.86 s, 39 telemetry samples
```

Committed C-4 screenshots:

```text
captures/c4_troubleshooting_en.png
captures/c4_troubleshooting_zh.png
```

Both screenshots use the mixed CPU/GPU finding and show the four-step
guide with the first step checked and `1/4 steps completed`.

Additional validation artifacts under `<validation-data>`
checked the 980×760 minimum window with simulated
`QT_SCALE_FACTOR` 1.25 and 1.50 in English and Chinese. The guide and
checkbox text remained readable and scrollable. These are simulated
scaling checks, not physical 125%/150% monitor tests.

## 7. Limitations

- Guide completion is in memory only and is not saved between analysis
  windows or application restarts.
- Guides are general category advice, not per-finding dynamic plans.
- The re-check button only prefills the target and switches tabs; the
  user must start the capture manually.
- No automatic A/B comparison, network diagnostics, cloud sync or new
  diagnostic rules were added.
- Final interactive acceptance on physical monitors and the full
  C-4 review are still pending.
