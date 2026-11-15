"""AI diagnostic log: privacy, size, rotation and error classification."""

import json
import os
import sys
import tempfile
import time
import unittest

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import ai_diagnostics  # noqa: E402
import ai_chat  # noqa: E402
import deepseek_client  # noqa: E402

from tests.test_ai_chat import (  # noqa: E402
    make_report,
    structured_answer,
    wait_until,
)


class RecordingDiagnostics:
    def __init__(self):
        self.events = []

    def record(self, event, **fields):
        self.events.append((event, fields))
        return True

    def named(self, event):
        return [
            fields
            for name, fields in self.events
            if name == event
        ]


class PrivacyAndRotationTests(unittest.TestCase):

    def test_report_identity_never_returns_a_full_path(self):
        report = make_report("secret-report")
        report_id, file_name = ai_diagnostics.report_identity(
            report
        )

        self.assertEqual(len(report_id), 12)
        self.assertEqual(file_name, "secret-report.csv")
        self.assertNotIn("report-a", report_id)
        self.assertNotIn("\\", file_name)
        self.assertNotIn("/", file_name)

    def test_record_drops_credentials_chat_and_full_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ai.jsonl"
            log = ai_diagnostics.AIDiagnosticLog(path=path)
            self.assertTrue(
                log.record(
                    "request",
                    api_key="sk-secret",
                    authorization="Bearer secret",
                    content="private chat text",
                    messages=[{"role": "user", "content": "secret"}],
                    answer="raw answer",
                    question="raw question",
                    report_path=r"C:\Users\example\secret\capture.csv",
                    usage={
                        "prompt_tokens": 12,
                        "completion_tokens": 7,
                        "total_tokens": 19,
                        "api_key": "nested-secret",
                    },
                )
            )
            raw = path.read_text(encoding="utf-8")

            self.assertNotIn("sk-secret", raw)
            self.assertNotIn("Bearer secret", raw)
            self.assertNotIn("private chat text", raw)
            self.assertNotIn("raw answer", raw)
            self.assertNotIn("raw question", raw)
            self.assertNotIn("C:\\\\Users", raw)
            self.assertNotIn("nested-secret", raw)
            record = json.loads(raw.strip())
            self.assertEqual(
                record["usage"],
                {
                    "prompt_tokens": 12,
                    "completion_tokens": 7,
                    "total_tokens": 19,
                },
            )

    def test_rotation_keeps_the_file_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ai.jsonl"
            log = ai_diagnostics.AIDiagnosticLog(
                path=path,
                max_bytes=500,
            )

            for index in range(40):
                log.record(
                    "event",
                    index=index,
                    reason="x" * 100,
                )

            self.assertTrue(path.is_file())
            backup = path.with_name(path.name + ".1")
            self.assertTrue(backup.is_file())
            total = path.stat().st_size + backup.stat().st_size
            self.assertLessEqual(total, 1100)

    def test_old_backup_is_pruned(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ai.jsonl"
            backup = path.with_name(path.name + ".1")
            backup.write_text("{}\n", encoding="utf-8")
            old = time.time() - 8 * 86400
            os.utime(backup, (old, old))
            log = ai_diagnostics.AIDiagnosticLog(
                path=path,
                retention_days=7,
            )

            log.record("event", value=1)

            self.assertFalse(backup.exists())
            self.assertTrue(path.is_file())

    def test_write_failure_is_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "not-a-file"
            directory.mkdir()
            log = ai_diagnostics.AIDiagnosticLog(
                path=directory
            )

            self.assertFalse(log.record("event", value=1))


class ErrorClassificationTests(unittest.TestCase):

    def test_numeric_error_keeps_fact_number_and_unit(self):
        classified = ai_diagnostics.classify_validation_errors(
            [
                "observation number does not match its fact "
                "longest_display_stall: 11 绉?
            ]
        )

        self.assertEqual(
            classified,
            [
                {
                    "type": "numeric",
                    "fact_id": "longest_display_stall",
                    "number": "11",
                    "unit": "绉?,
                }
            ],
        )

    def test_fact_and_json_errors_are_typed(self):
        classified = ai_diagnostics.classify_validation_errors(
            [
                "unknown fact_id: made_up",
                "response is not a JSON object",
                "conclusion not supported by available scenario/data",
                "network claim without network data",
                "unsafe recommendation: 娉ㄥ唽琛?,
            ]
        )
        types = [entry["type"] for entry in classified]

        self.assertIn("fact_reference", types)
        self.assertIn("json", types)
        self.assertIn("conclusion", types)
        self.assertIn("network", types)
        self.assertIn("safety", types)
        self.assertEqual(
            classified[0]["fact_id"],
            "made_up",
        )

    def test_usage_summary_keeps_only_token_counts(self):
        summary = ai_diagnostics.usage_summary(
            {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
                "api_key": "secret",
                "other": 1,
            }
        )

        self.assertEqual(
            summary,
            {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
            },
        )
        self.assertIsNone(ai_diagnostics.usage_summary(None))


class ChatDiagnosticFlowTests(unittest.TestCase):

    def _report(self):
        return make_report("diagnostic-report")

    def test_success_and_repair_are_logged_without_content(self):
        diagnostics = RecordingDiagnostics()
        calls = []

        def client(payload, api_key=None, timeout=None):
            calls.append(payload)

            if len(calls) == 1:
                return "not json"

            return structured_answer("ok")

        session = ai_chat.ChatSession(
            self._report(),
            diagnostics=diagnostics,
        )
        session.send("杩欐鎬庝箞鏍凤紵", api_key="sk-test", client=client)
        self.assertTrue(wait_until(lambda: not session.pending))

        names = [name for name, _ in diagnostics.events]
        self.assertEqual(
            names,
            [
                "request",
                "response",
                "repair_request",
                "repair_response",
                "final",
            ],
        )
        final = diagnostics.named("final")[0]
        self.assertEqual(final["final_source"], "ai")
        self.assertTrue(final["repair_attempted"])
        self.assertTrue(final["repair_ok"])
        self.assertEqual(
            diagnostics.named("response")[0]["parse_ok"],
            False,
        )
        serialized = json.dumps(
            diagnostics.events,
            ensure_ascii=False,
        )
        self.assertNotIn("sk-test", serialized)
        self.assertNotIn("杩欐鎬庝箞鏍?, serialized)

    def test_copied_fact_ids_are_repaired_without_another_call(self):
        diagnostics = RecordingDiagnostics()
        calls = []

        def client(payload, api_key=None, timeout=None):
            calls.append(payload)
            return json.dumps(
                {
                    "conclusion": "no_clear_issue",
                    "evidence_strength": "limited_evidence",
                    "observations": [
                        {
                            "fact_id": "display_fps=60.0FPS",
                            "text": "骞冲潎鏄剧ず 60 FPS銆?,
                        }
                    ],
                    "hypotheses": [],
                    "missing_evidence": [],
                    "recommended_actions": [],
                },
                ensure_ascii=False,
            )

        session = ai_chat.ChatSession(
            self._report(),
            diagnostics=diagnostics,
        )
        session.send("杩欐鎬庝箞鏍凤紵", api_key="sk-test", client=client)
        self.assertTrue(wait_until(lambda: not session.pending))

        self.assertEqual(len(calls), 1)
        self.assertEqual(session.last_validation_errors, [])
        self.assertIsNotNone(session.last_structured)
        final = diagnostics.named("final")[0]
        self.assertEqual(final["final_source"], "ai")
        self.assertFalse(final["repair_attempted"])
        self.assertTrue(diagnostics.named("local_repair"))

    def test_fallback_and_api_error_are_logged_safely(self):
        diagnostics = RecordingDiagnostics()

        def fallback_client(
            payload, api_key=None, timeout=None
        ):
            return "still not json"

        session = ai_chat.ChatSession(
            self._report(),
            diagnostics=diagnostics,
        )
        session.send(
            "杩欐鎬庝箞鏍凤紵",
            api_key="sk-test",
            client=fallback_client,
        )
        self.assertTrue(wait_until(lambda: not session.pending))
        final = diagnostics.named("final")[0]
        self.assertEqual(final["final_source"], "fallback")
        self.assertFalse(final["repair_ok"])

        diagnostics = RecordingDiagnostics()

        def failing_client(
            payload, api_key=None, timeout=None
        ):
            raise deepseek_client.DeepSeekError(
                "auth",
                status=401,
                detail="do not log this detail",
            )

        session = ai_chat.ChatSession(
            self._report(),
            diagnostics=diagnostics,
        )
        session.send(
            "杩欐鎬庝箞鏍凤紵",
            api_key="sk-test",
            client=failing_client,
        )
        self.assertTrue(wait_until(lambda: not session.pending))
        error = diagnostics.named("api_error")[0]
        self.assertEqual(error["error_code"], "auth")
        self.assertEqual(error["error_status"], 401)
        serialized = json.dumps(
            diagnostics.events,
            ensure_ascii=False,
        )
        self.assertNotIn("do not log this detail", serialized)
        self.assertNotIn("sk-test", serialized)


if __name__ == "__main__":
    unittest.main()
