# Phase UI Real-Game Regression Acceptance

Date: 2026-11-12
Game: Palworld / 幻兽帕鲁
Scope: real-game validation of the accepted Modern UI (UI-1/2/3)
before Phase C.
Result: **PASS for the tested core flows**

## User report

The user completed a real Palworld session with the new UI and a CSV
analysis:

- real PresentMon/ETW game capture completed and operated normally;
- CSV analysis operated normally;
- no obvious UI regression was observed.

This is recorded as the Phase UI real-game gate result. It is not a
full edge-case test matrix.

## Tested core flows (real game)

- LagLens could start a real Palworld capture and complete it normally.
- The Live page remained usable during the session; no obvious layout
  or interaction regression was reported.
- The saved CSV could be opened in the analysis window and analyzed
  normally.
- The new page hierarchy (capture/metric/chart cards, analysis sections)
  did not prevent the core capture-to-analysis workflow.

No frame count, duration or screenshot artifact was supplied with this
report, so those values are not claimed here.

## Not covered by this real-game run

The following are **not** claimed as real-hardware verified by this
regression:

- process-dialog Recommended/All/search/refresh edge cases;
- launcher/renderer suggestion and same-name collision warning;
- no-default-selection and Cancel behavior;
- target-control lock during the exact running-capture interval;
- stop-on-exit behavior;
- damaged CSV / zero-frame / permission-failure handling;
- missing NVML, non-NVIDIA GPU, hybrid GPU or multi-GPU behavior;
- `--no_track_gpu` (low-overhead) captures;
- success-path memory re-check in this run (it was validated in the
  earlier Phase B real Palworld run, but not re-run here);
- English/Chinese switching during this session;
- Hardware page and Settings page manual checks;
- 125%/150% physical display scaling and multi-monitor DPR switching;
- minimum-window 980x760 manual checks;
- VRR, tearing, multi-monitor presentation and unusual present modes.

Those areas retain automated-test evidence only where applicable and
must not be described as real-game validated.

## Evidence and test status

- Full automated suite at UI-3 close: **328 passing**.
- The suite was not rerun for this documentation-only acceptance.
- No functional code changed for this record.
- Prior acceptance records:
  - `docs/ACCEPTANCE_UI1.md`
  - `docs/ACCEPTANCE_UI2.md`
  - `docs/ACCEPTANCE_UI3.md`

## Gate decision

Phase UI is accepted for the tested core real-game workflow. Phase C
may start in design-only mode. No capture/analysis implementation may
change until the Phase C design is approved.
