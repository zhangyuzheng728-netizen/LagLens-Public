# C-1.1: Real Timebase Validation and Sampling Overhead

Date: 2026-11-12
Status: C-1.1 accepted; QPC is now integrated as an opt-in C-2.0
capture mode. The default CSV path remains legacy-compatible.
Scope: real elevated PresentMon capture, sidecar consistency, QPC
mapping, and 4 Hz/1 Hz/off overhead. No C-2 diagnostic rules and no
C-3 UI were implemented.

See `docs/C2_0_QPC_INTEGRATION.md` for the C-2.0 integration.

## 1. Executive summary

- A real elevated PresentMon 2.6 capture of the running Palworld
  process completed successfully and produced complete C-1 sidecars.
- `metadata`, `marker`, `sample`, `timebase` and `end` records were all
  present. `end.sample_count` matched the actual sample records, and
  `end.duration_ms` matched `ended_monotonic_ns - started_monotonic_ns`
  within sub-microsecond rounding.
- The default CSV path is **not reliably alignable by stdout row
  arrival time**. PresentMon's stdout is buffered, so the observed row
  arrival span is about 1.1–2.1 s shorter than the CSV's own
  `CPUStartTime` span. C-1 correctly marks this condition `untrusted`.
- PresentMon `--qpc_time_ms` and `--qpc_time` were verified on the same
  machine. Their timestamps use the same QPC epoch as Python
  `time.perf_counter_ns()`; the measured clock-read difference was
  below 0.01 ms. QPC therefore provides a reliable experimental
  absolute mapping.
- QPC output changes the CSV header to `CPUStartQPCTime` or
  `CPUStartQPC`. The existing `CPUStartTime`-based validation and
  analysis reject that CSV by design. QPC must remain an explicit
  experimental mode, not the default format.
- The 4 Hz sampler thread cost is within the C-1 budget. It used about
  0.34% of one logical core in a standalone 20 s run and about 0.53%
  inside the real LagLens capture process. The whole LagLens process
  averaged about 0.99% of one core at 4 Hz, versus about 0.42% with
  telemetry off; the whole-process figure includes the GUI and capture
  reader baseline and is close to, not well under, 1%.
- Observed 4 Hz cadence was about 264 ms (3.78 Hz), not exactly 250 ms,
  because Windows wait timeouts use the system timer granularity.
  1 Hz cadence was about 1011 ms.
- Full suite after adding the C-1.1 consistency tests:
  **364 tests in 14.591 s, OK**.

## 2. Environment and method

| Item | Value |
|---|---|
| OS | Windows 11 |
| Python | 3.12 (project venv) |
| PresentMon | 2.6.0 x64 |
| Game | Palworld / `Palworld-Win64-Shipping.exe` |
| GPU | NVIDIA GeForce RTX 5060 Laptop GPU |
| GPU association | `unknown` (NVML index 0 was sampled; not proven to be the game GPU) |
| PresentMon target PID | 9660 (real game process) |
| Capture mode | real ETW capture, elevated |
| Sampler | actual `HardwareSampler` from `hardware_sampler.py` |
| GUI overhead harness | actual `LagLens` window class, `CaptureWorker`, hardware timer and sampler; window not shown |

The real capture used the same command shape as the product:

```text
PresentMon-2.6.0-x64.exe
  --session_name <session>
  --stop_existing_session
  --process_name Palworld-Win64-Shipping.exe
  --output_stdout
  --no_console_stats
  --v2_metrics
  --no_track_input
  --timed <seconds>
  --terminate_after_timed
```

The experimental QPC runs added either:

```text
--qpc_time_ms
```

or:

```text
--qpc_time
```

Validation artifacts were written outside the repository under
`<validation-data>`. They were not committed. The product
capture command and default CSV format were not changed.

## 3. Real sidecar validation

### 3.1 Record presence and counts

Example real run: actual LagLens GUI harness, 4 Hz, 20 s Palworld
capture.

| Check | Result |
|---|---|
| CSV valid frames | 1,620 |
| Sidecar samples | 77 |
| Record counts | metadata 1, marker 1, sample 77, timebase 1, end 1 |
| `end.sample_count` | 77 |
| Actual sample records | 77 |
| `end.duration_ms` | 20,233.8016 ms |
| `ended_monotonic_ns - started_monotonic_ns` | 20,233.8009 ms |
| Difference | 0.0007 ms |
| Wall-clock duration | 20,482.1777 ms |
| Monotonic harness duration | 20,482.2364 ms |
| Difference | 0.0587 ms |

The same consistency held in the shorter probe runs: for example,
`c11_normal_a` had 31 samples, `end.sample_count == 31`, and
`end.duration_ms` differed from the start/end monotonic delta by
0.0005 ms.

### 3.2 Observed record order

The real order was:

```text
metadata
sample
marker
sample ...
timebase
end
```

The first sample can precede the `presentmon_started` marker because
the sampler starts before PresentMon is launched. This is expected.
Consumers must dispatch on the `type` field and must not assume that
the marker is always the second line.

### 3.3 Real sidecar excerpt (sanitized)

Full sample payloads are shortened here. GPU name/UUID are redacted;
the sidecar itself contains device identity, not personal paths.

```jsonl
{"type":"metadata","schema_version":1,"capture":{"csv_name":"<capture>.csv","target_name":"Palworld-Win64-Shipping.exe","profile":"default","started_monotonic_ns":13463671970800,"started_wall_ns":1794465080826429600,"sample_interval_ms":250,"presentmon_gpu_tracking":"enabled"},"gpu":{"available":true,"status":"ok","devices":[{"index":0,"name":"<redacted>","uuid":"<redacted>","bus_id":"","association":"unknown"}],"sampled_device":{"index":0,"name":"<redacted>","uuid":"<redacted>","bus_id":"","association":"unknown"},"multi_gpu":false,"association":"unknown"},"sampling":{"interval_ms":250,"low_overhead":false}}
{"type":"sample","t_ms":2.8563,"wall_ns":1794465080831935900,"sample_cost_ms":2.5293,"cpu":{"status":"ok","system_percent":0.0,"per_core_percent":[0.0,0.0,0.0,0.0]},"ram":{"status":"ok","used_bytes":21764251648,"total_bytes":33752997888,"percent":64.5,"available_bytes":11988746240},"target":{"status":"ok","pids":[{"pid":9660,"create_time":1794454531.7933846}],"cpu_percent":null,"rss_bytes":6079868928,"processes":[{"pid":9660,"create_time":1794454531.7933846,"cpu_percent":0.0,"rss_bytes":6079868928,"status":"ok"}],"pid_reuse_detected":false},"gpu":{"status":"ok","util_percent":71,"vram_used_bytes":5091942400,"vram_total_bytes":8546942976,"temperature_c":80,"association":"unknown"}}
{"type":"marker","name":"presentmon_started","monotonic_ns":13463691129700,"wall_ns":1794465080845460700}
{"type":"timebase","capture_outcome":"valid","valid_frames":1620,"capture_started_monotonic_ns":13463671970800,"presentmon_started_monotonic_ns":13463691129700,"first_row_monotonic_ns":13465956592400,"last_row_monotonic_ns":13483812454200,"first_cpu_start_ms":9.2435,"last_cpu_start_ms":19918.5462,"presentmon_start_offset_ms":19.1589,"row_span_ms":17855.8618,"csv_span_ms":19909.3027,"span_error_ms":2053.4409000000014,"offset_estimate_ms":2275.3781,"uncertainty_ms":2053.4409000000014,"relative_scale_trusted":false,"absolute_offset_trusted":false,"status":"untrusted","note":"CSV span and observed row span differ beyond tolerance"}
{"type":"end","reason":"requested_stop","ended_monotonic_ns":13483905771700,"ended_wall_ns":1794465101060282700,"duration_ms":20233.8016,"sample_count":77,"sampling_errors":[],"write_error":"","capture_outcome":"valid","valid_frames":1620}
```

### 3.4 Sample cadence

The requested interval was 250 ms (4 Hz), but the observed interval was
about 264 ms (3.78 Hz). The 1 Hz profile observed about 1011 ms.

| Profile | Requested | Observed mean interval | Effective rate | Samples / 20 s |
|---|---:|---:|---:|---:|
| 4 Hz | 250 ms | 264.3 ms | 3.78 Hz | 76–77 |
| 1 Hz | 1000 ms | 1011.0 ms | 0.99 Hz | 20–21 |

This is consistent with the Windows wait-timeout granularity
(approximately 15.6 ms). The sidecar records `sample_interval_ms` as
the requested interval. Consumers should compute actual cadence from
the `sample.t_ms` values rather than assuming exactly 250 ms.

If exact 4 Hz cadence becomes a requirement, the sampler needs a
high-resolution waitable timer or an equivalent reviewed mechanism.
It should not be achieved by busy-waiting, which would increase CPU
overhead.

## 4. Default CSV timebase result

The default CSV path uses `CPUStartTime` as capture-relative
milliseconds. C-1 maps sampler samples to capture time with:

```text
sample_t_capture_ms =
    (sample.perf_counter_ns - capture_started_monotonic_ns) / 1e6
```

It compares the observed CSV row-arrival span with the CSV's
`CPUStartTime` span to decide whether relative scale is trusted.

Real measurements:

| Run | CSV span | Row-arrival span | Difference | Timebase status |
|---|---:|---:|---:|---|
| `c11_normal_a` | 7,940.5 ms | 5,879.2 ms | 2,061.3 ms | `untrusted` |
| GUI 4 Hz, 20 s | 19,909.3 ms | 17,855.9 ms | 2,053.4 ms | `untrusted` |
| GUI 1 Hz, 20 s | 19,869.4 ms | 17,858.0 ms | 2,011.4 ms | `untrusted` |

The first CSV row arrived roughly 2.2 s after PresentMon started even
though its `CPUStartTime` was only a few milliseconds. The rest of the
stream then caught up. This is consistent with PresentMon writing to a
buffered stdout pipe: the first large block is delivered late, so row
arrival time is not the frame time.

C-1 therefore correctly recorded:

```json
"relative_scale_trusted": false,
"absolute_offset_trusted": false,
"status": "untrusted"
```

**Conclusion for the default path:** it does not currently support a
reliable absolute frame-to-sample time mapping. This is a real
limitation, not a calibration failure that can be fixed by assuming a
constant offset. C-2 must not claim frame-level correlation from
default CSV row arrival alone.

## 5. PresentMon QPC output

### 5.1 CLI behavior

PresentMon 2.6 help reports:

```text
--qpc_time
    Output the CPU start time as a performance counter value.
--qpc_time_ms
    Output the CPU start time as a performance counter value
    converted to milliseconds.
```

Real headers:

| Flag | CSV column | Value |
|---|---|---|
| `--qpc_time_ms` | `CPUStartQPCTime` | QPC milliseconds since boot |
| `--qpc_time` | `CPUStartQPC` | raw QPC ticks |

Both modes remove `CPUStartTime`. `validate_capture()` therefore
returns:

```text
CSV is missing required columns: CPUStartTime
```

That is expected. The default CSV parser, frame statistics and
swap-chain analysis must not be changed to accept QPC implicitly.

### 5.2 Clock identity with Python monotonic

On this machine, Windows QPC frequency was 10,000,000 Hz, so one tick
is 100 ns. Direct reads of `QueryPerformanceCounter()` and Python
`time.perf_counter_ns()` were compared three times per run:

| Run | Before capture | At PresentMon start | After capture |
|---|---:|---:|---:|
| QPC ms run | 0.0050 ms | 0.0085 ms | 0.0090 ms |
| QPC ticks run | 0.0041 ms | 0.0069 ms | 0.0063 ms |

These are sequential-read differences, not epoch offsets. Python's
`perf_counter` on Windows is QPC-derived, so the mapping is:

```text
monotonic_ns ≈ round(qpc_ms * 1_000_000)
monotonic_ns ≈ round(qpc_ticks * 1_000_000_000 / qpc_frequency)
```

The measured clock-read error is below 0.01 ms. QPC milliseconds in the
CSV have four decimal places (0.1 µs display resolution); raw ticks
have 100 ns resolution. The practical mapping uncertainty is therefore
well below 0.1 ms, and is not affected by stdout buffering.

### 5.3 Real QPC capture results

| Run | Mode | Rows | QPC first after PresentMon start | QPC last before capture end | Row-arrival lag min / p50 / max |
|---|---|---:|---:|---:|---:|
| `c11_qpc_ms_a` | `--qpc_time_ms` | 445 | +92.862 ms | 585.749 ms | 277 / 1,352 / 2,211 ms |
| `c11_qpc_ticks_b` | `--qpc_time` | 468 | +87.705 ms | 110.779 ms | 106 / 1,578 / 2,183 ms |

The QPC span exactly matched the CSV span in each run (for example,
7,480.253 ms). Row-arrival lag remained large and variable because of
stdout buffering, but that lag no longer affects the frame timestamps:
the QPC timestamp is embedded in the row.

The first frame's QPC timestamp was about 88–93 ms after the recorded
PresentMon process start, and the last frame was before capture end.
This is consistent with PresentMon startup and a real frame stream.

### 5.4 Confidence and limits

| Question | Result |
|---|---|
| Same clock epoch as Python monotonic? | **Yes**, measured difference < 0.01 ms |
| Absolute frame timestamp independent of stdout buffering? | **Yes**, QPC is embedded in the row |
| Error bound for clock mapping | **< 0.1 ms** practical bound |
| Frame-level CPU start vs display time | CPU start only; not display latency |
| Can C-2 claim GPU/CPU causation from this alone? | No; hardware samples remain context |
| Can the default CSV use QPC? | No; header changes and current validation rejects it |

Confidence is **high for the clock mapping** and **medium for
frame-to-hardware-sample association**. A 4 Hz hardware sample is still
coarse compared with individual frames, and QPC does not prove
causality.

### 5.5 Degradation behavior

- Default CSV with row-arrival mismatch: `status="untrusted"`,
  `relative_scale_trusted=false`, `absolute_offset_trusted=false`.
  No interpolation or guessed offset is written.
- Missing/corrupt sidecar: CSV analysis continues independently;
  C-2 must fall back to frame-only evidence.
- QPC not enabled: no absolute mapping is claimed.
- QPC is now an explicit, default-off C-2.0 capture option. The
  analyzer normalizes `CPUStartQPCTime` with the recorded capture-start
  origin; legacy `CPUStartTime` captures are unchanged. See
  `docs/C2_0_QPC_INTEGRATION.md`.

## 6. Sampling overhead

### 6.1 Sampler-only cost

No GUI, no PresentMon; only the real `HardwareSampler` and the live
Palworld target were present. Three 20 s runs per mode. Process CPU is
whole-process CPU; sampler CPU is measured directly from the sampler
thread with `GetThreadTimes` (100 ns resolution).

| Mode | Process CPU (avg) | Process CPU (% of one core) | Sampler thread CPU (avg) | Sampler thread (% of one core) | Samples |
|---|---:|---:|---:|---:|---:|
| Off | 0.0000 s | 0.000% | — | — | 0 |
| 4 Hz | 0.0833 s | 0.416% | 0.0677 s | 0.338% | 76 |
| 1 Hz | 0.0365 s | 0.182% | 0.0208 s | 0.104% | 20 |

The process CPU figure is quantized at about 15.6 ms by Windows, so the
sampler-thread measurement is the more precise attribution. The
4 Hz sampler thread cost is about 0.34% of one logical core; the 1 Hz
cost is about 0.10%.

### 6.2 Whole LagLens process cost

Actual LagLens window classes, `CaptureWorker`, 1 Hz hardware UI timer
and `HardwareSampler`; the window was constructed but not shown. Each
run was a real 20 s Palworld capture. PresentMon is a child process and
is excluded from the LagLens PID measurement.

| Mode | Runs | Avg process CPU | Avg % of one core | Direct sampler-thread CPU | Frames per run |
|---|---:|---:|---:|---:|---:|
| Off | 4 | 0.0859 s | 0.420% | — | 1,426–1,649 |
| 4 Hz | 5 | 0.2031 s | 0.991% | 0.1094 s / 0.534% (2 runs) | 1,613–1,650 |
| 1 Hz | 5 | 0.1438 s | 0.702% | 0.0391 s / 0.191% (2 runs) | 1,415–1,694 |

Observations:

- The sampler-thread cost is stable; whole-process CPU varies because
  of the 15.6 ms process CPU tick and normal game/system load changes.
- 4 Hz adds roughly 0.4–0.6 percentage points of one core to the whole
  LagLens process compared with telemetry off.
- 1 Hz adds roughly 0.1–0.3 percentage points.
- The 4 Hz sampler thread itself (about 0.53%) is within the 1%
  one-core budget. The whole-process figure (about 0.99%) includes the
  GUI/capture baseline and is close to the budget, not well under it.
- Capture validity and frame counts were comparable; no capture
  regression was observed.
- The hidden-window harness does not include visible UI painting, so
  the whole-process figures should be treated as a lower bound for a
  visibly interactive window.

Sidecar size:

| Profile | Sidecar size | Duration | Approx. rate |
|---|---:|---:|---:|
| 4 Hz | 62,012 bytes | 20.23 s | 3.1 KB/s |
| 1 Hz | 17,516 bytes | 20.23 s | 0.87 KB/s |

Low-overhead mode uses the same 1 Hz sampler cadence plus PresentMon's
`--no_track_gpu`. The 1 Hz measurements above are representative of
the sampler side of that profile; PresentMon's own `--no_track_gpu`
traffic reduction was not separately re-measured in C-1.1.

## 7. Time consistency tests added

New file: `tests/test_timebase_validation.py`.

1. `test_perf_counter_and_qpc_share_the_same_epoch` compares
   `time.perf_counter_ns()` with direct `QueryPerformanceCounter`
   reads five times and requires agreement within 5 ms.
2. `test_qpc_tick_and_millisecond_output_match_same_formula` locks in
   the 10 MHz tick-to-millisecond conversion.
3. `test_row_arrival_span_shorter_than_csv_span_is_untrusted` uses the
   real C-1.1 buffering shape and requires the timebase to remain
   `untrusted`.

Full suite result:

```text
Ran 364 tests in 14.591s

OK
```

Previous baseline was 361; C-1.1 adds 3 tests.

## 8. Conclusion

1. The C-1 sidecar data layer is valid in a real elevated Palworld
   capture. All required record types are present, sample counts are
   internally consistent, and duration/wall/monotonic timing is
   consistent within sub-millisecond rounding.
2. The default CSV path does **not** provide a reliable absolute
   frame-to-sampler time mapping. PresentMon stdout buffering causes
   row-arrival spans to be 1–2 s shorter than the CSV span. C-1
   correctly degrades to `untrusted`; this must not be papered over.
3. PresentMon QPC output **does** provide a reliable mapping to Python
   monotonic time: both use the same QPC epoch and the measured
   clock-read difference is below 0.01 ms. C-2.0 now exposes it as a
   default-off opt-in mode; it changes the CSV header, so the default
   product path remains legacy `CPUStartTime`.
4. 4 Hz sampler overhead is about 0.34% of one logical core in
   isolation and about 0.53% inside the real LagLens process. Whole
   process overhead at 4 Hz is about 0.99% versus 0.42% with telemetry
   off; the sampler itself is within the agreed budget, while the whole
   process is close to 1% because of the existing GUI/capture baseline.
5. C-1.1 adds only validation tests/documentation. No C-2 diagnostic
   rules or C-3 UI were implemented.

## 9. Limitations

- One machine, one game, one GPU (NVML index 0, association `unknown`);
  no multi-GPU or hybrid-GPU validation.
- No external hardware/display reference clock. QPC validates the
  monotonic clock mapping, not display latency or physical presentation.
- The GUI overhead harness did not show the window, so it excludes
  visible painting/compositing work.
- Process CPU resolution is about 15.6 ms; direct sampler-thread CPU
  was used for the precise sampler cost.
- Observed 4 Hz cadence is about 3.78 Hz due to Windows timer
  granularity. Exact 4 Hz would need a separate high-resolution timer
  change.
- QPC CSV is supported as a default-off C-2.0 option; the default
  parser/analysis path remains the legacy `CPUStartTime` format.
- No C-2 evidence rules or C-3 explanations were implemented.
