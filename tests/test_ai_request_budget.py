"""Exact request-body budget: measurement, compression and boundaries."""

import json
import os
import sys
import time
import unittest

from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import ai_chat  # noqa: E402
import ai_http  # noqa: E402
import ai_insight  # noqa: E402
import ai_providers  # noqa: E402
import i18n  # noqa: E402


def make_frames(count=5620, stalls=((120, 1400.0), (480, 1200.0))):

    frame_map = {index: value for index, value in stalls}
    frames = []
    time_ms = 0.0

    for index in range(count):

        duration = frame_map.get(index, 16.67)
        frames.append(
            {
                "time": time_ms,
                "duration": duration,
                "displayed": True,
                "row": {
                    "Application": "douyin.exe",
                    "DisplayedTime": str(duration),
                    "FrameTime": str(duration),
                },
            }
        )
        time_ms += duration

    return frames


def make_events():

    return [
        SimpleNamespace(
            index=120,
            time_ms=2000.0,
            duration_ms=1400.0,
            baseline_median_ms=16.6,
            threshold_ms=40.0,
        ),
        SimpleNamespace(
            index=480,
            time_ms=8000.0,
            duration_ms=1200.0,
            baseline_median_ms=16.6,
            threshold_ms=40.0,
        ),
    ]


def make_report(events=None, telemetry_aligned=False, frames=None):

    events = make_events() if events is None else events
    diagnostic = SimpleNamespace(
        events=events,
        findings=[],
        telemetry_aligned=telemetry_aligned,
    )
    telemetry = SimpleNamespace(
        available=True,
        complete=True,
        samples=[
            {
                "t_ms": index * 250.0,
                "target": {"cpu_percent": 20.0},
                "cpu": {"system_percent": 15.0},
                "gpu": {"util_percent": 30.0},
                "ram": {"percent": 50.0},
            }
            for index in range(40)
        ],
        metadata={},
    )
    return ai_insight.build_report_summary(
        frames or make_frames(),
        application="douyin.exe",
        target_fps=60,
        target_fps_explicit=False,
        diagnostic_report=diagnostic,
        telemetry=telemetry,
        network={
            "available": True,
            "gateway": {
                "timeouts": 23,
                "responses": 100,
                "samples": 123,
                "latency_median_ms": 4.0,
            },
            "public": {
                "timeouts": 23,
                "responses": 100,
                "samples": 123,
                "latency_median_ms": 20.0,
            },
            "coverage_start_s": 0.0,
            "coverage_end_s": 90.0,
        },
        file_name="douyin.csv",
        report_key="douyin",
    )


class RequestBudgetTests(unittest.TestCase):

    def setUp(self):

        i18n.get_manager().set_language("zh_CN")
        self.question = "请全面分析本次检测结果，判断是否存在异常。"

    def test_4096_body_is_sent_and_4097_is_not(self):

        report = make_report()

        def body_of_size(size):

            def body_fn(payload):

                return b"x" * size

            return body_fn

        payload, body = ai_insight.build_chat_payload(
            report,
            [],
            self.question,
            structured=False,
            body_fn=body_of_size(4096),
            body_limit=4096,
            return_body=True,
        )
        self.assertEqual(len(body), 4096)
        self.assertTrue(payload["messages"])

        with self.assertRaises(ai_insight.PromptTooLarge) as caught:

            ai_insight.build_chat_payload(
                report,
                [],
                self.question,
                structured=False,
                body_fn=body_of_size(4097),
                body_limit=4096,
                return_body=True,
            )

        self.assertEqual(caught.exception.actual_bytes, 4097)
        self.assertEqual(caught.exception.max_bytes, 4096)
        self.assertEqual(caught.exception.reason, "summary")

    def test_chinese_utf8_is_measured_in_bytes(self):

        report = make_report()

        def body_fn(payload):

            return ai_http.encode_json(payload)

        payload, body = ai_insight.build_chat_payload(
            report,
            [],
            "请用中文回答，并保留中文标点。",
            structured=False,
            body_fn=body_fn,
            body_limit=4096,
            return_body=True,
        )

        self.assertGreater(len(body), len(body.decode("utf-8")))
        self.assertIn("中文".encode("utf-8"), body)

    def test_douyin_shape_fits_every_provider_stream_body(self):

        report = make_report()
        providers = (
            ("deepseek", "deepseek-flash"),
            ("openai", "gpt-4.1"),
            ("claude", "claude-sonnet-4-5"),
            ("gemini", "gemini-2.5-flash"),
        )

        for provider_id, model in providers:

            with self.subTest(provider=provider_id):

                body_fn = lambda payload, pid=provider_id, m=model: (
                    ai_providers.request_body(pid, m, payload)
                )
                payload, body = ai_insight.build_chat_payload(
                    report,
                    [],
                    self.question,
                    structured=False,
                    body_fn=body_fn,
                    body_limit=4096,
                    return_body=True,
                    model=model,
                )
                text = payload["messages"][1]["content"]

                self.assertLessEqual(len(body), 4096)
                self.assertGreater(len(body), 0)
                for fact_id in (
                    "displayed_frames",
                    "display_p95_interval",
                    "display_p99_interval",
                    "abnormal_frame_events",
                    "stalls_over_1s",
                    "longest_display_stall",
                    "network_gateway_timeouts",
                    "network_gateway_timeout_rate",
                    "telemetry_alignment",
                ):

                    self.assertIn(fact_id, text)

                self.assertEqual(
                    payload["model"],
                    model,
                )

    def test_body_contains_provider_protocol_fields(self):

        report = make_report()
        payload = ai_insight.build_chat_payload(
            report,
            [],
            self.question,
            structured=False,
        )
        checks = {
            "deepseek": ("stream", "stream_options"),
            "openai": ("stream", "input"),
            "claude": ("stream", "max_tokens", "messages"),
            "gemini": ("contents", "systemInstruction"),
        }

        for provider_id, expected in checks.items():

            with self.subTest(provider=provider_id):

                body = ai_providers.request_body(
                    provider_id,
                    ai_providers.get(provider_id).default_model,
                    payload,
                )
                parsed = json.loads(body.decode("utf-8"))

                for key in expected:

                    self.assertIn(key, parsed)

    def test_each_provider_rejects_4097_before_transport(self):

        for provider_id in ai_providers.ids():

            with self.subTest(provider=provider_id):

                provider = ai_providers.get(provider_id)

                with mock.patch(
                    "urllib.request.urlopen",
                ) as urlopen:

                    with self.assertRaises(Exception) as caught:

                        list(
                            provider.stream_body(
                                b"x" * 4097,
                                api_key="sk-test",
                            )
                        )

                urlopen.assert_not_called()
                code = getattr(caught.exception, "code", "")
                if provider_id != "deepseek":

                    self.assertEqual(code, "too_large")

    def test_each_provider_sends_4096_through_transport(self):

        class EmptyResponse:

            def __enter__(self):

                return self

            def __exit__(self, *exc):

                return False

            def __iter__(self):

                return iter(())

        for provider_id in ai_providers.ids():

            with self.subTest(provider=provider_id):

                provider = ai_providers.get(provider_id)

                with mock.patch(
                    "urllib.request.urlopen",
                    return_value=EmptyResponse(),
                ) as urlopen:

                    stream = provider.stream_body(
                        b"x" * 4096,
                        api_key="sk-test",
                    )

                    try:

                        next(stream)

                    except Exception:

                        pass

                self.assertEqual(urlopen.call_count, 1)

    def test_key_facts_survive_tight_compression(self):

        report = make_report()
        text = ai_insight.build_report_text(
            report,
            include_optional=False,
            include_analysis_notes=False,
            compact=3,
            fact_drop_level=len(ai_insight._COMPACT_DROP_GROUPS),
        )

        for fact_id in (
            "displayed_frames",
            "display_p95_interval",
            "display_p99_interval",
            "abnormal_frame_events",
            "stalls_over_1s",
            "longest_display_stall",
            "network_gateway_timeouts",
            "network_gateway_timeout_rate",
            "telemetry_alignment",
        ):

            self.assertIn(fact_id, text)

    def test_size_does_not_grow_with_event_count(self):

        small = make_report(events=make_events())
        many_events = [
            SimpleNamespace(
                index=index,
                time_ms=index * 1000.0,
                duration_ms=1200.0 if index % 2 else 200.0,
                baseline_median_ms=16.6,
                threshold_ms=40.0,
            )
            for index in range(400)
        ]
        big = make_report(events=many_events)

        def fit(report):

            body_fn = ai_http.encode_json
            payload, body = ai_insight.build_chat_payload(
                report,
                [],
                self.question,
                structured=False,
                body_fn=body_fn,
                body_limit=4096,
                return_body=True,
            )
            return len(body), payload["messages"][1]["content"]

        small_size, small_text = fit(small)
        big_size, big_text = fit(big)

        self.assertLessEqual(small_size, 4096)
        self.assertLessEqual(big_size, 4096)
        self.assertLess(abs(big_size - small_size), 200)
        self.assertIn("abnormal_frame_events: 400", big_text)

    def test_question_too_long_has_question_reason(self):

        report = make_report()
        huge_question = "请分析" * 4000

        with self.assertRaises(ai_insight.PromptTooLarge) as caught:

            ai_insight.build_chat_payload(
                report,
                [],
                huge_question,
                structured=False,
                body_fn=ai_http.encode_json,
                body_limit=4096,
                return_body=True,
            )

        self.assertEqual(caught.exception.reason, "question")

    def test_summary_too_large_has_summary_reason(self):

        report = make_report()

        with self.assertRaises(ai_insight.PromptTooLarge) as caught:

            ai_insight.build_chat_payload(
                report,
                [],
                "好",
                structured=False,
                body_fn=ai_http.encode_json,
                body_limit=200,
                return_body=True,
            )

        self.assertEqual(caught.exception.reason, "summary")

    def test_failure_diagnostics_keep_only_sizes_and_stage(self):

        class Recorder:

            def __init__(self):

                self.events = []

            def record(self, event, **fields):

                self.events.append((event, fields))

        recorder = Recorder()
        session = ai_chat.ChatSession(
            {
                "report_key": "douyin",
                "application": "douyin.exe",
                "language": "zh_CN",
                "diagnosis": {},
            },
            mode="freeform",
            diagnostics=recorder,
        )

        with mock.patch(
            "ai_providers.request_body",
            return_value=b"x" * 5000,
        ), mock.patch(
            "ai_providers.get_api_key",
            return_value="sk-test",
        ):

            self.assertTrue(
                session.send(
                    "请全面分析",
                    provider="deepseek",
                    model="deepseek-flash",
                )
            )
            deadline = time.monotonic() + 5

            while session.pending and time.monotonic() < deadline:

                time.sleep(0.01)

        errors = [
            fields
            for event, fields in recorder.events
            if event == "api_error"
        ]
        self.assertTrue(errors)
        last = errors[-1]
        self.assertEqual(last.get("actual_bytes"), 5000)
        self.assertEqual(last.get("limit"), 4096)
        self.assertEqual(last.get("failure_stage"), "summary")
        self.assertNotIn("sk-test", str(recorder.events))
        self.assertNotIn("请全面分析", str(recorder.events))


if __name__ == "__main__":
    unittest.main()
