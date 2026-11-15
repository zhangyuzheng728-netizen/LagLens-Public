"""Generic streaming: adapter contract, UI path, stop, switch, failure."""

import http.client
import json
import os
import sys
import threading
import time
import unittest
import urllib.error

from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

import ai_chat  # noqa: E402
import ai_stream  # noqa: E402
import deepseek_client  # noqa: E402
import i18n  # noqa: E402

from tests.test_ai_chat import (  # noqa: E402
    make_report as make_full_report,
    structured_answer,
)


def wait_until(predicate, timeout=5.0):

    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:

        if predicate():
            return True

        time.sleep(0.01)

    return bool(predicate())


def make_report(key="capture-a", application="game-a.exe"):

    return {
        "report_key": key,
        "file": f"{key}.csv",
        "application": application,
        "language": "zh_CN",
        "session_id": f"session-{key}",
    }


def gated_streamer(texts, release, seen=None):

    def stream(
        payload,
        api_key=None,
        timeout=None,
        should_stop=None,
    ):

        if seen is not None:
            seen.append(payload)

        yield ai_stream.TextDelta(texts[0])
        release.wait(5)

        if should_stop is not None and should_stop():

            return

        for text in texts[1:]:

            yield ai_stream.TextDelta(text)

        yield ai_stream.StreamCompleted(
            usage={"total_tokens": 7},
            model="fake-model",
        )

    return stream


def quick_streamer(text, seen=None):

    def stream(
        payload,
        api_key=None,
        timeout=None,
        should_stop=None,
    ):

        if seen is not None:
            seen.append(payload)

        yield from ai_stream.buffered_stream(
            text,
            usage={"total_tokens": 1},
        )

    return stream


class FakeResponse:
    def __init__(self, lines):

        self._lines = lines

    def __enter__(self):

        return self

    def __exit__(self, *exc_info):

        return False

    def __iter__(self):

        return iter(self._lines)

    def close(self):

        pass


class DeepSeekAdapterTests(unittest.TestCase):
    """The adapter owns the DeepSeek protocol; the chat layer does not."""

    def _run(self, lines, **kwargs):

        captured = {}

        def fake_urlopen(request, timeout=None):

            captured["data"] = request.data
            captured["timeout"] = timeout
            return FakeResponse(lines)

        with mock.patch(
            "urllib.request.urlopen",
            side_effect=fake_urlopen,
        ):

            events = list(
                deepseek_client.stream_insight(
                    {
                        "model": "deepseek-flash",
                        "messages": [
                            {"role": "user", "content": "hi"}
                        ],
                    },
                    api_key="sk-test",
                    **kwargs,
                )
            )

        return events, captured

    def test_sse_deltas_ignore_reasoning_and_keep_usage(self):

        lines = [
            b'data: {"model": "deepseek-flash", "choices": '
            b'[{"delta": {"reasoning_content": "secret plan"}}]}\n',
            b'data: {"choices": [{"delta": {"content": '
            + json.dumps("你好", ensure_ascii=False).encode("utf-8")
            + b"}}]}\n",
            b'data: {"choices": [{"delta": {"content": "!\xe4\xb8\x96"}}]}\n',
            b"\n",
            b": keep-alive\n",
            b'data: {"choices": [{"delta": {}, "finish_reason": '
            b'"stop"}], "usage": {"total_tokens": 9}}\n',
            b"data: [DONE]\n",
        ]

        events, captured = self._run(lines)

        self.assertEqual(
            ai_stream.text_of(events),
            "你好!世",
        )
        self.assertTrue(
            all(
                "secret plan"
                not in getattr(event, "text", "")
                for event in events
            )
        )
        completed = [
            event
            for event in events
            if isinstance(event, ai_stream.StreamCompleted)
        ]
        self.assertEqual(len(completed), 1)
        self.assertEqual(
            completed[0].usage,
            {"total_tokens": 9},
        )

        body = json.loads(captured["data"].decode("utf-8"))
        self.assertTrue(body["stream"])
        self.assertTrue(
            body["stream_options"]["include_usage"]
        )

    def test_http_error_maps_to_auth_code(self):

        def fake_urlopen(request, timeout=None):

            raise urllib.error.HTTPError(
                deepseek_client.API_URL,
                401,
                "Unauthorized",
                {},
                None,
            )

        with mock.patch(
            "urllib.request.urlopen",
            side_effect=fake_urlopen,
        ):

            with self.assertRaises(
                deepseek_client.DeepSeekError
            ) as caught:

                list(
                    deepseek_client.stream_insight(
                        {"model": "deepseek-flash", "messages": []},
                        api_key="sk-test",
                    )
                )

        self.assertEqual(caught.exception.code, "auth")
        self.assertEqual(caught.exception.status, 401)

    def test_mid_stream_incomplete_read_maps_to_connection(self):

        class BrokenResponse(FakeResponse):

            def __iter__(self):

                yield (
                    b'data: {"choices": [{"delta": '
                    b'{"content": "part"}}]}\n'
                )
                raise http.client.IncompleteRead(b"x", 10)

        def fake_urlopen(request, timeout=None):

            return BrokenResponse([])

        with mock.patch(
            "urllib.request.urlopen",
            side_effect=fake_urlopen,
        ):

            stream = deepseek_client.stream_insight(
                {"model": "deepseek-flash", "messages": []},
                api_key="sk-test",
            )
            first = next(stream)
            self.assertEqual(first.text, "part")

            with self.assertRaises(
                deepseek_client.DeepSeekError
            ) as caught:

                next(stream)

        self.assertEqual(
            caught.exception.code,
            "connection",
        )

    def test_should_stop_ends_the_stream_early(self):

        lines = [
            b'data: {"choices": [{"delta": {"content": "one"}}]}\n',
            b'data: {"choices": [{"delta": {"content": "two"}}]}\n',
            b"data: [DONE]\n",
        ]
        calls = {"count": 0}

        def should_stop():

            calls["count"] += 1
            return calls["count"] > 1

        events, _captured = self._run(
            lines,
            should_stop=should_stop,
        )

        self.assertEqual(ai_stream.text_of(events), "one")
        self.assertFalse(
            any(
                isinstance(event, ai_stream.StreamCompleted)
                for event in events
            )
        )


class StreamSessionTests(unittest.TestCase):
    """Session-level behavior without Qt widgets."""

    def test_partial_reply_is_kept_and_excluded_from_history(self):

        release = threading.Event()
        session = ai_chat.ChatSession(
            make_report(),
            mode="freeform",
        )

        self.assertTrue(
            session.send(
                "为什么卡顿？",
                api_key="k",
                streamer=gated_streamer(
                    ["第一段", "第二段"],
                    release,
                ),
            )
        )
        self.assertTrue(
            wait_until(
                lambda: any(
                    message.get("streaming")
                    for message in session.messages
                )
            )
        )

        self.assertTrue(session.cancel())
        self.assertFalse(session.pending)
        self.assertTrue(session.stopped)

        partial = session.messages[-1]
        self.assertEqual(partial["role"], "assistant")
        self.assertFalse(partial["complete"])
        self.assertEqual(partial["interrupted"], "stopped")
        self.assertEqual(partial["content"], "第一段")

        release.set()
        self.assertTrue(
            wait_until(
                lambda: not any(
                    "第二段" in message.get("content", "")
                    for message in session.messages
                ),
                timeout=1.0,
            )
        )

        seen = []
        self.assertTrue(
            session.send(
                "再问一次",
                api_key="k",
                streamer=quick_streamer("完整回答", seen),
            )
        )
        self.assertTrue(
            wait_until(lambda: not session.pending)
        )
        self.assertIn(
            "完整回答",
            session.messages[-1]["content"],
        )

        payload_text = json.dumps(seen[0], ensure_ascii=False)
        self.assertNotIn("第一段", payload_text)

    def test_mid_stream_error_marks_incomplete_without_auto_resend(self):

        attempts = []

        def broken(
            payload,
            api_key=None,
            timeout=None,
            should_stop=None,
        ):

            attempts.append(payload)
            yield ai_stream.TextDelta("已经显示的半句")
            raise ai_stream.StreamError(
                "connection",
                detail="reset",
            )

        session = ai_chat.ChatSession(
            make_report(),
            mode="freeform",
        )

        self.assertTrue(
            session.send(
                "问题",
                api_key="k",
                streamer=broken,
            )
        )
        self.assertTrue(
            wait_until(lambda: not session.pending)
        )

        self.assertEqual(len(attempts), 1)
        self.assertEqual(
            session.last_error_code,
            "connection",
        )
        message = session.messages[-1]
        self.assertEqual(message["content"], "已经显示的半句")
        self.assertFalse(message["complete"])
        self.assertEqual(message["interrupted"], "error")
        self.assertTrue(session.can_retry)

        self.assertTrue(
            session.retry(
                api_key="k",
                streamer=quick_streamer("重试完成"),
            )
        )
        self.assertTrue(
            wait_until(lambda: not session.pending)
        )
        self.assertEqual(
            session.messages[-1]["content"],
            "重试完成",
        )
        self.assertTrue(session.messages[-1]["complete"])

    def test_structured_mode_still_waits_for_the_full_answer(self):

        gate = threading.Event()

        def client(payload, api_key=None, timeout=None):

            gate.wait(5)
            return structured_answer("观察完成")

        session = ai_chat.ChatSession(
            make_full_report(key="structured"),
            mode="structured",
        )

        self.assertTrue(
            session.send(
                "问题",
                api_key="k",
                client=client,
            )
        )
        time.sleep(0.1)
        self.assertTrue(session.pending)
        self.assertFalse(
            any(
                message.get("role") == "assistant"
                for message in session.messages
            )
        )

        gate.set()
        self.assertTrue(
            wait_until(lambda: not session.pending)
        )
        self.assertTrue(session.messages[-1]["complete"])


class StreamUiTests(unittest.TestCase):
    """The same UI path works with any provider adapter."""

    app = None

    @classmethod
    def setUpClass(cls):

        cls.app = (
            QApplication.instance()
            or QApplication([])
        )
        i18n.get_manager().set_language("en")

    def setUp(self):

        self.hosts = []

    def tearDown(self):

        for host in self.hosts:

            try:

                host.close()
                host.deleteLater()

            except RuntimeError:

                pass

        self.app.processEvents()
        deepseek_client.clear_session_api_key()

    def wait_qt(self, predicate, timeout=5.0):

        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:

            self.app.processEvents()

            if predicate():
                return True

            time.sleep(0.01)

        self.app.processEvents()
        return bool(predicate())

    def _page(self, streamer):

        host = QWidget()
        page = ai_chat.AIChatPage(
            ai_chat.ChatStore(mode="freeform"),
            language="en",
            streamer=streamer,
            parent=host,
        )
        self.hosts.append(host)
        host.show()
        self.app.processEvents()
        return page

    def test_first_delta_is_visible_before_completion(self):

        release = threading.Event()
        page = self._page(
            gated_streamer(
                ["First visible part", " and the rest"],
                release,
            )
        )
        page.set_report_context(make_report())
        page.panel.input.setPlainText("How is it?")
        page.panel._send()

        self.assertTrue(
            self.wait_qt(
                lambda: (
                    "First visible part"
                    in page.panel.transcript.toPlainText()
                )
            )
        )
        self.assertTrue(page.session.pending)
        self.assertNotIn(
            "and the rest",
            page.panel.transcript.toPlainText(),
        )

        release.set()

        self.assertTrue(
            self.wait_qt(
                lambda: (
                    not page.session.pending
                    and "First visible part and the rest"
                    in page.panel.transcript.toPlainText()
                )
            )
        )
        self.assertTrue(page.session.messages[-1]["complete"])

    def test_report_switch_during_stream_keeps_conversations_apart(self):

        release = threading.Event()
        page = self._page(
            gated_streamer(["A 的第一段", "A 的第二段"], release)
        )
        page.set_report_context(
            make_report("capture-a", "game-a.exe")
        )
        page.panel.input.setPlainText("A 问题")
        page.panel._send()

        self.assertTrue(
            self.wait_qt(
                lambda: "A 的第一段"
                in page.panel.transcript.toPlainText()
            )
        )

        page.set_report_context(
            make_report("capture-b", "game-b.exe")
        )
        self.assertEqual(page.report_key, "capture-b")
        self.assertNotIn(
            "A 的第一段",
            page.panel.transcript.toPlainText(),
        )

        release.set()
        self.assertTrue(
            self.wait_qt(
                lambda: not page.store.get("capture-a").pending
            )
        )
        self.app.processEvents()

        self.assertNotIn(
            "A 的第二段",
            page.panel.transcript.toPlainText(),
        )
        self.assertEqual(page.report_key, "capture-b")

        page.set_report_context(
            make_report("capture-a", "game-a.exe")
        )
        self.assertIn(
            "A 的第一段A 的第二段",
            page.panel.transcript.toPlainText(),
        )

    def test_stop_button_keeps_partial_and_ui_can_send_again(self):

        release = threading.Event()
        page = self._page(
            gated_streamer(["开始输出", "后面的内容"], release)
        )
        page.set_report_context(make_report())
        page.panel.input.setPlainText("问题")
        page.panel._send()

        self.assertTrue(
            self.wait_qt(
                lambda: "开始输出"
                in page.panel.transcript.toPlainText()
            )
        )
        self.assertFalse(page.panel.stop_button.isHidden())
        self.assertIn(
            "Generating",
            page.panel.status.text(),
        )

        page.panel.stop_button.click()
        self.app.processEvents()

        self.assertFalse(page.session.pending)
        self.assertIn(
            "Stopped",
            page.panel.status.text(),
        )
        self.assertIn(
            "Incomplete",
            page.panel.transcript.toPlainText(),
        )

        release.set()
        self.app.processEvents()

        page.panel.input.setPlainText("再来一次")
        page.panel.streamer = quick_streamer("新的完整回答")
        page.panel._send()
        self.assertTrue(
            self.wait_qt(
                lambda: (
                    not page.session.pending
                    and "新的完整回答"
                    in page.panel.transcript.toPlainText()
                )
            )
        )


if __name__ == "__main__":
    unittest.main()
