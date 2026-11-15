"""Independent AI chat: context, retry, isolation and budget tests."""

import json
import os
import sys
import threading
import time
import unittest

from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtGui import (  # noqa: E402
    QInputMethodEvent,
    QKeyEvent,
)
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QWidget,
)

import ai_chat  # noqa: E402
import ai_insight  # noqa: E402
import deepseek_client  # noqa: E402
import i18n  # noqa: E402


def make_report(
    key="report-a",
    intervals=None,
    target=60,
    explicit=True,
    opening="",
):

    intervals = intervals or [1000.0 / 60.0] * 300
    frames = []
    time_ms = 0.0

    for interval in intervals:

        frames.append(
            {
                "time": time_ms,
                "duration": interval,
                "displayed": True,
                "row": {
                    "Application": "test-game.exe",
                    "DisplayedTime": str(interval),
                    "FrameTime": str(interval),
                },
            }
        )
        time_ms += interval

    report = ai_insight.build_report_summary(
        frames,
        application="test-game.exe",
        target_fps=target,
        target_fps_explicit=explicit,
        file_name=f"{key}.csv",
        report_key=key,
    )

    if opening:
        report["opening_answer"] = opening

    return report


def structured_answer(text):

    return json.dumps(
        {
            "conclusion": "no_clear_issue",
            "evidence_strength": "limited_evidence",
            "observations": [
                {
                    "fact_id": "display_fps",
                    "text": "显示数据已记录。",
                }
            ],
            "hypotheses": [],
            "missing_evidence": [],
            "recommended_actions": [
                {
                    "text": text,
                    "risk": "low",
                    "verification": "",
                }
            ],
        },
        ensure_ascii=False,
    )


def wait_until(predicate, timeout=4.0):

    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:

        if predicate():
            return True

        time.sleep(0.01)

    return bool(predicate())


class ChatSessionTests(unittest.TestCase):

    def test_opening_answer_is_shown_without_a_request(self):

        session = ai_chat.ChatSession(
            make_report(),
            opening_answer="这次不用改。",
        )

        self.assertEqual(len(session.messages), 1)
        self.assertEqual(
            session.messages[0]["kind"],
            "opening",
        )
        self.assertFalse(session.pending)

    def test_duplicate_send_is_blocked_while_pending(self):

        gate = threading.Event()
        calls = []

        def client(payload, api_key=None, timeout=None):
            calls.append(payload)
            gate.wait(5)
            return structured_answer("回复一")

        session = ai_chat.ChatSession(make_report())

        self.assertTrue(
            session.send(
                "第一个问题",
                api_key="sk-test",
                client=client,
            )
        )
        self.assertFalse(
            session.send(
                "第二个问题",
                api_key="sk-test",
                client=client,
            )
        )

        gate.set()
        self.assertTrue(
            wait_until(lambda: not session.pending)
        )

        self.assertEqual(len(calls), 1)
        self.assertEqual(
            [item["role"] for item in session.messages],
            ["user", "assistant"],
        )

    def test_failure_keeps_question_and_retry_does_not_duplicate(self):

        attempts = []

        def client(payload, api_key=None, timeout=None):
            attempts.append(payload)

            if len(attempts) == 1:
                raise deepseek_client.DeepSeekError(
                    "auth",
                    status=401,
                )

            return structured_answer("重试成功。")

        session = ai_chat.ChatSession(make_report())

        self.assertTrue(
            session.send(
                "为什么不像显卡？",
                api_key="sk-test",
                client=client,
            )
        )
        self.assertTrue(
            wait_until(lambda: not session.pending)
        )

        self.assertTrue(session.can_retry)
        self.assertEqual(
            session.messages[-1]["role"],
            "user",
        )
        self.assertIn(
            "显卡",
            session.messages[-1]["content"],
        )
        self.assertEqual(session.last_error_code, "auth")

        self.assertTrue(session.retry(api_key="sk-test", client=client))
        self.assertTrue(
            wait_until(lambda: not session.pending)
        )

        self.assertFalse(session.can_retry)
        self.assertEqual(
            sum(
                1 for item in session.messages
                if item["role"] == "user"
            ),
            1,
        )
        self.assertIn(
            "重试成功。",
            session.messages[-1]["content"],
        )

    def test_follow_up_sends_recent_previous_turn(self):

        payloads = []

        def client(payload, api_key=None, timeout=None):
            payloads.append(payload)
            return structured_answer(f"回答 {len(payloads)}")

        session = ai_chat.ChatSession(make_report())

        session.send("第一问", api_key="k", client=client)
        self.assertTrue(
            wait_until(lambda: not session.pending)
        )
        session.send("第二问", api_key="k", client=client)
        self.assertTrue(
            wait_until(lambda: not session.pending)
        )

        second = "\n".join(
            message["content"]
            for message in payloads[1]["messages"]
        )

        self.assertIn("第一问", second)
        self.assertIn("回答 1", second)
        self.assertIn("第二问", second)
        self.assertEqual(
            [item["role"] for item in session.messages],
            ["user", "assistant", "user", "assistant"],
        )

    def test_late_reply_updates_only_its_own_report(self):

        store = ai_chat.ChatStore()
        gate_a = threading.Event()
        gate_b = threading.Event()

        def client_a(payload, api_key=None, timeout=None):
            gate_a.wait(5)
            return structured_answer("A 的回复")

        def client_b(payload, api_key=None, timeout=None):
            gate_b.wait(5)
            return structured_answer("B 的回复")

        session_a = store.session_for(make_report("a"))
        session_b = store.session_for(make_report("b"))

        session_a.send("A 问题", api_key="k", client=client_a)
        session_b.send("B 问题", api_key="k", client=client_b)

        gate_b.set()
        self.assertTrue(
            wait_until(lambda: not session_b.pending)
        )
        self.assertTrue(session_a.pending)

        gate_a.set()
        self.assertTrue(
            wait_until(lambda: not session_a.pending)
        )

        self.assertIn(
            "A 的回复",
            session_a.messages[-1]["content"],
        )
        self.assertIn(
            "B 的回复",
            session_b.messages[-1]["content"],
        )
        self.assertNotIn(
            "B 的回复",
            [item["content"] for item in session_a.messages],
        )
        self.assertNotIn(
            "A 的回复",
            [item["content"] for item in session_b.messages],
        )

    def test_same_report_reuses_session_and_history(self):

        store = ai_chat.ChatStore()
        report = make_report("same")
        first = store.session_for(report)
        first.messages.append(
            {
                "role": "user",
                "content": "保留这条",
                "kind": "chat",
            }
        )

        second = store.session_for(report)

        self.assertIs(first, second)
        self.assertEqual(
            second.messages[-1]["content"],
            "保留这条",
        )

        empty = store.session_for(make_report("opening"))
        store.session_for(
            make_report("opening"),
            opening_answer="开场解读",
        )
        self.assertEqual(
            empty.messages[-1]["kind"],
            "opening",
        )


class ChatPayloadBudgetTests(unittest.TestCase):

    def test_budget_trims_old_turns_and_optional_details(self):

        report = make_report(
            intervals=[1000.0 / 45.0] * 450,
            target=60,
            explicit=True,
        )
        report["optional_findings"] = [
            {
                "category": "cpu",
                "code": "optional",
                "claim": "observed",
                "summary": "x" * 500,
            }
            for _ in range(20)
        ]

        history = []

        for index in range(12):

            history.append(
                {
                    "role": "user",
                    "content": f"旧问题 {index} " + "x" * 300,
                    "kind": "chat",
                }
            )
            history.append(
                {
                    "role": "assistant",
                    "content": f"旧回答 {index} " + "y" * 300,
                    "kind": "chat",
                }
            )

        question = "最新问题：更像哪里出了问题？"

        payload = ai_insight.build_chat_payload(
            report,
            history,
            question,
        )
        body = ai_insight.encode_payload(payload)
        messages = payload["messages"]
        text = "\n".join(
            message["content"] for message in messages
        )

        self.assertLessEqual(len(body), 4096)
        self.assertEqual(messages[-1]["content"], question)
        self.assertIn("整体帧率偏低", text)
        self.assertNotIn("旧问题 0", text)
        self.assertNotIn("可选的本地诊断明细", text)

    def test_latest_question_and_core_facts_are_kept(self):

        report = make_report()
        payload = ai_insight.build_chat_payload(
            report,
            [],
            "这次需要改吗？",
        )
        text = "\n".join(
            message["content"]
            for message in payload["messages"]
        )

        self.assertIn("这次需要改吗？", text)
        self.assertIn("平均", text)
        self.assertIn("整体判断", text)

    def test_report_text_lists_fact_ids_and_event_time(self):

        report = make_report()
        text = ai_insight.build_report_text(
            report,
            include_optional=False,
        )

        self.assertIn("- display_fps: 60.0FPS", text)
        self.assertIn(
            "- longest_display_stall: 0.017s（事件时间 0.0s）",
            text,
        )
        self.assertNotIn("事实ID：", text)

    def test_oversize_question_raises_instead_of_silent_cut(self):

        report = make_report()

        with self.assertRaises(ai_insight.PromptTooLarge):

            ai_insight.build_chat_payload(
                report,
                [],
                "x" * 5000,
            )


class FreeformModeTests(unittest.TestCase):

    def test_default_mode_is_freeform(self):

        with mock.patch.dict(
            os.environ,
            {},
            clear=False,
        ):
            os.environ.pop("LAGLENS_AI_MODE", None)
            self.assertEqual(
                ai_chat.default_mode(),
                "freeform",
            )
            os.environ["LAGLENS_AI_MODE"] = "structured"
            self.assertEqual(
                ai_chat.default_mode(),
                "structured",
            )
            os.environ.pop("LAGLENS_AI_MODE", None)

    def test_freeform_prompt_uses_the_current_language(self):

        payload = ai_insight.build_chat_payload(
            make_report(),
            [],
            "Overall, how does this look?",
            language="en",
            structured=False,
        )
        system = payload["messages"][0]["content"]

        self.assertIn("English", system)
        self.assertNotIn("evidence_strength", system)

    def test_freeform_prompt_avoids_repeating_old_answers(self):

        payload = ai_insight.build_chat_payload(
            make_report(),
            [],
            "Can you speak Japanese?",
            language="en",
            structured=False,
        )
        system = payload["messages"][0]["content"]

        self.assertIn("不附带性能摘要", system)
        self.assertIn("同一结论", system)
        self.assertIn("不要每轮重写", system)

    def test_freeform_answer_is_shown_without_validation(self):

        calls = []

        def client(payload, api_key=None, timeout=None):
            calls.append(payload)
            return "这次整体稳定，没有发现明显异常。"

        session = ai_chat.ChatSession(
            make_report(),
            mode="freeform",
        )
        session.send("这次怎么样？", api_key="k", client=client)
        self.assertTrue(wait_until(lambda: not session.pending))

        self.assertEqual(len(calls), 1)
        self.assertEqual(
            session.messages[-1]["content"],
            "这次整体稳定，没有发现明显异常。",
        )
        self.assertEqual(session.last_validation_errors, [])
        self.assertIsNone(session.last_structured)

    def test_freeform_payload_has_no_json_schema(self):

        payload = ai_insight.build_chat_payload(
            make_report(),
            [],
            "这次怎么样？",
            structured=False,
        )
        text = "\n".join(
            message["content"]
            for message in payload["messages"]
        )

        self.assertNotIn("evidence_strength", text)
        self.assertNotIn("recommended_actions", text)
        self.assertIn("这次怎么样", text)
        self.assertLessEqual(
            len(ai_insight.encode_payload(payload)),
            4096,
        )


class AIChatPageTests(unittest.TestCase):

    app = None

    @classmethod
    def setUpClass(cls):

        cls.app = (
            QApplication.instance()
            or QApplication([])
        )
        i18n.get_manager().set_language("en")

    def wait_qt(self, predicate, timeout=4.0):

        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:

            self.app.processEvents()

            if predicate():
                return True

            time.sleep(0.01)

        self.app.processEvents()
        return bool(predicate())

    def tearDown(self):

        for host in getattr(self, "hosts", []):

            try:

                host.close()
                host.deleteLater()

            except RuntimeError:

                pass

        self.app.processEvents()
        deepseek_client.clear_session_api_key()

    def _page(self, client=None, store=None):

        host = QWidget()
        page = ai_chat.AIChatPage(
            store or ai_chat.ChatStore(),
            language="en",
            client=client,
            parent=host,
        )
        self.hosts = getattr(self, "hosts", [])
        self.hosts.append(host)
        host.show()
        self.app.processEvents()
        return page

    def test_page_is_embedded_and_shows_answer(self):

        def client(payload, api_key=None, timeout=None):
            return structured_answer("这次不用改。")

        page = self._page(client=client)
        page.set_report_context(make_report())
        page.panel.input.setPlainText("整体怎么样？")

        with mock.patch(
            "deepseek_client.get_api_key",
            return_value="sk-test",
        ):
            page.panel._send()

        self.assertTrue(
            self.wait_qt(
                lambda: (
                    not page.session.pending
                    and "这次不用改"
                    in page.panel.transcript.toPlainText()
                )
            )
        )
        self.app.processEvents()

        self.assertFalse(page.isWindow())
        self.assertIn(
            "test-game.exe",
            page.report_label.text(),
        )
        self.assertFalse(
            page.view_report_button.isHidden()
        )
        self.assertFalse(
            page.panel.input.isHidden()
        )
        self.assertIn(
            "这次不用改",
            page.panel.transcript.toPlainText(),
        )

    def test_failure_keeps_question_and_retry_works(self):

        attempts = []

        def client(payload, api_key=None, timeout=None):
            attempts.append(payload)

            if len(attempts) == 1:
                raise deepseek_client.DeepSeekError(
                    "auth",
                    status=401,
                )

            return structured_answer("重试后的回答。")

        page = self._page(client=client)
        page.set_report_context(make_report())
        page.panel.input.setPlainText("为什么不像显卡？")

        with mock.patch(
            "deepseek_client.get_api_key",
            return_value="sk-test",
        ):
            page.panel._send()

        self.assertTrue(
            self.wait_qt(
                lambda: (
                    not page.session.pending
                    and "为什么不像显卡"
                    in page.panel.transcript.toPlainText()
                )
            )
        )
        self.app.processEvents()

        self.assertFalse(
            page.panel.retry_button.isHidden()
        )
        self.assertIn(
            "authentication failed",
            page.panel.status.text().lower(),
        )

        page.panel._retry()
        self.assertTrue(
            self.wait_qt(
                lambda: (
                    not page.session.pending
                    and "重试后的回答"
                    in page.panel.transcript.toPlainText()
                )
            )
        )
        self.app.processEvents()

        self.assertIn(
            "重试后的回答",
            page.panel.transcript.toPlainText(),
        )

    def test_report_switch_is_explicit_and_keeps_drafts(self):

        page = self._page()
        report_a = make_report("a")
        report_b = make_report("b")

        page.set_report_context(report_a)
        page.session.messages.append(
            {
                "role": "user",
                "content": "A 的报告问题",
                "kind": "chat",
            }
        )
        page.panel.input.setPlainText("A 的未发送草稿")

        page.set_report_context(report_b)
        self.assertEqual(
            page.session.messages,
            [],
        )
        self.assertEqual(
            page.panel.input.toPlainText(),
            "",
        )

        page.set_report_context(report_a)
        self.assertEqual(
            page.panel.input.toPlainText(),
            "A 的未发送草稿",
        )
        self.assertIn(
            "A 的报告问题",
            [
                item["content"]
                for item in page.session.messages
            ],
        )

    def test_no_key_shows_settings_entry(self):

        page = self._page()

        with mock.patch(
            "deepseek_client.get_api_key_source",
            return_value="none",
        ):
            page.refresh_key_state()

        self.assertFalse(
            page.settings_button.isHidden()
        )
        captured = []
        page.open_ai_settings_requested.connect(
            lambda: captured.append(True)
        )
        page.settings_button.click()
        self.assertTrue(captured)

        with mock.patch(
            "deepseek_client.get_api_key_source",
            return_value="saved",
        ):
            page.refresh_key_state()

        self.assertTrue(
            page.settings_button.isHidden()
        )

    def test_view_report_emits_linked_key(self):

        page = self._page()
        report = make_report("view")
        page.set_report_context(report)
        captured = []
        page.view_report_requested.connect(captured.append)

        page.view_report_button.click()

        self.assertEqual(
            captured,
            ["view"],
        )

    def test_report_context_uses_current_ui_language(self):

        page = self._page()
        report = make_report("language-context")
        self.assertEqual(report["language"], "zh_CN")

        page.set_report_context(report)
        self.assertEqual(
            page.session.report["language"],
            "en",
        )

        manager = i18n.get_manager()

        try:

            manager.set_language("zh_CN")
            page.retranslate()
            self.assertEqual(
                page.session.report["language"],
                "zh_CN",
            )
            manager.set_language("en")
            page.retranslate()
            self.assertEqual(
                page.session.report["language"],
                "en",
            )

        finally:

            manager.set_language("en")

    def test_refresh_report_context_is_key_isolated(self):

        page = self._page()
        page.set_report_context(make_report("a"))

        self.assertFalse(
            page.refresh_report_context(make_report("b"))
        )
        self.assertEqual(
            page.session.report["report_key"],
            "a",
        )

        updated = make_report("a")
        updated["scenario_override"] = "video"
        self.assertTrue(
            page.refresh_report_context(updated)
        )
        self.assertEqual(
            page.session.report["scenario_override"],
            "video",
        )

    def test_default_quick_question_asks_for_full_analysis(self):

        page = self._page()
        page.set_report_context(make_report())
        label = page.quick_button.text().lower()
        tooltip = page.quick_button.toolTip().lower()

        self.assertIn("full analysis", label)
        self.assertIn("comprehensively", tooltip)
        self.assertIn("optimization", tooltip)
        self.assertNotIn(
            "network problem or a local",
            tooltip,
        )

        for kind, button in page.quick_buttons.items():
            self.assertTrue(button.text())
            self.assertNotEqual(
                button.text().lower(),
                label,
                kind,
            )

    def test_unlinked_page_hides_all_quick_buttons(self):

        page = self._page()
        page.set_report_context(None)

        self.assertTrue(page.quick_button.isHidden())

        for button in page.quick_buttons.values():
            self.assertTrue(button.isHidden())

    def test_optional_quick_questions_send_their_own_prompt(self):

        sent = []

        def client(payload, api_key=None, timeout=None):
            sent.append(payload["messages"][-1]["content"])
            return structured_answer("ok")

        page = self._page(client=client)
        page.set_report_context(make_report())

        with mock.patch(
            "deepseek_client.get_api_key",
            return_value="sk-test",
        ):
            for kind in (
                "smoothness",
                "hardware",
                "network",
                "optimization",
            ):
                sent.clear()
                self.assertTrue(
                    page.panel.ask_quick_question(kind)
                )
                self.assertTrue(
                    self.wait_qt(
                        lambda: not page.session.pending
                    )
                )
                self.assertEqual(
                    sent,
                    [i18n.tr(f"ai.chat.quick.{kind}")],
                )

    def test_quick_question_sends_only_when_linked(self):

        calls = []

        def client(payload, api_key=None, timeout=None):
            calls.append(payload)
            return structured_answer("整体不错，这次不用改。")

        page = self._page(client=client)

        self.assertTrue(page.quick_button.isHidden())

        page.set_report_context(make_report())
        self.assertFalse(page.quick_button.isHidden())

        with mock.patch(
            "deepseek_client.get_api_key",
            return_value="sk-test",
        ):
            page.quick_button.click()

        self.assertTrue(
            self.wait_qt(
                lambda: (
                    not page.session.pending
                    and len(page.session.messages) >= 2
                )
            )
        )
        self.assertTrue(calls)
        self.assertEqual(
            page.session.messages[0]["content"],
            i18n.tr("ai.chat.quick_question"),
        )

    def test_unlinked_chat_has_no_capture_facts(self):

        payloads = []

        def client(payload, api_key=None, timeout=None):
            payloads.append(payload)
            return "可以聊一般问题。"

        page = self._page(client=client)
        page.panel.input.setPlainText("你能分析这次采集吗？")

        with mock.patch(
            "deepseek_client.get_api_key",
            return_value="sk-test",
        ):
            page.panel._send()

        self.assertTrue(
            self.wait_qt(
                lambda: (
                    not page.session.pending
                    and bool(payloads)
                )
            )
        )

        text = "\n".join(
            message["content"]
            for message in payloads[0]["messages"]
        )

        self.assertEqual(
            page.report_label.text(),
            "No report linked",
        )
        self.assertIn("没有关联报告", text)
        self.assertNotIn("2.44", text)
        self.assertNotIn("平均显示", text)

    def test_ime_composition_does_not_submit_enter(self):

        input_box = ai_chat.ChatInput()
        key = QKeyEvent(
            QEvent.Type.KeyPress,
            Qt.Key.Key_Return,
            Qt.KeyboardModifier.NoModifier,
        )

        input_box.inputMethodEvent(
            QInputMethodEvent("ni", [])
        )
        self.assertFalse(input_box.can_submit_key(key))

        input_box.inputMethodEvent(
            QInputMethodEvent()
        )
        self.assertTrue(input_box.can_submit_key(key))

        shift_enter = QKeyEvent(
            QEvent.Type.KeyPress,
            Qt.Key.Key_Return,
            Qt.KeyboardModifier.ShiftModifier,
        )
        self.assertFalse(
            input_box.can_submit_key(shift_enter)
        )


if __name__ == "__main__":

    unittest.main()
