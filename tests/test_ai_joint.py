"""Joint frame/hardware/network evidence in AI requests."""

import sys
import unittest

from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import ai_insight  # noqa: E402
import network_sampler  # noqa: E402


def make_frames(
    count=600,
    stall_index=None,
    stall_ms=500.0,
):

    frames = []
    time_ms = 0.0

    for index in range(count):

        interval = 1000.0 / 60.0

        if index == stall_index:
            interval = stall_ms

        frames.append(
            {
                "time": time_ms,
                "duration": interval,
                "displayed": True,
                "row": {
                    "Application": "test-game.exe",
                    "DisplayedTime": str(interval),
                    "FrameTime": str(interval),
                    "CPUBusy": (
                        "80.0"
                        if stall_index is not None
                        and abs(index - stall_index) <= 2
                        else "16.0"
                    ),
                    "GPUBusy": (
                        "30.0"
                        if stall_index is not None
                        and abs(index - stall_index) <= 2
                        else "8.0"
                    ),
                },
            }
        )
        time_ms += interval

    return frames


def make_telemetry(
    end_ms=3000.0,
    event_ms=None,
):

    samples = []
    time_ms = 0.0

    while time_ms <= end_ms:

        high = (
            event_ms is not None
            and event_ms - 100.0 <= time_ms <= event_ms + 700.0
        )
        samples.append(
            {
                "t_ms": time_ms,
                "target": {
                    "cpu_percent": 85.0 if high else 20.0,
                },
                "cpu": {
                    "system_percent": 70.0 if high else 25.0,
                },
                "gpu": {
                    "util_percent": 40.0 if high else 35.0,
                },
                "ram": {"percent": 60.0},
            }
        )
        time_ms += 100.0

    return SimpleNamespace(
        available=True,
        complete=True,
        metadata={"sampling": {"interval_ms": 100}},
        samples=samples,
    )


def network_samples(
    end_ms=6000.0,
    timeout_ms=None,
    stable=True,
):

    samples = []
    time_ms = 0.0
    index = 0

    while time_ms <= end_ms:

        status = "ok"
        rtt = 20.0 + (index % 2)
        gateway = 4.0

        if timeout_ms is not None and abs(time_ms - timeout_ms) < 1:
            status = "timeout"
            rtt = None

        if not stable and abs(time_ms - 2000.0) < 1:
            rtt = 100.0
            gateway = 30.0

        samples.append(
            {
                "t_ms": time_ms,
                "gateway": {
                    "status": "ok",
                    "rtt_ms": gateway,
                },
                "public": {
                    "status": status,
                    "rtt_ms": rtt,
                },
            }
        )
        time_ms += 500.0
        index += 1

    return samples


def make_report(
    frames,
    telemetry=None,
    nets=None,
):

    nets = nets if nets is not None else network_samples()
    summary = network_sampler.summarize_samples(nets)

    return ai_insight.build_report_summary(
        frames,
        application="test-game.exe",
        target_fps=60,
        target_fps_explicit=True,
        telemetry=telemetry,
        network=summary,
        network_samples=nets,
        file_name="joint.csv",
        report_key="joint",
    )


class JointReportTests(unittest.TestCase):

    def test_hardware_scope_and_alignment_enter_the_request(self):

        report = make_report(
            make_frames(count=120),
            telemetry=make_telemetry(end_ms=2000),
        )
        text = ai_insight.build_report_text(report)

        self.assertIn("硬件（本次实际保存）", text)
        self.assertIn("目标进程 CPU 中位", text)
        self.assertIn("进程级", text)
        self.assertIn("每帧 CPUBusy 中位", text)
        self.assertIn("每帧", text)
        self.assertIn("网络：", text)
        self.assertNotIn("192.168", text)
        self.assertNotIn("1.1.1.1", text)

    def test_all_three_normal_has_no_forced_evidence_section(self):

        report = make_report(
            make_frames(count=120),
            telemetry=make_telemetry(end_ms=2000),
        )
        text = ai_insight.build_report_text(report)

        self.assertIn("硬件", text)
        self.assertIn("网络：", text)
        self.assertNotIn("同段证据", text)
        self.assertFalse(
            report["joint"]["needs_attention"]
        )

    def test_generic_overall_question_considers_all_three_sides(self):

        report = make_report(
            make_frames(count=120),
            telemetry=make_telemetry(end_ms=2000),
        )
        payload = ai_insight.build_chat_payload(
            report,
            [],
            "这次表现怎么样？",
        )
        text = "\n".join(
            message["content"]
            for message in payload["messages"]
        )

        self.assertIn("cpu_process_median", text)
        self.assertIn("network_gateway_samples", text)
        self.assertNotIn(
            "诊断 Skill｜网络还是本机",
            text,
        )
        self.assertIn("这次表现怎么样", text)

    def test_unaligned_telemetry_is_marked(self):

        telemetry = make_telemetry(end_ms=1000)
        for sample in telemetry.samples:
            sample["t_ms"] += 10000.0

        report = make_report(
            make_frames(count=120),
            telemetry=telemetry,
        )
        text = ai_insight.build_report_text(report)

        self.assertFalse(report["hardware"]["aligned"])
        self.assertIn("未覆盖采集区间", text)

    def test_probed_but_no_valid_reply_is_not_normal(self):

        samples = network_samples(end_ms=3000)
        for sample in samples:
            sample["public"] = {
                "status": "timeout",
                "rtt_ms": None,
            }

        report = make_report(
            make_frames(count=120),
            telemetry=make_telemetry(end_ms=3000),
            nets=samples,
        )
        text = ai_insight.build_report_text(report)

        self.assertIn(
            report["joint"]["network_status"],
            ("fluctuating", "no_response"),
        )
        self.assertIn("公网探测", text)
        self.assertIn("超时", text)
        self.assertIn("同段证据", text)

    def test_small_stall_is_not_averaged_away(self):

        frames = make_frames(
            count=600,
            stall_index=300,
        )
        report = make_report(
            frames,
            telemetry=make_telemetry(
                end_ms=6000,
                event_ms=5000,
            ),
            nets=network_samples(end_ms=6000),
        )
        text = ai_insight.build_report_text(report)

        self.assertTrue(
            report["joint"]["needs_attention"]
        )
        self.assertIn("同段证据", text)
        self.assertIn(
            "画面停顿",
            text,
        )
        self.assertIn("每帧 CPUBusy", text)
        self.assertIn("网络样本间隔", text)

    def test_only_network_abnormality_has_its_own_window(self):

        report = make_report(
            make_frames(count=120),
            telemetry=make_telemetry(end_ms=3000),
            nets=network_samples(
                end_ms=6000,
                timeout_ms=2000.0,
            ),
        )
        text = ai_insight.build_report_text(report)

        self.assertTrue(
            report["joint"]["needs_attention"]
        )
        self.assertFalse(
            report["classification"]["needs_attention"]
        )
        self.assertIn("网络超时", text)
        self.assertIn("同段证据", text)

    def test_both_sides_are_reported_separately(self):

        frames = make_frames(
            count=600,
            stall_index=300,
        )
        report = make_report(
            frames,
            telemetry=make_telemetry(
                end_ms=6000,
                event_ms=5000,
            ),
            nets=network_samples(
                end_ms=6000,
                timeout_ms=2000.0,
            ),
        )
        text = ai_insight.build_report_text(report)

        self.assertIn("画面停顿", text)
        self.assertIn("网络超时", text)
        self.assertIn("同段证据", text)

    def test_missing_hardware_and_network_are_not_normal(self):

        report = make_report(
            make_frames(count=120),
            telemetry=None,
            nets=[],
        )
        text = ai_insight.build_report_text(report)

        self.assertIn("硬件（本次实际保存）", text)
        self.assertIn("未采集：目标进程 CPU", text)
        self.assertIn("网络：未测量", text)

    def test_chat_budget_keeps_question_and_joint_evidence(self):

        frames = make_frames(
            count=600,
            stall_index=300,
        )
        report = make_report(
            frames,
            telemetry=make_telemetry(
                end_ms=6000,
                event_ms=5000,
            ),
            nets=network_samples(
                end_ms=6000,
                timeout_ms=2000.0,
            ),
        )
        history = [
            {
                "role": "user",
                "content": "旧问题 " + "x" * 400,
            },
            {
                "role": "assistant",
                "content": "旧回答 " + "y" * 400,
            },
        ]
        payload = ai_insight.build_chat_payload(
            report,
            history,
            "这次更像网络问题还是本机性能问题？",
        )
        body = ai_insight.encode_payload(payload)
        text = "\n".join(
            message["content"]
            for message in payload["messages"]
        )

        self.assertLessEqual(len(body), 4096)
        self.assertIn(
            "这次更像网络问题还是本机性能问题？",
            text,
        )
        self.assertIn("同段证据", text)
        self.assertNotIn("192.168", text)

    def test_metric_question_does_not_load_network_skill(self):

        report = make_report(
            make_frames(count=120),
            telemetry=make_telemetry(end_ms=2000),
        )
        payload = ai_insight.build_chat_payload(
            report,
            [],
            "1% Low 是什么？",
        )
        text = "\n".join(
            message["content"]
            for message in payload["messages"]
        )

        self.assertNotIn("诊断 Skill｜网络还是本机", text)
        self.assertIn("1% Low 是什么", text)


if __name__ == "__main__":

    unittest.main()
