"""AI service settings card and credential-state tests."""

import os
import sys
import time
import unittest

from contextlib import ExitStack
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

import ai_settings  # noqa: E402
import deepseek_client  # noqa: E402
import i18n  # noqa: E402


class AISettingsTests(unittest.TestCase):

    app = None

    @classmethod
    def setUpClass(cls):

        cls.app = (
            QApplication.instance()
            or QApplication([])
        )
        i18n.get_manager().set_language("en")

    def tearDown(self):

        self.app.processEvents()

    def wait_until(self, predicate, timeout=3.0):

        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:

            self.app.processEvents()

            if predicate():
                return True

            time.sleep(0.01)

        self.app.processEvents()
        return bool(predicate())

    def _card(self, source, env=False, test=None):

        holder = {"source": source}

        patches = [
            mock.patch(
                "deepseek_client.get_api_key_source",
                side_effect=lambda: holder["source"],
            ),
            mock.patch(
                "deepseek_client.has_env_api_key",
                return_value=env,
            ),
        ]

        if test is not None:
            patches.append(
                mock.patch(
                    "deepseek_client.test_connection",
                    test,
                )
            )

        stack = ExitStack()

        for patch in patches:
            stack.enter_context(patch)

        card = ai_settings.AISettingsCard()
        card.show()
        self.app.processEvents()
        self.addCleanup(stack.close)
        self.addCleanup(card.close)
        self.addCleanup(card.deleteLater)
        return card, holder

    def test_open_does_not_send_a_connection_test(self):

        test = mock.Mock(return_value="OK")
        card, _holder = self._card("none", test=test)

        self.assertIn("Not configured", card.status.text())
        self.assertFalse(card.test_button.isEnabled())
        self.assertTrue(card.save_button.isEnabled())
        test.assert_not_called()

    def test_save_key_clears_input_and_requests_next_state(self):

        def save(value):
            holder["source"] = "saved"

        holder = {"source": "none"}

        with mock.patch(
            "deepseek_client.get_api_key_source",
            side_effect=lambda: holder["source"],
        ), mock.patch(
            "deepseek_client.has_env_api_key",
            return_value=False,
        ), mock.patch(
            "deepseek_client.set_saved_api_key",
            side_effect=save,
        ) as setter:

            card = ai_settings.AISettingsCard()
            card.show()
            changed = []
            card.key_changed.connect(
                lambda: changed.append(True)
            )
            card.key_input.setText("sk-test")
            card.save_key()
            self.app.processEvents()

            setter.assert_called_once_with("sk-test")
            self.assertEqual(
                card.key_input.text(),
                "",
            )
            self.assertTrue(changed)
            self.assertIn("Configured", card.status.text())
            card.close()
            card.deleteLater()

    def test_save_failure_is_visible(self):

        with mock.patch(
            "deepseek_client.get_api_key_source",
            return_value="none",
        ), mock.patch(
            "deepseek_client.set_saved_api_key",
            side_effect=RuntimeError("write failed"),
        ):

            card = ai_settings.AISettingsCard()
            card.key_input.setText("sk-test")
            card.save_key()

            self.assertIn(
                "Save failed",
                card.status.text(),
            )
            card.close()
            card.deleteLater()

    def test_environment_fallback_is_explicit(self):

        card, _holder = self._card(
            "environment",
            env=True,
        )

        self.assertIn(
            "environment-variable",
            card.status.text(),
        )
        self.assertFalse(
            card.remove_button.isEnabled()
        )
        self.assertTrue(
            card.test_button.isEnabled()
        )

    def test_remove_keeps_environment_fallback_visible(self):

        holder = {"source": "saved"}

        def delete():
            holder["source"] = "environment"
            return True

        with mock.patch(
            "deepseek_client.get_api_key_source",
            side_effect=lambda: holder["source"],
        ), mock.patch(
            "deepseek_client.has_env_api_key",
            return_value=True,
        ), mock.patch(
            "deepseek_client.delete_saved_api_key",
            side_effect=delete,
        ):

            card = ai_settings.AISettingsCard()
            card.remove_key()

            self.assertIn(
                "still in use",
                card.status.text(),
            )
            card.close()
            card.deleteLater()

    def test_test_connection_success(self):

        card, _holder = self._card(
            "saved",
            test=lambda: "OK",
        )

        card.test_connection()
        self.assertTrue(
            self.wait_until(
                lambda: "successful" in card.test_status.text().lower()
            )
        )
        self.assertTrue(card.test_button.isEnabled())

    def test_test_connection_authentication_failure(self):

        def fail():
            raise deepseek_client.DeepSeekError(
                "auth",
                status=401,
            )

        card, _holder = self._card(
            "saved",
            test=fail,
        )

        card.test_connection()
        self.assertTrue(
            self.wait_until(
                lambda: "authentication failed"
                in card.test_status.text().lower()
            )
        )


if __name__ == "__main__":

    unittest.main()
