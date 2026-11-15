"""Network-vs-local diagnostic skill and network evidence tests."""

import sys
import unittest

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import ai_insight  # noqa: E402
import ai_skills  # noqa: E402


def make_frames(intervals, application="test-game.exe"):

    frames = []
    time_ms = 0.0

    for interval in intervals:

        frames.append(
            {
                "time": time_ms,
                "duration": interval,
                "displayed": True,
                "row": {
                    "Application": application,
                    "DisplayedTime": str(interval),
                    "FrameTime": str(interval),
                },
            }
        )
        time_ms += interval

    return frames


def make_report(
    intervals=None,
    network=None,
    key="report",
):

    intervals = intervals or [1000.0 / 60.0] * 300

    return ai_insight.build_report_summary(
        make_frames(intervals),
        application="test-game.exe",
        target_fps=60,
        target_fps_explicit=True,
        network=network,
        file_name=f"{key}.csv",
        report_key=key,
    )


NETWORK_BAD = {
    "gateway": {
        "samples": 120,
        "latency_median_ms": 4.0,
        "jitter_ms": 28.0,
        "loss_percent": 2.5,
        "timeouts": 3,
    },
    "public": {
        "samples": 120,
        "latency_median_ms": 35.0,
        "jitter_ms": 40.0,
        "loss_percent": 3.0,
        "timeouts": 5,
    },
}

NETWORK_GOOD = {
    "gateway": {
        "samples": 120,
        "latency_median_ms": 3.0,
        "jitter_ms": 1.0,
        "loss_percent": 0.0,
        "timeouts": 0,
    },
    "public": {
        "samples": 120,
        "latency_median_ms": 20.0,
        "jitter_ms": 2.0,
        "loss_percent": 0.0,
        "timeouts": 0,
    },
}


class SkillSelectionTests(unittest.TestCase):

    def test_normal_question_does_not_load_a_skill(self):

        self.assertEqual(
            ai_skills.select_skills(
                "这次表现怎么样？需要改吗？",
                [],
                True,
            ),
            (),
        )

    def test_metric_definition_does_not_load_network_skill(self):

        for question in (
            "1% Low 是什么？",
            "P95 怎么算？",
            "帧率指标是什么意思？",
        ):

            with self.subTest(question=question):

                self.assertEqual(
                    ai_skills.select_skills(
                        question,
                        [],
                        True,
                    ),
                    (),
                )

    def test_network_question_loads_skill(self):

        self.assertEqual(
            ai_skills.select_skills(
                "是不是网络？",
                [],
                True,
            ),
            (ai_skills.NETWORK_LOCAL_SKILL_ID,),
        )

    def test_stutter_vs_network_question_loads_skill(self):

        self.assertEqual(
            ai_skills.select_skills(
                "画面偶尔卡一下，是网络还是本机？",
                [],
                True,
            ),
            (ai_skills.NETWORK_LOCAL_SKILL_ID,),
        )

    def test_deictic_follow_up_uses_recent_context(self):

        history = [
            {
                "role": "user",
                "content": "网络延迟和画面停顿都有。",
            },
            {
                "role": "assistant",
                "content": "先分开看网络和本机。",
            },
        ]

        self.assertEqual(
            ai_skills.select_skills(
                "那更像哪边？",
                history,
                True,
            ),
            (ai_skills.NETWORK_LOCAL_SKILL_ID,),
        )

    def test_deictic_follow_up_without_context_does_not_load(self):

        self.assertEqual(
            ai_skills.select_skills(
                "那更像哪边？",
                [
                    {
                        "role": "user",
                        "content": "这次帧率看起来还可以。",
                    }
                ],
                True,
            ),
            (),
        )

    def test_no_report_still_allows_general_distinction_help(self):

        self.assertEqual(
            ai_skills.select_skills(
                "怎么区分网络延迟和画面卡顿？",
                [],
                False,
            ),
            (ai_skills.NETWORK_LOCAL_SKILL_ID,),
        )


class NetworkEvidenceTests(unittest.TestCase):

    def test_missing_network_data_is_marked_unknown(self):

        report = make_report()
        text = ai_insight.build_report_text(report)

        self.assertIn("网络：未测量", text)
        self.assertIn("画面正常不能排除网络问题", text)
        self.assertFalse(
            report["quality"]["network_measured"]
        )

    def test_network_probe_data_is_included_with_caveat(self):

        report = make_report(network=NETWORK_BAD)
        text = ai_insight.build_report_text(report)

        self.assertTrue(
            report["quality"]["network_measured"]
        )
        self.assertIn("网关探测", text)
        self.assertIn("公网探测", text)
        self.assertIn("抖动 28.0 ms", text)
        self.assertIn("丢包 2.5%", text)
        self.assertIn(
            "公网探测不能代替游戏内延迟",
            text,
        )

    def test_core_facts_and_network_stay_in_payload(self):

        report = make_report(network=NETWORK_BAD)
        payload = ai_insight.build_chat_payload(
            report,
            [],
            "画面稳定但队友瞬移，是不是网络？",
        )
        text = "\n".join(
            message["content"]
            for message in payload["messages"]
        )

        self.assertIn("画面稳定但队友瞬移", text)
        self.assertIn("network_gateway_samples", text)
        self.assertIn("network_public_samples", text)
        self.assertIn("同段证据", text)
        self.assertLessEqual(
            len(ai_insight.encode_payload(payload)),
            4096,
        )

    def test_metric_question_has_no_skill_card(self):

        report = make_report()
        payload = ai_insight.build_chat_payload(
            report,
            [],
            "1% Low 是什么？",
        )
        text = "\n".join(
            message["content"]
            for message in payload["messages"]
        )

        self.assertNotIn("诊断 Skill", text)
        self.assertIn("1% Low 是什么", text)

    def test_unlinked_general_chat_has_skill_but_no_capture_facts(self):

        payload = ai_insight.build_chat_payload(
            {
                "report_key": "__general__",
                "no_report": True,
                "language": "zh_CN",
            },
            [],
            "怎么区分网络延迟和画面卡顿？",
        )
        text = "\n".join(
            message["content"]
            for message in payload["messages"]
        )

        self.assertIn("没有关联报告", text)
        self.assertIn("诊断 Skill｜网络还是本机", text)
        self.assertNotIn("平均显示帧率", text)

    def test_skill_is_dropped_before_core_when_over_budget(self):

        report = make_report(network=NETWORK_BAD)
        base = ai_insight.build_chat_payload(
            report,
            [],
            "是不是网络？",
            skills=(),
        )
        base_size = len(ai_insight.encode_payload(base))

        payload = ai_insight.build_chat_payload(
            report,
            [],
            "是不是网络？",
            max_bytes=base_size,
        )
        text = "\n".join(
            message["content"]
            for message in payload["messages"]
        )

        self.assertLessEqual(
            len(ai_insight.encode_payload(payload)),
            base_size,
        )
        self.assertNotIn("诊断 Skill", text)
        self.assertIn("是不是网络？", text)
        self.assertIn("network_gateway_samples", text)

    def test_long_history_with_skill_stays_under_budget(self):

        report = make_report(network=NETWORK_BAD)
        history = []

        for index in range(12):

            history.append(
                {
                    "role": "user",
                    "content": f"旧问题 {index} " + "x" * 250,
                }
            )
            history.append(
                {
                    "role": "assistant",
                    "content": f"旧回答 {index} " + "y" * 250,
                }
            )

        payload = ai_insight.build_chat_payload(
            report,
            history,
            "那更像哪边？",
        )
        text = "\n".join(
            message["content"]
            for message in payload["messages"]
        )

        self.assertLessEqual(
            len(ai_insight.encode_payload(payload)),
            4096,
        )
        self.assertIn("那更像哪边？", text)
        self.assertIn("network_gateway_samples", text)

    def test_other_report_network_values_do_not_leak(self):

        report_a = make_report(
            network=NETWORK_BAD,
            key="a",
        )
        report_b = make_report(
            network=NETWORK_GOOD,
            key="b",
        )

        payload = ai_insight.build_chat_payload(
            report_b,
            [],
            "网络怎么样？",
        )
        text = "\n".join(
            message["content"]
            for message in payload["messages"]
        )

        self.assertIn("network_public_timeouts: 0timeouts", text)
        self.assertNotIn(
            "network_public_timeouts: 5timeouts",
            text,
        )
        self.assertNotIn(
            "network_public_timeout_rate: 0.0417ratio",
            text,
        )


if __name__ == "__main__":

    unittest.main()
