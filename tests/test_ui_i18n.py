"""A-2: Settings tab and live language switching tests."""

import os
import sys
import tempfile
import time
import unittest

from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QDialog,
    QLabel,
)

import capture_core  # noqa: E402
import i18n  # noqa: E402
import main as laglens  # noqa: E402
from settings import AppSettings  # noqa: E402


class RunningWorker:
    """Stand-in for a running CaptureWorker."""

    csv_path = None

    def __init__(self):

        self.stopped = False

    def isRunning(self):
        return True

    def stop(self):
        self.stopped = True


class UiI18nTests(unittest.TestCase):

    app = None

    @classmethod
    def setUpClass(cls):

        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):

        import pynvml

        try:

            pynvml.nvmlInit()
            gpu = pynvml.nvmlDeviceGetHandleByIndex(0)

        except Exception:  # pragma: no cover - no NVIDIA GPU

            self.skipTest("NVML unavailable")

        i18n.get_manager().set_mode("en")

        self.tmpdir = tempfile.TemporaryDirectory()

        self.settings = AppSettings(
            Path(self.tmpdir.name) / "test.ini"
        )
        self.settings.set_language_mode("en")

        self.window = laglens.LagLens(
            gpu,
            settings=self.settings,
        )
        self.window.analysis_async = False

        self.window.timer.stop()
        self.window.auto_analyze.setChecked(False)

    def tearDown(self):

        self.window.worker = None

        self.window.close()
        self.window.deleteLater()

        QApplication.sendPostedEvents(
            None,
            QEvent.Type.DeferredDelete,
        )
        QApplication.processEvents()

        self.window = None
        self.tmpdir.cleanup()

        i18n.get_manager().set_mode("en")

        import pynvml

        try:
            pynvml.nvmlShutdown()

        except Exception:  # pragma: no cover

            pass

    def switch(self, mode):

        index = self.window.language_combo.findData(mode)

        self.assertGreaterEqual(index, 0)

        self.window.language_combo.setCurrentIndex(index)

        QApplication.processEvents()

    def test_english_static_text(self):

        self.assertEqual(
            self.window.windowTitle(),
            "LagLens - Live Performance Monitor",
        )
        self.assertEqual(
            [
                self.window.tabs.tabText(index)
                for index in range(
                    self.window.tabs.count()
                )
            ],
            [
                "Hardware",
                "Network",
                "Live Frames",
                "Analysis",
                "AI assistant",
                "Settings",
            ],
        )
        self.assertEqual(
            self.window.start_btn.text(),
            "Start Monitoring",
        )
        self.assertEqual(
            self.window._card_labels[
                "hardware.card.vram"
            ].text(),
            "VRAM",
        )

        labels = [
            label.text()
            for label in self.window.findChildren(
                QLabel
            )
        ]

        self.assertIn(
            "GPU Usage History - Last 60 Samples",
            labels,
        )
        self.assertIn(
            "Live Frame Time - Peak of Each Update Batch",
            labels,
        )

    def test_switch_to_chinese_updates_static_text(self):

        self.switch("zh_CN")

        self.assertEqual(
            self.window.windowTitle(),
            "LagLens - 实时性能监控",
        )
        self.assertEqual(
            [
                self.window.tabs.tabText(index)
                for index in range(
                    self.window.tabs.count()
                )
            ],
            [
                "硬件",
                "网络",
                "实时帧",
                "分析报告",
                "AI 助手",
                "设置",
            ],
        )
        self.assertEqual(
            self.window.start_btn.text(),
            "开始监控",
        )
        self.assertEqual(
            self.window._card_labels[
                "hardware.card.vram"
            ].text(),
            "显存",
        )
        self.assertEqual(
            self.window.language_combo.itemText(0),
            "跟随 Windows 系统语言",
        )
        self.assertEqual(
            self.settings.language_mode,
            "zh_CN",
        )

    def test_switch_back_to_english(self):

        self.switch("zh_CN")
        self.switch("en")

        self.assertEqual(
            self.window.windowTitle(),
            "LagLens - Live Performance Monitor",
        )
        self.assertEqual(
            self.window.start_btn.text(),
            "Start Monitoring",
        )
        self.assertEqual(
            self.settings.language_mode,
            "en",
        )

    def test_language_survives_restart(self):

        self.switch("zh_CN")

        reloaded = AppSettings(self.settings.path)

        self.assertEqual(
            reloaded.language_mode,
            "zh_CN",
        )

    def test_saved_language_is_applied_on_startup(self):

        self.settings.set_language_mode("zh_CN")

        i18n.get_manager().set_mode(
            self.settings.language_mode,
            system_locale="en-US",
        )

        self.assertEqual(
            i18n.get_manager().language,
            "zh_CN",
        )

        self.window.retranslate()

        self.assertEqual(
            self.window.windowTitle(),
            "LagLens - 实时性能监控",
        )
        self.assertEqual(
            self.window.language_combo.currentData(),
            "zh_CN",
        )

    def test_switch_preserves_process_and_live_data(self):
        """No worker, process selection or chart data may be touched."""

        worker = RunningWorker()

        self.window.worker = worker

        self.window.process_combo.setCurrentText(
            "Palworld-Win64-Shipping.exe"
        )

        self.window.frame_history.extend(
            [10.0, 20.0, 30.0]
        )
        self.window.frame_chart.add(12.5)

        self.window.capture_started = time.monotonic()
        self.window._last_count = 42

        history = list(self.window.frame_history)
        samples = list(self.window.frame_chart.samples)

        self.switch("zh_CN")

        self.assertEqual(
            self.window.process_combo.currentText(),
            "Palworld-Win64-Shipping.exe",
        )
        self.assertEqual(
            list(self.window.frame_history),
            history,
        )
        self.assertEqual(
            list(self.window.frame_chart.samples),
            samples,
        )
        self.assertIs(self.window.worker, worker)
        self.assertFalse(worker.stopped)
        self.assertIn(
            "实时 - 42 帧",
            self.window.frame_status.text(),
        )

    def test_saved_status_is_retranslated(self):

        self.window.set_status(
            "status.saved",
            frames=10,
            name="a.csv",
        )

        self.assertIn(
            "Saved 10 frames",
            self.window.frame_status.text(),
        )

        self.switch("zh_CN")

        self.assertIn(
            "已保存 10 帧到 a.csv",
            self.window.frame_status.text(),
        )

    def test_page_section_titles_and_data_locations(self):

        labels = [
            label.text()
            for label in self.window.findChildren(QLabel)
        ]

        for title in (
            "Capture",
            "Live metrics",
            "System metrics",
            "Appearance",
            "Data & files",
        ):

            self.assertIn(title, labels)

        self.assertEqual(
            self.window.settings_path_value.text(),
            str(self.settings.path),
        )
        self.assertEqual(
            self.window.captures_path_value.text(),
            str(laglens.CAPTURES),
        )

        self.switch("zh_CN")

        labels = [
            label.text()
            for label in self.window.findChildren(QLabel)
        ]

        for title in (
            "抓取",
            "实时指标",
            "系统指标",
            "外观",
            "数据与文件",
        ):

            self.assertIn(title, labels)

    def test_hardware_status_is_retranslated(self):

        self.window.set_hw_status(
            "hardware.vram_status",
            used=1024,
            total=8192,
        )

        self.switch("zh_CN")

        self.assertIn(
            "显存 1024/8192 MiB",
            self.window.hw_status.text(),
        )

    def test_damaged_csv_is_reported_as_unusable(self):

        with tempfile.TemporaryDirectory() as folder:

            csv_path = Path(folder) / "damaged.csv"
            csv_path.write_text(
                "Application,FrameTime\n"
                "game.exe,16.7\n",
                encoding="utf-8",
            )

            log_path = Path(folder) / "damaged.log"
            log_path.write_bytes(b"")

            result = capture_core.CaptureResult(
                csv_path=str(csv_path),
                log_path=str(log_path),
                exit_code=0,
                rows=0,
                valid_frames=0,
            )

            self.window.capture_target = "game.exe"

            with mock.patch.object(
                laglens.QMessageBox,
                "warning",
                return_value=None,
            ) as warning:

                self.window.on_capture_completed(result)

            status = self.window.frame_status.text().lower()

            self.assertIn("not usable", status)
            self.assertNotIn("captured no frames", status)

            message = warning.call_args.args[2]

            self.assertIn(
                "missing required columns",
                message,
            )

    def test_capture_failure_is_translated_and_retranslated(self):

        with tempfile.TemporaryDirectory() as folder:

            csv_path = Path(folder) / "capture.csv"
            csv_path.write_bytes(b"")

            log_path = Path(folder) / "capture.log"
            log_path.write_bytes(
                b"\xff\xfe"
                + (
                    "error: failed to start trace session: "
                    "access denied.\n"
                ).encode("utf-16-le")
            )

            result = capture_core.CaptureResult(
                csv_path=str(csv_path),
                log_path=str(log_path),
                exit_code=6,
                rows=0,
                valid_frames=0,
                error="CSV is empty",
            )

            self.window.capture_target = "Palworld.exe"

            self.switch("zh_CN")

            with mock.patch.object(
                laglens.QMessageBox,
                "warning",
                return_value=None,
            ) as warning:

                self.window.on_capture_completed(result)

            self.assertIn(
                "管理员",
                self.window.frame_status.text(),
            )

            message = warning.call_args.args[2]

            self.assertIn("管理员", message)
            self.assertIn("PresentMon", message)

            # Retranslating the last failure must not reopen a dialog.
            self.switch("en")

            self.assertIn(
                "administrator",
                self.window.frame_status.text().lower(),
            )

    def test_choose_process_button_is_localized(self):

        self.assertEqual(
            self.window.choose_process_btn.text(),
            "Select Process…",
        )

        self.switch("zh_CN")

        self.assertEqual(
            self.window.choose_process_btn.text(),
            "选择进程…",
        )

    def test_choose_process_updates_combo_without_starting_capture(self):

        class FakeDialog:

            def __init__(
                self,
                parent=None,
                remembered_targets=(),
            ):

                self.remembered_targets = (
                    remembered_targets
                )

            def exec(self):

                return QDialog.DialogCode.Accepted

            def selected_entry(self):

                return SimpleNamespace(
                    name="Game.exe"
                )

        with mock.patch.object(
            laglens,
            "ProcessDialog",
            FakeDialog,
        ):

            with mock.patch.object(
                self.window,
                "start_capture",
            ) as start:

                self.window.choose_process_btn.click()
                QApplication.processEvents()

        self.assertEqual(
            self.window.process_combo.currentText(),
            "Game.exe",
        )
        start.assert_not_called()
        self.assertIsNone(self.window.worker)

    def test_cancelled_process_dialog_keeps_the_current_target(self):

        before = self.window.process_combo.currentText()

        class FakeDialog:

            def __init__(self, parent=None, remembered_targets=()):

                pass

            def exec(self):

                return QDialog.DialogCode.Rejected

        with mock.patch.object(
            laglens,
            "ProcessDialog",
            FakeDialog,
        ):

            self.window.choose_process_btn.click()
            QApplication.processEvents()

        self.assertEqual(
            self.window.process_combo.currentText(),
            before,
        )

    def test_repeated_switching_keeps_combo_consistent(self):

        self.switch("zh_CN")
        self.switch("en")
        self.switch("zh_CN")

        self.assertEqual(
            self.window.language_combo.currentData(),
            "zh_CN",
        )
        self.assertEqual(
            self.window.language_combo.currentText(),
            "简体中文",
        )
        self.assertEqual(
            self.window.tabs.tabText(5),
            "设置",
        )


if __name__ == "__main__":
    unittest.main()
