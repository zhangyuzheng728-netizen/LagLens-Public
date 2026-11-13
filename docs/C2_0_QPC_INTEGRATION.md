# Capture timebases

LagLens supports two PresentMon CSV timestamp formats.

| Timestamp | Mode | Telemetry alignment |
| --- | --- | --- |
| `CPUStartTime` | Legacy / Relative, the default | Capture-relative time. Does not claim an absolute QPC mapping. |
| `CPUStartQPCTime` | QPC, opt-in | A verified capture-start origin allows absolute alignment. If the origin cannot be verified, LagLens labels the result and limits the conclusions. |

The QPC option passes `--qpc_time_ms` to PresentMon. For display and analysis,
LagLens normalizes raw QPC timestamps to capture-relative milliseconds.
Without a trusted capture-start origin, the first valid frame can serve as
a relative origin, but the result must not be treated as a verified clock
alignment. CSV rows are not rewritten.

See [frame_timebase.py](../frame_timebase.py) for the timebase model and
[tests/test_frame_timebase.py](../tests/test_frame_timebase.py) for examples.
