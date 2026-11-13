"""C-3 diagnostic summary, stutter-event and export UI tests."""

import os
import sys
import tempfile
import unittest

from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QListView  # noqa: E402

import i18n  # noqa: E402
import diagnostic_text  # noqa: E402
import diagnostics  # noqa: E402
from frame_viewer import FrameViewer  # noqa: E402
from telemetry import TelemetryReadResult  # noqa: E402


def make_frames():

    frames = []

    for index in range(120):

        duration = (
            40.0 if index in (60, 100) else 16.7
        )
        cpu = 39.0 if index in (60, 100) else 16.2
        wait = 1.0 if index in (60, 100) else 0.5
        gpu = 7.0 if index in (60, 100) else 6.0
        gpu_wait = 10.0 if index in (60, 100) else 10.7

        frames.append(
            {
                "time": index * 16.7,
                "duration": duration,
                "displayed": True,
                "row": {
                    "Application": "game.exe",
                    "CPUBusy": str(cpu),
                    "CPUWait": str(wait),
                    "GPUBusy": str(gpu),
                    "GPUWait": str(gpu_wait),
                    "GPUTime": str(gpu + gpu_wait),
                    "DisplayLatency": "32.0",
                    "DisplayedTime": "16.0",
                },
                "timebase_kind": "qpc_ms",
                "sync_quality": "verified_qpc",
                "absolute_mapping_trusted": True,
            }
        )

    return frames


def make_telemetry():

    samples = []

    for index in range(12):

        samples.append(
            {
                "t_ms": index * 250.0,
                "cpu": {"system_percent": 30.0},
                "ram": {"percent": 60.0},
                "target": {
                    "cpu_percent": 55.0,
                    "rss_bytes": 2_000_000_000,
                },
                "gpu": {"util_percent": 99.0},
            }
        )

    return TelemetryReadResult(
        available=True,
        complete=True,
        metadata={
            "type": "metadata",
            "capture": {
                "started_monotonic_ns": 0,
                "profile": "default",
            },
        },
        samples=samples,
        timebase={
            "type": "timebase",
            "frame_timebase": {
                "kind": "qpc_ms",
                "sync_quality": "verified_qpc",
                "absolute_mapping_trusted": True,
            },
        },
        end={"type": "end", "reason": "finished"},
    )


class DiagnosticUiTests(unittest.TestCase):

    app = None

    @classmethod
    def setUpClass(cls):

        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):

        i18n.get_manager().set_language("en")
        self.window = FrameViewer(
            make_frames(),
            "capture.csv",
            target_fps=60,
        )

    def tearDown(self):

        self.window.close()
        self.window.deleteLater()

        QApplication.sendPostedEvents(
            None,
            QEvent.Type.DeferredDelete,
        )
        QApplication.processEvents()

        i18n.get_manager().set_language("en")
        self.window = None

    def test_summary_and_events_are_populated(self):

        self.assertIsNotNone(
            self.window.diagnostic_report
        )
        self.assertGreater(
            self.window.finding_list.count(),
            0,
        )
        self.assertGreater(
            self.window.event_table.rowCount(),
            0,
        )
        self.assertGreater(
            len(self.window._display_events),
            0,
        )
        self.assertIn(
            "Fixed-threshold stutters:",
            self.window.summary.text(),
        )
        self.assertIn(
            "Detected 1 local frame-time anomaly",
            self.window.overview_label.text(),
        )
        self.assertIn(
            "The event was associated with increased CPU frame work",
            self.window.overview_label.text(),
        )
        self.assertIn(
            "CPU",
            self.window.finding_list.item(0).text(),
        )
        self.assertIn(
            "Possible link, not confirmed",
            self.window.finding_list.item(0).text(),
        )
        self.assertIn(
            "nearby frames",
            self.window.events_note.text(),
        )
        self.assertFalse(
            self.window.event_hint.isHidden()
        )
        self.assertTrue(
            self.window.event_detail.isHidden()
        )
        self.assertIn(
            "no sidecar",
            self.window.sync_detail.text(),
        )

    def test_event_selection_links_chart_and_frame_details(self):

        self.window.event_table.setCurrentCell(0, 0)
        QApplication.processEvents()

        self.assertIsNotNone(
            self.window._selected_index
        )
        self.assertEqual(
            self.window.chart.selected_index,
            self.window._selected_index,
        )
        self.assertIn(
            "local baseline",
            self.window.event_detail.text(),
        )
        self.assertIn(
            "Frame Time",
            self.window.details.text(),
        )
        self.assertFalse(
            self.window.event_detail.isHidden()
        )

    def test_runtime_language_switch_localizes_diagnostics(self):

        self.window.event_table.setCurrentCell(0, 0)
        QApplication.processEvents()

        i18n.get_manager().set_language("zh_CN")
        QApplication.processEvents()

        self.assertIn(
            "固定阈值卡顿",
            self.window.summary.text(),
        )
        self.assertIn(
            "CPU",
            self.window.finding_list.item(0).text(),
        )
        self.assertIn(
            "可能相关，尚未确认",
            self.window.finding_list.item(0).text(),
        )
        self.assertIn(
            "检测到 1 次帧时间异常",
            self.window.overview_label.text(),
        )
        self.assertIn(
            "附近帧",
            self.window.events_note.text(),
        )
        self.assertIn(
            "发现了什么",
            self.window.finding_detail.text(),
        )
        self.assertIn(
            "遥测",
            self.window.sync_detail.text(),
        )
        self.assertIn(
            "局部基线",
            self.window.event_detail.text(),
        )
        self.assertIn(
            "发现了什么",
            self.window.finding_blocks[0]["details"].text(),
        )
        self.assertIn(
            "严重程度",
            self.window.finding_blocks[0]["badges"].text(),
        )

    def test_grouped_local_events_use_one_finding_and_one_table(self):

        times = (
            8077.8189,
            28654.4834,
            49224.3901,
            69793.7094,
            90363.5611,
            104357.2580,
            110933.3445,
            131503.4047,
        )
        events = tuple(
            diagnostics.DiagnosticEvent(
                time_ms=time_ms,
                duration_ms=129.93,
                baseline_median_ms=20.91,
                threshold_ms=41.83,
                window_start_ms=time_ms - 750.0,
                window_end_ms=time_ms + 750.0,
                frame_index=0,
                finding_codes=(
                    "local_stutter_cpu_association",
                ),
            )
            for time_ms in times
        )
        findings = tuple(
            diagnostics.Finding(
                code="local_stutter_cpu_association",
                category="cpu",
                severity="warning",
                confidence="medium",
                claim_level="likely",
                summary="CPU work rose.",
                window_start_ms=start,
                window_end_ms=end,
                metrics={
                    "cpu_increase_ms": 109.0,
                    "gpu_increase_ms": 1.0,
                    "cpu_wait_ratio": 0.0,
                },
            )
            for start, end in (
                (event.window_start_ms, event.window_end_ms)
                for event in events
            )
        )
        report = diagnostics.DiagnosticReport(
            findings=findings,
            frame_count=120,
            duration_s=2.0,
            target_fps=60,
            target_budget_ms=16.67,
            timebase={
                "kind": "qpc_ms",
                "sync_quality": "verified_qpc",
                "absolute_mapping_trusted": True,
            },
            telemetry_aligned=False,
            event_count=len(events),
            events=events,
        )

        with mock.patch(
            "frame_viewer.diagnostics.analyze",
            return_value=report,
        ):

            window = FrameViewer(
                make_frames(),
                "capture.csv",
                target_fps=60,
            )

        try:

            self.assertEqual(
                window.finding_list.count(),
                1,
            )
            self.assertIn(
                "8 events",
                window.finding_list.item(0).text(),
            )
            self.assertEqual(
                window.event_table.rowCount(),
                8,
            )
            self.assertIn(
                "7 of 8 events",
                window.overview_label.text(),
            )
            self.assertIn(
                "20.57 s",
                window.overview_label.text(),
            )
            self.assertIn(
                "User-perceived stutter cannot be confirmed",
                window.overview_label.text(),
            )
            self.assertTrue(
                window.event_detail.isHidden()
            )
            self.assertFalse(
                window.event_hint.isHidden()
            )

            window.event_table.setCurrentCell(0, 0)
            QApplication.processEvents()

            self.assertFalse(
                window.event_detail.isHidden()
            )
            self.assertIn(
                "local baseline",
                window.event_detail.text(),
            )
            self.assertEqual(
                window.event_detail.text().count(
                    "During this slow moment"
                ),
                1,
            )

        finally:

            window.close()
            window.deleteLater()

    def test_guide_has_steps_progress_and_recheck(self):

        self.assertEqual(
            self.window._guide_category,
            "cpu",
        )
        self.assertEqual(
            len(self.window.guide_checks),
            4,
        )
        self.assertIn(
            "one variable",
            self.window.guide_note.text(),
        )
        self.assertEqual(
            self.window.guide_progress.text(),
            "0/4 steps completed",
        )
        self.assertTrue(
            self.window.guide_empty.isHidden()
        )
        self.assertTrue(
            self.window.recheck_btn.isEnabled()
        )
        self.assertEqual(
            self.window.target_name,
            "game.exe",
        )

    def test_guide_checkbox_progress_and_reset(self):

        self.window.guide_checks[0].setChecked(True)
        self.window.guide_checks[1].setChecked(True)

        self.assertEqual(
            self.window.guide_progress.text(),
            "2/4 steps completed",
        )

        self.window.reset_guide_steps()

        self.assertFalse(
            any(
                check.isChecked()
                for check in self.window.guide_checks
            )
        )
        self.assertEqual(
            self.window.guide_progress.text(),
            "0/4 steps completed",
        )

    def test_guide_state_is_kept_per_category(self):

        self.window.guide_checks[0].setChecked(True)
        self.window._show_guide("memory")

        self.assertEqual(
            len(self.window.guide_checks),
            4,
        )
        self.assertEqual(
            self.window.guide_progress.text(),
            "0/4 steps completed",
        )

        self.window.guide_checks[1].setChecked(True)
        self.window._show_guide("cpu")

        self.assertTrue(
            self.window.guide_checks[0].isChecked()
        )
        self.assertEqual(
            self.window.guide_progress.text(),
            "1/4 steps completed",
        )

        self.window.reset_guide_steps()
        self.window._show_guide("memory")

        self.assertTrue(
            self.window.guide_checks[1].isChecked()
        )
        self.assertEqual(
            self.window.guide_progress.text(),
            "1/4 steps completed",
        )

    def test_unknown_category_uses_data_quality_guide(self):

        self.window._show_guide("unknown")

        self.assertEqual(
            self.window._guide_category,
            "data_quality",
        )
        self.assertIn(
            "QPC",
            self.window.guide_step_labels[0].text(),
        )

    def test_all_finding_categories_have_three_to_five_steps(self):

        for category in (
            "cpu",
            "gpu",
            "mixed",
            "memory",
            "presentation",
            "data_quality",
            "unknown",
        ):

            steps = diagnostic_text.guide_steps(category)

            self.assertGreaterEqual(len(steps), 3)
            self.assertLessEqual(len(steps), 5)
            self.assertTrue(
                all(step.strip() for step in steps)
            )

    def test_runtime_language_switch_localizes_guide(self):

        self.window.guide_checks[0].setChecked(True)

        i18n.get_manager().set_language("zh_CN")
        QApplication.processEvents()

        self.assertIn(
            "一次只改变一个变量",
            self.window.guide_note.text(),
        )
        self.assertIn(
            "后台程序",
            self.window.guide_step_labels[0].text(),
        )
        self.assertEqual(
            self.window.guide_progress.text(),
            "已完成 1/4 步",
        )
        self.assertEqual(
            self.window.guide_reset_btn.text(),
            "重置步骤",
        )
        self.assertEqual(
            self.window.recheck_btn.text(),
            "重新抓取检测",
        )

    def test_recheck_emits_target_without_starting_capture(self):

        targets = []
        self.window.recheck_requested.connect(
            targets.append
        )

        self.window.recheck_btn.click()

        self.assertEqual(targets, ["game.exe"])

    def test_legacy_capture_without_telemetry_still_offers_guide(self):

        self.assertIsNone(self.window.telemetry)
        self.assertEqual(
            len(self.window.guide_checks),
            4,
        )

    def test_finding_detail_uses_plain_language_order(self):

        detail = self.window.finding_detail.text()
        labels = (
            "What we found",
            "Why this appears",
            "How certain is this?",
            "What this does not tell you",
            "What you can do next",
        )
        positions = [
            detail.index(label) for label in labels
        ]

        self.assertEqual(positions, sorted(positions))
        self.assertIn(
            "possible link, not a confirmed cause",
            detail,
        )
        self.assertNotIn("Median CPUBusy", detail)

    def test_technical_details_are_collapsed_by_default(self):

        self.assertTrue(
            self.window.technical_panel.isHidden()
        )
        self.assertEqual(
            self.window.technical_toggle.text(),
            "Show technical details",
        )

        self.window.technical_toggle.click()

        self.assertFalse(
            self.window.technical_panel.isHidden()
        )
        self.assertEqual(
            self.window.technical_toggle.text(),
            "Hide technical details",
        )

        detail = self.window.technical_detail.text()

        self.assertIn("Median CPUBusy", detail)
        self.assertIn("observed_association", detail)
        self.assertIn(
            "Fixed-threshold stutter threshold",
            detail,
        )
        self.assertIn(
            "Engine evidence (raw)",
            detail,
        )
        self.assertIn(
            "no sidecar",
            self.window.sync_detail.text(),
        )

        self.window.technical_toggle.click()
        self.assertTrue(
            self.window.technical_panel.isHidden()
        )

    def test_glossary_explains_metrics_and_terms(self):

        self.assertTrue(
            self.window.glossary_panel.isHidden()
        )
        self.assertEqual(
            self.window.glossary_toggle.text(),
            "Explain these numbers",
        )

        self.window.glossary_toggle.click()

        self.assertFalse(
            self.window.glossary_panel.isHidden()
        )
        text = self.window.glossary_panel.text()

        for term in (
            "FPS",
            "1% Low",
            "P99",
            "Frame time",
            "QPC",
            "Telemetry",
        ):

            self.assertIn(term, text)

    def test_finding_list_and_event_table_avoid_horizontal_scroll(self):

        self.assertEqual(
            self.window.finding_list.resizeMode(),
            QListView.ResizeMode.Adjust,
        )
        self.assertEqual(
            self.window.finding_list.horizontalScrollBarPolicy(),
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
        )
        self.assertEqual(
            self.window.finding_list.horizontalScrollBar().maximum(),
            0,
        )
        self.assertEqual(
            self.window.event_table.columnCount(),
            5,
        )
        self.assertEqual(
            self.window.event_table.horizontalScrollBarPolicy(),
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff,
        )
        self.assertEqual(
            self.window.event_table.horizontalScrollBar().maximum(),
            0,
        )

    def test_missing_telemetry_is_explained_in_plain_detail(self):

        self.assertIn(
            "No telemetry sidecar was found",
            self.window.finding_detail.text(),
        )
        self.assertIn(
            "frame-level CPU/GPU timing is still available",
            self.window.finding_detail.text(),
        )

    def test_untrusted_timebase_is_explained_in_plain_detail(self):

        frames = make_frames()

        for frame in frames:

            frame["timebase_kind"] = "relative"
            frame["sync_quality"] = "untrusted"
            frame["absolute_mapping_trusted"] = False

        window = FrameViewer(
            frames,
            "legacy.csv",
            telemetry=make_telemetry(),
            target_fps=60,
        )

        try:

            self.assertFalse(
                window.diagnostic_report.telemetry_aligned
            )
            self.assertIn(
                "timing is not reliable enough",
                window.finding_detail.text(),
            )
            self.assertIn(
                "do not treat a specific slow frame",
                window.finding_detail.text(),
            )

        finally:

            window.close()
            window.deleteLater()

    def test_runtime_language_switch_localizes_plain_technical_and_glossary(
        self,
    ):

        self.window.technical_toggle.click()
        self.window.glossary_toggle.click()

        i18n.get_manager().set_language("zh_CN")
        QApplication.processEvents()

        self.assertIn(
            "发现了什么",
            self.window.finding_detail.text(),
        )
        self.assertIn(
            "可能相关，尚未确认",
            self.window.finding_list.item(0).text(),
        )
        self.assertEqual(
            self.window.technical_toggle.text(),
            "收起专业数据",
        )
        self.assertIn(
            "分类",
            self.window.technical_detail.text(),
        )
        self.assertEqual(
            self.window.glossary_toggle.text(),
            "收起数值解释",
        )
        self.assertIn(
            "每秒帧数",
            self.window.glossary_panel.text(),
        )

    def test_every_category_has_plain_why_limit_and_advice(self):

        categories = (
            "cpu",
            "gpu",
            "mixed",
            "memory",
            "presentation",
            "data_quality",
            "unknown",
        )

        for language in ("en", "zh_CN"):

            i18n.get_manager().set_language(language)

            for category in categories:

                finding = diagnostics.Finding(
                    code="insufficient_evidence",
                    category=category,
                    severity="info",
                    confidence="low",
                    claim_level="insufficient_evidence",
                    summary="Insufficient evidence.",
                )

                self.assertTrue(
                    diagnostic_text.why_text(finding).strip()
                )
                self.assertTrue(
                    diagnostic_text.limit_text(finding).strip()
                )
                self.assertTrue(
                    diagnostic_text.advice_text(finding).strip()
                )

    def test_insufficient_evidence_certainty_is_explicit(self):

        finding = diagnostics.Finding(
            code="insufficient_evidence",
            category="unknown",
            severity="info",
            confidence="low",
            claim_level="insufficient_evidence",
            summary="Insufficient evidence.",
        )
        text = diagnostic_text.certainty_text(finding)

        self.assertIn("not enough evidence", text)
        self.assertIn("not a diagnosis", text)
        self.assertNotIn("confirmed cause", text)

    def test_no_confirmed_claim_in_normal_ui_report(self):

        i18n.get_manager().set_language("zh_CN")
        QApplication.processEvents()

        self.assertFalse(
            any(
                finding.claim_level
                == "confirmed_by_control"
                for finding in self.window.diagnostic_report.findings
            )
        )
        self.assertNotIn(
            "受控 A/B 确认",
            self.window.finding_list.item(0).text(),
        )

    def test_sync_status_shows_verified_qpc_and_telemetry_coverage(self):

        window = FrameViewer(
            make_frames(),
            "capture.csv",
            telemetry=make_telemetry(),
            target_fps=60,
        )

        try:

            self.assertTrue(
                window.diagnostic_report.telemetry_aligned
            )
            self.assertIn(
                "verified",
                window.sync_detail.text(),
            )
            self.assertIn(
                "12 samples",
                window.sync_detail.text(),
            )

        finally:

            window.close()
            window.deleteLater()

    def test_report_overview_has_required_metrics(self):

        values = self.window.overview_values

        self.assertEqual(
            values["game"].text(),
            "game.exe",
        )
        self.assertEqual(
            values["frames"].text(),
            "120",
        )
        self.assertTrue(
            values["duration"].text().endswith("s")
        )
        self.assertNotEqual(
            values["average_fps"].text(),
            "--",
        )
        self.assertNotEqual(
            values["p95"].text(),
            "--",
        )
        self.assertNotEqual(
            values["one_percent_low"].text(),
            "--",
        )
        self.assertEqual(
            values["anomalies"].text(),
            str(
                len(
                    self.window.diagnostic_report.events
                )
            ),
        )

    def test_full_report_renders_every_group_with_required_sections(self):

        self.assertGreaterEqual(
            len(self.window.finding_blocks),
            2,
        )
        self.assertEqual(
            len(self.window.finding_blocks),
            len(self.window._display_groups),
        )
        self.assertEqual(
            sum(
                block["group"]["count"]
                for block in self.window.finding_blocks
            ),
            len(self.window.diagnostic_report.findings),
        )
        self.assertTrue(
            any(
                "Data quality" in block["heading"].text()
                for block in self.window.finding_blocks
            )
        )

        all_details = " ".join(
            block["details"].text()
            for block in self.window.finding_blocks
        )

        for label in (
            "What we found",
            "Why this appears",
            "How certain is this?",
            "What this does not tell you",
            "What to try next",
        ):

            self.assertIn(label, all_details)

        for block in self.window.finding_blocks:

            self.assertTrue(
                block["heading"].text()
            )
            self.assertIn(
                "Severity",
                block["badges"].text(),
            )
            self.assertIn(
                "Confidence",
                block["badges"].text(),
            )

    def test_finding_block_evidence_is_collapsible(self):

        block = self.window.finding_blocks[0]

        self.assertTrue(
            block["evidence"].isHidden()
        )
        self.assertEqual(
            block["evidence_toggle"].text(),
            "Show evidence and metrics",
        )

        block["evidence_toggle"].setChecked(True)
        QApplication.processEvents()

        self.assertFalse(
            block["evidence"].isHidden()
        )
        self.assertEqual(
            block["evidence_toggle"].text(),
            "Hide evidence and metrics",
        )

    def test_event_detail_expands_extended_cpu_gpu_fields(self):

        self.window.event_table.setCurrentCell(0, 0)
        QApplication.processEvents()

        detail = self.window.event_detail.text()

        self.assertIn("CPU wait", detail)
        self.assertIn("GPU latency", detail)
        self.assertIn("GPU time", detail)
        self.assertFalse(
            self.window.event_detail_title.isHidden()
        )

    def test_export_report_writes_safe_markdown(self):

        with tempfile.TemporaryDirectory() as folder:

            target = Path(folder) / "report.md"

            with mock.patch(
                "frame_viewer.QFileDialog.getSaveFileName",
                return_value=(str(target), "Markdown (*.md)"),
            ):

                self.window.export_report()

            text = target.read_text(encoding="utf-8")

            self.assertIn("LagLens Diagnostic Report", text)
            self.assertIn("Findings", text)
            self.assertIn("game.exe", text)
            self.assertNotIn(folder, text)

    def test_embedded_viewer_export_report_writes_json(self):

        window = FrameViewer(
            make_frames(),
            "capture.csv",
            target_fps=60,
            embedded=True,
        )

        try:

            with tempfile.TemporaryDirectory() as folder:

                target = Path(folder) / "embedded.json"

                with mock.patch(
                    "frame_viewer.QFileDialog.getSaveFileName",
                    return_value=(
                        str(target),
                        "JSON (*.json)",
                    ),
                ):

                    window.export_report()

                text = target.read_text(encoding="utf-8")

                self.assertIn('"schema_version": 1', text)
                self.assertIn('"events"', text)

        finally:

            window.close()
            window.deleteLater()

    def test_export_report_writes_safe_json(self):

        with tempfile.TemporaryDirectory() as folder:

            target = Path(folder) / "report.json"

            with mock.patch(
                "frame_viewer.QFileDialog.getSaveFileName",
                return_value=(str(target), "JSON (*.json)"),
            ):

                self.window.export_report()

            text = target.read_text(encoding="utf-8")

            self.assertIn('"schema_version": 1', text)
            self.assertIn('"events"', text)
            self.assertIn('"game.exe"', text)
            self.assertNotIn(folder, text)


if __name__ == "__main__":

    unittest.main()
