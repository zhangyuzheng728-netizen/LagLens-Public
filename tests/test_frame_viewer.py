"""P2-2: FrameViewer integration with the statistics engine."""

import os
import sys
import unittest

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import i18n  # noqa: E402
import swap_chains  # noqa: E402
from frame_viewer import FrameViewer  # noqa: E402


def make_rows(specs):
    """specs: (swap_chain, count, start_ms, step_ms)."""

    rows = []

    for swap_chain, count, start, step in specs:

        for index in range(count):

            rows.append(
                {
                    "Application": "game.exe",
                    "ProcessID": "100",
                    "SwapChainAddress": swap_chain,
                    "CPUStartTime": str(
                        start + index * step
                    ),
                    "FrameTime": str(step),
                    "DisplayedTime": "16.0",
                }
            )

    return rows


def make_frames(durations):

    frames = []
    start = 0.0

    for duration in durations:

        frames.append(
            {
                "time": start,
                "duration": duration,
                "displayed": True,
                "row": {},
            }
        )

        start += duration

    return frames


class FrameViewerStatsTests(unittest.TestCase):

    app = None

    @classmethod
    def setUpClass(cls):

        cls.app = QApplication.instance() or QApplication([])
        i18n.get_manager().set_language("en")

    def _destroy(self, window):

        window.close()
        window.deleteLater()

        QApplication.sendPostedEvents(
            None,
            QEvent.Type.DeferredDelete,
        )
        QApplication.processEvents()

    def test_summary_reports_percentiles_and_low_fps(self):

        window = FrameViewer(
            make_frames([10.0] * 99 + [100.0]),
            "capture.csv",
        )

        text = window.summary.text()
        stats = window.stats

        self.assertIn("P50", text)
        self.assertIn("P95", text)
        self.assertIn("P99", text)
        self.assertIn("1% Low", text)

        self.assertIn(
            f"{stats.p95_frame_ms:.2f}",
            text,
        )
        self.assertIn(
            f"{stats.one_percent_low_fps:.1f}",
            text,
        )

        self._destroy(window)

    def test_manual_threshold_updates_chart_and_summary(self):

        durations = [10.0] * 90 + [30.0] * 9 + [100.0]

        window = FrameViewer(
            make_frames(durations),
            "capture.csv",
        )

        self.assertEqual(window.stats.stutter_count, 1)
        self.assertAlmostEqual(
            window.chart.threshold,
            50.0,
        )

        window.auto_threshold.setChecked(False)
        window.threshold_input.setValue(20.0)

        self.assertAlmostEqual(window.chart.threshold, 20.0)
        self.assertEqual(window.stats.stutter_count, 10)
        self.assertIn(
            "Fixed-threshold stutters: 10",
            window.summary.text(),
        )

        self._destroy(window)

    def test_auto_threshold_restores_median_based_value(self):

        durations = [10.0] * 90 + [30.0] * 9 + [100.0]

        window = FrameViewer(
            make_frames(durations),
            "capture.csv",
        )

        window.auto_threshold.setChecked(False)
        window.threshold_input.setValue(20.0)

        window.auto_threshold.setChecked(True)

        self.assertAlmostEqual(window.chart.threshold, 50.0)
        self.assertEqual(window.stats.stutter_count, 1)
        self.assertAlmostEqual(
            window.threshold_input.value(),
            50.0,
        )

        self._destroy(window)


class FrameViewerChainSelectionTests(unittest.TestCase):

    app = None

    @classmethod
    def setUpClass(cls):

        cls.app = QApplication.instance() or QApplication([])
        i18n.get_manager().set_language("en")

    def _build(self, specs):

        rows = make_rows(specs)

        index = swap_chains.build_index(rows)
        selection = swap_chains.recommend(index)

        window = FrameViewer(
            selection.legacy_frames(),
            "capture.csv",
            index=index,
            selection=selection,
        )

        return window, index, selection, rows

    def _combo_index(self, window, needle):

        for position in range(
            window.chain_combo.count()
        ):

            if needle in window.chain_combo.itemText(
                position
            ):

                return position

        self.fail(f"combo item containing {needle!r} not found")

    def _destroy(self, window):

        window.close()
        window.deleteLater()

        QApplication.sendPostedEvents(
            None,
            QEvent.Type.DeferredDelete,
        )
        QApplication.processEvents()

    def test_panel_lists_choices_and_explains_recommendation(self):

        window, index, selection, _ = self._build(
            [
                ("0x1", 100, 0.0, 100.0),
                ("0x2", 50, 0.0, 100.0),
            ]
        )

        choices = swap_chains.list_choices(index)

        self.assertEqual(
            window.chain_combo.count(),
            1 + len(choices),
        )
        self.assertIn(
            "Automatic",
            window.chain_combo.itemText(0),
        )
        self.assertIn(
            selection.confidence,
            window.confidence_label.text(),
        )
        self.assertIn(
            "frames from",
            window.chain_reason.text(),
        )
        self.assertIn(
            "CSV",
            window.chain_note.text(),
        )

        self._destroy(window)

    def test_manual_selection_updates_stats_and_chart(self):

        window, index, selection, _ = self._build(
            [
                ("0x1", 100, 0.0, 100.0),
                ("0x2", 50, 0.0, 100.0),
            ]
        )

        initial_frames = window.stats.frame_count

        window.chain_combo.setCurrentIndex(
            self._combo_index(window, "0x2")
        )

        self.assertEqual(window.stats.frame_count, 50)
        self.assertEqual(len(window.chart.frames), 50)
        self.assertIn(
            "Frames: 50",
            window.summary.text(),
        )
        self.assertIn(
            "manual",
            window.confidence_label.text().lower(),
        )
        self.assertIn(
            "excluded from this analysis",
            window.chain_note.text().lower(),
        )

        window.chain_combo.setCurrentIndex(0)

        self.assertEqual(
            window.stats.frame_count,
            initial_frames,
        )
        self.assertIn(
            "Frames: 100",
            window.summary.text(),
        )

        self._destroy(window)

    def test_reused_address_segments_can_be_selected(self):

        window, index, _, _ = self._build(
            [
                ("0x1", 5, 0.0, 16.0),
                ("0x1", 5, 40000.0, 16.0),
                ("0x2", 5, 80000.0, 16.0),
            ]
        )

        window.chain_combo.setCurrentIndex(
            self._combo_index(window, "segment 2")
        )

        self.assertEqual(window.stats.frame_count, 5)

        times = [
            frame["time"]
            for frame in window.frames
        ]

        self.assertTrue(
            all(time >= 40000.0 for time in times)
        )

        # The original index still contains every chain.
        self.assertEqual(len(index.chains), 3)

        self._destroy(window)

    def test_all_chains_note_when_merged(self):

        window, _, _, _ = self._build(
            [
                ("0x1", 3, 1000.0, 16.0),
                ("0x2", 3, 1500.0, 16.0),
            ]
        )

        self.assertIn(
            "All captured chains",
            window.chain_note.text(),
        )

        labels = [
            window.chain_combo.itemText(position)
            for position in range(
                window.chain_combo.count()
            )
        ]

        self.assertTrue(
            any("2 chains" in label for label in labels)
        )

        self._destroy(window)


if __name__ == "__main__":
    unittest.main()

