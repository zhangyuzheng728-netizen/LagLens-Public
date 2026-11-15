# Phase C Design: Evidence-Based Performance Diagnostics

Date: 2026-11-12
Status: design approved; C-1, C-1.1, C-2.0, C-2.1 and C-2.2 accepted;
C-3 diagnostic UI and reports implemented, awaiting review. Packaging
and release are out of scope.
Scope: C-1 telemetry foundation, C-2 diagnostic engine, C-3
explanations/reference ranges/target FPS and diagnostic UI.
See `docs/C1_IMPLEMENTATION.md`, `docs/C1_TIMEBASE_VALIDATION.md`,
`docs/C2_0_QPC_INTEGRATION.md`, `docs/C2_1_DIAGNOSTICS.md`,
`docs/C2_2_RELIABILITY.md` and `docs/C3_IMPLEMENTATION.md`.

## 1. Executive summary

LagLens currently measures frame time well, but it does not yet explain
why frame time changes. Phase C should turn the tool into an
evidence-based CPU/GPU/RAM/VRAM bottleneck and stutter diagnostic tool.

Recommended direction:

1. **C-1 — telemetry foundation**: add a timestamped hardware sidecar
   next to each capture, synchronize it to the PresentMon timebase, and
   explicitly record data quality and missing metrics.
2. **C-2 — diagnostic engine**: classify CPU-bound, GPU-bound,
   presentation/display-limited, memory-pressure and unknown/insufficient
   scenarios using frame-level PresentMon fields first and hardware
   samples as context, with confidence and evidence.
3. **C-3 — explanations and UI**: metric explanations, reference ranges,
   target FPS, evidence panels, stutter details and exported reports.

Core principle: **frame-level PresentMon data is primary evidence;
hardware samples are context; correlation is not causation.** Findings
must say what was observed, what is inferred, and what is not proven.

## 2. Current-state audit

### 2.1 PresentMon CSV fields

A real Palworld 2.6 capture in this repository has 21 columns:

```text
Application,ProcessID,SwapChainAddress,PresentRuntime,
SyncInterval,PresentFlags,AllowsTearing,PresentMode,
CPUStartTime,FrameTime,CPUBusy,CPUWait,GPULatency,GPUTime,
GPUBusy,GPUWait,DisplayLatency,DisplayedTime,
AnimationError,AnimationTime,MsFlipDelay
```

The unit-test header also includes optional
`AllInputToPhotonLatency` and `ClickToPhotonLatency`; these were not
present in the real 2.6 capture. New analysis code must treat optional
columns as optional.

| Field | Observed unit | Availability | Current use |
|---|---|---|---|
| Application | name | required | chain identity |
| ProcessID | integer | required | chain identity; transient path memory |
| SwapChainAddress | address | required | chain grouping |
| PresentRuntime | string | present | not used |
| SyncInterval | integer | present | not used |
| PresentFlags | integer | present | not used |
| AllowsTearing | 0/1 | present | not used |
| PresentMode | string | present | not used |
| CPUStartTime | milliseconds | required | frame timebase |
| FrameTime | milliseconds | required | statistics |
| CPUBusy | milliseconds | present | raw detail only |
| CPUWait | milliseconds | present | not shown |
| GPULatency | milliseconds | present | not used |
| GPUTime | milliseconds | present | not used |
| GPUBusy | milliseconds | present unless GPU tracking off | raw detail only |
| GPUWait | milliseconds | present unless GPU tracking off | raw detail only |
| DisplayLatency | milliseconds | present/NA | not used |
| DisplayedTime | milliseconds | present/NA | displayed/no-display flag |
| AnimationError | milliseconds | present/NA; can be negative | not used |
| AnimationTime | milliseconds | present/NA | not used |
| MsFlipDelay | milliseconds | present/NA | not used |
| AllInputToPhotonLatency | ms | absent in real 2.6 capture | not used |
| ClickToPhotonLatency | ms | absent in real 2.6 capture | not used |

Important observations from real CSVs:

- `CPUStartTime` is a capture-relative millisecond timebase. In the
  real Palworld captures the first/last values span the capture duration
  (for example one 11,385-frame capture runs from 5,924.8 ms to
  167,354.8 ms; another 34,484-frame capture runs from 15.3 ms to
  396,733.9 ms). The first frame can be delayed while PresentMon waits
  for the target or first present.
- `FrameTime` is a CPU frame interval, not confirmed display FPS. The
  existing UI disclaimer is correct.
- `DisplayedTime` and `DisplayLatency` can be `NA`; do not require them.
- `GPUBusy`/`GPUWait` are present in the real Palworld CSV, but
  `--no_track_gpu` deliberately removes GPU tracking in low-overhead
  mode. Diagnostics must degrade gracefully.
- `ProcessID` and `SwapChainAddress` can represent multiple processes or
  recreated chains. Existing swap-chain selection remains the frame
  source.
- The exact semantics of `GPUBusy`, `GPUWait` and presentation fields
  must be validated against the PresentMon 2.6 documentation and
  controlled captures; they must not be interpreted from names alone.

### 2.2 Current hardware data

| Metric | Source | Rate | Scope | Timestamp stored | Current UI |
|---|---|---:|---|---|---|
| CPU % | `psutil.cpu_percent(interval=None)` | 1000 ms GUI timer | system-wide | none | current card |
| RAM % | `psutil.virtual_memory()` | 1000 ms | system-wide | none | current card |
| GPU util % | NVML `nvmlDeviceGetUtilizationRates` | 1000 ms | GPU 0 only | none | card + 60-value chart |
| VRAM used/total | NVML `nvmlDeviceGetMemoryInfo` | 1000 ms | GPU 0 only | none | current card/status |
| GPU temp | NVML | 1000 ms | GPU 0 only | none | current card |
| CPU per-core/clock | none | — | — | — | — |
| Process CPU | none | — | — | — | — |
| Process working set | none | — | — | — | — |
| Process GPU/VRAM | none | — | — | — | — |

Current characteristics:

- `update_hardware()` runs on a QTimer in the GUI thread every 1000 ms;
  the capture worker runs independently. UI work, dialogs or timer
  jitter can delay samples.
- The GPU chart stores only values in a deque and plots by sample index,
  not by timestamp. It cannot be aligned to the frame timeline.
- CPU and RAM have no history; only the GPU has a 60-sample chart.
- NVML is initialized once for GPU index 0. There is no multi-GPU
  selection or AMD/Intel fallback.
- There is no per-process CPU/RAM/GPU attribution.
- On NVML errors, the status changes to an error but previous GPU card
  values may remain visible until the next successful update.
- The existing `target_fps` setting is present in `settings.py` but is
  not used by the UI or analysis yet.
- The analysis window shows raw `CPUBusy`, `GPUBusy` and `GPUWait`
  strings; there is no interpretation, confidence or evidence model.

### 2.3 Audit findings

| Priority | Finding | Impact |
|---|---|---|
| P0 | Hardware samples have no timestamps and are not aligned to PresentMon frame time | Cannot make defensible frame/stutter correlations |
| P0 | 1 Hz hardware sampling in the GUI thread | Misses short events; jitter makes alignment worse |
| P0 | No per-process or per-GPU context; only system-wide NVML/psutil | Bottleneck attribution can be misleading |
| P1 | Missing metrics are implicit (`NA`, missing GPU tracking, NVML failure) | Risk of false confidence |
| P1 | Field semantics for GPU/presentation metrics are not validated | Rule engine could overclaim |
| P1 | No explicit correlation/causation policy | Users may treat association as cause |
| P1 | No data-quality model or sidecar | Reports cannot be audited or reproduced |
| P2 | GPU index fixed to 0; no multi-GPU | Hybrid/multi-GPU machines unsupported |
| P2 | Target FPS exists but is unused | Reference ranges/targets cannot be evaluated |

## 3. Goals and non-goals

### Goals

- Record enough timestamped telemetry to explain frame-time changes.
- Identify likely CPU/GPU/presentation/memory bottlenecks with evidence.
- Explain stutter events and provide ranges, not just raw numbers.
- Support target FPS and frame-time budgets.
- Degrade explicitly when evidence is missing.
- Keep every finding reproducible and auditable.
- Preserve existing capture, frame-statistics and swap-chain behavior.

### Non-goals for the first Phase C implementation

- No kernel driver, overclocking or hardware control.
- No per-process GPU attribution through undocumented APIs.
- No ML classifier before labeled data exists.
- No automatic “confirmed cause” claims without user-controlled
  experiments.
- No change to PresentMon command semantics unless a separate proposal
  is approved.
- No new runtime dependency without explicit approval.

## 4. Technical architecture

```text
Capture session
  ├─ PresentMon 2.6 ──> CSV (frame timeline, CPU/GPU/presentation fields)
  ├─ metadata.json ───> start/end clocks, flags, hardware identity
  └─ hardware sampler ─> telemetry.jsonl (timestamped samples)
                │
                ▼
Diagnostic engine (pure Python)
  ├─ frame classification / stutter events
  ├─ telemetry window association
  ├─ evidence + confidence + claim level
  └─ report/findings
                │
                ▼
Analysis UI (C-3)
  ├─ diagnostic summary
  ├─ metric explanations/reference ranges
  ├─ stutter evidence and timeline
  └─ target FPS / export
```

Recommended modules:

| Module | Responsibility |
|---|---|
| `telemetry_schema.py` | Versioned `CaptureMetadata`, `HardwareSample`, `DataQuality`, `Finding` dataclasses and JSON serialization. |
| `hardware_sampler.py` | Headless sampler thread using psutil/NVML; monotonic timestamps; explicit missing values; sidecar writer. |
| `diagnostics.py` | Pure analysis of frames + stats + telemetry; no Qt and no capture I/O. |
| `frame_stats.py` | Existing statistics remain; diagnostics consumes them without changing definitions. |
| `frame_viewer.py` | C-3 presentation only; no capture logic. |
| `main.py` | Start/stop sampler with capture; UI integration later. |

C-1 should not change `capture_core.py` command construction or CSV
validation unless a separate, reviewed need appears.

## 5. Time synchronization design

### 5.1 Clocks

Record both clocks at capture start and end:

- `started_monotonic_ns = time.perf_counter_ns()` for intervals;
- `started_wall_ns = time.time_ns()` for human-readable metadata only.

Every hardware sample records `t_monotonic_ms` relative to the capture
start marker. Do not use wall-clock deltas for analysis; wall clock can
jump due to NTP or manual changes.

### 5.2 PresentMon timebase

The real CSVs show `CPUStartTime` behaving as a capture-relative
millisecond timer, with the first frame possibly delayed. C-1 should
record:

- `capture_started_monotonic_ns` before starting PresentMon;
- `presentmon_started_monotonic_ns` when the process is actually
  created;
- `first_csv_row_monotonic_ns` when the first valid CSV row is read;
- `first_frame_cpu_start_ms` from that row.

The initial analysis mapping should use:

```text
frame_t_capture_ms  = CPUStartTime
sample_t_capture_ms = monotonic_ms - capture_started_monotonic_ns
```

Then validate the offset between PresentMon start and the first row in
controlled tests. If PresentMon's zero is actually its own start rather
than the LagLens marker, apply the measured `presentmon_started -
capture_started` offset. This must be a documented calibration, not an
assumption.

### 5.3 Alignment policy

- Use nearest sample within a configured tolerance for context only.
- Never interpolate missing hardware values into fabricated samples.
- Do not claim frame-level causation from a 250 ms hardware sample.
- Report a data-quality warning if the frame timebase and sample
  timebase cannot be aligned within tolerance.
- Keep the raw sample timestamps for audit.

## 6. Hardware sampling design

### Recommended first version

| Metric | Source | Suggested rate | Scope |
|---|---|---:|---|
| CPU system % | psutil | 4 Hz | all cores |
| CPU per-core % | psutil | 4 Hz | per logical core |
| RAM used/total/percent | psutil | 4 Hz | system |
| Target CPU % | psutil.Process | 4 Hz | selected target PID(s) |
| Target working set | psutil.Process | 4 Hz | selected target PID(s) |
| GPU util % | NVML | 4 Hz | selected GPU |
| VRAM used/total | NVML | 4 Hz | selected GPU |
| GPU temp | NVML | 4 Hz | selected GPU |
| GPU clocks/throttle reason | NVML if available | 1 Hz | selected GPU |
| Process GPU/VRAM | not available via stable NVML graphics API | — | not claimed |

4 Hz (250 ms) is a starting recommendation. Frame-level PresentMon
fields remain the primary evidence for sub-second stutters; hardware
samples provide surrounding context. 1 Hz is too coarse; 10 Hz is
possible but adds overhead and data volume without clear benefit for
the first version.

### Threading and overhead

- Use a dedicated sampler thread started outside the PresentMon
  `QThread`, or a dedicated QThread with a timer. Do not add a helper
  Python thread inside `CaptureWorker.run()`; the repository already
  documents a deadlock risk there.
- One sampler owns NVML access during capture; the UI should read a
  latest-snapshot cache rather than calling NVML concurrently.
- Prime `psutil.cpu_percent(interval=None)` before the first real
  sample to avoid a misleading zero.
- Use `threading.Event.wait(interval)` for cadence and stop promptly.
- Budget: target well under 1% CPU overhead; measure before/after on
  the Palworld test.
- If the target process is gone, keep system-wide samples but mark
  target-specific fields unavailable.

### Missing data and quality

Every sample and report should distinguish:

- `unavailable`: NVML missing, permissions, unsupported GPU;
- `disabled`: `--no_track_gpu` or GPU tracking intentionally off;
- `not_applicable`: field is `NA` in PresentMon;
- `stale`: last successful sample is older than tolerance;
- `partial`: some fields missing.

No interpolation. Diagnostics must be allowed to return
“insufficient evidence” rather than inventing a cause.

## 7. Telemetry storage format

Recommended:

- `<capture>.telemetry.jsonl` next to the CSV;
- first record: metadata with schema version;
- subsequent records: samples;
- final record: end marker and quality summary;
- UTF-8, one JSON object per line, flush periodically;
- atomic/partial recovery: an incomplete sidecar is marked incomplete,
  never silently treated as complete;
- never write to C:; use the capture directory on D:/E:.

Alternative: two files (`*.meta.json` + `*.samples.jsonl`). The single
JSONL is recommended because it survives crash truncation and keeps
ordering.

## 8. Diagnostic engine design (C-2)

### Inputs

- selected frames from `swap_chains.recommend()`;
- `FrameStats` from `frame_stats.compute_stats()`;
- telemetry metadata and samples;
- target FPS/reference configuration;
- optional user-controlled experiment metadata.

### Findings model

```text
Finding:
  code            stable identifier
  category        cpu | gpu | presentation | memory | data_quality
  window_ms       start/end in capture time
  severity        info | warning | critical
  confidence      low | medium | high
  claim_level     observed_association | likely | confirmed_by_control
  evidence        frame fields, stats, samples and comparison window
  caveats         missing data / alternative explanation
```

### Initial rule set (to be calibrated)

- **CPU-bound candidate**: high `CPUBusy / FrameTime`, system CPU
  saturation, target CPU high, GPU not saturated; repeated across the
  window.
- **GPU-bound candidate**: high `GPUBusy / FrameTime` or high
  `GPUWait`, GPU utilization high, VRAM pressure; CPU not saturated.
- **Presentation/display-limited candidate**: frame time normal while
  `DisplayedTime`/`DisplayLatency` or presentation mode indicates a
  display-path issue.
- **Memory-pressure association**: RAM/VRAM near capacity and a
  temporally adjacent spike; association only unless a controlled test
  supports more.
- **Unknown/insufficient**: missing fields, no telemetry, sidecar
  missing, alignment failure, mixed chains or contradictory evidence.

Thresholds are initial hypotheses, not final truths. They must be
calibrated against real Palworld captures and synthetic fixtures, and
displayed with the finding so users can understand the rule.

### Stutter analysis

For each stutter from `FrameStats`:

1. take a window before/after the event (for example -1 s to +1 s);
2. compare with a local baseline (for example the preceding 5 s);
3. aggregate frame-level ratios and hardware context;
4. attach only evidence that is temporally present;
5. mark confidence based on data completeness, repeatability and
   alignment.

Do not call a spike “GPU-caused” merely because GPU utilization was high
at the nearest sample.

### Correlation vs causation policy

- Default claim level is `observed_association`.
- `likely` requires repeated temporal precedent and multiple
  independent signals.
- `confirmed_by_control` requires a user-run controlled A/B change
  (for example resolution, frame cap, graphics preset) with comparable
  captures.
- Never show a single number as a definitive cause.
- Report alternative explanations and missing evidence.

### Reference ranges and target FPS

- Use the existing `settings.target_fps` (default 60, configurable).
- Frame budget = `1000 / target_fps` ms.
- Report average FPS, 1% Low, P95/P99, stutter percentage and long
  frames relative to the target.
- GPU/CPU utilization are context, not pass/fail scores.
- VRAM/RAM headroom should be shown with clear thresholds and caveats.
- Reference ranges should be labelled “general guidance”, not
  game-specific guarantees.

## 9. C-1 / C-2 / C-3 implementation plan

### C-1 — telemetry and timebase foundation

Deliverables:

- `telemetry_schema.py` and JSONL sidecar;
- `hardware_sampler.py` with 4 Hz sampling and explicit missing values;
- capture start/end markers and metadata;
- sampler lifecycle integration with Start/Stop, without changing
  PresentMon commands;
- data-quality flags and crash recovery;
- tests for time mapping, missing fields, permissions, sampler stop,
  overhead.

Acceptance:

- a real Palworld capture produces a sidecar with timestamps;
- alignment error is measured and documented;
- no capture behavior/regression; 328 tests still green;
- no frame-rate impact beyond the agreed overhead budget;
- no C: writes.

### C-2 — diagnostic engine

Deliverables:

- pure `diagnostics.py` and report dataclasses;
- frame/stutter classification rules with confidence and claim levels;
- evidence windows and data-quality handling;
- reference ranges and target FPS calculations;
- golden synthetic fixtures for CPU/GPU/presentation/memory/unknown.

Acceptance:

- synthetic scenarios classify correctly without false certainty;
- missing GPU/telemetry cases return insufficient evidence;
- rule thresholds and evidence are documented;
- no capture or frame-statistics changes;
- full tests green.

### C-3 — explanations, reference ranges and UI

Deliverables:

- analysis-window diagnostic summary, evidence panel, stutter list and
  optional timeline overlay;
- metric explanations/tooltips, reference ranges, target FPS UI;
- confidence/claim labels and “insufficient data” states;
- EN/ZH localization, UI tokens and screenshots;
- export/report option if approved;
- real Palworld controlled A/B validation.

Acceptance:

- user can see why a bottleneck/stutter is reported and what is missing;
- no definitive causal claim without evidence;
- UI remains readable at supported scaling sizes;
- screenshots and tests pass;
- real game A/B validates at least one CPU/GPU scenario.

## 10. Alternatives and trade-offs

### Data sources

| Option | Pros | Cons | Recommendation |
|---|---|---|---|
| PresentMon fields only | no new sampler; frame-level | no RAM/VRAM/system history; limited context | fallback only |
| PresentMon + NVML/psutil | existing deps; low overhead; timestamped sidecar | system-wide GPU/VRAM; no per-process GPU | **C-1 recommendation** |
| + Windows PDH GPU Engine counters | per-process GPU engine possible | complex, permissions, overhead, semantics | evaluate after C-2 |
| Vendor SDKs (NVML per-process, ADL, Intel) | richer GPU data | vendor-specific, unstable, new dependencies | defer |

### Sampling rate

- 1 Hz: current; too coarse for short stutters.
- 4 Hz: recommended default; good context, low overhead.
- 10 Hz: more resolution, more data/overhead; optional later.
- Frame-boundary sampling: intrusive to capture; reject.

### Diagnostics

- Rule-based: explainable, testable, no training data; recommended C-2.
- Statistical correlation: useful as a secondary signal; risk of false
  positives.
- ML classifier: needs labeled real-game data; not explainable enough
  for the first version; defer.

### Causation

- Observational only: safe, but user may over-interpret.
- Guided A/B: stronger evidence, requires user effort; recommended as
  an optional C-2/C-3 path.
- Automatic experiments: too invasive for first version.

### Sidecar

- JSONL: streaming, crash-tolerant, easy to inspect; recommended.
- CSV: simple but schema evolution and nested data are awkward.
- SQLite: queryable but heavier, concurrent file concerns.

## 11. Risks and mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| PresentMon timebase mismatch with sampler | Medium | High | capture markers, calibration tests, quality warning |
| GPU/VRAM per-process attribution unavailable | High | Medium | be explicit; use frame-level GPU fields; do not fake attribution |
| NVML missing/permission/multi-GPU | Medium | High | `unavailable` state, fallback to frame-only, no false confidence |
| `--no_track_gpu` removes GPU evidence | Medium | Medium | detect flag, report disabled evidence |
| Sampler overhead/jitter | Medium | Medium | 4 Hz thread, fast calls, measure overhead, no GUI blocking |
| Missing/NA fields | High | High | explicit quality model; no interpolation; insufficient-evidence state |
| GPU/presentation field semantics unclear | High | High | validate against docs and controlled captures before rules |
| Correlation reported as cause | Medium | High | claim levels, caveats, controlled A/B only for confirmation |
| False positives/negatives | Medium | High | fixture suite, thresholds configurable, confidence labels |
| Sidecar corruption/crash | Medium | Medium | JSONL + end marker, partial recovery, never silently complete |
| Multi-process/mixed chains | Medium | High | reuse existing chain selection; scope findings to selected chain |
| Data volume/privacy | Low | Medium | bounded sample rate; no C:; document storage |
| UI complexity | Medium | Medium | C-3 uses accepted design system; progressive disclosure |
| Regression risk | Medium | High | no changes to capture/statistics; 328 tests; feature flags |

## 12. Test strategy

### C-1

- fake clocks and sampler loops;
- synthetic NVML/psutil providers;
- missing/permission/unsupported cases;
- JSONL schema/round-trip/partial sidecar;
- time alignment with first-frame delay;
- sampler stop/join and no dangling threads;
- overhead measurement on a real capture.

### C-2

- synthetic frame fixtures:
  - CPU-bound, GPU-bound, presentation-limited, VRAM pressure,
    RAM pressure, mixed, unknown;
- telemetry windows offset by known amounts;
- missing sidecar/fields/GPU tracking;
- thresholds and confidence boundaries;
- claim-level policy (no confirmed without control);
- no mutation of frame data/stats.

### C-3

- UI tests with synthetic reports;
- EN/ZH, reference ranges, target FPS, evidence labels;
- missing-data states;
- screenshots at 100/125/150 and minimum window;
- real Palworld A/B:
  - CPU-heavy vs GPU-heavy setting change;
  - VRAM pressure;
  - missing GPU tracking;
  - capture + analysis + report.

### Regression

- Existing 328 tests must remain green at every sub-phase.
- No changes to `capture_core` command construction or CSV validation
  unless separately approved.
- No changes to swap-chain selection or frame-statistics definitions.

## 13. Acceptance criteria

### C-1

- timestamped telemetry sidecar for a real capture;
- alignment documented and validated;
- explicit unavailable/disabled/partial states;
- overhead within budget and no capture regression;
- tests green; no C: writes.

### C-2

- findings for all synthetic scenario classes;
- confidence/claim levels and evidence windows;
- missing data never yields a confident cause;
- target FPS/reference ranges computed;
- tests green; no capture/statistics changes.

### C-3

- diagnostic summary, evidence panel, stutter list and explanations;
- reference ranges and target FPS;
- EN/ZH and responsive UI;
- real Palworld controlled A/B demonstrating at least one CPU/GPU
  scenario;
- screenshots and manual acceptance.

## 14. Decisions requested

1. Approve the **C-1 sidecar + 4 Hz sampler** direction, or request a
   different rate/format.
2. Confirm that per-process CPU/RAM is in scope, while per-process
   GPU/VRAM is explicitly out of scope until a reliable source is
   approved.
3. Approve rule-based diagnostics with confidence/claim levels as the
   first implementation; defer ML.
4. Approve using the existing `target_fps` setting for frame budgets
   and reference ranges.
5. Confirm that controlled A/B is the only path to a
   `confirmed_by_control` claim.
6. Confirm whether PDH/ETW per-process GPU counters should be explored
   after C-2, or deferred.

## 15. Non-goals and boundaries

- No changes to PresentMon capture command or CSV validation in the
  design phase.
- No changes to frame statistics, swap-chain selection or successful
  target memory.
- No hardware control, overclocking or driver changes.
- No definitive causal claims from observational correlation.
- No Phase C implementation until this design is approved.
