# C-2.2: Diagnostic Reliability and False-Positive Validation

Date: 2026-11-12
Status: accepted 2026-11-12.
Scope: fix the C-1 target-CPU data quality issue, tighten diagnostic
event independence and false-positive behaviour, and require genuine
controlled-A/B metadata before controlled confirmation. C-3 UI is
documented separately; no machine learning.

## 1. Summary

- Fixed the C-1 target CPU issue: `TargetProcessTracker` was creating a
  fresh `psutil.Process` for every sample, so `cpu_percent(interval=None)`
  returned its first-call baseline of `0.0` on every sample.
- The tracker now keeps one persistent process object per PID, resets
  its baseline on PID reuse/restart, and preserves exit/missing-data
  handling.
- A real busy Python process measured 96.9%, 103.1% and 93.8% of one
  logical core. A post-fix real Palworld QPC sidecar reported target CPU
  median 64.6% and max 82.2% (30 non-null samples).
- Local stutter events whose context windows overlap are now merged
  before counting support. They cannot be counted as independent
  evidence for `likely`.
- Added positive, negative and boundary tests for CPU, GPU, mixed,
  memory and presentation rules.
- Tightened `ControlExperiment`: same scenario, exactly one changed
  setting matching the declared factor, comparable capture durations,
  minimum duration/frame counts, recognized metric, and a minimum
  improvement. Two unrelated CSVs are no longer enough.
- No real A/B experiment was available, so no real finding was marked
  `confirmed_by_control`.
- Full suite: **419 tests in 14.343 s, OK**.

## 2. C-1 target CPU fix

### 2.1 Root cause

`psutil.Process.cpu_percent(interval=None)` computes a percentage
relative to the previous call **on that Process object**. On a new
object the first call returns `0.0` and establishes the baseline.

C-1 `TargetProcessTracker.sample()` previously did:

```text
process = self._process_factory(pid)
cpu = process.cpu_percent(interval=None)
```

A new `psutil.Process` was created for every sample, so after the initial
`_primed` bookkeeping every later call was again that object's first call
and returned `0.0`. The real Palworld sidecars therefore contained
`target.cpu_percent = 0.0` throughout.

### 2.2 Fix

`TargetProcessTracker` now keeps:

```text
self._processes[pid] = persistent psutil.Process object
self._known[pid]     = verified create_time
self._primed         = set of PIDs whose first sample is done
```

Rules:

- refresh creates a process object only for new PIDs;
- the same object is reused for every sample while `create_time` is
  unchanged;
- PID reuse or process restart clears the old object and primed state;
- process exit removes the object and reports `target_exited` once the
  target had been seen;
- `NoSuchProcess` removes the process; other sampling failures produce
  explicit missing values without inventing a percentage;
- the first sample is still `None` for that PID (baseline only);
  subsequent samples are non-zero interval averages.

The PID-reuse, target-exit and missing-state tests remain green.

### 2.3 Real CPU-load validation

A separate real `pythonw.exe` process ran a busy loop. A real
`TargetProcessTracker("pythonw.exe")` produced:

```text
sample 0: status=ok, cpu_percent=None (baseline)
sample 1: status=ok, cpu_percent=96.9
sample 2: status=ok, cpu_percent=103.1
sample 3: status=ok, cpu_percent=93.8
```

Values are percentages of one logical core; values above 100 are legal
for a process using more than one core. The process was terminated after
the probe.

A post-fix real Palworld QPC capture (`qpc_c22`) produced 31 samples,
30 of them non-null:

```text
target CPU min 47.0%, median 64.6%, max 82.2%
```

This confirms the target CPU field is now useful and that the previous
all-zero data was an instrumentation issue, not a game property.

## 3. Diagnostic reliability changes

### 3.1 Independent local events

A local stutter's event window is:

```text
[event - 500 ms, event + 1000 ms]
```

Two events whose windows overlap are not independent evidence. The
engine now merges events within:

```text
max(event_merge_ms, event_window_before_ms + event_window_after_ms)
```

which is 1500 ms with the defaults. As a result:

- overlapping events produce one event/finding, not multiple `likely`
  support votes;
- `likely` still requires at least two *separate* local events plus a
  global pattern;
- a single event cannot be promoted to `likely`.

A dedicated test places two events 0.6 s apart and verifies
`event_count == 1` and no `likely`.

### 3.2 Positive, negative and boundary coverage

The diagnostic suite now includes:

| Rule area | Positive | Negative / boundary |
|---|---|---|
| CPU | CPU busy dominates with low CPU wait, repeated events | high CPU wait; frame-cap/VSync-like wait; exact local threshold |
| GPU | GPU busy dominates with low GPU wait | missing GPU fields; high NVML util alone; CPU wait high |
| Mixed | CPU and GPU busy close to the frame interval | frame rate under target budget |
| Memory | high system RAM + target RSS growth + QPC | RAM low; legacy/untrusted timebase |
| Presentation | displayed-fraction drop / `DisplayedTime=NA` | fully displayed capture |
| Data quality | missing fields/timebase/sidecar | abnormal/zero/NA frames; too few frames |
| Events | repeated independent CPU/GPU events → `likely` | single event; overlapping windows |
| Controls | valid comparable A/B metadata | same captures, wrong target, scenario mismatch, two changed settings, duration/frame shortages, insufficient improvement |

A synthetic reliability matrix runs nine classification scenarios with
required and forbidden findings:

```text
9/9 scenarios matched the asserted expected/forbidden findings
0 unexpected findings in that matrix
```

This is a deterministic fixture matrix, not a statistical precision /
recall estimate. In addition, targeted negative/boundary tests cover
frame cap, VSync, high CPU wait, missing GPU fields, untrusted timebase,
NVML-only GPU utilization, single/overlapping events, exact threshold,
abnormal frames and fully displayed captures.

### 3.3 Real-data checks

No heuristic result is labelled as a confirmed real-game cause.

## 4. Controlled A/B evidence

`ControlExperiment` now requires all of the following before any
`confirmed_by_control` upgrade:

- non-empty target and factor;
- two different capture identifiers;
- non-empty, identical baseline/treatment scenario identifiers;
- non-empty baseline/treatment settings dictionaries;
- exactly one changed setting, and the declared factor must match that
  setting key;
- baseline/treatment durations >= 30 seconds;
- duration ratio <= 1.20;
- at least 300 frames in each capture;
- a recognized metric;
- finite values and at least 20% relative improvement by default.

If any condition fails:

- the finding is not upgraded;
- the reason is written to `report.control_rejections`;
- no `confirmed_by_control` claim is emitted.

The engine still does not re-analyse the A/B captures; it validates the
caller-provided metadata and records that limitation. No real A/B data
was available in C-2.2, so all real outputs remain observational.

## 5. Real Palworld validation

### 5.1 Post-fix QPC capture

`qpc_c22`: 953 frames, complete QPC sidecar, target CPU median 64.6%,
max 82.2%.

At the user-visible 60 FPS target:

```text
insufficient_evidence
```

The capture was running near 120 FPS, so no CPU/GPU bottleneck was
claimed against a 60 FPS budget. This is the intended no-false-positive
behaviour.

At a 120 FPS target (the actual frame interval):

```text
global_cpu_bottleneck_candidate
category=cpu
claim_level=observed_association
confidence=medium
target CPU median 64.6%
```

This is still an observed association, not a confirmed cause.

### 5.2 Pre-fix QPC capture

`qpc_live_2` (before the target-CPU fix) has an all-zero target CPU
sidecar. C-2.2 diagnostics detect:

```text
target_cpu_unusable
```

and do not use target CPU. The existing findings remain:

- `mixed_frame_pressure` — observed association, low confidence;
- `local_stutter_cpu_association` — observed association, low confidence.

No confirmed cause.

### 5.3 Legacy capture

The existing 11,385-frame legacy Palworld capture, with no sidecar:

- 12 local events under the independent-window policy;
- 6 observed CPU associations;
- 1 observed GPU association;
- 5 unclassified events;
- 14.4% `DisplayedTime=NA`;
- telemetry unavailable.

No frame-to-hardware temporal association, no `likely`/confirmed cause.
Long holes remain unclassified.

## 6. Tests

New/changed coverage:

- persistent process object and first-call baseline;
- real busy-process CPU probe (manual validation, not a unit test);
- PID reuse, target exit and missing data remain correct;
- overlapping local events merge and cannot support `likely`;
- frame-cap and VSync-like false-positive controls;
- exact local threshold boundary;
- abnormal frames are skipped/retained without invented metrics;
- memory requires high RAM and aligned QPC;
- presentation negative case;
- NVML GPU utilization is not process GPU use;
- strict A/B comparability and rejection cases;
- synthetic reliability matrix.

Full suite:

```text
Ran 419 tests in 14.343s

OK
```

31 diagnostic tests are included.

## 7. Known false positives and limits

- The rule matrix is synthetic. It is not a statistically representative
  precision/recall measurement.
- Local stutter associations remain heuristic; ETW loss, loading,
  external processes and work outside the captured chain can produce
  long frames.
- 4 Hz telemetry is context only; it is not per-frame hardware data.
- NVML device utilization/VRAM has unknown target-process association
  and is not used as target GPU/VRAM usage.
- `DisplayedTime=NA` identifies non-display, not its cause.
- HAGS/HWS can reduce GPU execution metric accuracy.
- Target CPU is an interval percentage of one core; the first sample per
  PID is a baseline/null, and values above 100% are possible.
- A/B validation trusts structured metadata; it cannot prove that the
  user actually ran a controlled experiment without re-analysing both
  captures.
- No C-3 UI, no machine learning, and no C-2.2 real confirmed cause.
