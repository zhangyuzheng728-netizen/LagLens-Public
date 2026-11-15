# Joint AI Analysis

## Shared summary

`ai_insight.build_report_summary` is the single source for the one-shot
quick question and follow-up chat. `frame_viewer.ai_context` passes the
same report, telemetry and network samples.

The report now includes:

- display verdict and longest/stall facts;
- `hardware`: only telemetry saved with this capture, plus per-frame CPU/
  GPU medians;
- `network`: gateway/public aggregate stats and status;
- `joint`: display+network attention flag, network sampling interval,
  and up to three evidence windows;
- missing/alignment markers.

## Hardware scope

The AI request labels every hardware metric:

- target process CPU: process level;
- system CPU and RAM: system level;
- GPU utilisation: device/system level;
- CPUBusy/GPUBusy: per-frame.

If telemetry is absent or misaligned, the request says so and does not
use current values from the Hardware tab. Total system CPU is never
presented as per-core load.

## Evidence windows

Up to three candidate windows are selected locally from:

- display stalls;
- network timeouts/unreachable/errors;
- network latency spikes relative to the capture's own median.

Each window contains capture-relative time, event duration, frame CPU/
GPU medians, target/system/GPU/telemetry medians, gateway/public network
medians/timeouts, baseline values from the preceding nearby normal
window, sample counts, network sampling interval and missing markers.

The network probes are approximately once per second. The request says
this is not millisecond-level causal evidence and never treats a public
probe as game-server latency.

## Prompt behavior

The general system prompt now says to consider actual hardware and
network evidence even when the user only asks about overall performance.
The default quick question is:

> 请全面分析本次检测结果，判断是否存在异常、可能的原因，以及是否需要优化。

Optional quick questions cover smoothness, hardware load, network
performance and optimization advice. They send their own prompt and do
not force the AI to choose between network and local performance.

The `network_vs_local` skill remains optional and is selected from the
question/recent context. It can be dropped when the 4 KiB budget is tight.

## Budget priority

The request keeps:

1. latest question;
2. display/hardware/network core facts and missing markers;
3. selected same-period evidence;
4. optional diagnostics and skill card;
5. old conversation turns.

The chat builder drops the oldest extra turns, optional details, the
skill card, then uses compact report levels 1 and 2. It drops the last
previous turns only after compact level 1, then reduces evidence windows
and finally analysis notes before raising `PromptTooLarge`. The latest
question and core facts are never silently truncated.

## Verification

`tests/test_ai_joint.py` covers:

- all three normal, no forced evidence section;
- network-only anomalies;
- display anomaly with hardware support;
- both sides abnormal;
- missing hardware/network;
- unaligned telemetry;
- probed with no valid public reply;
- a normal global average with a small local stall;
- 4 KiB budget with evidence;
- no IP/raw probe logs.

The real joint PresentMon capture is still not accepted; see
`docs/JOINT_CAPTURE_VALIDATION.md`.
