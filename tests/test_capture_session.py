"""Capture-session metadata and cross-session report isolation."""

import json
import os
import sys
import tempfile
import unittest

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

import ai_insight  # noqa: E402
import capture_session  # noqa: E402
import i18n  # noqa: E402
import network_sampler  # noqa: E402
from frame_viewer import FrameViewer  # noqa: E402


def make_frames():

    return [
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
        for index in range(120)
    ]


def write_session(
    csv_path,
    session_id,
    network_status,
    reason="",
    frame_timebase=None,
):

    data = {
        "schema_version": 1,
        "session_id": session_id,
        "capture": {
            "csv_name": csv_path.name,
            "target_name": "game.exe",
            "started_monotonic_ns": 1,
            "started_wall_ns": 2,
            "status": "captured",
            "reason": "",
        },
        "timebase": {
            "origin_monotonic_ns": 1,
            "frame": frame_timebase,
        },
        "data": {
            "network": {
                "status": network_status,
                "reason": reason,
            },
            "telemetry": {
                "status": "unavailable",
                "reason": "",
            },
        },
    }
    capture_session.session_path(csv_path).write_text(
        json.dumps(data),
        encoding="utf-8",
    )


def write_network(csv_path, session_id, t_ms=2000.0):

    path = network_sampler.network_path(csv_path)
    records = [
        {
            "type": "metadata",
            "schema_version": 1,
            "session_id": session_id,
            "capture": {
                "csv_name": csv_path.name,
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
            "t_ms": t_ms,
            "gateway": {"status": "ok", "rtt_ms": 4.0},
            "public": {"status": "ok", "rtt_ms": 20.0},
        },
        {
            "type": "end",
            "sample_count": 1,
            "reason": "finished",
            "outcome": "valid",
        },
    ]
    path.write_text(
        "\n".join(json.dumps(item) for item in records)
        + "\n",
        encoding="utf-8",
    )


class CaptureSessionMetadataTests(unittest.TestCase):

    def test_session_writes_shared_identity_and_timebase(self):

        with tempfile.TemporaryDirectory() as tmp:

            csv_path = Path(tmp) / "capture.csv"
            session = capture_session.CaptureSession.create(
                csv_path,
                "game.exe",
            )
            self.assertTrue(session.write())
            data = capture_session.read_session(csv_path)

            self.assertEqual(
                data["session_id"],
                session.session_id,
            )
            self.assertEqual(
                data["timebase"]["origin_monotonic_ns"],
                session.started_monotonic_ns,
            )
            self.assertEqual(
                data["data"]["network"]["sidecar"],
                csv_path.name + ".network.jsonl",
            )


class SessionReportIsolationTests(unittest.TestCase):

    app = None

    @classmethod
    def setUpClass(cls):

        cls.app = (
            QApplication.instance()
            or QApplication([])
        )
        i18n.get_manager().set_language("en")

    def _viewer(self, network=True, session_status="captured"):

        self.tmp = tempfile.TemporaryDirectory()
        csv_path = Path(self.tmp.name) / "capture.csv"
        csv_path.write_text("", encoding="utf-8")
        write_session(
            csv_path,
            "session-a",
            session_status,
            "access denied" if session_status == "start_failed" else "",
        )

        if network:
            write_network(csv_path, "session-a")

        viewer = FrameViewer(
            make_frames(),
            filename=csv_path.name,
            csv_path=csv_path,
            embedded=True,
        )
        return viewer, csv_path

    def test_network_start_failure_reason_is_visible(self):

        viewer, _csv_path = self._viewer(
            network=False,
            session_status="start_failed",
        )

        try:

            self.assertEqual(
                viewer.network_capture_state,
                "start_failed",
            )
            self.assertIn(
                "failed to start",
                viewer.network_summary_label.text().lower(),
            )
            text = ai_insight.build_report_text(
                viewer.ai_context()
            )
            self.assertIn("启动失败", text)
            self.assertNotIn("网络：未测量", text)

        finally:

            viewer.close()
            viewer.deleteLater()
            self.tmp.cleanup()
            self.app.processEvents()

    def test_unverified_qpc_alignment_is_not_claimed(self):

        self.tmp = tempfile.TemporaryDirectory()
        csv_path = Path(self.tmp.name) / "capture.csv"
        csv_path.write_text("", encoding="utf-8")
        write_session(
            csv_path,
            "session-a",
            "captured",
            frame_timebase={
                "kind": "qpc_ms",
                "origin_kind": "capture_start",
                "origin_qpc_ms": 10000.0,
                "capture_started_monotonic_ns": 10_000_000_000,
                "qpc_clock_delta_ms": 100.0,
                "qpc_frequency_hz": 10_000_000,
                "sync_quality": "unverified_qpc",
                "absolute_mapping_trusted": False,
            },
        )
        write_network(csv_path, "session-a", t_ms=500.0)
        viewer = FrameViewer(
            make_frames(),
            filename=csv_path.name,
            csv_path=csv_path,
            embedded=True,
        )

        try:

            self.assertEqual(
                viewer.frame_alignment_quality,
                "qpc_unverified",
            )
            self.assertIn(
                "unverified",
                viewer.network_coverage.text().lower(),
            )
            text = ai_insight.build_report_text(
                viewer.ai_context()
            )
            self.assertIn("时间对齐未验证", text)

        finally:

            viewer.close()
            viewer.deleteLater()
            self.tmp.cleanup()
            self.app.processEvents()

    def test_network_sidecar_from_another_session_is_isolated(self):

        self.tmp = tempfile.TemporaryDirectory()
        csv_path = Path(self.tmp.name) / "capture.csv"
        csv_path.write_text("", encoding="utf-8")
        write_session(csv_path, "session-a", "captured")
        write_network(csv_path, "session-b")
        viewer = FrameViewer(
            make_frames(),
            filename=csv_path.name,
            csv_path=csv_path,
            embedded=True,
        )

        try:

            self.assertTrue(viewer.network_session_mismatch)
            self.assertIn(
                "another session",
                viewer.network_summary_label.text().lower(),
            )
            text = ai_insight.build_report_text(
                viewer.ai_context()
            )
            self.assertIn("其他采集会话", text)

        finally:

            viewer.close()
            viewer.deleteLater()
            self.tmp.cleanup()
            self.app.processEvents()

    def test_non_overlapping_network_time_is_not_compared(self):

        self.tmp = tempfile.TemporaryDirectory()
        csv_path = Path(self.tmp.name) / "capture.csv"
        csv_path.write_text("", encoding="utf-8")
        write_session(csv_path, "session-a", "captured")
        write_network(
            csv_path,
            "session-a",
            t_ms=100000.0,
        )
        viewer = FrameViewer(
            make_frames(),
            filename=csv_path.name,
            csv_path=csv_path,
            embedded=True,
        )

        try:

            self.assertFalse(viewer.network_time_aligned)
            self.assertEqual(
                viewer.network_capture_state,
                "time_mismatch",
            )
            self.assertIn(
                "do not overlap",
                viewer.network_summary_label.text().lower(),
            )

        finally:

            viewer.close()
            viewer.deleteLater()
            self.tmp.cleanup()
            self.app.processEvents()


if __name__ == "__main__":

    unittest.main()
