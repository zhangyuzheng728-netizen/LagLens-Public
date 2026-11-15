# Network Sampling

## Purpose

The **Network** page is a first-class main-window tab:

```text
Hardware → Network → Live Frames → Analysis → AI assistant → Settings
```

It can run alone without a game or frame capture. Every normal Live
Frames monitoring session now starts frames, hardware telemetry and
network probes together from the single Start button. There is no mode
choice that can disable network capture for a normal session.

## Probe method

`network_sampler.py` uses Windows ICMP through `iphlpapi`:

- default gateway discovery via `route print -4`, with `ipconfig` fallback;
- one public comparison target, configurable in the Network page and
  stored in the INI as `network/public_target` (default `1.1.1.1`);
- gateway and public probes run in parallel;
- default interval 1 s, timeout equal to the sample interval;
- a timeout is stored with `rtt_ms: null`, never `0 ms`;
- a missing gateway or failed probe does not block frame capture.

It does not require administrator rights. The sampler is independent of
the PresentMon/ETW capture.

## States and lifecycle

- Opening the Network page does not start a probe.
- **Start network test** starts standalone sampling; **Stop** ends it.
- Switching tabs does not stop the sampler.
- Stopping keeps the last samples visible but starts no new samples.
- A capture attaches to the same sampler. If standalone sampling is
  already running, it is reused; a second sampler is never started. The
  standalone test is left running after the capture ends.
- Samples before the capture origin are not written to the capture
  report.
- If the capture started the sampler, capture end stops it. If standalone
  sampling was already running, capture end leaves it running.
- Closing LagLens stops both modes.

## Sidecar

Joint captures write `<capture>.network.jsonl` next to the CSV:

- `metadata`: schema, CSV basename, target name, public target, interval;
- `sample`: `t_ms` relative to the capture start, monotonic time,
  gateway/public status and RTT;
- `end`: stop reason, outcome, sample count.

No full user path is written. The sidecar is read by the Analysis page;
old reports without it show **未采集网络**.

Each capture also has `<capture>.session.json` with a shared session ID,
the `perf_counter_ns`/wall-clock origin, sidecar statuses and failure
reasons. Telemetry and network metadata carry the same session ID.

QPC validation on this host: `perf_counter` uses
`QueryPerformanceCounter()`, QPC frequency is 10,000,000 Hz, and the
clock-read delta was about -0.006 ms. A real QPC CSV's `origin_qpc_ms`
equals `capture_started_monotonic_ns / 1e6`. The session metadata records
the resolved frame timebase. If QPC alignment is unverified, the report
marks the frame/network time alignment as unverified instead of
claiming correlation.

## Analysis page

The report starts with a local **Conclusion** card: frame verdict,
measured-network verdict and the next action. The hardware card below
shows only telemetry saved with that capture. The network details include
the **Network and frames** card:

- the local display verdict and network verdict together;
- gateway/public median, robust recent variation (MAD), timeouts and
  sample count;
- a separate network chart aligned to the same capture-relative x-axis
  as the frame chart;
- an explicit **Game-server latency is not measured** line;
- no raw probe log, IP or Wi-Fi name in the AI request.

The AI summary receives only local aggregate stats, not the original
probe records.

## Limits

- ICMP may be blocked by a gateway, public target or local firewall. The
  UI then shows no response/timeouts rather than inventing latency.
- A public target is not a game server.
- A probe timeout is not game packet loss.
- A real joint ETW capture could not be run in the development shell
  because it is not elevated. The sampler, recorder, sidecar reader and
  UI were exercised with real standalone probes and synthetic capture
  sidecars for deterministic tests.
