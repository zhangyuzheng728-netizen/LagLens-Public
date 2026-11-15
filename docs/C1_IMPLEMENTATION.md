# C-1 Implementation: Hardware Telemetry and Timebase

Date: 2026-11-12
Status: implementation complete; C-1 and C-1.1 accepted. QPC
integration is covered by C-2.0 (`docs/C2_0_QPC_INTEGRATION.md`).
Scope: telemetry data layer only. No C-2 diagnostic rules and no C-3
UI.

## 1. Delivered

- `telemetry.py`
  - versioned JSONL schema;
  - sidecar writer/reader;
  - missing/corrupt sidecar handling;
  - PresentMon/sampler timebase calibration model.
- `hardware_sampler.py`
  - independent sampler thread;
  - CPU system/per-core, RAM, target process CPU/working set;
  - NVML GPU utilization, VRAM and temperature;
  - 4 Hz default, configurable through `telemetry/interval_ms`;
  - low-overhead profile at 1 Hz (and `--no_track_gpu` metadata);
  - PID reuse/exit tracking;
  - explicit missing values, no stale reuse.
- `settings.py`
  - `telemetry/interval_ms`, default 250 ms, valid range
    100–5000 ms.
- `main.py`
  - starts/stops the sampler around the existing capture worker;
  - records PresentMon start, first/last CSV row arrival and
    CPUStartTime values;
  - writes timebase/end records without blocking or changing the CSV
    pipeline.
- `CaptureWorker`
  - records timestamps/markers only. The CSV writing and frame
    validation path are unchanged.

No PresentMon command, CSV format, frame-statistics or swap-chain
selection logic was changed.

## 2. Sidecar lifecycle

For a capture CSV named:

```text
Palworld-Win64-Shipping.exe_YYYYMMDD_HHMMSS_ffffff.csv
```

the sidecar is written next to it:

```text
Palworld-Win64-Shipping.exe_YYYYMMDD_HHMMSS_ffffff.csv.telemetry.jsonl
```

Records are written incrementally:
`metadata`, then `sample`/`marker` records as they occur, then
`timebase` and `end`. The first sample may precede the
`presentmon_started` marker because the sampler starts first.
Consumers must dispatch on the `type` field, not on line position.

If the process crashes or the file is truncated, the reader marks the
sidecar incomplete/partial and never blocks CSV analysis. A missing or
corrupt sidecar produces an empty/unavailable telemetry result.

## 3. Sanitized sidecar example

The following example is deliberately redacted and shortened. It
contains no full user paths; the CSV is identified by basename only.

```jsonl
{"type":"metadata","schema_version":1,"capture":{"csv_name":"Palworld-Win64-Shipping.exe_20261112_114008_782460.csv","target_name":"Palworld-Win64-Shipping.exe","profile":"default","started_monotonic_ns":123456789000,"started_wall_ns":1762900000000000000,"sample_interval_ms":250,"presentmon_gpu_tracking":"enabled"},"gpu":{"available":true,"status":"ok","devices":[{"index":0,"name":"<GPU name redacted>","uuid":"<GPU-UUID redacted>","bus_id":"","association":"unknown"}],"sampled_device":{"index":0,"name":"<GPU name redacted>","uuid":"<GPU-UUID redacted>","bus_id":"","association":"unknown"},"multi_gpu":false,"association":"unknown","note":"sampled NVML device identity is recorded; association with the captured process is unknown"},"sampling":{"interval_ms":250,"low_overhead":false}}
{"type":"marker","name":"presentmon_started","monotonic_ns":123506789000,"wall_ns":1762900000100000000}
{"type":"sample","t_ms":250.4,"wall_ns":1762900000250000000,"sample_cost_ms":1.13,"cpu":{"status":"ok","system_percent":37.5,"per_core_percent":[22.0,41.0,18.0,54.0]},"ram":{"status":"ok","used_bytes":17179869184,"total_bytes":34359738368,"percent":50.0,"available_bytes":17179869184},"target":{"status":"ok","pids":[{"pid":29864,"create_time":1762899000.0}],"cpu_percent":28.4,"rss_bytes":6442450944,"processes":[{"pid":29864,"create_time":1762899000.0,"cpu_percent":28.4,"rss_bytes":6442450944,"status":"ok"}],"pid_reuse_detected":false},"gpu":{"status":"ok","util_percent":86,"vram_used_bytes":7516192768,"vram_total_bytes":8589934592,"temperature_c":68,"association":"unknown"}}
{"type":"timebase","capture_outcome":"valid","valid_frames":11385,"capture_started_monotonic_ns":123456789000,"presentmon_started_monotonic_ns":123506789000,"first_row_monotonic_ns":183456789000,"last_row_monotonic_ns":344876789000,"first_cpu_start_ms":5924.8208,"last_cpu_start_ms":167354.7716,"presentmon_start_offset_ms":50.0,"row_span_ms":161420.0,"csv_span_ms":161429.9508,"span_error_ms":9.9508,"offset_estimate_ms":45.3584,"uncertainty_ms":500.0,"relative_scale_trusted":true,"absolute_offset_trusted":false,"status":"relative_verified","note":"CSV and row spans are consistent; absolute offset still includes CSV read/buffering latency and is not trusted"}
{"type":"end","reason":"finished","ended_monotonic_ns":344900000000,"ended_wall_ns":1762900160000000000,"duration_ms":161443.211,"sample_count":646,"sampling_errors":[],"write_error":"","capture_outcome":"valid","valid_frames":11385}
```

Notes:

- PIDs and create times are diagnostic sample context. They are not
  written to `processes/successful_targets`; successful-target memory
  remains path-only and PID-free.
- GPU name/UUID are device identity, not personal paths. The
  `association` field is always `unknown` in C-1 because LagLens cannot
  prove which GPU renders the captured process.
- `bus_id` may be empty if the driver does not expose it; identity still
  includes name/UUID.

## 4. Time synchronization verification

### What C-1 records

- capture start monotonic/wall clock;
- PresentMon process-start monotonic timestamp;
- first and last valid CSV row arrival monotonic timestamps;
- first and last `CPUStartTime` values;
- observed row span, CSV span, span error, offset estimate and
  uncertainty.

### What is trusted

- **Relative scale** is marked trusted only when the observed CSV row
  span and the CSV `CPUStartTime` span agree within
  `max(250 ms, 1% of span)`.
- **Absolute offset is deliberately never trusted** in C-1. The first
  row arrival includes CSV/stdio read and buffering latency, which has
  not been independently calibrated. The sidecar records an estimate
  plus uncertainty, not a pretend exact mapping.
- If timings are missing or the span check fails, the timebase status
  is `untrusted` and the record still exists for audit.

### Test coverage

Automated tests cover:

- consistent spans (`relative_verified`);
- inconsistent spans (`untrusted`);
- missing timing values;
- first-frame delay / offset estimate;
- PresentMon start marker;
- sidecar incomplete/corrupt handling.

### Real-capture status

Existing real Palworld CSVs show `CPUStartTime` behaving as a
capture-relative millisecond timebase:

- 11,385 rows: first 5,924.8 ms → last 167,354.8 ms;
- 34,484 rows: first 15.3 ms → last 396,733.9 ms.

A real ETW calibration attempt in the current non-elevated shell failed
with `access denied` (PresentMon requires administrator privileges or
the Performance Log Users group). C-1.1 later completed real elevated
Palworld captures and validated the sidecar records. That validation
found that stdout buffering makes the default row-arrival timebase
untrusted in practice. PresentMon `--qpc_time_ms` was verified as a
reliable experimental mapping to Python monotonic time, but it changes
the CSV header and is not enabled in the default path. See
`docs/C1_TIMEBASE_VALIDATION.md`. Absolute offset remains untrusted in
the default CSV path.

## 5. Sampling overhead measurement

Measured with real psutil + NVML providers at 4 Hz for approximately
4 seconds on the target machine:

```text
samples:                  16
sample cost average:      1.03 ms
sample cost maximum:      1.45 ms
sampler start:            12.8 ms wall
sampler stop:             0.5 ms wall
process CPU time:         0.015625 s
wall time:                4.0214 s
CPU overhead:             ~0.39% of one logical core
sidecar size:             20,735 bytes for ~4 s (~5 KB/s)
```

This is below the 1% one-core budget proposed in the design. The first
implementation queried `create_time` for every process and spent ~0.86
s at start; it now queries `create_time` only for target-name matches
and refreshes target process membership every 5 s.

Low-overhead mode uses a 1 s interval (or the configured interval if
larger) and records `presentmon_gpu_tracking: "disabled"` when
`--no_track_gpu` is active. The sampler still records NVML device
telemetry at that slower rate; it does not claim PresentMon GPU fields
exist.

## 6. Failure and missing-data behavior

- GPU read failure writes `status="unavailable"` and null values; old
  values are never reused.
- NVML unavailable/unsupported writes unavailable metadata and samples.
- Target process exit writes `target_exited` with null target fields.
- PID reuse is detected by `create_time`; the new process is not
  confused with the old one and the flag is recorded.
- Sampler thread stop is bounded and idempotent; a timeout is recorded.
- Sidecar open/write failure never raises into the capture path.
- Partial/corrupt sidecars are marked incomplete/partial by the reader.
- CSV analysis does not depend on telemetry; a missing sidecar cannot
  block the existing analysis.

## 7. Tests

Full suite:

```text
Ran 361 tests in 12.764s

OK
```

New C-1 coverage:

- 26 telemetry/sampler/timebase tests;
- 2 settings interval tests;
- 4 main-window telemetry lifecycle tests;
- 1 worker timing/marker integration test.

Total: 328 previous + 33 C-1 tests = **361 passing**.

C-1.1 adds three timebase consistency tests (QPC epoch, QPC
tick/millisecond conversion, and the real stdout-buffering span
mismatch). The C-2.0 suite is now **387 passing**; see
`docs/C1_TIMEBASE_VALIDATION.md` and
`docs/C2_0_QPC_INTEGRATION.md`.

## 8. Known limits

- Per-process GPU/VRAM attribution is not implemented and not claimed.
- GPU-to-target association is `unknown`; multiple GPUs are enumerated
  and the sampled device identity is recorded.
- 4 Hz is context, not frame-level evidence; C-2 must rely primarily on
  PresentMon frame fields.
- Absolute timebase offset is not trusted in C-1.
- C-1.1 real validation confirmed that default CSV row-arrival timing
  is affected by stdout buffering (about 1–2 s), so the default
  timebase is `untrusted` in practice. QPC output was validated as a
  reliable experimental mapping, but is not part of the default CSV
  format. See `docs/C1_TIMEBASE_VALIDATION.md`.
- Observed 4 Hz cadence is about 264 ms (3.78 Hz) because of Windows
  wait-timer granularity; exact 4 Hz would require a separate
  high-resolution timer change.
- The sidecar has no C-3 UI yet; it is a data artifact only.
- No C-2 diagnostic rules or C-3 explanations/reference ranges are
  implemented.
