"""Evidence-driven diagnosis: scenario, facts, quality and validation."""

import json
import os
import sys
import time
import unittest

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import ai_chat  # noqa: E402
import diagnosis_pipeline  # noqa: E402


def network_probe(samples, timeouts, median_ms=20.0, jitter_ms=1.0):
    return {
        "samples": samples,
        "responses": max(0, samples - timeouts),
        "timeouts": timeouts,
        "median_ms": median_ms,
        "jitter_ms": jitter_ms,
        "loss_percent": round(100.0 * timeouts / samples, 2)
        if samples
        else None,
        "range_s": [0.0, 60.0],
    }


def make_video_report(
    application="douyin.exe",
    fps=27.0,
    cpu_busy=32.0,
    gpu_util=20.0,
    target_cpu=75.0,
    samples=60,
    timeouts=0,
    alignment="verified_qpc",
    network_available=True,
):
    return {
        "application": application,
        "file": "douyin.csv",
        "report_key": "douyin-key",
        "target_fps": None,
        "target_source": "unknown",
        "display": {
            "available": True,
            "average_fps": fps,
            "frames": 600,
            "seconds": 22.2,
            "median_interval_ms": 1000.0 / fps,
            "p95_interval_ms": 1000.0 / fps,
            "p99_interval_ms": 1000.0 / fps,
            "longest_stall_s": 0.3,
            "longest_stall_at_s": 5.0,
            "cap_fps": None,
        },
        "game_output": {"average_fps": fps, "p95_frame_ms": 1000.0 / fps},
        "hardware": {
            "available": True,
            "aligned": True,
            "samples": 80,
            "target_cpu_median": target_cpu,
            "system_cpu_median": 60.0,
            "gpu_util_median": gpu_util,
            "ram_percent_median": 55.0,
            "frame_cpu_busy_median_ms": cpu_busy,
            "frame_gpu_busy_median_ms": 8.0,
        },
        "network": {
            "available": network_available,
            "probes": {
                "gateway": network_probe(samples, timeouts),
                "public": network_probe(samples, timeouts),
            },
        },
        "alignment_quality": alignment,
        "quality": {
            "sync_quality": alignment,
            "telemetry_available": True,
        },
        "joint": {
            "network_status": "stable",
            "evidence": [{"at_s": 5.0, "kind": "stall"}],
        },
        "session_status": "complete",
    }


def make_chrome_report():
    """Facts from chrome.exe_20261113_171411_475047.csv (real capture)."""

    report = make_video_report(
        application="chrome.exe",
        fps=67.76,
        cpu_busy=6.92,
        gpu_util=7.0,
        target_cpu=14.7,
        samples=0,
        timeouts=0,
        alignment="verified_qpc",
        network_available=False,
    )
    report["network"]["probes"] = {}
    report["display"].update(
        {
            "average_fps": 67.76,
            "frames": 1791,
            "seconds": 26.431,
            "median_interval_ms": 6.95,
            "p95_interval_ms": 9.85,
            "p99_interval_ms": 9.9,
            "longest_stall_s": 5.695,
            "longest_stall_at_s": 11.125,
        }
    )
    report["game_output"] = {
        "average_fps": 68.34,
        "p95_frame_ms": 9.85,
    }
    report["hardware"].update(
        {
            "target_cpu_median": 14.7,
            "system_cpu_median": 4.5,
            "gpu_util_median": 7.0,
            "ram_percent_median": 50.2,
            "frame_cpu_busy_median_ms": 6.92,
            "frame_gpu_busy_median_ms": 1.49,
        }
    )
    report["joint"]["network_status"] = "unmeasured"
    report["session_status"] = "unknown"
    return report


def structured(
    conclusion="no_clear_issue",
    strength="limited_evidence",
    observations=None,
    hypotheses=None,
    missing=None,
    actions=None,
):
    return {
        "conclusion": conclusion,
        "evidence_strength": strength,
        "observations": observations or [],
        "hypotheses": hypotheses or [],
        "missing_evidence": missing or [],
        "recommended_actions": actions or [],
    }


def valid_for(report):
    diagnosis = diagnosis_pipeline.build_diagnosis(report)
    return diagnosis


class ScenarioTests(unittest.TestCase):

    def test_douyin_process_is_video(self):
        scenario = diagnosis_pipeline.detect_scenario(
            r"C:\Games\douyin.exe"
        )

        self.assertEqual(scenario["id"], "video")
        self.assertEqual(scenario["source"], "process_name")

    def test_user_override_wins(self):
        scenario = diagnosis_pipeline.detect_scenario(
            "douyin.exe",
            "game",
        )

        self.assertEqual(scenario["id"], "game")
        self.assertEqual(scenario["source"], "user")
        self.assertEqual(scenario["confidence"], "high")

    def test_unknown_application_stays_unknown(self):
        scenario = diagnosis_pipeline.detect_scenario("mystery.exe")

        self.assertEqual(scenario["id"], "unknown")
        self.assertEqual(scenario["confidence"], "insufficient")

    def test_browser_activity_is_not_a_claim(self):
        scenario = diagnosis_pipeline.detect_scenario("chrome.exe")

        self.assertEqual(scenario["id"], "browser")
        self.assertEqual(scenario["confidence"], "low")
        self.assertIn("unknown", scenario["reason"])


class VideoCaseTests(unittest.TestCase):
    """The Douyin regression: no CPU bottleneck from 27 FPS alone."""

    def setUp(self):
        self.report = make_video_report()
        self.diagnosis = diagnosis_pipeline.build_diagnosis(
            self.report
        )
        self.facts = {
            fact["id"]: fact
            for fact in self.diagnosis["facts"]
        }

    def test_scenario_is_video_and_local_performance_is_not_allowed(self):
        self.assertEqual(
            self.diagnosis["scenario"]["id"],
            "video",
        )
        self.assertNotIn(
            "local_performance",
            self.diagnosis["allowed_conclusions"],
        )

    def test_source_fps_fact_is_unknown_and_marked_invalid(self):
        source = self.facts["video_source_fps"]

        self.assertIsNone(source["value"])
        self.assertFalse(source["valid"])
        self.assertIn("unknown", source["limit"])

    def test_display_fps_fact_carries_the_limit(self):
        display = self.facts["display_fps"]

        self.assertEqual(display["value"], 27.0)
        self.assertIn("not the source", display["limit"])

    def test_cpu_bottleneck_conclusion_is_rejected(self):
        answer = structured(
            conclusion="local_performance",
            hypotheses=[
                {
                    "text": "CPU 单核瓶颈",
                    "fact_ids": [
                        "cpu_process_median",
                        "frame_cpu_busy_median",
                    ],
                    "alternative": "",
                    "confidence": "likely",
                }
            ],
        )

        errors = diagnosis_pipeline.validate_structured(
            answer,
            self.diagnosis,
            self.report,
        )

        self.assertTrue(
            any("conclusion not supported" in item for item in errors)
        )

    def test_high_cpu_and_low_gpu_alone_do_not_prove_a_bottleneck(self):
        answer = structured(
            hypotheses=[
                {
                    "text": "CPU 性能不足导致掉帧",
                    "fact_ids": [
                        "cpu_process_median",
                        "frame_cpu_busy_median",
                        "gpu_util_median",
                    ],
                    "alternative": "视频源帧率未知",
                    "confidence": "likely",
                }
            ],
            missing=["video_source_fps"],
        )

        errors = diagnosis_pipeline.validate_structured(
            answer,
            self.diagnosis,
            self.report,
        )

        self.assertTrue(
            any(
                "performance problem without source evidence"
                in item
                for item in errors
            )
        )

    def test_cpu_bottleneck_wording_is_also_rejected(self):
        answer = structured(
            hypotheses=[
                {
                    "text": "CPU 是瓶颈",
                    "fact_ids": [
                        "cpu_process_median",
                        "gpu_util_median",
                    ],
                    "alternative": "",
                    "confidence": "possible",
                }
            ],
        )

        errors = diagnosis_pipeline.validate_structured(
            answer,
            self.diagnosis,
            self.report,
        )

        self.assertTrue(
            any(
                "performance problem without source evidence"
                in item
                for item in errors
            )
        )

    def test_conservative_answer_passes(self):
        answer = structured(
            conclusion="no_clear_issue",
            observations=[
                {
                    "fact_id": "display_fps",
                    "text": "显示平均 27 FPS，但这只是显示节奏。",
                }
            ],
            hypotheses=[
                {
                    "text": "可能是视频源本身只有较低帧率",
                    "fact_ids": [
                        "display_fps",
                        "video_source_fps",
                    ],
                    "alternative": "也可能是解码或渲染问题",
                    "confidence": "unclear",
                }
            ],
            missing=["视频源帧率", "视频是否真实掉帧"],
            actions=[
                {
                    "text": "对比同一视频在播放器内的原始帧率",
                    "risk": "low",
                    "verification": "播放器统计或视频文件信息",
                }
            ],
        )
        # Citing video_source_fps is not allowed because it is invalid.
        errors = diagnosis_pipeline.validate_structured(
            answer,
            self.diagnosis,
            self.report,
        )

        self.assertTrue(
            any("invalid fact: video_source_fps" in item for item in errors)
        )

        answer["hypotheses"][0]["fact_ids"] = ["display_fps"]
        errors = diagnosis_pipeline.validate_structured(
            answer,
            self.diagnosis,
            self.report,
        )

        self.assertEqual(errors, [])


class DiagnosisGuidanceTests(unittest.TestCase):

    def test_clean_game_report_allows_no_clear_issue(self):
        report = make_video_report(
            application="game.exe",
            fps=60.0,
            cpu_busy=8.0,
            gpu_util=70.0,
            target_cpu=30.0,
        )
        diagnosis = diagnosis_pipeline.build_diagnosis(report)
        answer = structured(
            observations=[
                {
                    "fact_id": "display_fps",
                    "text": "显示平均 60 FPS。",
                }
            ],
            actions=[
                {
                    "text": "这次无需优化。",
                    "risk": "low",
                    "verification": "",
                }
            ],
        )

        self.assertIn(
            "no_clear_issue",
            diagnosis["allowed_conclusions"],
        )
        self.assertEqual(
            diagnosis_pipeline.validate_structured(
                answer,
                diagnosis,
                report,
            ),
            [],
        )

    def test_insufficient_data_allows_insufficient_evidence(self):
        report = make_video_report(application="game.exe")
        report["display"]["available"] = False
        report["display"]["frames"] = 0
        report["display"]["seconds"] = 0.0
        report["hardware"]["available"] = False
        report["hardware"]["aligned"] = False
        diagnosis = diagnosis_pipeline.build_diagnosis(report)
        answer = structured(
            conclusion="insufficient_evidence",
            strength="insufficient_evidence",
            missing=["缺少有效的显示数据"],
        )

        self.assertEqual(
            diagnosis["evidence_strength"],
            "insufficient_evidence",
        )
        self.assertEqual(
            diagnosis_pipeline.validate_structured(
                answer,
                diagnosis,
                report,
            ),
            [],
        )

    def test_hardware_bottleneck_without_telemetry_is_rejected(self):
        report = make_video_report(application="game.exe")
        hardware = report["hardware"]
        hardware["available"] = False
        hardware["aligned"] = False
        for key in (
            "target_cpu_median",
            "system_cpu_median",
            "gpu_util_median",
            "ram_percent_median",
            "frame_cpu_busy_median_ms",
            "frame_gpu_busy_median_ms",
        ):
            hardware[key] = None
        diagnosis = diagnosis_pipeline.build_diagnosis(report)
        answer = structured(
            hypotheses=[
                {
                    "text": "CPU 性能不足导致卡顿",
                    "fact_ids": ["longest_display_stall"],
                    "alternative": "",
                    "confidence": "likely",
                }
            ],
        )

        errors = diagnosis_pipeline.validate_structured(
            answer,
            diagnosis,
            report,
        )

        self.assertTrue(
            any(
                "hardware bottleneck claim" in item
                for item in errors
            )
        )

    def test_hardware_claim_with_telemetry_is_allowed(self):
        report = make_video_report(application="game.exe")
        diagnosis = diagnosis_pipeline.build_diagnosis(report)
        answer = structured(
            hypotheses=[
                {
                    "text": "CPU 占用偏高，可能导致帧时间波动",
                    "fact_ids": ["cpu_process_median"],
                    "alternative": "也可能是游戏本身出帧问题",
                    "confidence": "possible",
                }
            ],
        )

        errors = diagnosis_pipeline.validate_structured(
            answer,
            diagnosis,
            report,
        )

        self.assertFalse(
            any(
                "hardware bottleneck claim" in item
                for item in errors
            )
        )

    def test_action_without_evidence_is_rejected(self):
        report = make_video_report(application="game.exe")
        diagnosis = diagnosis_pipeline.build_diagnosis(report)
        answer = structured(
            actions=[
                {
                    "text": "关闭所有后台程序",
                    "risk": "low",
                    "verification": "",
                }
            ],
        )

        errors = diagnosis_pipeline.validate_structured(
            answer,
            diagnosis,
            report,
        )

        self.assertTrue(
            any(
                "no supporting evidence" in item
                for item in errors
            )
        )

    def test_action_with_missing_evidence_is_allowed(self):
        report = make_video_report(application="game.exe")
        diagnosis = diagnosis_pipeline.build_diagnosis(report)
        answer = structured(
            missing=["缺少 CPU/GPU 遥测"],
            actions=[
                {
                    "text": "下次采集时记录硬件遥测",
                    "risk": "low",
                    "verification": "查看遥测状态",
                }
            ],
        )

        self.assertEqual(
            diagnosis_pipeline.validate_structured(
                answer,
                diagnosis,
                report,
            ),
            [],
        )

    def test_network_claim_without_network_data_is_rejected(self):
        report = make_video_report(
            application="game.exe",
            network_available=False,
            samples=0,
            timeouts=0,
        )
        report["network"]["probes"] = {}
        diagnosis = diagnosis_pipeline.build_diagnosis(report)
        answer = structured(
            conclusion="local_performance",
            hypotheses=[
                {
                    "text": "网络正常，所以是本机问题",
                    "fact_ids": ["frame_cpu_busy_median"],
                    "alternative": "",
                    "confidence": "possible",
                }
            ],
        )

        errors = diagnosis_pipeline.validate_structured(
            answer,
            diagnosis,
            report,
        )

        self.assertTrue(
            any(
                "network claim without network data" in item
                for item in errors
            )
        )


class RealCaptureValidationRegressionTests(unittest.TestCase):
    """Regression for the real browser capture that failed on "11 秒"."""

    def setUp(self):
        self.report = make_chrome_report()
        self.diagnosis = diagnosis_pipeline.build_diagnosis(
            self.report
        )
        self.facts = {
            fact["id"]: fact
            for fact in self.diagnosis["facts"]
        }

    def test_stall_event_time_accepts_11_seconds(self):
        answer = structured(
            observations=[
                {
                    "fact_id": "longest_display_stall",
                    "text": (
                        "在约 11 秒处出现最长显示停顿，"
                        "持续 5.695 秒。"
                    ),
                }
            ],
        )

        self.assertEqual(
            diagnosis_pipeline.validate_structured(
                answer,
                self.diagnosis,
                self.report,
            ),
            [],
        )

    def test_stall_event_time_is_not_the_stall_duration(self):
        event = self.facts["longest_display_stall"]

        self.assertAlmostEqual(event["value"], 5.695)
        self.assertAlmostEqual(event["time_s"], 11.125)
        self.assertEqual(event["range_s"], [11.125, 11.125])

    def test_stall_event_time_on_wrong_fact_is_rejected(self):
        answer = structured(
            observations=[
                {
                    "fact_id": "display_interval_median",
                    "text": "在约 11 秒处出现最长显示停顿。",
                }
            ],
        )

        errors = diagnosis_pipeline.validate_structured(
            answer,
            self.diagnosis,
            self.report,
        )

        self.assertTrue(
            any("does not match its fact" in item for item in errors)
        )

    def test_wrong_event_time_is_rejected(self):
        answer = structured(
            observations=[
                {
                    "fact_id": "longest_display_stall",
                    "text": "在约 12 秒处出现最长显示停顿。",
                }
            ],
        )

        errors = diagnosis_pipeline.validate_structured(
            answer,
            self.diagnosis,
            self.report,
        )

        self.assertTrue(
            any("does not match its fact" in item for item in errors)
        )

    def test_stall_duration_in_milliseconds_is_accepted(self):
        answer = structured(
            observations=[
                {
                    "fact_id": "longest_display_stall",
                    "text": "最长显示停顿持续 5695 ms。",
                }
            ],
        )

        self.assertEqual(
            diagnosis_pipeline.validate_structured(
                answer,
                self.diagnosis,
                self.report,
            ),
            [],
        )

    def test_capture_duration_is_accepted_for_display_window(self):
        answer = structured(
            observations=[
                {
                    "fact_id": "display_fps",
                    "text": (
                        "本次采集约 26.4 秒，平均显示 67.76 FPS。"
                    ),
                }
            ],
        )

        self.assertEqual(
            diagnosis_pipeline.validate_structured(
                answer,
                self.diagnosis,
                self.report,
            ),
            [],
        )

    def test_browser_long_stall_is_not_automatically_a_stutter(self):
        answer = structured(
            hypotheses=[
                {
                    "text": "浏览器发生卡顿，性能不足",
                    "fact_ids": ["longest_display_stall"],
                    "alternative": "",
                    "confidence": "likely",
                }
            ],
        )

        errors = diagnosis_pipeline.validate_structured(
            answer,
            self.diagnosis,
            self.report,
        )

        self.assertTrue(
            any(
                "performance problem without source evidence" in item
                for item in errors
            )
        )

    def test_browser_stutter_observation_is_rejected(self):
        answer = structured(
            observations=[
                {
                    "fact_id": "longest_display_stall",
                    "text": "浏览器发生了卡顿。",
                }
            ],
        )

        errors = diagnosis_pipeline.validate_structured(
            answer,
            self.diagnosis,
            self.report,
        )

        self.assertTrue(
            any(
                "observation claims a performance problem" in item
                for item in errors
            )
        )

    def test_verified_qpc_without_network_is_not_network_normal(self):
        answer = structured(
            hypotheses=[
                {
                    "text": "时间对齐已验证，网络正常",
                    "fact_ids": ["network_alignment"],
                    "alternative": "",
                    "confidence": "possible",
                }
            ],
        )

        errors = diagnosis_pipeline.validate_structured(
            answer,
            self.diagnosis,
            self.report,
        )

        self.assertTrue(
            any(
                "network claim without network data" in item
                for item in errors
            )
        )
        self.assertEqual(
            self.facts["network_available"]["value"],
            "unavailable",
        )
        self.assertIn(
            "does not mean the network is normal",
            self.facts["network_alignment"]["limit"],
        )

    def test_simultaneous_network_claim_without_network_data_is_rejected(self):
        answer = structured(
            hypotheses=[
                {
                    "text": "网络超时和卡顿同时出现",
                    "fact_ids": [
                        "network_public_timeouts",
                        "longest_display_stall",
                    ],
                    "alternative": "",
                    "confidence": "possible",
                }
            ],
        )

        errors = diagnosis_pipeline.validate_structured(
            answer,
            self.diagnosis,
            self.report,
        )

        self.assertTrue(
            any(
                "verified alignment and network data" in item
                for item in errors
            )
        )

    def test_session_status_unknown_is_not_rewritten_as_success(self):
        fact = self.facts["session_status"]

        self.assertEqual(fact["value"], "unknown")
        self.assertIn("unknown is not success", fact["limit"])


class StructuredIdRepairTests(unittest.TestCase):
    """Models sometimes copy 'id=value' as the whole fact ID."""

    def setUp(self):
        self.report = make_chrome_report()
        self.diagnosis = diagnosis_pipeline.build_diagnosis(
            self.report
        )

    def test_copied_value_is_reduced_to_the_fact_id(self):
        answer = structured(
            observations=[
                {
                    "fact_id": "display_fps=67.76FPS",
                    "text": "平均显示 67.76 FPS。",
                }
            ],
        )

        normalized, repairs = (
            diagnosis_pipeline.normalize_structured_ids(
                answer,
                self.diagnosis,
            )
        )

        self.assertEqual(
            normalized["observations"][0]["fact_id"],
            "display_fps",
        )
        self.assertTrue(repairs)
        self.assertEqual(
            diagnosis_pipeline.validate_structured(
                normalized,
                self.diagnosis,
                self.report,
            ),
            [],
        )

    def test_wrong_number_is_still_rejected_after_id_repair(self):
        answer = structured(
            observations=[
                {
                    "fact_id": "display_fps=60FPS",
                    "text": "平均显示 60 FPS。",
                }
            ],
        )

        normalized, _repairs = (
            diagnosis_pipeline.normalize_structured_ids(
                answer,
                self.diagnosis,
            )
        )
        errors = diagnosis_pipeline.validate_structured(
            normalized,
            self.diagnosis,
            self.report,
        )

        self.assertEqual(
            normalized["observations"][0]["fact_id"],
            "display_fps",
        )
        self.assertTrue(
            any("does not match its fact" in item for item in errors)
        )

    def test_hypothesis_fact_id_list_is_repaired(self):
        answer = structured(
            hypotheses=[
                {
                    "text": "可能是浏览器的显示节奏问题",
                    "fact_ids": [
                        "longest_display_stall=5.695s",
                    ],
                    "alternative": "",
                    "confidence": "possible",
                }
            ],
        )

        normalized, repairs = (
            diagnosis_pipeline.normalize_structured_ids(
                answer,
                self.diagnosis,
            )
        )

        self.assertEqual(
            normalized["hypotheses"][0]["fact_ids"],
            ["longest_display_stall"],
        )
        self.assertTrue(repairs)


class NetworkEvidenceTests(unittest.TestCase):

    def test_timeout_rate_depends_on_total_samples(self):
        few = diagnosis_pipeline.build_diagnosis(
            make_video_report(samples=20, timeouts=9)
        )
        many = diagnosis_pipeline.build_diagnosis(
            make_video_report(samples=1000, timeouts=9)
        )
        few_facts = {fact["id"]: fact for fact in few["facts"]}
        many_facts = {fact["id"]: fact for fact in many["facts"]}

        self.assertAlmostEqual(
            few_facts["network_gateway_timeout_rate"]["value"],
            0.45,
        )
        self.assertAlmostEqual(
            many_facts["network_gateway_timeout_rate"]["value"],
            0.009,
        )
        self.assertEqual(
            few_facts["network_gateway_timeouts"]["value"],
            many_facts["network_gateway_timeouts"]["value"],
        )

    def test_missing_samples_do_not_judge_a_rate(self):
        report = make_video_report(
            network_available=False,
            samples=0,
            timeouts=0,
        )
        report["network"]["probes"] = {}
        diagnosis = diagnosis_pipeline.build_diagnosis(report)
        facts = {fact["id"]: fact for fact in diagnosis["facts"]}
        rate = facts["network_public_timeout_rate"]

        self.assertIsNone(rate["value"])
        self.assertFalse(rate["valid"])
        self.assertIn("do not judge", rate["limit"])

        answer = structured(
            conclusion="network",
            hypotheses=[
                {
                    "text": "公网超时率很高",
                    "fact_ids": ["network_public_timeout_rate"],
                    "alternative": "",
                    "confidence": "likely",
                }
            ],
        )
        errors = diagnosis_pipeline.validate_structured(
            answer,
            diagnosis,
            report,
        )

        self.assertTrue(
            any("invalid fact" in item or "not supported" in item for item in errors)
        )

    def test_timeout_requires_a_number_when_cited(self):
        report = make_video_report(samples=20, timeouts=9)
        diagnosis = diagnosis_pipeline.build_diagnosis(report)
        answer = structured(
            observations=[
                {
                    "fact_id": "network_gateway_timeout_rate",
                    "text": "网关超时率 90%。",
                }
            ],
        )

        errors = diagnosis_pipeline.validate_structured(
            answer,
            diagnosis,
            report,
        )

        self.assertTrue(
            any("does not match" in item for item in errors)
        )

    def test_percent_matches_ratio_fact(self):
        report = make_video_report(samples=20, timeouts=9)
        diagnosis = diagnosis_pipeline.build_diagnosis(report)
        answer = structured(
            observations=[
                {
                    "fact_id": "network_gateway_timeout_rate",
                    "text": "网关超时率 45%。",
                }
            ],
        )

        errors = diagnosis_pipeline.validate_structured(
            answer,
            diagnosis,
            report,
        )

        self.assertEqual(errors, [])

    def test_seconds_and_milliseconds_are_comparable(self):
        report = make_video_report()
        diagnosis = diagnosis_pipeline.build_diagnosis(report)
        answer = structured(
            observations=[
                {
                    "fact_id": "longest_display_stall",
                    "text": "最长停顿 300 ms。",
                }
            ],
        )

        errors = diagnosis_pipeline.validate_structured(
            answer,
            diagnosis,
            report,
        )

        self.assertEqual(errors, [])

    def test_unverified_alignment_rejects_simultaneous_claim(self):
        report = make_video_report(alignment="unknown")
        diagnosis = diagnosis_pipeline.build_diagnosis(report)
        answer = structured(
            conclusion="network",
            hypotheses=[
                {
                    "text": "网络超时和卡顿同时发生",
                    "fact_ids": [
                        "network_public_timeouts",
                        "longest_display_stall",
                    ],
                    "alternative": "",
                    "confidence": "likely",
                }
            ],
        )

        errors = diagnosis_pipeline.validate_structured(
            answer,
            diagnosis,
            report,
        )

        self.assertTrue(
            any("verified alignment" in item for item in errors)
        )

    def test_verified_alignment_allows_correlation_as_hypothesis(self):
        report = make_video_report(alignment="verified_qpc")
        diagnosis = diagnosis_pipeline.build_diagnosis(report)
        answer = structured(
            conclusion="network",
            hypotheses=[
                {
                    "text": "网络超时与停顿同时出现，值得复查",
                    "fact_ids": [
                        "network_public_timeouts",
                        "longest_display_stall",
                    ],
                    "alternative": "",
                    "confidence": "possible",
                }
            ],
        )

        errors = diagnosis_pipeline.validate_structured(
            answer,
            diagnosis,
            report,
        )

        self.assertEqual(errors, [])


class ValidationTests(unittest.TestCase):

    def setUp(self):
        self.report = make_video_report()
        self.diagnosis = diagnosis_pipeline.build_diagnosis(
            self.report
        )

    def test_non_numeric_fact_values_do_not_crash(self):
        answer = structured(
            observations=[
                {
                    "fact_id": "timebase_quality",
                    "text": "时间同步为 verified_qpc。",
                },
                {
                    "fact_id": "network_alignment",
                    "text": "网络对齐为 verified_qpc。",
                },
            ],
        )

        errors = diagnosis_pipeline.validate_structured(
            answer,
            self.diagnosis,
            self.report,
        )

        self.assertEqual(errors, [])

    def test_non_numeric_fact_with_a_number_in_text_is_ignored(self):
        answer = structured(
            observations=[
                {
                    "fact_id": "timebase_quality",
                    "text": "时间同步为 verified_qpc，采样 5 s。",
                }
            ],
        )

        errors = diagnosis_pipeline.validate_structured(
            answer,
            self.diagnosis,
            self.report,
        )

        self.assertEqual(errors, [])

    def test_unknown_fact_id_is_rejected(self):
        answer = structured(
            observations=[
                {
                    "fact_id": "made_up_fact",
                    "text": "未知事实",
                }
            ],
        )

        errors = diagnosis_pipeline.validate_structured(
            answer,
            self.diagnosis,
            self.report,
        )

        self.assertTrue(
            any("unknown fact_id" in item for item in errors)
        )

    def test_wrong_number_is_rejected(self):
        answer = structured(
            observations=[
                {
                    "fact_id": "display_fps",
                    "text": "显示平均 60 FPS。",
                }
            ],
        )

        errors = diagnosis_pipeline.validate_structured(
            answer,
            self.diagnosis,
            self.report,
        )

        self.assertTrue(
            any("does not match" in item for item in errors)
        )

    def test_strength_above_local_limit_is_rejected(self):
        answer = structured(strength="strong_evidence")

        errors = diagnosis_pipeline.validate_structured(
            answer,
            self.diagnosis,
            self.report,
        )

        self.assertTrue(
            any("exceeds local limit" in item for item in errors)
        )

    def test_too_many_actions_are_rejected(self):
        answer = structured(
            actions=[
                {"text": "一", "risk": "low", "verification": ""},
                {"text": "二", "risk": "low", "verification": ""},
            ],
        )

        errors = diagnosis_pipeline.validate_structured(
            answer,
            self.diagnosis,
            self.report,
        )

        self.assertTrue(
            any("at most one" in item for item in errors)
        )

    def test_unsafe_recommendation_is_rejected(self):
        answer = structured(
            actions=[
                {
                    "text": "修改注册表禁用服务",
                    "risk": "low",
                    "verification": "",
                }
            ],
        )

        errors = diagnosis_pipeline.validate_structured(
            answer,
            self.diagnosis,
            self.report,
        )

        self.assertTrue(
            any("unsafe recommendation" in item for item in errors)
        )

    def test_hypothesis_confidence_must_not_claim_certainty(self):
        answer = structured(
            hypotheses=[
                {
                    "text": "可能是 CPU 瓶颈",
                    "fact_ids": ["cpu_process_median"],
                    "alternative": "",
                    "confidence": "confirmed",
                }
            ],
        )

        errors = diagnosis_pipeline.validate_structured(
            answer,
            self.diagnosis,
            self.report,
        )

        self.assertTrue(
            any("invalid hypothesis confidence" in item for item in errors)
        )

    def test_hypothesis_needs_supporting_facts(self):
        answer = structured(
            hypotheses=[
                {
                    "text": "只是猜测",
                    "fact_ids": [],
                    "alternative": "",
                    "confidence": "unclear",
                }
            ],
        )

        errors = diagnosis_pipeline.validate_structured(
            answer,
            self.diagnosis,
            self.report,
        )

        self.assertTrue(
            any("no supporting fact" in item for item in errors)
        )

    def test_parse_structured_accepts_fenced_json(self):
        text = "```json\n" + json.dumps(
            structured(),
            ensure_ascii=False,
        ) + "\n```"

        self.assertEqual(
            diagnosis_pipeline.parse_structured(text),
            structured(),
        )

    def test_parse_structured_rejects_plain_text(self):
        self.assertIsNone(
            diagnosis_pipeline.parse_structured("这次不用改。")
        )

    def test_summary_and_fallback_are_readable(self):
        answer = structured(
            observations=[
                {
                    "fact_id": "display_fps",
                    "text": "显示平均 27 FPS。",
                }
            ],
            missing=["视频源帧率"],
        )

        summary = diagnosis_pipeline.structured_summary(answer)
        fallback = diagnosis_pipeline.fallback_text(
            self.diagnosis,
            "test",
        )

        self.assertIn("结论：no_clear_issue", summary)
        self.assertIn("显示平均 27 FPS", summary)
        self.assertIn("无法确定", summary)
        self.assertIn("AI 回答未通过本地事实校验", fallback)
        self.assertIn("display_fps", fallback)

    def test_summary_uses_the_requested_language(self):
        answer = structured(
            observations=[
                {
                    "fact_id": "display_fps",
                    "text": "Displayed 27 FPS.",
                }
            ],
        )

        summary = diagnosis_pipeline.structured_summary(
            answer,
            language="en",
        )
        fallback = diagnosis_pipeline.fallback_text(
            self.diagnosis,
            "test",
            language="en",
        )

        self.assertIn(
            "Conclusion: no_clear_issue (No clear issue)",
            summary,
        )
        self.assertIn("Observations:", summary)
        self.assertIn("failed local fact validation", fallback)

    def test_fallback_explains_numeric_mismatch_in_plain_language(self):
        text = diagnosis_pipeline.fallback_text(
            self.diagnosis,
            "observation number does not match its fact "
            "longest_display_stall: 11 秒",
        )
        english = diagnosis_pipeline.fallback_text(
            self.diagnosis,
            "observation number does not match its fact "
            "longest_display_stall: 11 s",
            language="en",
        )

        self.assertIn(
            "AI 引用的数字与本地事实不一致",
            text,
        )
        self.assertNotIn("does not match its fact", text)
        self.assertIn("quoted a number", english)

    def test_non_object_action_is_rejected(self):
        answer = structured(actions=["直接重启"])

        errors = diagnosis_pipeline.validate_structured(
            answer,
            self.diagnosis,
            self.report,
        )

        self.assertTrue(
            any("recommended_action must be an object" in item for item in errors)
        )


def wait_until(predicate, timeout=4.0):
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:

        if predicate():
            return True

        time.sleep(0.01)

    return bool(predicate())


class ChatStructuredFlowTests(unittest.TestCase):

    def _report(self):
        report = make_video_report()
        report["diagnosis"] = diagnosis_pipeline.build_diagnosis(
            report
        )
        report["language"] = "zh_CN"
        return report

    def test_valid_answer_needs_no_repair(self):
        calls = []

        def client(payload, api_key=None, timeout=None):
            calls.append(payload)
            return json.dumps(
                structured(),
                ensure_ascii=False,
            )

        session = ai_chat.ChatSession(self._report())
        session.send("这次怎么样？", api_key="k", client=client)
        self.assertTrue(wait_until(lambda: not session.pending))

        self.assertEqual(len(calls), 1)
        self.assertEqual(session.last_validation_errors, [])
        self.assertIsNotNone(session.last_structured)
        self.assertIn(
            "结论：no_clear_issue",
            session.messages[-1]["content"],
        )

    def test_invalid_json_is_repaired_once(self):
        calls = []

        def client(payload, api_key=None, timeout=None):
            calls.append(payload)

            if len(calls) == 1:
                return "这次可能是 CPU 瓶颈。"

            return json.dumps(
                structured(),
                ensure_ascii=False,
            )

        session = ai_chat.ChatSession(self._report())
        session.send("这次怎么样？", api_key="k", client=client)
        self.assertTrue(wait_until(lambda: not session.pending))

        self.assertEqual(len(calls), 2)
        self.assertIn(
            "JSON",
            calls[1]["messages"][0]["content"],
        )
        self.assertEqual(session.last_validation_errors, [])
        self.assertIsNotNone(session.last_structured)

    def test_failed_repair_falls_back_to_local_facts(self):
        calls = []

        def client(payload, api_key=None, timeout=None):
            calls.append(payload)
            return "仍然不是 JSON。"

        session = ai_chat.ChatSession(self._report())
        session.send("这次怎么样？", api_key="k", client=client)
        self.assertTrue(wait_until(lambda: not session.pending))

        self.assertEqual(len(calls), 2)
        self.assertTrue(session.last_validation_errors)
        answer = session.messages[-1]["content"]
        self.assertIn("AI 回答未通过本地事实校验", answer)
        self.assertIn("display_fps", answer)
        self.assertEqual(
            sum(
                1
                for item in session.messages
                if item["role"] == "assistant"
            ),
            1,
        )

    def test_overclaimed_video_answer_is_repaired(self):
        calls = []

        def overclaim():
            return json.dumps(
                structured(
                    conclusion="local_performance",
                    hypotheses=[
                        {
                            "text": "CPU 性能不足导致掉帧",
                            "fact_ids": ["frame_cpu_busy_median"],
                            "alternative": "",
                            "confidence": "likely",
                        }
                    ],
                ),
                ensure_ascii=False,
            )

        def client(payload, api_key=None, timeout=None):
            calls.append(payload)

            if len(calls) == 1:
                return overclaim()

            return json.dumps(
                structured(),
                ensure_ascii=False,
            )

        session = ai_chat.ChatSession(self._report())
        session.send("是不是 CPU 不行？", api_key="k", client=client)
        self.assertTrue(wait_until(lambda: not session.pending))

        self.assertEqual(len(calls), 2)
        repair_text = calls[1]["messages"][1]["content"]
        self.assertIn("校验错误", repair_text)
        self.assertIn("conclusion not supported", repair_text)
        self.assertEqual(session.last_validation_errors, [])


    def test_update_report_rejects_other_report_key(self):

        session = ai_chat.ChatSession(self._report())
        other = dict(self._report())
        other["report_key"] = "another-key"
        other["application"] = "other.exe"

        self.assertFalse(
            session.update_report(other, "another-key")
        )
        self.assertEqual(
            session.report["report_key"],
            "douyin-key",
        )
        self.assertEqual(
            session.report["application"],
            "douyin.exe",
        )

    def test_update_report_refreshes_same_report_only(self):

        session = ai_chat.ChatSession(self._report())
        session.messages.append(
            {
                "role": "user",
                "content": "保留这条",
                "kind": "chat",
            }
        )

        updated = dict(self._report())
        updated["application"] = "douyin.exe"
        updated["diagnosis"] = diagnosis_pipeline.build_diagnosis(
            updated,
            scenario_override="game",
        )

        self.assertTrue(session.update_report(updated))
        self.assertEqual(
            session.report["diagnosis"]["scenario"]["id"],
            "game",
        )
        self.assertEqual(
            [item["content"] for item in session.messages],
            ["保留这条"],
        )


    def test_store_refreshes_the_same_report_context(self):

        store = ai_chat.ChatStore()
        first = store.session_for(self._report())
        updated = dict(self._report())
        updated["diagnosis"] = diagnosis_pipeline.build_diagnosis(
            updated,
            scenario_override="game",
        )

        same = store.session_for(updated)

        self.assertIs(first, same)
        self.assertEqual(
            same.report["diagnosis"]["scenario"]["id"],
            "game",
        )


if __name__ == "__main__":
    unittest.main()
