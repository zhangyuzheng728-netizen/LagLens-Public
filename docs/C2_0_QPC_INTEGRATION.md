# C-2.0: QPC Time Synchronization Integration

Date: 2026-11-12
Status: accepted 2026-11-12.
Scope: opt-in QPC capture, CSV compatibility, internal time
normalization, and real Palworld validation. C-2.1 diagnostic rules are
documented separately in `docs/C2_1_DIAGNOSTICS.md`; no C-3 UI.

## 1. Summary

- Added a default-off **QPC timebase (experimental)** capture option.
- QPC mode adds `--qpc_time_ms`; legacy captures still use
  `CPUStartTime` with exactly the previous command and CSV format.
- The CSV validator and parser now accept either `CPUStartTime` or
  `CPUStartQPCTime`, but QPC absolute milliseconds are normalized to
  capture-relative time before statistics or charting.
- The original raw timestamp and an explicit timebase description are
  preserved for future diagnostics.
- A real elevated Palworld QPC capture completed successfully. The
  sidecar recorded `sync_quality: verified_qpc`, a QPC/Python clock
  delta of **-0.0026 ms**, and `absolute_mapping_trusted: true`.
- Legacy captures and historical CSVs still analyse normally.
- Full suite: **387 tests in 17.633 s, OK**.

## 2. Design

### 2.1 Capture option

The Live page has a separate default-off checkbox:

```text
QPC timebase (experimental)
```

When enabled, `capture_core.build_capture_command()` appends:

```text
--qpc_time_ms
```

It is independent of low-overhead mode, so both flags can be enabled
together. Disabling the checkbox restores the exact legacy command.

The setting is intentionally not persisted: a fresh application starts
in the safe legacy mode. This is the rollback path.

### 2.2 Frame timebase model

New module: `frame_timebase.py`.

A `FrameTimebase` records:

| Field | Meaning |
|---|---|
| `kind` | `relative`, `qpc_ms`, or `unknown` |
| `raw_column` | `CPUStartTime` or `CPUStartQPCTime` |
| `origin_kind` | `capture_relative`, `capture_start`, or `first_frame` |
| `origin_qpc_ms` | QPC capture-start origin, if known |
| `capture_started_monotonic_ns` | Python perf_counter start used as origin |
| `qpc_clock_delta_ms` | measured Python perf_counter minus direct QPC |
| `qpc_frequency_hz` | Windows QPC frequency |
| `sync_quality` | `exact_relative`, `verified_qpc`, `unverified_qpc`, `inferred_qpc`, or `untrusted` |
| `applicability` | `capture_relative`, `absolute_frame_time`, `frame_relative_only`, or `none` |
| `absolute_mapping_trusted` | true only for a verified/sidecar capture-start QPC origin |
| raw/normalized first/last | audit values |

Behavior:

- **Legacy `CPUStartTime`**: normalized time equals the raw value.
  `sync_quality=exact_relative`; no absolute QPC mapping is claimed.
- **QPC `CPUStartQPCTime` with capture start**: normalized time is
  `raw_qpc_ms - capture_start_qpc_ms`. The capture start comes from
  Python `perf_counter_ns`, which shares the Windows QPC epoch.
- **QPC with no capture origin**: the first valid frame becomes the
  origin. `sync_quality=inferred_qpc`; frame statistics still work, but
  `absolute_mapping_trusted` is false.
- **QPC with a missing or out-of-tolerance clock measurement**: sync is
  `unverified_qpc`; absolute correlation is not allowed.
- **No time column**: `kind=unknown`, `applicability=none`; no precise
  frame/hardware correlation is allowed.

`QPC_CLOCK_TOLERANCE_MS` is 5 ms. C-1.1 measured an actual difference
below 0.01 ms, so this is a conservative guard rather than a tuning
threshold.

### 2.3 CSV compatibility

`capture_core` changes:

- `REQUIRED_COLUMNS` no longer hard-codes `CPUStartTime`.
- `validate_capture()` requires exactly one supported time column and
  records it in `CaptureInfo.time_column`.
- `CsvTailer` follows either column and exposes `time_column`.
- `build_capture_command()` only adds `--qpc_time_ms` when requested.

Analysis changes:

- `swap_chains.build_index()` parses the detected column and stores
  both normalized `time_ms` and raw `raw_time_ms`.
- `frame_viewer.load_frames()` resolves the sidecar timebase for QPC
  CSVs before chain selection.
- `frame_analyzer.py` uses the same normalization in the standalone
  analyzer.
- `frame_stats` still consumes only normalized `time` and `duration`.

No CSV is rewritten. QPC captures keep `CPUStartQPCTime` in the file;
legacy captures keep `CPUStartTime`. The original row remains available
as `frame["row"]`.

### 2.4 No row-arrival inference

QPC frame time comes from the timestamp embedded in the CSV row, not
from when LagLens reads the row. The C-1.1 finding that PresentMon's
stdout can be buffered by 1–2 seconds still applies to row-arrival
timing. For QPC mode:

- row arrival is not used to assign frame time;
- the legacy row-arrival span check may still report
  `relative_scale_trusted=false`;
- the authoritative QPC result is in `timebase.frame_timebase`, with
  `status=qpc_verified` when the clock mapping is verified.

## 3. Real Palworld validation

Environment: Windows 11, Python 3.12, PresentMon 2.6, real
`Palworld-Win64-Shipping.exe`, elevated capture, RTX 5060 Laptop GPU
(NVML index 0, association `unknown`).

| Run | CSV time column | Frames | Sidecar samples | Timebase status | Sync quality | Clock delta |
|---|---|---:|---:|---|---|---:|
| QPC, 10 s | `CPUStartQPCTime` | 615 | 39 | `qpc_verified` | `verified_qpc` | -0.0026 ms |
| Legacy, 10 s | `CPUStartTime` | 568 | 39 | `untrusted` (row arrival) | `exact_relative` | — |

The QPC sidecar's `frame_timebase`:

```json
{
  "kind": "qpc_ms",
  "raw_column": "CPUStartQPCTime",
  "origin_kind": "capture_start",
  "origin_qpc_ms": 14997061.3524,
  "capture_started_monotonic_ns": 14997061352400,
  "qpc_clock_delta_ms": -0.0026,
  "qpc_frequency_hz": 10000000,
  "sync_quality": "verified_qpc",
  "applicability": "absolute_frame_time",
  "absolute_mapping_trusted": true,
  "raw_first_time_ms": 14997197.9535,
  "raw_last_time_ms": 15007044.1125,
  "normalized_first_ms": 136.6011,
  "normalized_last_ms": 9982.7601
}
```

The first QPC frame is therefore 136.6 ms after the recorded capture
start; the last is at 9982.8 ms. The QPC span is 9,846.2 ms. The
first frame delay is expected (PresentMon/target startup) and is not
mistaken for zero.

The QPC CSV was validated as:

```text
validate_capture(...).ok = true
valid_frames = 615
time_column = CPUStartQPCTime
```

`load_frames()` then produced capture-relative times and the existing
statistics engine reported:

```text
frames = 615
mean frame time = 16.035 ms
average FPS = 62.363
P95 = 20.057 ms
1% low = 36.071 FPS
```

The legacy 10 s run remained fully compatible:

```text
time_column = CPUStartTime
frames = 568
sync_quality = exact_relative
status = untrusted (stdout row-arrival span)
mean frame time = 17.406 ms
average FPS = 57.453
```

The two runs are different game moments, so their FPS values must not be
used as a performance comparison. They only demonstrate that both
timebase modes feed the existing analysis path.

### 3.1 Missing-sidecar fallback

A copy of the real QPC CSV without its sidecar was loaded through
`load_frames()`:

- first frame normalized to 0 ms;
- `sync_quality=inferred_qpc`;
- `absolute_mapping_trusted=false`;
- all 1,192 frames still produced valid statistics.

This is deliberate: frame statistics remain usable, but no absolute
hardware/frame correlation may be claimed.

### 3.2 Historical legacy compatibility

An existing real Palworld CSV (`CPUStartTime`, 11,385 frames) loaded
with `timebase_kind=relative`, `sync_quality=exact_relative`, unchanged
statistics (69.88 FPS in that capture). Existing files do not need a
migration or sidecar.

## 4. Error bounds and sync quality

| Item | Result |
|---|---|
| Python `perf_counter_ns` vs direct Windows QPC | -0.0026 ms in the real QPC run; C-1.1 range was below 0.01 ms |
| QPC milliseconds in CSV | 4 decimal places; about 0.1 µs display resolution |
| QPC frequency | 10,000,000 Hz; one raw tick = 100 ns |
| Practical absolute clock bound | well below 0.1 ms |
| Frame timestamp semantics | PresentMon CPU start, not display time |
| Legacy absolute mapping | not claimed |
| QPC without capture origin | relative frame differences only |
| Missing/unverified QPC clock | `unverified_qpc`, absolute mapping disabled |

The 5 ms `QPC_CLOCK_TOLERANCE_MS` is much larger than the observed
error. It protects against a mismatched clock implementation or a
measurement failure without rejecting normal QPC reads.

## 5. Sidecar fields

Sampler metadata now records:

```json
"qpc_time_requested": true,
"timebase_kind": "qpc_ms",
"expected_time_column": "CPUStartQPCTime"
```

The `timebase` record includes `frame_timebase` with the full
kind/origin/sync model. For a verified QPC capture the top-level status
is `qpc_verified`; the row-arrival fields remain available for audit
but are not used for QPC mapping.

## 6. Tests

New/updated coverage:

- legacy/QPC column detection and preferred-column rules;
- QPC capture origin subtraction;
- QPC without capture start falls back to first frame;
- QPC clock mismatch and missing measurement are not absolute-trusted;
- sidecar origin and corrupt-sidecar fallback;
- QPC `validate_capture`, `CsvTailer`, and command construction;
- QPC `load_frames` with and without sidecar, including frame stats;
- worker QPC normalization and raw CSV preservation;
- sampler QPC metadata and `frame_timebase` sidecar record;
- main-window QPC option passed to sampler/worker;
- existing legacy loader/statistics/swap-chain tests unchanged.

Full result:

```text
Ran 387 tests in 17.633s

OK
```

## 7. Conclusion

C-2.0 is complete as a data/timebase layer:

- legacy `CPUStartTime` remains the default and is byte-for-byte
  compatible with the previous capture/analysis path;
- QPC is an explicit default-off opt-in with verified real-game
  mapping, raw timestamp preservation, and explicit sync quality;
- QPC absolute milliseconds are never treated as relative milliseconds;
- missing or untrusted QPC timebase falls back to relative-only
  analysis and disables absolute correlation;
- no C-2.1 diagnostic rules or C-3 UI were added.

## 8. Limitations

- One machine, game, GPU and session; no multi-GPU/hybrid-GPU
  validation.
- QPC mode is exposed in the Live page but was validated through an
  actual LagLens window harness that was not visually interactive; a
  dedicated visual/manual acceptance is still useful.
- QPC raw-tick output (`--qpc_time`) is not product-enabled; only
  `--qpc_time_ms` is used.
- QPC is CPU start time, not display latency or physical presentation.
- The default legacy timebase remains row-arrival-untrusted due to
  stdout buffering. QPC is the path for reliable absolute mapping.
- C-2.1 diagnostics and C-3 explanations remain unimplemented.
