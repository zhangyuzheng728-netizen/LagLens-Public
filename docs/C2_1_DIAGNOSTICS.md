# C-2.1: Evidence-Based Diagnostic Engine

Date: 2026-11-12
Status: accepted; C-2.2 reliability changes are documented in
`docs/C2_2_RELIABILITY.md`.
Scope: pure Python diagnostic rules over the selected frame chain,
existing FrameStats, QPC frame timebase, optional C-1 telemetry and
target FPS. No C-3 UI, no machine learning.

## 1. Summary

- Added `diagnostics.py`: a pure-Python rule engine with structured
  `Finding` output, evidence, caveats, confidence, claim level and time
  windows.
- Rules cover CPU-side pressure, GPU-side pressure, mixed/ambiguous
  pressure, local stutter associations, memory-pressure association,
  presentation/display observations and insufficient evidence.
- PresentMon field semantics were checked against the official
  PresentMon console documentation and source rather than inferred from
  column names.
- Local stutter analysis uses a preceding local baseline (median/MAD),
  not only one global threshold.
- Frame-to-telemetry correlation is allowed only with a verified QPC
  capture-start timebase and a complete sidecar.
- NVML device utilization is never treated as target-process GPU usage.
- `likely` requires repeated local support plus a global pattern and no
  contradictory opposite-side signal. `confirmed_by_control` requires
  valid caller-supplied A/B evidence; no control means it can never be
  emitted.
- Real Palworld QPC and legacy CSVs were analysed. All causes remain
  observational; no real-game cause is marked confirmed.
- Full suite: **409 tests in 14.065 s, OK**.

## 2. Inputs and output

### Inputs

```text
frames              selected frames from frame_viewer.load_frames()
stats               existing frame_stats.FrameStats (optional)
telemetry           telemetry.TelemetryReadResult (optional)
target_fps          existing setting (default 60)
config              DiagnosticConfig thresholds (optional)
control_experiments optional ControlExperiment A/B metadata
```

`frames` carry the normalized `time`, `duration`, raw CSV `row`, and
C-2.0 timebase keys (`timebase_kind`, `sync_quality`,
`absolute_mapping_trusted`). The engine never mutates them.

### Output

`DiagnosticReport` contains:

- `findings`: tuple of structured `Finding` objects;
- frame count and duration;
- target FPS and frame budget;
- timebase description;
- whether telemetry was aligned;
- local event count;
- rejected control experiments.

Each `Finding` has:

```text
code, category, severity, confidence, claim_level
window_start_ms, window_end_ms
summary
evidence[]
caveats[]
metrics{}
```

Categories currently used: `cpu`, `gpu`, `mixed`, `memory`,
`presentation`, `data_quality`, `unknown`.

## 3. PresentMon field semantics verification

Official PresentMon console documentation describes the relevant v2
metrics as:

| Column (v2 CSV) | Official meaning |
|---|---|
| `CPUBusy` (`MsCPUBusy`) | CPU time spent working on this frame before presenting it |
| `CPUWait` (`MsCPUWait`) | CPU time spent waiting before starting the next frame |
| `GPULatency` (`MsGPULatency`) | Time from this frame's start until the GPU started working on it |
| `GPUTime` (`MsGPUTime`) | Total time the GPU was working on this frame |
| `GPUBusy` (`MsGPUBusy`) | Time at least one GPU engine was executing work from the target process |
| `GPUWait` (`MsGPUWait`) | Time the GPU was idle while working on this frame |
| `DisplayLatency` | Time from frame start until the frame was displayed |
| `DisplayedTime` | How long the frame was displayed, or `NA` if it was not displayed |

The PresentMon v2 CSV writer source also confirms two important
identities:

```text
FrameTime = CPUBusy + CPUWait
GPUTime   = GPUBusy + GPUWait
```

Consequences used by the rules:

- `CPUBusy / FrameTime` is normally near 1 **by construction** because
  `FrameTime` is the sum of CPU busy and CPU wait. It is not, by itself,
  a CPU-bound discriminator.
- `CPUWait / FrameTime` is the useful CPU-side waiting signal. High
  values mean the CPU is waiting for another stage; low values mean it
  is continuously busy.
- `GPUBusy / GPUTime` is the GPU active fraction; `GPUWait / GPUTime`
  is the idle fraction. Both are used together.
- `DisplayedTime = NA` means the frame was not displayed. It does not
  identify the cause.
- `--no_track_gpu` removes `GPULatency`, `GPUTime`, `GPUBusy` and
  `GPUWait`; GPU diagnosis must be disabled rather than guessed.
- PresentMon documents that GPU execution metrics are less accurate
  when Hardware-Accelerated GPU Scheduling (HGS/HAGS) is enabled; this
  remains a caveat, not a hidden assumption.

NVIDIA device utilization from NVML is not the same as
`GPUBusy` and is not attributed to the target process. It is not used
as process GPU usage evidence.

## 4. Rule set

Thresholds live in `DiagnosticConfig`. They are initial, testable
hypotheses and can be recalibrated without changing the rule shape.

### 4.1 Global CPU-side candidate

Requires:

- enough valid `CPUBusy`/`CPUWait` frames;
- frame pressure relative to `1000 / target_fps`;
- median `CPUWait / FrameTime` low;
- median `CPUBusy` exceeds median `GPUBusy` by a dynamic margin, or GPU
  fields are unavailable.

It is an `observed_association` candidate. If GPU fields are missing,
confidence is low and a caveat says a GPU explanation cannot be
excluded.

### 4.2 Global GPU-side candidate

Requires:

- enough valid GPU frame fields;
- frame pressure;
- median `GPUBusy / GPUTime` high;
- median `GPUWait / GPUTime` low;
- `GPUBusy` exceeds `CPUBusy` by a dynamic margin, or CPU wait is high.

If CPU fields are missing, confidence is low and a CPU explanation
cannot be excluded. NVML device utilization is not used.

### 4.3 Mixed/ambiguous pressure

If both CPU busy and GPU active fractions are high, their busy times are
within the dynamic margin, and neither side clearly dominates, the
engine emits `mixed_frame_pressure` rather than forcing one cause.
Multiple candidate explanations remain valid.

### 4.4 Local stutter analysis

A local stutter candidate is a frame whose duration exceeds:

```text
max(local_median * 2,
    local_median + 3 * 1.4826 * local_MAD,
    local_floor_ms)
```

where `local_median`/`MAD` come from the preceding 5 seconds, excluding
the immediately preceding 500 ms. This is deliberately local and does
not rely only on the global 50 ms/2x stutter threshold.

C-2.2 additionally merges events whose context windows overlap
(1,500 ms with the default 500 ms before + 1,000 ms after window), so
overlapping events cannot be counted as independent support for
`likely`.

For each local event, the engine compares the event frame with the
preceding local baseline:

- CPU association: elevated `CPUBusy` versus baseline, low event
  `CPUWait`, and CPU increase larger than GPU increase.
- GPU association: elevated `GPUBusy` versus baseline, high event GPU
  active fraction, low event GPU wait, and GPU increase larger than CPU
  increase.
- Presentation observation: displayed-fraction drop or display-latency
  increase, only when CPU/GPU associations are absent.
- Memory association: only with a verified QPC timebase and complete
  sidecar; high system RAM plus target working-set growth in the event
  window versus its local baseline.
- Otherwise: `local_stutter_unclassified` with
  `claim_level=insufficient_evidence`.

Long frame holes can be caused by ETW loss, loading, or work outside the
process; they are not silently converted into a cause.

### 4.5 Memory pressure

Memory findings require:

- a verified QPC capture-start timebase;
- a complete C-1 sidecar with enough samples;
- high system RAM;
- target working-set growth.

This is an `observed_association` only. System RAM is not per-process
pressure, working-set growth can be normal caching, and device-wide
VRAM/NVML data is not attributed to the target process.

### 4.6 Presentation/display observation

If `DisplayedTime` exists and fewer than 98% of frames were displayed,
the engine emits `displayed_frames_missing`. A local displayed-fraction
drop or display-latency jump can produce a local presentation
association. `DisplayedTime=NA` is an observation, not a cause.

### 4.7 Data quality and insufficient evidence

The report explicitly marks:

- missing CPU fields;
- missing GPU fields (for example `--no_track_gpu`);
- missing display fields;
- missing telemetry sidecar;
- telemetry existing but timebase untrusted;
- too few telemetry samples;
- target CPU samples that are all `0.0`;
- too few frames;
- no rule meeting its evidence threshold.

When a timebase is legacy, inferred or untrusted, no frame-to-hardware
temporal association is produced, even if a sidecar exists.

## 5. Confidence and claim levels

### `observed_association`

Default for all rules. It means the evidence is temporally and
quantitatively associated, not that it caused the frame time.

### `likely`

Only when:

- a global candidate exists;
- at least two local stutter windows support the same side;
- the opposite-side fields are available and show no contradictory
  global/local association;
- relevant frame fields are present.

Even then, the finding carries a caveat that a controlled A/B is still
needed.

### `confirmed_by_control`

Only when the caller supplies a valid `ControlExperiment` matching the
finding code or category. C-2.2 tightened the requirements:

- non-empty target and changed factor;
- two different capture identifiers;
- identical, non-empty baseline/treatment scenario identifiers;
- non-empty baseline/treatment settings, with exactly one changed
  setting and a factor that matches that setting key;
- baseline/treatment durations at least 30 s and within 20% of each
  other;
- at least 300 frames in each capture;
- a recognized metric (`average_fps`, `one_percent_low_fps`,
  `p95_frame_ms`, `p99_frame_ms`, `stutter_percent`,
  `stutter_total_ms`);
- finite baseline/treatment values;
- a relative improvement of at least 20% by default.

Invalid experiments are rejected and listed in
`report.control_rejections`; they never upgrade a finding. The engine
does not re-analyse the A/B captures; it trusts only the structured
metadata and records that limitation.

There is no path to `confirmed_by_control` without a valid experiment.
C-3 keeps `allow_confirmed_by_control=False` by default, so normal UI
and report callers cannot obtain a controlled claim from metadata
alone. No real Palworld cause is marked confirmed by C-2.1.

## 6. Real Palworld validation

### 6.1 QPC capture

Input: real QPC `Palworld-Win64-Shipping.exe` capture with a complete
C-1 sidecar, 615 frames, `verified_qpc`, target 60 FPS.

Report:

| Finding | Category | Claim | Confidence |
|---|---|---|---|
| `target_cpu_unusable` | data_quality | `insufficient_evidence` | low |
| `mixed_frame_pressure` | mixed | `observed_association` | low |
| `local_stutter_cpu_association` | cpu | `observed_association` | low |

The mixed finding reports median `CPUBusy` 15.65 ms and `GPUBusy`
15.49 ms, within the 1.50 ms discrimination margin. The local event at
8,956.4 ms lasts 42.57 ms against a 15.55 ms local median and a 31.10 ms
local threshold. At the event frame, `CPUBusy` is 42.39 ms versus a
15.50 ms baseline median; `GPUBusy` is 18.98 ms versus 15.39 ms;
`CPUWait/FrameTime` is 0.0042.

This is recorded as an observed CPU-side association for one local
stutter, **not** as a confirmed cause. The global picture is explicitly
mixed.

The sidecar's target CPU samples were all `0.0` in this historical run.
The engine detected this and emitted `target_cpu_unusable`; target CPU
was not used as evidence. C-2.2 subsequently fixed the C-1 sampler
lifecycle issue; see `docs/C2_2_RELIABILITY.md`. This was not a C-2.1
finding about the game.

### 6.2 Legacy capture

Input: existing real Palworld `CPUStartTime` capture, 11,385 frames, no
sidecar, target 60 FPS.

Result:

- 12 local events;
- 6 observed CPU-side associations;
- 1 observed GPU-side association;
- 5 unclassified events;
- 1 `displayed_frames_missing` observation (14.4% `DisplayedTime=NA`);
- 1 `telemetry_unavailable` data-quality finding.

No telemetry/window correlation is claimed. No finding is `likely` or
`confirmed_by_control`; the long frame holes are not assigned a unique
cause. This demonstrates the intended degradation path for legacy
captures.

## 7. Evidence example

A typical structured finding:

```json
{
  "code": "local_stutter_cpu_association",
  "category": "cpu",
  "severity": "warning",
  "confidence": "low",
  "claim_level": "observed_association",
  "window_start_ms": 8456.37,
  "window_end_ms": 9956.37,
  "summary": "CPU busy work rose more than GPU work during this local stutter.",
  "evidence": [
    "Local stutter at 8956.4 ms lasts 42.57 ms; preceding local median 15.55 ms, local threshold 31.10 ms.",
    "Target 60 FPS gives a 16.67 ms frame budget; mean 16.04 ms, P95 20.06 ms, 1% low 36.07 FPS.",
    "Event frame CPUBusy 42.39 ms vs baseline median 15.50 ms; event frame GPUBusy 18.98 ms vs baseline median 15.39 ms.",
    "CPUBusy increase 26.88 ms; GPUBusy increase 3.59 ms.",
    "Event frame CPUWait/FrameTime 0.0042."
  ],
  "caveats": [
    "Findings are observational associations, not proof of causality.",
    "PresentMon v2 FrameTime is CPUBusy + CPUWait, so CPUBusy/FrameTime alone is not a CPU-bound discriminator.",
    "GPUBusy is target-process GPU-engine activity, not device-wide GPU utilization.",
    "4 Hz telemetry is window context, not a per-frame measurement."
  ]
}
```

## 8. Tests

New file: `tests/test_diagnostics.py` (22 tests).

Coverage:

- synthetic CPU-bound global + repeated local events → `likely`;
- synthetic GPU-bound global + repeated local events → `likely`;
- mixed pressure retains multiple candidates;
- local baseline catches a short spike that a global floor would miss;
- high CPU wait prevents a CPU candidate;
- local stutter without a matching signal → unclassified/insufficient;
- memory association requires aligned QPC;
- legacy/untrusted timebase disables hardware association;
- NVML GPU utilization alone does not produce a GPU finding;
- missing GPU fields disable GPU diagnosis and prevent `likely`;
- target CPU all-zero is reported as unusable;
- displayed frames missing is an observation, not a cause;
- too few frames returns insufficient evidence;
- missing timebase degrades correctly;
- valid control A/B confirms matching CPU findings only when the
  explicit `allow_confirmed_by_control` opt-in is enabled;
- the default engine rejects control confirmation for safety;
- invalid control (same captures, insufficient improvement) does not
  confirm;
- wrong control target does not confirm CPU;
- CPU + memory candidates can coexist;
- report/finding JSON serialization;
- FPS validation;
- compatibility with existing `FrameStats`.

Full suite:

```text
Ran 409 tests in 14.065s

OK
```

## 9. Known false positives and limits

- The rules are heuristic and calibrated with synthetic fixtures plus
  one QPC and one legacy real capture, not a labeled real-game corpus.
- Local stutters can be caused by ETW loss, loading, external processes
  or work outside the captured chain; unclassified is the correct
  outcome rather than a forced cause.
- 4 Hz telemetry is context only. It cannot establish per-frame CPU/GPU
  values or prove that a sample caused a frame.
- NVML device utilization and VRAM association are unknown for the
  target process; they are not used as target-process GPU or VRAM
  evidence.
- `DisplayedTime=NA` says the frame was not displayed; it does not
  identify why.
- `GPUBusy`/`GPUWait` accuracy can be reduced by Hardware-Accelerated
  GPU Scheduling.
- The historical C-1 sidecar used for C-2.1 validation had all-zero
  target CPU samples. C-2.1 detects and excludes them; C-2.2 later fixed
  the C-1 process-object lifecycle so new captures provide usable target
  CPU percentages.
- `likely` is not a causal proof. `confirmed_by_control` depends on
  valid caller-supplied A/B metadata and is not produced by the real
  validation runs.
- C-2.2 reliability work is documented separately; no C-3 UI was
  added.
