"""A-3: analysis window i18n and runtime switching tests."""

import os
import sys
import unittest

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QLabel,
)

import i18n  # noqa: E402
import swap_chains  # noqa: E402
from frame_viewer import FrameViewer  # noqa: E402


def make_rows():

    rows = []

    for swap_chain, count, step in (
        ("0x1", 100, 100.0),
        ("0x2", 50, 100.0),
    ):

        for index in range(count):

            rows.append(
                {
                    "Application": "game.exe",
                    "ProcessID": "100",
                    "SwapChainAddress": swap_chain,
                    "CPUStartTime": str(index * step),
                    "FrameTime": str(step),
                    "DisplayedTime": "16.0",
                }
            )

    return rows


class FrameViewerI18nTests(unittest.TestCase):

    app = None

    @classmethod
    def setUpClass(cls):

        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):

        i18n.get_manager().set_language("en")

        rows = make_rows()

        self.index = swap_chains.build_index(rows)
        self.selection = swap_chains.recommend(self.index)

        self.window = FrameViewer(
            self.selection.legacy_frames(),
            "capture.csv",
            index=self.index,
            selection=self.selection,
        )

    def tearDown(self):

        self.window.close()
        self.window.deleteLater()

        QApplication.sendPostedEvents(
            None,
            QEvent.Type.DeferredDelete,
        )
        QApplication.processEvents()

        self.window = None

        i18n.get_manager().set_language("en")

    def combo_index(self, needle):

        for index in range(
            self.window.chain_combo.count()
        ):

            if needle in self.window.chain_combo.itemText(
                index
            ):

                return index

        self.fail(f"combo item {needle!r} not found")

    def test_section_titles_are_localized(self):

        labels = [
            label.text()
            for label in self.window.findChildren(QLabel)
        ]

        for title in (
            "Capture summary",
            "Frame time",
            "Selected frame",
        ):

            self.assertIn(title, labels)

        i18n.get_manager().set_language("zh_CN")

        labels = [
            label.text()
            for label in self.window.findChildren(QLabel)
        ]

        for title in (
            "抓取摘要",
            "帧时间",
            "选中帧",
        ):

            self.assertIn(title, labels)

    def test_english_text(self):

        self.assertEqual(
            self.window.windowTitle(),
            "LagLens - Frame Analysis",
        )
        self.assertIn(
            "Frames: 100",
            self.window.summary.text(),
        )
        self.assertIn(
            "1% Low",
            self.window.summary.text(),
        )
        self.assertIn(
            "1% Low",
            self.window.metrics_help.text(),
        )
        self.assertIn(
            "Automatic",
            self.window.chain_combo.itemText(0),
        )
        self.assertIn(
            "high confidence",
            self.window.confidence_label.text(),
        )
        self.assertIn(
            "Why:",
            self.window.chain_reason.text(),
        )
        self.assertIn(
            "one swap chain",
            self.window.chain_reason.text(),
        )

    def test_chinese_text(self):

        i18n.get_manager().set_language("zh_CN")

        self.assertEqual(
            self.window.windowTitle(),
            "LagLens - 帧分析",
        )
        self.assertIn(
            "帧数：100",
            self.window.summary.text(),
        )
        self.assertIn(
            "1% Low",
            self.window.summary.text(),
        )
        self.assertIn(
            "FPS 越高",
            self.window.metrics_help.text(),
        )
        self.assertEqual(
            self.window.chain_combo.itemText(0),
            "自动（推荐）",
        )
        self.assertEqual(
            self.window.confidence_label.text(),
            "高置信度",
        )
        self.assertIn(
            "原因：",
            self.window.chain_reason.text(),
        )
        self.assertIn(
            "来自 1 条交换链",
            self.window.chain_reason.text(),
        )
        self.assertEqual(
            self.window.auto_threshold.text(),
            "自动卡顿阈值",
        )

    def test_switch_preserves_statistics_chart_and_selection(self):

        stats = self.window.stats
        frames = list(self.window.frames)
        chart_frames = list(self.window.chart.frames)
        selection = self.window.selection
        combo_index = self.window.chain_combo.currentIndex()

        i18n.get_manager().set_language("zh_CN")

        self.assertIs(self.window.selection, selection)
        self.assertEqual(self.window.stats, stats)
        self.assertEqual(
            [frame["time"] for frame in self.window.frames],
            [frame["time"] for frame in frames],
        )
        self.assertEqual(
            len(self.window.chart.frames),
            len(chart_frames),
        )
        self.assertEqual(
            self.window.chain_combo.currentIndex(),
            combo_index,
        )

    def test_manual_chain_selection_survives_switch(self):

        index = self.combo_index("0x2")

        self.window.chain_combo.setCurrentIndex(index)

        self.assertEqual(
            self.window.stats.frame_count,
            50,
        )

        selected_before = self.window.selection

        i18n.get_manager().set_language("zh_CN")

        self.assertIs(
            self.window.selection,
            selected_before,
        )
        self.assertEqual(
            self.window.stats.frame_count,
            50,
        )
        self.assertEqual(
            self.window.chain_combo.currentIndex(),
            index,
        )
        self.assertIn(
            "0x2",
            self.window.chain_combo.currentText(),
        )
        self.assertIn(
            "50 帧",
            self.window.chain_combo.currentText(),
        )

    def test_selected_frame_details_are_retranslated(self):

        self.window.show_details(0)

        self.assertIn(
            "Frame #1",
            self.window.details.text(),
        )

        i18n.get_manager().set_language("zh_CN")

        self.assertIn(
            "第 1 帧",
            self.window.details.text(),
        )
        self.assertIn(
            "帧时间",
            self.window.details.text(),
        )


if __name__ == "__main__":
    unittest.main()
