"""Background analysis loading, fast switching and failure isolation."""

import os
import sys
import tempfile
import time
import unittest

from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import analysis_loader  # noqa: E402
import i18n  # noqa: E402
import settings as app_settings  # noqa: E402

from tests.test_capture import write_session_capture  # noqa: E402


def wait_until(predicate, timeout=12.0):

    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:

        QApplication.processEvents()

        if predicate():

            return True

        time.sleep(0.01)

    QApplication.processEvents()
    return bool(predicate())


class AsyncAnalysisTests(unittest.TestCase):

    app = None

    @classmethod
    def setUpClass(cls):

        cls.app = (
            QApplication.instance()
            or QApplication([])
        )
        i18n.get_manager().set_language("en")

    def setUp(self):

        import pynvml

        try:

            pynvml.nvmlInit()
            gpu = pynvml.nvmlDeviceGetHandleByIndex(0)

        except Exception:  # pragma: no cover - no NVIDIA GPU

            self.skipTest("NVML unavailable")

        import main as laglens

        self.laglens = laglens
        self.pynvml = pynvml
        self.tmpdir = tempfile.TemporaryDirectory()
        self.settings = app_settings.AppSettings(
            Path(self.tmpdir.name) / "test.ini"
        )
        self.settings.set_language_mode("en")
        self.window = laglens.LagLens(
            gpu,
            settings=self.settings,
        )
        self.window.analysis_async = True
        self.window.timer.stop()
        self.window.auto_analyze.setChecked(False)

    def tearDown(self):

        self.window.close()
        self.window.deleteLater()
        QApplication.sendPostedEvents(
            None,
            QEvent.Type.DeferredDelete,
        )
        QApplication.processEvents()
        self.tmpdir.cleanup()

        try:

            self.pynvml.nvmlShutdown()

        except Exception:  # pragma: no cover

            pass

    def _capture(self, tmp, name, target):

        return write_session_capture(
            tmp,
            name,
            target,
            f"session-{name}",
        )

    def test_loading_is_shown_before_a_slow_load_finishes(self):

        with tempfile.TemporaryDirectory() as tmp:

            path = self._capture(tmp, "a.csv", "game-a.exe")
            real = analysis_loader.load_analysis_bundle
            calls = []

            def slow(filename, **kwargs):

                calls.append(filename)
                time.sleep(0.5)
                return real(filename, **kwargs)

            loaded = []
            self.window.analysis_loaded.connect(loaded.append)
            started = time.monotonic()

            with mock.patch.object(
                analysis_loader,
                "load_analysis_bundle",
                side_effect=slow,
            ):

                self.assertTrue(
                    self.window.show_analysis(str(path))
                )
                elapsed = time.monotonic() - started

                self.assertLess(elapsed, 0.25)
                self.assertIs(
                    self.window.analysis_stack.currentWidget(),
                    self.window.analysis_loading,
                )
                self.assertIsNone(self.window.viewer)

                self.assertTrue(
                    wait_until(
                        lambda: self.window.viewer
                        is not None
                    )
                )

            self.assertEqual(
                self.window._active_analysis_path,
                str(path.resolve()),
            )
            self.assertEqual(loaded, [str(path.resolve())])

    def test_fast_switch_keeps_b_and_ai_context(self):

        with tempfile.TemporaryDirectory() as tmp:

            path_a = self._capture(tmp, "a.csv", "game-a.exe")
            path_b = self._capture(tmp, "b.csv", "game-b.exe")
            real = analysis_loader.load_analysis_bundle

            def slow(filename, **kwargs):

                if Path(filename).name == "a.csv":

                    time.sleep(0.8)

                return real(filename, **kwargs)

            with mock.patch.object(
                analysis_loader,
                "load_analysis_bundle",
                side_effect=slow,
            ):

                self.window.show_analysis(str(path_a))

                if self.window.ai_page is not None:

                    self.window.ask_ai_about_active_report()

                self.window.show_analysis(str(path_b))

                self.assertTrue(
                    wait_until(
                        lambda: (
                            self.window.viewer is not None
                            and self.window._active_analysis_path
                            == str(path_b.resolve())
                        )
                    )
                )

                # Let A finish; its stale result must be ignored.
                time.sleep(1.2)
                QApplication.processEvents()
                self.assertEqual(
                    self.window._active_analysis_path,
                    str(path_b.resolve()),
                )
                self.assertEqual(
                    str(self.window.viewer.csv_path),
                    str(path_b.resolve()),
                )

                if self.window.ai_page is not None:

                    self.assertEqual(
                        self.window.ai_page.report_key,
                        str(path_b.resolve()),
                    )

    def test_async_switch_relinks_ai_context_to_b(self):

        with tempfile.TemporaryDirectory() as tmp:

            path_a = self._capture(tmp, "a.csv", "game-a.exe")
            path_b = self._capture(tmp, "b.csv", "game-b.exe")

            self.window.show_analysis(str(path_a))
            self.assertTrue(
                wait_until(
                    lambda: self.window.viewer is not None
                )
            )
            self.window.ask_ai_about_active_report()
            self.assertEqual(
                self.window.ai_page.report_key,
                str(path_a.resolve()),
            )

            self.window.show_analysis(str(path_b))
            self.assertTrue(
                wait_until(
                    lambda: (
                        self.window.viewer is not None
                        and self.window._active_analysis_path
                        == str(path_b.resolve())
                    )
                )
            )

            self.assertEqual(
                self.window.ai_page.report_key,
                str(path_b.resolve()),
            )
            self.assertEqual(
                self.window.ai_page.session.report.get(
                    "report_key"
                ),
                str(path_b.resolve()),
            )

    def test_failure_keeps_current_report_then_opens_another(self):

        with tempfile.TemporaryDirectory() as tmp:

            path_a = self._capture(tmp, "a.csv", "game-a.exe")
            path_b = self._capture(tmp, "b.csv", "game-b.exe")
            bad = self._capture(tmp, "bad.csv", "bad.exe")
            real = analysis_loader.load_analysis_bundle

            def fail_bad(filename, **kwargs):

                if Path(filename).name == "bad.csv":

                    raise ValueError("damaged CSV")

                return real(filename, **kwargs)

            self.window.show_analysis(str(path_a))
            self.assertTrue(
                wait_until(
                    lambda: self.window.viewer is not None
                )
            )
            active = self.window._active_analysis_path

            with mock.patch.object(
                analysis_loader,
                "load_analysis_bundle",
                side_effect=fail_bad,
            ), mock.patch.object(
                self.laglens.QMessageBox,
                "warning",
            ) as warning:

                self.window.show_analysis(str(bad))
                self.assertTrue(
                    wait_until(lambda: warning.called)
                )

                self.assertEqual(
                    self.window._active_analysis_path,
                    active,
                )
                self.assertIsNotNone(self.window.viewer)

                self.window.show_analysis(str(path_b))
                self.assertTrue(
                    wait_until(
                        lambda: (
                            self.window._active_analysis_path
                            == str(path_b.resolve())
                        )
                    )
                )

            self.assertEqual(
                str(self.window.viewer.csv_path),
                str(path_b.resolve()),
            )


if __name__ == "__main__":
    unittest.main()
