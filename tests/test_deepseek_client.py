"""DeepSeek client tests using mocked HTTP responses."""

import json
import os
import socket
import sys
import unittest
import urllib.error

from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import ai_insight  # noqa: E402
import deepseek_client  # noqa: E402


class FakeResponse:

    def __init__(self, payload):

        self.payload = payload

    def read(self):

        return self.payload

    def __enter__(self):

        return self

    def __exit__(self, *_args):

        return False


def summary():

    return {
        "application": "sample-game.exe",
        "displayed_frames": 600,
        "displayed_seconds": 10.0,
        "average_display_fps": 60.0,
        "longest_display_seconds": 0.25,
        "longest_display_at_seconds": 4.0,
        "display_data_unknown": False,
    }


def payload():

    return ai_insight.build_payload(summary())


def response_body(text):

    return json.dumps(
        {
            "choices": [
                {
                    "message": {
                        "content": text,
                    }
                }
            ]
        },
        ensure_ascii=False,
    ).encode("utf-8")


class DeepSeekSuccessTests(unittest.TestCase):

    def tearDown(self):

        deepseek_client.clear_session_api_key()

    def test_return_usage_returns_content_and_token_counts(self):

        body = json.dumps(
            {
                "choices": [
                    {
                        "message": {
                            "content": "OK",
                        }
                    }
                ],
                "usage": {
                    "prompt_tokens": 12,
                    "completion_tokens": 3,
                    "total_tokens": 15,
                },
            }
        ).encode("utf-8")

        with mock.patch(
            "deepseek_client.urllib.request.urlopen",
            return_value=FakeResponse(body),
        ):

            content, usage = deepseek_client.request_insight(
                payload(),
                api_key="sk-test",
                return_usage=True,
            )

        self.assertEqual(content, "OK")
        self.assertEqual(usage["prompt_tokens"], 12)
        self.assertEqual(usage["total_tokens"], 15)

    def test_successful_request_uses_verified_model_and_thinking(self):

        captured = {}

        def fake_urlopen(request, timeout):

            captured["request"] = request
            captured["timeout"] = timeout
            captured["body"] = json.loads(
                request.data.decode("utf-8")
            )
            return FakeResponse(
                response_body("这次不用改。")
            )

        with mock.patch(
            "deepseek_client.urllib.request.urlopen",
            fake_urlopen,
        ):

            answer = deepseek_client.request_insight(
                payload(),
                api_key="sk-test",
                timeout=12,
            )

        self.assertEqual(answer, "这次不用改。")
        self.assertEqual(captured["timeout"], 12.0)
        self.assertEqual(
            captured["body"]["model"],
            "deepseek-flash",
        )
        self.assertEqual(
            captured["body"]["thinking"],
            {"type": "disabled"},
        )
        self.assertEqual(
            captured["request"].get_header(
                "Authorization"
            ),
            "Bearer sk-test",
        )
        self.assertLessEqual(
            len(captured["request"].data),
            ai_insight.MAX_REQUEST_BYTES,
        )

    def test_saved_key_then_environment_then_session(self):

        with mock.patch(
            "deepseek_client.get_saved_api_key",
            return_value="saved-key",
        ), mock.patch.dict(
            os.environ,
            {"DEEPSEEK_API_KEY": "env-key"},
        ):

            self.assertEqual(
                deepseek_client.get_api_key(),
                "saved-key",
            )
            self.assertEqual(
                deepseek_client.get_api_key_source(),
                "saved",
            )

        with mock.patch(
            "deepseek_client.get_saved_api_key",
            return_value=None,
        ), mock.patch.dict(
            os.environ,
            {"DEEPSEEK_API_KEY": "env-key"},
        ):

            self.assertEqual(
                deepseek_client.get_api_key(),
                "env-key",
            )
            self.assertEqual(
                deepseek_client.get_api_key_source(),
                "environment",
            )

        with mock.patch(
            "deepseek_client.get_saved_api_key",
            return_value=None,
        ), mock.patch.dict(
            os.environ,
            {},
            clear=True,
        ):

            deepseek_client.set_session_api_key(
                "session-key"
            )

            self.assertEqual(
                deepseek_client.get_api_key(),
                "session-key",
            )
            self.assertEqual(
                deepseek_client.get_api_key_source(),
                "session",
            )

    def test_saved_key_uses_credential_store(self):

        with mock.patch(
            "credential_store.save_secret"
        ) as save:

            deepseek_client.set_saved_api_key("sk-new")

        save.assert_called_once_with("sk-new")

    def test_delete_saved_key_uses_credential_store(self):

        with mock.patch(
            "credential_store.delete_secret",
            return_value=True,
        ) as delete:

            self.assertTrue(
                deepseek_client.delete_saved_api_key()
            )

        delete.assert_called_once_with()

    def test_test_connection_sends_minimal_payload(self):

        captured = {}

        def fake_urlopen(request, timeout):

            captured["body"] = json.loads(
                request.data.decode("utf-8")
            )
            captured["timeout"] = timeout
            return FakeResponse(response_body("OK"))

        with mock.patch(
            "deepseek_client.urllib.request.urlopen",
            fake_urlopen,
        ):

            answer = deepseek_client.test_connection(
                api_key="sk-test",
                timeout=7,
            )

        self.assertEqual(answer, "OK")
        self.assertEqual(captured["timeout"], 7.0)
        self.assertEqual(
            captured["body"]["max_tokens"],
            8,
        )
        self.assertEqual(
            len(captured["body"]["messages"]),
            1,
        )
        self.assertNotIn(
            "report",
            json.dumps(captured["body"]).lower(),
        )
        self.assertLessEqual(
            len(
                json.dumps(
                    captured["body"],
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
            ),
            4096,
        )


class DeepSeekFailureTests(unittest.TestCase):

    def tearDown(self):

        deepseek_client.clear_session_api_key()

    def assert_code(self, code, exception):

        self.assertIsInstance(
            exception,
            deepseek_client.DeepSeekError,
        )
        self.assertEqual(exception.code, code)

    def test_missing_key_is_reported_before_network(self):

        with mock.patch(
            "deepseek_client.get_saved_api_key",
            return_value=None,
        ), mock.patch.dict(os.environ, {}, clear=True):

            deepseek_client.clear_session_api_key()

            with self.assertRaises(
                deepseek_client.DeepSeekError
            ) as caught:

                deepseek_client.request_insight(
                    payload()
                )

        self.assert_code("missing_key", caught.exception)

    def test_http_statuses_map_to_clear_error_codes(self):

        cases = {
            401: "auth",
            403: "auth",
            402: "balance",
            413: "too_large",
            429: "rate_limit",
            500: "server",
            400: "http",
        }

        for status, code in cases.items():

            with self.subTest(status=status):

                error = urllib.error.HTTPError(
                    deepseek_client.API_URL,
                    status,
                    "failure",
                    None,
                    None,
                )

                with mock.patch(
                    "deepseek_client.urllib.request.urlopen",
                    side_effect=error,
                ):

                    with self.assertRaises(
                        deepseek_client.DeepSeekError
                    ) as caught:

                        deepseek_client.request_insight(
                            payload(),
                            api_key="sk-test",
                        )

                self.assert_code(
                    code,
                    caught.exception,
                )
                self.assertEqual(
                    caught.exception.status,
                    status,
                )

    def test_connection_and_timeout_are_distinguished(self):

        connection = urllib.error.URLError(
            OSError("network unreachable")
        )

        with mock.patch(
            "deepseek_client.urllib.request.urlopen",
            side_effect=connection,
        ):

            with self.assertRaises(
                deepseek_client.DeepSeekError
            ) as caught:

                deepseek_client.request_insight(
                    payload(),
                    api_key="sk-test",
                )

        self.assert_code("connection", caught.exception)

        timeout = urllib.error.URLError(
            socket.timeout("timed out")
        )

        with mock.patch(
            "deepseek_client.urllib.request.urlopen",
            side_effect=timeout,
        ):

            with self.assertRaises(
                deepseek_client.DeepSeekError
            ) as caught:

                deepseek_client.request_insight(
                    payload(),
                    api_key="sk-test",
                )

        self.assert_code("timeout", caught.exception)

    def test_oversize_body_is_rejected_before_sending(self):

        oversized = {
            "model": "deepseek-flash",
            "thinking": {"type": "disabled"},
            "messages": [
                {
                    "role": "user",
                    "content": "x" * 5000,
                }
            ],
        }

        with mock.patch(
            "deepseek_client.urllib.request.urlopen"
        ) as urlopen:

            with self.assertRaises(
                deepseek_client.DeepSeekError
            ) as caught:

                deepseek_client.request_insight(
                    oversized,
                    api_key="sk-test",
                )

        self.assert_code("too_large", caught.exception)
        urlopen.assert_not_called()

    def test_unparseable_response_is_reported(self):

        with mock.patch(
            "deepseek_client.urllib.request.urlopen",
            return_value=FakeResponse(b"not json"),
        ):

            with self.assertRaises(
                deepseek_client.DeepSeekError
            ) as caught:

                deepseek_client.request_insight(
                    payload(),
                    api_key="sk-test",
                )

        self.assert_code(
            "invalid_response",
            caught.exception,
        )

    def test_empty_assistant_content_is_reported(self):

        with mock.patch(
            "deepseek_client.urllib.request.urlopen",
            return_value=FakeResponse(
                response_body("   ")
            ),
        ):

            with self.assertRaises(
                deepseek_client.DeepSeekError
            ) as caught:

                deepseek_client.request_insight(
                    payload(),
                    api_key="sk-test",
                )

        self.assert_code(
            "invalid_response",
            caught.exception,
        )


if __name__ == "__main__":

    unittest.main()
