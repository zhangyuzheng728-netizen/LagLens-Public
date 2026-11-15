"""Multi-provider streaming: adapters, settings, shared UI path."""

import json
import os
import sys
import tempfile
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
import ai_providers  # noqa: E402
import ai_stream  # noqa: E402
import ai_settings  # noqa: E402
import credential_store  # noqa: E402
import settings as app_settings  # noqa: E402
import i18n  # noqa: E402


PROVIDER_CASES = (
    (
        "deepseek",
        "deepseek-flash",
        "api.deepseek.com",
        '{"choices":[{"delta":{"content":"第一段"}}]}',
        '{"choices":[{"delta":{"content":" 第二段"}}]}',
        '{"choices":[{"delta":{"reasoning_content":"hidden"}}]}',
    ),
    (
        "openai",
        "gpt-4.1",
        "api.openai.com/v1/responses",
        '{"type":"response.output_text.delta","delta":"第一段"}',
        '{"type":"response.output_text.delta","delta":" 第二段"}',
        '{"type":"response.reasoning_summary_text.delta","delta":"hidden"}',
    ),
    (
        "claude",
        "claude-sonnet-4-5",
        "api.anthropic.com/v1/messages",
        '{"type":"content_block_delta","delta":{"type":"text_delta","text":"第一段"}}',
        '{"type":"content_block_delta","delta":{"type":"text_delta","text":" 第二段"}}',
        '{"type":"content_block_delta","delta":{"type":"thinking_delta","thinking":"hidden"}}',
    ),
    (
        "gemini",
        "gemini-2.5-flash",
        "generativelanguage.googleapis.com",
        '{"candidates":[{"content":{"parts":[{"text":"第一段"}]}}]}',
        '{"candidates":[{"content":{"parts":[{"text":" 第二段"}]}}]}',
        '{"candidates":[{"content":{"parts":[{"text":"hidden","thought":true}]}}]}',
    ),
)


def data_line(payload):

    return f"data: {payload}".encode("utf-8") + b"\n"


def first_and_second(case):

    _pid, _model, _url, first, second, _reasoning = case
    return first, second


def collect(events):

    return list(events)


class FakeResponse:

    def __init__(self, lines_factory):

        self._lines_factory = lines_factory

    def __enter__(self):

        return self

    def __exit__(self, *exc_info):

        return False

    def __iter__(self):

        return self._lines_factory()


def stream_response(provider_id, case, release=None, include_second=True):

    first, second = first_and_second(case)

    def factory():

        if provider_id == "claude":

            yield data_line(
                '{"type":"message_start","message":'
                '{"model":"claude-sonnet-4-5","usage":'
                '{"input_tokens":5}}}'
            )

        yield data_line(case[5])
        yield data_line(first)

        if release is not None:

            release.wait(5)

        if provider_id == "deepseek":

            yield data_line(second)
            yield data_line(
                '{"choices":[],"usage":{"prompt_tokens":5,'
                '"completion_tokens":7,"total_tokens":12}}'
            )
            yield b"data: [DONE]\n"
            return

        if provider_id == "claude":

            yield data_line(second)
            yield data_line(
                '{"type":"message_delta","delta":'
                '{"stop_reason":"end_turn"},'
                '"usage":{"output_tokens":7}}'
            )
            yield data_line('{"type":"message_stop"}')
            return

        if provider_id == "gemini":

            yield data_line(second)
            yield data_line(
                '{"candidates":[{"content":{"parts":[]},'
                '"finishReason":"STOP"}],"usageMetadata":'
                '{"promptTokenCount":5,'
                '"candidatesTokenCount":7,'
                '"totalTokenCount":12}}'
            )
            return

        yield data_line(second)
        yield data_line(
            '{"type":"response.output_text.done",'
            '"text":"第一段 第二段"}'
        )
        yield data_line(
            '{"type":"response.completed","response":'
            '{"model":"gpt-4.1","usage":{"input_tokens":5,'
            '"output_tokens":7,"total_tokens":12}}}'
        )

    return FakeResponse(factory)


def streamer_for(provider_id, model):

    return ai_providers.make_streamer(provider_id, model)


class AdapterTests(unittest.TestCase):
    """Each adapter converts its own protocol to the shared events."""

    def test_each_adapter_streams_text_and_usage(self):

        for case in PROVIDER_CASES:

            provider_id, model, url_part, _first, _second, _reasoning = case

            with self.subTest(provider=provider_id):

                captured = {}

                def fake_urlopen(request, timeout=None):

                    captured["url"] = request.full_url
                    captured["headers"] = dict(request.headers)
                    captured["body"] = request.data
                    return stream_response(provider_id, case)

                with mock.patch(
                    "urllib.request.urlopen",
                    side_effect=fake_urlopen,
                ):

                    events = collect(
                        streamer_for(provider_id, model)(
                            {"messages": [
                                {"role": "system", "content": "sys"},
                                {"role": "user", "content": "hi"},
                                {"role": "assistant", "content": "old"},
                                {"role": "user", "content": "now"},
                            ]},
                            api_key="sk-test",
                        )
                    )

                text = ai_stream.text_of(events)
                self.assertEqual(text, "第一段 第二段")
                self.assertNotIn("hidden", text)
                self.assertIn(url_part, captured["url"])
                bodies = captured["body"].decode("utf-8")
                self.assertNotIn("reasoning", bodies)

                completed = [
                    event
                    for event in events
                    if isinstance(event, ai_stream.StreamCompleted)
                ]
                self.assertEqual(len(completed), 1)
                self.assertEqual(
                    completed[0].usage.get("total_tokens"),
                    12,
                )

    def test_each_adapter_rejects_a_short_stream(self):

        for case in PROVIDER_CASES:

            provider_id, model, _url, _first, _second, _reasoning = case

            with self.subTest(provider=provider_id):

                def fake_urlopen(request, timeout=None):

                    def factory():

                        yield data_line(case[3])

                    return FakeResponse(factory)

                with mock.patch(
                    "urllib.request.urlopen",
                    side_effect=fake_urlopen,
                ):

                    stream = streamer_for(provider_id, model)(
                        {"messages": [
                            {"role": "user", "content": "hi"}
                        ]},
                        api_key="sk-test",
                    )

                    self.assertEqual(next(stream).text, "第一段")

                    with self.assertRaises(ai_stream.StreamError) as caught:

                        next(stream)

                self.assertEqual(
                    caught.exception.code,
                    "connection",
                )

    def test_each_adapter_maps_auth_failure(self):

        for case in PROVIDER_CASES:

            provider_id, model, _url, _first, _second, _reasoning = case

            with self.subTest(provider=provider_id):

                def fake_urlopen(request, timeout=None):

                    raise urllib.error.HTTPError(
                        request.full_url,
                        401,
                        "Unauthorized",
                        {},
                        None,
                    )

                with mock.patch(
                    "urllib.request.urlopen",
                    side_effect=fake_urlopen,
                ):

                    stream = streamer_for(provider_id, model)(
                        {"messages": [
                            {"role": "user", "content": "hi"}
                        ]},
                        api_key="sk-test",
                    )

                    with self.assertRaises(ai_stream.StreamError) as caught:

                        next(stream)

                self.assertEqual(caught.exception.code, "auth")
                self.assertEqual(caught.exception.status, 401)


class ProviderRegistryTests(unittest.TestCase):

    def test_default_provider_is_deepseek(self):

        self.assertEqual(
            ai_providers.DEFAULT_PROVIDER,
            "deepseek",
        )
        self.assertEqual(
            ai_providers.get(None).id,
            "deepseek",
        )

    def test_deepseek_credentials_delegate_to_existing_store(self):

        with mock.patch(
            "deepseek_client.get_api_key_source",
            return_value="saved",
        ), mock.patch(
            "deepseek_client.get_api_key",
            return_value="sk-existing",
        ):

            self.assertEqual(
                ai_providers.api_key_source("deepseek"),
                "saved",
            )
            self.assertEqual(
                ai_providers.get_api_key("deepseek"),
                "sk-existing",
            )

    def test_other_providers_use_their_own_credential_target(self):

        saved = []

        def save(value, target=None):

            saved.append((value, target))

        with mock.patch(
            "credential_store.save_secret",
            side_effect=save,
        ):

            ai_providers.set_saved_api_key("openai", "sk-openai")
            ai_providers.set_saved_api_key("claude", "sk-claude")
            ai_providers.set_saved_api_key("gemini", "sk-gemini")

        self.assertEqual(
            [target for _value, target in saved],
            [
                "LagLens/OpenAIApiKey",
                "LagLens/ClaudeApiKey",
                "LagLens/GeminiApiKey",
            ],
        )

    def test_selection_from_settings_keeps_deepseek_default(self):

        with tempfile.TemporaryDirectory() as tmp:

            settings = app_settings.AppSettings(
                Path(tmp) / "t.ini"
            )

            self.assertEqual(
                ai_providers.selection_from_settings(settings),
                ("deepseek", "deepseek-flash"),
            )

            settings.set_ai_provider("claude")
            settings.set_ai_model(
                "claude",
                "claude-haiku-4-5",
            )

            self.assertEqual(
                ai_providers.selection_from_settings(settings),
                ("claude", "claude-haiku-4-5"),
            )


class ProviderSettingsTests(unittest.TestCase):

    app = None

    @classmethod
    def setUpClass(cls):

        cls.app = (
            QApplication.instance()
            or QApplication([])
        )
        i18n.get_manager().set_language("en")

    def _card(self, tmp):

        settings = app_settings.AppSettings(
            Path(tmp) / "t.ini"
        )
        card = ai_settings.AISettingsCard(settings)
        card.show()
        self.app.processEvents()
        self.addCleanup(card.close)
        self.addCleanup(card.deleteLater)
        return card, settings

    def test_switching_provider_persists_without_requests(self):

        with tempfile.TemporaryDirectory() as tmp:

            card, settings = self._card(tmp)
            changed = []
            card.selection_changed.connect(
                lambda provider, model: changed.append(
                    (provider, model)
                )
            )

            with mock.patch(
                "urllib.request.urlopen",
            ) as urlopen:

                index = card.provider_combo.findData("openai")
                card.provider_combo.setCurrentIndex(index)
                self.app.processEvents()

                self.assertEqual(
                    settings.ai_provider(),
                    "openai",
                )
                self.assertEqual(
                    settings.ai_model("openai"),
                    "gpt-4.1",
                )
                urlopen.assert_not_called()

            self.assertEqual(
                changed[-1],
                ("openai", "gpt-4.1"),
            )
            self.assertIn(
                "OpenAI",
                card.current_label.text(),
            )
            self.assertIn(
                "gpt-4.1",
                card.current_label.text(),
            )

    def test_provider_switch_restores_saved_model(self):

        with tempfile.TemporaryDirectory() as tmp:

            card, settings = self._card(tmp)
            settings.set_ai_model(
                "gemini",
                "gemini-2.5-pro",
            )
            index = card.provider_combo.findData("gemini")
            card.provider_combo.setCurrentIndex(index)
            self.app.processEvents()

            self.assertEqual(
                card.selection(),
                ("gemini", "gemini-2.5-pro"),
            )
            self.assertIn(
                "gemini-2.5-pro",
                card.model_combo.currentText(),
            )

    def test_key_save_targets_the_selected_provider(self):

        with tempfile.TemporaryDirectory() as tmp:

            card, _settings = self._card(tmp)
            index = card.provider_combo.findData("claude")
            card.provider_combo.setCurrentIndex(index)

            with mock.patch(
                "credential_store.save_secret",
            ) as save:
                card.key_input.setText("sk-claude")
                card.save_key()

            save.assert_called_once()
            self.assertEqual(
                save.call_args.kwargs.get("target")
                or save.call_args[1].get("target"),
                "LagLens/ClaudeApiKey",
            )

    def test_status_follows_the_selected_provider(self):

        with tempfile.TemporaryDirectory() as tmp:

            card, _settings = self._card(tmp)

            with mock.patch(
                "ai_providers.api_key_source",
                return_value="none",
            ):
                index = card.provider_combo.findData("gemini")
                card.provider_combo.setCurrentIndex(index)
                self.app.processEvents()

            self.assertIn("Gemini", card.status.text())


class ProviderUiStreamTests(unittest.TestCase):
    """Every provider uses the same AIChatPage/ChatPanel path."""

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

    def wait_qt(self, predicate, timeout=5.0):

        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:

            self.app.processEvents()

            if predicate():
                return True

            time.sleep(0.01)

        self.app.processEvents()
        return bool(predicate())

    def _page(self, selection, client=None, streamer=None):

        host = QWidget()
        page = ai_chat.AIChatPage(
            ai_chat.ChatStore(mode="freeform"),
            language="en",
            client=client,
            streamer=streamer,
            selection=selection,
            parent=host,
        )
        self.hosts.append(host)
        host.show()
        self.app.processEvents()
        return page

    def test_first_segment_before_completion_for_every_provider(self):

        for case in PROVIDER_CASES:

            provider_id, model, url_part, _first, _second, _reasoning = case

            with self.subTest(provider=provider_id):

                release = threading.Event()
                urls = []

                def fake_urlopen(request, timeout=None):

                    urls.append(request.full_url)
                    return stream_response(
                        provider_id,
                        case,
                        release=release,
                    )

                page = self._page(
                    lambda pid=provider_id, m=model: (pid, m)
                )

                with mock.patch(
                    "urllib.request.urlopen",
                    side_effect=fake_urlopen,
                ), mock.patch(
                    "ai_providers.get_api_key",
                    return_value="sk-test",
                ):

                    page.panel.input.setPlainText("How is it?")
                    page.panel._send()

                    self.assertTrue(
                        self.wait_qt(
                            lambda: "第一段"
                            in page.panel.transcript.toPlainText()
                        )
                    )
                    self.assertTrue(page.session.pending)
                    self.assertNotIn(
                        "第二段",
                        page.panel.transcript.toPlainText(),
                    )

                    release.set()

                    self.assertTrue(
                        self.wait_qt(
                            lambda: (
                                not page.session.pending
                                and "第一段 第二段"
                                in page.panel.transcript.toPlainText()
                            )
                        )
                    )

                self.assertTrue(urls)
                self.assertIn(url_part, urls[0])
                last = page.session.messages[-1]
                self.assertTrue(last["complete"])
                self.assertEqual(last["provider"], provider_id)
                self.assertEqual(last["model"], model)

    def test_auth_failure_points_to_settings_without_retry(self):

        for case in PROVIDER_CASES:

            provider_id, model, _url, _first, _second, _reasoning = case

            with self.subTest(provider=provider_id):

                calls = []

                def fake_urlopen(request, timeout=None):

                    calls.append(request.full_url)
                    raise urllib.error.HTTPError(
                        request.full_url,
                        401,
                        "Unauthorized",
                        {},
                        None,
                    )

                page = self._page(
                    lambda pid=provider_id, m=model: (pid, m)
                )

                with mock.patch(
                    "urllib.request.urlopen",
                    side_effect=fake_urlopen,
                ), mock.patch(
                    "ai_providers.get_api_key",
                    return_value="sk-test",
                ), mock.patch(
                    "ai_providers.api_key_source",
                    return_value="saved",
                ):

                    page.refresh_selection()
                    self.assertTrue(
                        page.settings_button.isHidden()
                    )

                    page.panel.input.setPlainText("How is it?")
                    page.panel._send()

                    self.assertTrue(
                        self.wait_qt(
                            lambda: page.session.last_error_code
                            == "auth"
                        )
                    )

                self.assertEqual(len(calls), 1)
                self.assertIn(
                    "authentication failed",
                    page.panel.status.text().lower(),
                )
                self.assertIn(
                    "Settings",
                    page.panel.status.text(),
                )
                self.assertFalse(
                    page.settings_button.isHidden()
                )

    def test_mid_stream_disconnect_keeps_partial_and_can_retry(self):

        for case in PROVIDER_CASES:

            provider_id, model, _url, _first, _second, _reasoning = case

            with self.subTest(provider=provider_id):

                def fake_urlopen(request, timeout=None):

                    def factory():

                        yield data_line(case[3])

                    return FakeResponse(factory)

                page = self._page(
                    lambda pid=provider_id, m=model: (pid, m)
                )

                with mock.patch(
                    "urllib.request.urlopen",
                    side_effect=fake_urlopen,
                ), mock.patch(
                    "ai_providers.get_api_key",
                    return_value="sk-test",
                ):

                    page.panel.input.setPlainText("How is it?")
                    page.panel._send()

                    self.assertTrue(
                        self.wait_qt(
                            lambda: (
                                page.session.last_error_code
                                == "connection"
                                and "第一段"
                                in page.panel.transcript.toPlainText()
                            )
                        )
                    )

                self.assertIn(
                    "第一段",
                    page.panel.transcript.toPlainText(),
                )
                self.assertIn(
                    "Incomplete",
                    page.panel.transcript.toPlainText(),
                )
                self.assertTrue(page.session.can_retry)

                with mock.patch(
                    "urllib.request.urlopen",
                    side_effect=lambda request, timeout=None: stream_response(
                        provider_id,
                        case,
                    ),
                ), mock.patch(
                    "ai_providers.get_api_key",
                    return_value="sk-test",
                ):

                    page.panel._retry()

                    self.assertTrue(
                        self.wait_qt(
                            lambda: (
                                not page.session.pending
                                and "第一段 第二段"
                                in page.panel.transcript.toPlainText()
                            )
                        )
                    )

    def test_stop_then_resend_switches_provider_cleanly(self):

        cases = {
            "openai": PROVIDER_CASES[1],
            "claude": PROVIDER_CASES[2],
        }
        release = threading.Event()
        selected = {"value": ("openai", "gpt-4.1")}

        page = self._page(lambda: selected["value"])

        def fake_urlopen(request, timeout=None):

            provider_id = selected["value"][0]
            return stream_response(
                provider_id,
                cases[provider_id],
                release=release,
            )

        with mock.patch(
            "urllib.request.urlopen",
            side_effect=fake_urlopen,
        ), mock.patch(
            "ai_providers.get_api_key",
            return_value="sk-test",
        ):

            page.panel.input.setPlainText("How is it?")
            page.panel._send()

            self.assertTrue(
                self.wait_qt(
                    lambda: "第一段"
                    in page.panel.transcript.toPlainText()
                )
            )

            page.panel.stop_button.click()
            self.app.processEvents()
            self.assertFalse(page.session.pending)
            self.assertIn(
                "Stopped",
                page.panel.status.text(),
            )

            release.set()
            self.app.processEvents()

            selected["value"] = ("claude", "claude-sonnet-4-5")
            page.panel.input.setPlainText("Second question")
            page.panel._send()

            self.assertTrue(
                self.wait_qt(
                    lambda: (
                        not page.session.pending
                        and page.session.messages[-1].get(
                            "provider"
                        )
                        == "claude"
                    )
                )
            )

        self.assertEqual(
            page.session.messages[-1]["provider"],
            "claude",
        )
        self.assertTrue(page.session.messages[-1]["complete"])

    def test_injected_client_still_wins_over_the_network(self):

        calls = []

        def client(payload, api_key=None, timeout=None):

            calls.append(payload)
            return "injected answer"

        page = self._page(
            lambda: ("openai", "gpt-4.1"),
            client=client,
        )

        with mock.patch(
            "urllib.request.urlopen",
        ) as urlopen, mock.patch(
            "ai_providers.get_api_key",
            return_value="sk-test",
        ):

            page.panel.input.setPlainText("How is it?")
            page.panel._send()

            self.assertTrue(
                self.wait_qt(
                    lambda: (
                        not page.session.pending
                        and "injected answer"
                        in page.panel.transcript.toPlainText()
                    )
                )
            )

            urlopen.assert_not_called()

        self.assertEqual(len(calls), 1)
        self.assertEqual(
            page.session.messages[-1]["provider"],
            "openai",
        )

    def test_in_flight_request_keeps_its_provider(self):

        selected = {"value": ("openai", "gpt-4.1")}
        release = threading.Event()
        urls = []

        def fake_urlopen(request, timeout=None):

            urls.append(request.full_url)
            return stream_response(
                "openai",
                PROVIDER_CASES[1],
                release=release,
            )

        page = self._page(lambda: selected["value"])

        with mock.patch(
            "urllib.request.urlopen",
            side_effect=fake_urlopen,
        ), mock.patch(
            "ai_providers.get_api_key",
            return_value="sk-test",
        ):

            page.panel.input.setPlainText("How is it?")
            page.panel._send()

            self.assertTrue(
                self.wait_qt(
                    lambda: "第一段"
                    in page.panel.transcript.toPlainText()
                )
            )

            selected["value"] = ("gemini", "gemini-2.5-flash")
            page.refresh_selection()

            release.set()

            self.assertTrue(
                self.wait_qt(lambda: not page.session.pending)
            )

        self.assertEqual(len(urls), 1)
        self.assertIn("api.openai.com", urls[0])
        self.assertEqual(
            page.session.messages[-1]["provider"],
            "openai",
        )
        self.assertIn(
            "Gemini",
            page.provider_label.text(),
        )


if __name__ == "__main__":
    unittest.main()
