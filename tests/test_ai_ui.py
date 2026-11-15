"""FrameViewer context used by the embedded AI assistant page."""

import os
import sys
import unittest

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

import i18n  # noqa: E402
from frame_viewer import FrameViewer  # noqa: E402


def make_frames(displayed="16.0"):

    frames = []

    for index in range(120):

        frames.append(
            {
                "time": index * 16.0,
                "duration": 16.0,
                "displayed": displayed != "NA",
                "row": {
                    "Application": "test-game.exe",
                    "DisplayedTime": displayed,
                    "FrameTime": "16.0",
                },
            }
        )

    return frames


class FrameViewerAIContextTests(unittest.TestCase):

    app = None

    @classmethod
    def setUpClass(cls):

        cls.app = (
            QApplication.instance()
            or QApplication([])
        )
        i18n.get_manager().set_language("en")

    def setUp(self):

        self.viewer = FrameViewer(
            make_frames(),
            filename="test.csv",
            csv_path=None,
            embedded=True,
        )

    def tearDown(self):

        self.viewer.close()
        self.viewer.deleteLater()
        self.app.processEvents()

    def test_context_uses_shared_report_summary(self):

        context = self.viewer.ai_context()

        self.assertEqual(context["report_key"], "test.csv")
        self.assertEqual(context["file"], "test.csv")
        self.assertEqual(
            context["classification"]["status"],
            "stable_meets_target",
        )
        self.assertEqual(
            context["display"]["average_fps"],
            62.5,
        )
        self.assertNotIn("frames", context)
        self.assertNotIn(
            "row",
            context.get("display", {}),
        )

    def test_missing_display_data_context_is_unknown(self):

        viewer = FrameViewer(
            make_frames("NA"),
            filename="missing.csv",
            csv_path=None,
            embedded=True,
        )

        try:

            context = viewer.ai_context()

            self.assertFalse(context["display"]["available"])
            self.assertEqual(
                context["classification"]["status"],
                "insufficient_display_data",
            )

        finally:

            viewer.close()
            viewer.deleteLater()
            self.app.processEvents()


    def test_scenario_combo_retranslates_with_the_ui(self):

        manager = i18n.get_manager()

        try:

            manager.set_language("zh_CN")
            self.viewer.retranslate()
            self.assertEqual(
                self.viewer.scenario_combo.itemText(0),
                "自动识别",
            )
            manager.set_language("en")
            self.viewer.retranslate()
            self.assertEqual(
                self.viewer.scenario_combo.itemText(0),
                "Auto-detect",
            )

        finally:

            manager.set_language("en")

    def test_scenario_override_updates_context_and_emits(self):

        captured = []
        self.viewer.ai_context_changed.connect(captured.append)
        index = self.viewer.scenario_combo.findData("video")

        self.assertGreaterEqual(index, 0)
        self.viewer.scenario_combo.setCurrentIndex(index)
        self.app.processEvents()

        self.assertEqual(self.viewer.scenario_override, "video")
        self.assertTrue(captured)
        context = captured[-1]
        self.assertEqual(
            context["diagnosis"]["scenario"]["id"],
            "video",
        )
        self.assertNotIn(
            "local_performance",
            context["diagnosis"]["allowed_conclusions"],
        )

    def test_auto_scenario_uses_process_name(self):

        index = self.viewer.scenario_combo.findData("video")
        self.viewer.scenario_combo.setCurrentIndex(index)
        self.app.processEvents()
        auto = self.viewer.scenario_combo.findData(None)

        self.viewer.scenario_combo.setCurrentIndex(auto)
        self.app.processEvents()

        self.assertIsNone(self.viewer.scenario_override)
        self.assertEqual(
            self.viewer.ai_context()["diagnosis"]["scenario"]["id"],
            "game",
        )


if __name__ == "__main__":

    unittest.main()
