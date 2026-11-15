"""Local two-hour (432k-frame) report/export/AI-budget verification.

Not a capture and not a real API call.  Run manually:

    .venv\\Scripts\\python.exe tests\\verify_two_hour_report.py
"""

import os
import sys
import time

from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import ai_insight  # noqa: E402
import ai_providers  # noqa: E402
import diagnostic_report  # noqa: E402
import diagnostics  # noqa: E402
import frame_stats  # noqa: E402
import i18n  # noqa: E402


def make_frames():

    # 2 hours at 60 FPS plus the long frames themselves.
    count = 432_000
    long_frames = {}

    for index in range(300, count, 1400):

        long_frames[index] = 70.0

    for index, duration in (
        (10_000, 1200.0),
        (60_000, 1500.0),
        (120_000, 1100.0),
        (180_000, 1300.0),
        (240_000, 1600.0),
        (300_000, 1400.0),
        (360_000, 1250.0),
        (390_000, 1300.0),
        (410_000, 1500.0),
        (420_000, 1100.0),
        (425_000, 1200.0),
        # Second half, and the longest event.
        (360_000 + 1, 4200.0),
    ):

        long_frames[index] = duration

    frames = []
    time_ms = 0.0

    for index in range(count):

        duration = long_frames.get(index, 1000.0 / 60.0)
        frames.append(
            {
                "time": time_ms,
                "duration": duration,
                "displayed": True,
                "row": {
                    "Application": "sim-game.exe",
                    "DisplayedTime": str(duration),
                    "FrameTime": str(duration),
                },
            }
        )
        time_ms += duration

    return frames


def make_telemetry(duration_ms):

    samples = []
    interval = 500.0
    count = int(duration_ms // interval) + 1

    for index in range(count):

        samples.append(
            {
                "t_ms": index * interval,
                "target": {"cpu_percent": 25.0},
                "cpu": {"system_percent": 18.0},
                "gpu": {"util_percent": 35.0},
                "ram": {"percent": 55.0},
            }
        )

    return SimpleNamespace(
        available=True,
        complete=True,
        samples=samples,
        metadata={},
    )


def network_summary(duration_s):

    return {
        "available": True,
        "gateway": {
            "timeouts": 37,
            "responses": 500,
            "samples": 537,
            "latency_median_ms": 4.2,
        },
        "public": {
            "timeouts": 41,
            "responses": 495,
            "samples": 536,
            "latency_median_ms": 22.0,
        },
        "coverage_start_s": 0.0,
        "coverage_end_s": duration_s,
    }


def main():

    i18n.get_manager().set_language("zh_CN")
    started = time.monotonic()
    frames = make_frames()
    print("frames:", len(frames))

    stats_started = time.monotonic()
    stats = frame_stats.compute_stats(frames)
    print("stats_s:", round(time.monotonic() - stats_started, 2))

    telemetry = make_telemetry(frames[-1]["time"] + frames[-1]["duration"])
    analyze_started = time.monotonic()
    diag = diagnostics.analyze(
        frames,
        stats=stats,
        telemetry=telemetry,
        target_fps=60,
    )
    print(
        "diagnostics_s:",
        round(time.monotonic() - analyze_started, 2),
        "events:",
        len(diag.events),
        "aligned:",
        diag.telemetry_aligned,
    )
    second_half = [
        event
        for event in diag.events
        if event.time_ms >= 3_600_000.0
    ]
    print(
        "second_half_events:",
        len(second_half),
        "longest_s:",
        round(
            max(
                (event.duration_ms for event in diag.events),
                default=0.0,
            )
            / 1000.0,
            3,
        ),
    )

    report = ai_insight.build_report_summary(
        frames,
        application="sim-game.exe",
        target_fps=60,
        target_fps_explicit=True,
        diagnostic_report=diag,
        stats=stats,
        telemetry=telemetry,
        network=network_summary(
            frames[-1]["time"] / 1000.0
        ),
        file_name="two_hour.csv",
        report_key="two-hour",
    )

    markdown = diagnostic_report.build_markdown(
        diag,
        "two_hour.csv",
        "sim-game.exe",
    )
    export_path = Path(os.environ["TEMP"]) / "laglens_two_hour.md"
    export_path.write_text(markdown, encoding="utf-8")
    longest_hint = str(int(report["events"]["longest_at_s"]))
    export_has_longest = longest_hint in markdown

    print(
        "markdown:",
        "bytes=", len(markdown.encode("utf-8")),
        "has_second_half=", export_has_longest,
        "path=", export_path,
    )
    print(
        "report_second_half_stats:",
        "frames=", report["display"]["frames"],
        "p95_ms=", report["display"]["p95_interval_ms"],
        "p99_ms=", report["display"]["p99_interval_ms"],
        "events=", report["events"]["count"],
        "over_1s=", report["events"]["over_1s"],
        "longest_s=", report["events"]["longest_s"],
        "longest_at_s=", report["events"]["longest_at_s"],
        "aligned=", report["quality"]["telemetry_aligned"],
    )

    question = "请全面分析本次检测结果，判断是否存在异常、可能的原因，以及是否需要优化。"
    body_fn = lambda payload: ai_providers.request_body(
        "deepseek",
        "deepseek-flash",
        payload,
    )
    payload, body = ai_insight.build_chat_payload(
        report,
        [],
        question,
        language="zh_CN",
        structured=False,
        body_fn=body_fn,
        body_limit=4096,
        return_body=True,
    )
    text = payload["messages"][1]["content"]
    sample_text = ai_insight.build_report_text(
        report,
        include_optional="events",
        evidence_limit=3,
        include_analysis_notes=True,
        compact=1,
    )
    sample_lines = [
        line
        for line in sample_text.splitlines()
        if line.startswith("- ") and "持续" in line
    ]

    print(
        "ai_body_bytes:", len(body),
        "key_facts:", {
            key: key in text
            for key in (
                "displayed_frames",
                "display_p95_interval",
                "display_p99_interval",
                "abnormal_frame_events",
                "stalls_over_1s",
                "longest_display_stall",
                "network_gateway_timeouts",
                "network_gateway_timeout_rate",
                "telemetry_alignment",
            )
        },
        "event_sample_lines:", len(sample_lines),
        "samples_include_second_half:", longest_hint in sample_text,
        "has_second_half_time:", longest_hint in text,
    )
    print(
        "total_s:", round(time.monotonic() - started, 2),
    )


if __name__ == "__main__":
    main()
