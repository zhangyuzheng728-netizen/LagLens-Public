"""Network page states and network-aware analysis report tests."""

import os
import sys
import tempfile
import unittest

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

import i18n  # noqa: E402
import network_sampler  # noqa: E402
import network_page  # noqa: E402
from frame_viewer import FrameViewer  # noqa: E402
from settings import AppSettings  # noqa: E402
from tests.test_network_sampler import (  # noqa: E402
    FakeSampler,
    ok_sample,
)


def make_frames(count=120):

    frames = []

    for index in range(count):

        frames.append(
            {
                "time": index * 16.0,
                "duration": 16.0,
                "displayed": True,
                "row": {
                    "Application": "game.exe",
                    "DisplayedTime": "16.0",
                    "FrameTime": "16.0",
                },
            }
        )

    return frames


def write_network_sidecar(csv_path, stable=False):

    path = network_sampler.network_path(csv_path)
    public_samples = (
        [
            {"status": "ok", "rtt_ms": 20.0},
            {"status": "ok", "rtt_ms": 21.0},
            {"status": "ok", "rtt_ms": 22.0},
        ]
        if stable
        else [
            {"status": "ok", "rtt_ms": 25.0},
            {"status": "timeout", "rtt_ms": None},
            {"status": "ok", "rtt_ms": 30.0},
        ]
    )
    records = [
        {
            "type": "metadata",
            "schema_version": 1,
            "capture": {
                "csv_name": Path(csv_path).name,
                "target_name": "game.exe",
            },
            "network": {
                "gateway_available": True,
                "public_target": "1.1.1.1",
                "interval_ms": 1000,
            },
        },
        {
            "type": "sample",
            "t_ms": 200.0,
            "gateway": {"status": "ok", "rtt_ms": 4.0},
            "public": public_samples[0],
        },
        {
            "type": "sample",
            "t_ms": 500.0,
            "gateway": {"status": "ok", "rtt_ms": 5.0},
            "public": public_samples[1],
        },
        {
            "type": "sample",
            "t_ms": 800.0,
            "gateway": {"status": "ok", "rtt_ms": 6.0},
            "public": public_samples[2],
        },
        {
            "type": "end",
            "sample_count": 3,
            "reason": "finished",
            "outcome": "valid",
        },
    ]
    path.write_text(
        "\n".join(__import__("json").dumps(item) for item in records)
        + "\n",
        encoding="utf-8",
    )


class NetworkPageTests(unittest.TestCase):

    app = None

    @classmethod
    def setUpClass(cls):

        cls.app = (
            QApplication.instance()
            or QApplication([])
        )
        i18n.get_manager().set_language("en")

    def setUp(self):

        self.tmp = tempfile.TemporaryDirectory()
        self.settings = AppSettings(
            Path(self.tmp.name) / "LagLens.ini"
        )
        self.sampler = FakeSampler()
        self.service = network_sampler.NetworkService(
            sampler=self.sampler
        )
        self.page = network_page.NetworkPage(
            self.service,
            self.settings,
        )
        self.page.show()
        self.app.processEvents()

    def tearDown(self):

        self.page.close()
        self.page.deleteLater()
        self.tmp.cleanup()
        self.app.processEvents()

    def test_open_does_not_start_probe(self):

        self.assertFalse(self.sampler.running)
        self.assertIn(
            "Not testing",
            self.page.status.text(),
        )
        self.assertTrue(self.page.start_button.isEnabled())

    def test_start_stop_and_valid_state(self):

        self.page._start()
        self.sampler.samples.extend(
            [
                ok_sample(1_000_000_000, gateway=4, public=20),
                ok_sample(2_000_000_000, gateway=5, public=21),
            ]
        )
        self.page.refresh()

        self.assertTrue(self.sampler.running)
        self.assertIn(
            "Valid data",
            self.page.status.text(),
        )
        self.assertEqual(
            self.page.gateway_values["current"].text(),
            "5.0 ms",
        )

        self.page._stop()
        self.assertFalse(self.sampler.running)

    def test_capture_state_disables_standalone_controls(self):

        self.page.set_capture_state(True, False)
        self.assertFalse(
            self.page.start_button.isEnabled()
        )
        self.assertIn(
            "not enabled",
            self.page.status.text(),
        )

        self.page.set_capture_state(True, True)
        self.assertFalse(
            self.page.start_button.isEnabled()
        )
        self.assertFalse(
            self.page.stop_button.isEnabled()
        )
        self.assertIn(
            "Joint capture",
            self.page.status.text(),
        )

        self.page.set_capture_state(
            True,
            False,
            "access denied",
        )
        self.assertIn(
            "access denied",
            self.page.status.text(),
        )


class NetworkReportTests(unittest.TestCase):

    app = None

    @classmethod
    def setUpClass(cls):

        cls.app = (
            QApplication.instance()
            or QApplication([])
        )
        i18n.get_manager().set_language("en")

    def _viewer(
        self,
        with_network=True,
        stable=False,
        frames=None,
    ):

        self.tmp = tempfile.TemporaryDirectory()
        csv_path = Path(self.tmp.name) / "capture.csv"
        csv_path.write_text("", encoding="utf-8")

        if with_network:
            write_network_sidecar(csv_path, stable=stable)

        viewer = FrameViewer(
            frames or make_frames(),
            filename=csv_path.name,
            csv_path=csv_path,
            embedded=True,
        )
        return viewer, csv_path

    def test_old_report_without_network_says_not_captured(self):

        viewer, _csv_path = self._viewer(False)

        try:

            self.assertFalse(viewer.network.available)
            self.assertIn(
                "Network not captured",
                viewer.network_summary_label.text(),
            )
            self.assertTrue(
                viewer.network_chart.isHidden()
            )

        finally:

            viewer.close()
            viewer.deleteLater()
            self.tmp.cleanup()
            self.app.processEvents()

    def test_verdict_prioritises_network_when_frames_are_stable(self):

        viewer, _csv_path = self._viewer(
            stable=False
        )

        try:

            self.assertIn(
                "Check the network first",
                viewer.verdict_action.text(),
            )
            self.assertIn(
                "Network:",
                viewer.verdict_network.text(),
            )

        finally:

            viewer.close()
            viewer.deleteLater()
            self.tmp.cleanup()
            self.app.processEvents()

    def test_verdict_prioritises_local_when_network_is_stable(self):

        frames = make_frames()
        frames[60]["row"]["DisplayedTime"] = "500.0"
        frames[60]["duration"] = 500.0

        viewer, _csv_path = self._viewer(
            stable=True,
            frames=frames,
        )

        try:

            self.assertIn(
                "Check game output or local performance",
                viewer.verdict_action.text(),
            )

        finally:

            viewer.close()
            viewer.deleteLater()
            self.tmp.cleanup()
            self.app.processEvents()

    def test_unmeasured_network_is_not_called_normal(self):

        viewer, _csv_path = self._viewer(False)

        try:

            self.assertIn(
                "Network not captured",
                viewer.verdict_network.text(),
            )
            self.assertIn(
                "network was not measured",
                viewer.verdict_action.text(),
            )
            self.assertIn(
                "not captured",
                viewer.hardware_status.text(),
            )

        finally:

            viewer.close()
            viewer.deleteLater()
            self.tmp.cleanup()
            self.app.processEvents()

    def test_network_card_and_ai_context_use_sidecar(self):

        viewer, _csv_path = self._viewer(True)

        try:

            self.assertTrue(viewer.network.available)
            self.assertTrue(
                viewer.network_summary["available"]
            )
            self.assertEqual(
                viewer.network_values["gateway"][
                    "median"
                ].text(),
                "5.0 ms",
            )
            self.assertEqual(
                viewer.network_values["public"][
                    "timeouts"
                ].text(),
                "1",
            )
            self.assertFalse(
                viewer.network_chart.isHidden()
            )
            self.assertIn(
                "Game-server latency is not measured",
                viewer.network_summary_label.text(),
            )

            context = viewer.ai_context()
            text = __import__("ai_insight").build_report_text(
                context
            )
            self.assertIn("网关探测", text)
            self.assertIn("公网探测", text)
            self.assertIn(
                "公网探测不能代替游戏内延迟",
                text,
            )
            self.assertNotIn("192.168", text)
            self.assertNotIn("1.1.1.1", text)

        finally:

            viewer.close()
            viewer.deleteLater()
            self.tmp.cleanup()
            self.app.processEvents()


if __name__ == "__main__":

    unittest.main()
