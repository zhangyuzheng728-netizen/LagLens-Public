"""Shared stutter summary: event totals, alignment wording, no overreach."""

import os
import sys
import unittest

from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import ai_insight  # noqa: E402


def make_frames():
    """Smooth 60 FPS frames with 12 recorded long display intervals."""

    durations = [16.67] * 400
    long_frames = {
        218: 3538.0,
        300: 1212.0,
        500: 1251.0,
        700: 1296.0,
        900: 1232.0,
        1100: 1262.0,
        1300: 1258.0,
        1500: 1221.0,
        1700: 1277.0,
        1900: 1280.0,
        2100: 963.0,
        2300: 355.0,
    }

    frames = []
    time_ms = 0.0

    for index, duration in enumerate(durations):

        value = long_frames.get(index, duration)
        frames.append(
            {
                "time": time_ms,
                "duration": value,
                "displayed": True,
                "row": {
                    "Application": "Cyberpunk2077.exe",
                    "DisplayedTime": str(value),
                    "FrameTime": str(value),
                },
            }
        )
        time_ms += value

    return frames


def make_events():
    events = []

    for index, duration in enumerate(
        (
            3537.953,
            1211.6381,
            355.0,
            1251.0,
            1296.0,
            1232.0,
            1262.0,
            1258.0,
            1221.0,
            1277.0,
            1280.0,
            963.0,
        )
    ):
        events.append(
            SimpleNamespace(
                index=index * 10,
                time_ms=4336.653 + index * 1000.0,
                duration_ms=duration,
                baseline_median_ms=4.28,
                threshold_ms=20.0,
            )
        )

    return events


def make_diagnostic_report(aligned=False):
    finding = SimpleNamespace(
        code="telemetry_timebase_untrusted",
        category="data_quality",
        severity="info",
        confidence="low",
        claim_level="insufficient_evidence",
        summary="Telemetry exists, but the frame timebase is untrusted.",
    )
    return SimpleNamespace(
        events=make_events(),
        findings=[finding],
        telemetry_aligned=aligned,
    )


def make_telemetry(samples=40):
    values = []

    for index in range(samples):

        values.append(
            {
                "t_ms": index * 250.0,
                "target": {"cpu_percent": 40.0},
                "cpu": {"system_percent": 20.0},
                "gpu": {"util_percent": 50.0},
                "ram": {"percent": 65.0},
            }
        )

    return SimpleNamespace(
        available=True,
        complete=True,
        samples=values,
        metadata={},
    )


def build(aligned=False, network=None):
    return ai_insight.build_report_summary(
        make_frames(),
        application="Cyberpunk2077.exe",
        target_fps=60,
        target_fps_explicit=False,
        diagnostic_report=make_diagnostic_report(aligned),
        telemetry=make_telemetry(),
        network=network,
        file_name="cyberpunk.csv",
        report_key="cyberpunk",
    )


def fact(report, fact_id):

    for item in (report.get("diagnosis") or {}).get("facts") or []:

        if item.get("id") == fact_id:
            return item

    return None


class StutterSummaryTests(unittest.TestCase):

    def test_event_total_and_longest_survive_in_shared_facts(self):

        report = build()
        count = fact(report, "abnormal_frame_events")
        over_1s = fact(report, "stalls_over_1s")
        longest = fact(report, "longest_display_stall")

        self.assertIsNotNone(count)
        self.assertEqual(count["value"], 12)
        self.assertIsNotNone(over_1s)
        self.assertEqual(over_1s["value"], 10)
        self.assertIsNotNone(longest)
        self.assertAlmostEqual(longest["value"], 3.538, places=3)
        self.assertIn(
            "not necessarily",
            longest["limit"],
        )

    def test_report_text_keeps_the_total_not_only_one_event(self):

        report = build()
        text = ai_insight.build_report_text(report)

        self.assertIn("异常长帧", text)
        self.assertIn("12", text)
        self.assertIn("10", text)
        self.assertIn(
            "不等于玩家实际看到",
            text,
        )

    def test_compact_chat_text_keeps_total_and_scope_note(self):

        report = build()
        text = ai_insight.build_report_text(
            report,
            include_optional=False,
            include_analysis_notes=False,
            compact=2,
        )

        self.assertIn("abnormal_frame_events: 12", text)
        self.assertIn("stalls_over_1s: 10", text)
        self.assertIn(
            "不等于玩家实际看到卡顿",
            text,
        )
        self.assertIn(
            "longest_display_stall: 3.538",
            text,
        )

    def test_unaligned_telemetry_is_not_reported_as_missing(self):

        report = build(aligned=False)
        text = ai_insight.build_report_text(report)
        missing = " ".join(
            (report.get("evidence") or {}).get("missing") or []
        )
        hardware_line = ai_insight._hardware_line(report)

        self.assertIn("硬件遥测已采集", text)
        self.assertIn("无法与具体停顿对齐", text)
        self.assertNotIn("缺少 CPU/GPU 遥测", text)
        self.assertNotIn("没有可用的 CPU/GPU 遥测", text)
        self.assertIn("硬件遥测已采集", missing)
        self.assertIn("帧时间基准未验证", missing)
        self.assertIn("不足以判断 CPU 或 GPU", hardware_line)
        self.assertNotIn("时间对齐未确认", hardware_line)

    def test_aligned_telemetry_keeps_event_windows(self):

        report = build(aligned=True)
        missing = " ".join(
            (report.get("evidence") or {}).get("missing") or []
        )
        events = (report.get("evidence") or {}).get("events") or []

        self.assertNotIn("帧时间基准未验证", missing)
        self.assertTrue(events)
        self.assertTrue(
            any(
                event.get("baseline_telemetry")
                is not None
                for event in events
            )
        )

    def test_network_timeouts_are_not_attributed_to_the_game_server(self):

        report = build()
        report["network"] = {
            "available": True,
            "probes": {
                "gateway": {
                    "timeouts": 104,
                    "samples": 687,
                },
                "public": {
                    "timeouts": 106,
                    "samples": 687,
                },
            },
        }

        text = ai_insight.build_report_text(report)

        self.assertIn("游戏服务器：未测", text)
        self.assertIn("不能归因给游戏服务器", text)

        compact = ai_insight.build_report_text(
            report,
            include_optional=False,
            include_analysis_notes=False,
            compact=2,
        )
        self.assertIn("未测游戏服务器", compact)
        self.assertIn("不能归因给服务器", compact)

    def test_chat_payload_uses_the_same_event_facts(self):

        report = build()
        payload = ai_insight.build_chat_payload(
            report,
            [],
            "请全面分析本次检测结果。",
            language="zh_CN",
            structured=False,
        )
        text = payload["messages"][1]["content"]

        self.assertIn("abnormal_frame_events: 12", text)
        self.assertIn("stalls_over_1s: 10", text)
        self.assertIn("longest_display_stall: 3.538", text)
        self.assertIn(
            "硬件遥测已采集",
            text,
        )


if __name__ == "__main__":
    unittest.main()
