"""Presentation-layer grouping and periodicity tests."""

import json
import unittest

from dataclasses import replace

import diagnostic_report
import diagnostic_text
import diagnostics
import i18n


TIMES = (
    8077.8189,
    28654.4834,
    49224.3901,
    69793.7094,
    90363.5611,
    104357.2580,
    110933.3445,
    131503.4047,
)


def make_event(time_ms, code="local_stutter_cpu_association"):

    return diagnostics.DiagnosticEvent(
        time_ms=time_ms,
        duration_ms=129.93,
        baseline_median_ms=20.91,
        threshold_ms=41.83,
        window_start_ms=time_ms - 750.0,
        window_end_ms=time_ms + 750.0,
        frame_index=0,
        finding_codes=(code,),
    )


def make_finding(event, code="local_stutter_cpu_association"):

    return diagnostics.Finding(
        code=code,
        category="cpu",
        severity="warning",
        confidence="medium",
        claim_level="likely",
        summary="CPU work rose during this slow moment.",
        window_start_ms=event.window_start_ms,
        window_end_ms=event.window_end_ms,
        metrics={
            "cpu_increase_ms": 109.0,
            "gpu_increase_ms": 1.0,
            "cpu_wait_ratio": 0.0,
        },
    )


def make_report(times=TIMES, with_events=True):

    events = (
        tuple(
            make_event(time_ms)
            for time_ms in times
        )
        if with_events
        else ()
    )
    findings = (
        tuple(
            make_finding(event)
            for event in events
        )
        if with_events
        else ()
    )

    return diagnostics.DiagnosticReport(
        findings=findings,
        frame_count=6106,
        duration_s=136.49,
        target_fps=60,
        target_budget_ms=16.67,
        timebase={
            "kind": "qpc_ms",
            "sync_quality": "verified_qpc",
            "absolute_mapping_trusted": True,
        },
        telemetry_aligned=True,
        event_count=len(events),
        events=events,
        telemetry_available=True,
        telemetry_complete=True,
        telemetry_sample_count=543,
    )


class PeriodicityTests(unittest.TestCase):

    def setUp(self):

        i18n.get_manager().set_language("en")

    def tearDown(self):

        i18n.get_manager().set_language("en")

    def test_seven_of_eight_share_the_dominant_interval(self):

        report = make_report()
        period = diagnostic_text.event_periodicity(
            report.events
        )

        self.assertAlmostEqual(
            period["period_ms"] / 1000.0,
            20.57,
            places=2,
        )
        self.assertEqual(
            len(period["regular_indices"]),
            7,
        )
        self.assertEqual(
            period["extra_indices"],
            (5,),
        )

    def test_summary_does_not_claim_all_eight_are_periodic(self):

        lines = diagnostic_text.anomaly_summary(
            make_report()
        )
        text = "\n".join(lines)

        self.assertIn(
            "7 of 8 events follow approximately 20.57 s",
            text,
        )
        self.assertIn(
            "1 event falls outside this pattern",
            text,
        )
        self.assertIn(
            "event timestamps only",
            text,
        )
        self.assertIn(
            "User-perceived stutter cannot be confirmed",
            text,
        )
        self.assertNotIn(
            "All 8 events follow",
            text,
        )

    def test_all_regular_events_are_reported_as_all(self):

        times = (0.0, 10000.0, 20000.0, 30000.0)
        period = diagnostic_text.event_periodicity(
            [
                make_event(time)
                for time in times
            ]
        )

        self.assertEqual(
            len(period["regular_indices"]),
            4,
        )
        self.assertEqual(
            period["extra_indices"],
            (),
        )

        text = "\n".join(
            diagnostic_text.anomaly_summary(
                make_report(times=times)
            )
        )
        self.assertIn(
            "All 4 events follow approximately 10.00 s",
            text,
        )

    def test_irregular_events_do_not_invent_a_period(self):

        times = (0.0, 1000.0, 7000.0, 15000.0)
        period = diagnostic_text.event_periodicity(
            [
                make_event(time)
                for time in times
            ]
        )

        self.assertIsNone(period["period_ms"])
        self.assertIn(
            "No consistent interval was found",
            "\n".join(
                diagnostic_text.anomaly_summary(
                    make_report(times=times)
                )
            ),
        )

    def test_empty_report_has_no_events_and_no_crash(self):

        report = make_report(with_events=False)
        text = diagnostic_report.build_markdown(
            report,
            "capture.csv",
        )

        self.assertIn(
            "No local frame-time anomalies were detected",
            text,
        )
        self.assertIn(
            "No local dynamic anomalies were detected",
            text,
        )


class GroupingTests(unittest.TestCase):

    def setUp(self):

        i18n.get_manager().set_language("en")

    def tearDown(self):

        i18n.get_manager().set_language("en")

    def test_repeated_findings_are_grouped_once(self):

        report = make_report()
        groups = diagnostic_text.group_findings(
            report.findings
        )

        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["count"], 8)
        self.assertEqual(
            groups[0]["code"],
            "local_stutter_cpu_association",
        )
        self.assertEqual(
            diagnostic_text.group_count_label(8),
            " · 8 events",
        )

    def test_event_table_marks_regular_and_extra_rows(self):

        rows, period = diagnostic_text.event_table_rows(
            make_report()
        )

        self.assertEqual(len(rows), 8)
        self.assertEqual(
            sum(
                1
                for row in rows
                if row["pattern"] == "Regular"
            ),
            7,
        )
        self.assertEqual(
            sum(
                1
                for row in rows
                if row["pattern"] == "Extra"
            ),
            1,
        )
        self.assertIn(
            "CPU +109.0 ms",
            rows[0]["evidence"],
        )

    def test_negative_event_evidence_does_not_double_the_sign(self):

        event = make_event(0.0)
        finding = replace(
            make_finding(event),
            metrics={
                "cpu_increase_ms": -0.4,
                "gpu_increase_ms": 2.5,
            },
        )
        report = replace(
            make_report(times=(0.0,)),
            findings=(finding,),
        )
        rows, _periodicity = (
            diagnostic_text.event_table_rows(report)
        )

        self.assertIn(
            "CPU -0.4 ms",
            rows[0]["evidence"],
        )
        self.assertNotIn(
            "+-",
            rows[0]["evidence"],
        )
        self.assertIn(
            "GPU +2.5 ms",
            rows[0]["evidence"],
        )

    def test_markdown_groups_repeated_explanation_and_keeps_table(self):

        report = make_report()
        summary = diagnostic_text.finding_summary(
            report.findings[0]
        )
        text = diagnostic_report.build_markdown(
            report,
            "capture.csv",
            target_name="game.exe",
        )

        self.assertEqual(
            text.count(summary),
            2,
        )
        self.assertEqual(
            text.count("Try closing one high-CPU background app"),
            1,
        )
        self.assertEqual(
            text.count("| 8.08 s | 129.93 ms |"),
            1,
        )
        self.assertEqual(
            text.count("| 104.36 s | 129.93 ms |"),
            1,
        )
        self.assertIn("| Time | Duration | Type | Pattern | Key evidence |", text)

    def test_same_category_advice_appears_only_once(self):

        report = make_report()
        global_finding = diagnostics.Finding(
            code="global_cpu_bottleneck_candidate",
            category="cpu",
            severity="warning",
            confidence="medium",
            claim_level="likely",
            summary="CPU frame work is the main pressure.",
            window_start_ms=0.0,
            window_end_ms=report.duration_s * 1000.0,
            metrics={
                "cpu_busy_median_ms": 20.85,
                "gpu_busy_median_ms": 0.87,
            },
        )
        report = replace(
            report,
            findings=(global_finding,)
            + report.findings,
        )
        text = diagnostic_report.build_markdown(
            report,
            "capture.csv",
        )

        self.assertEqual(text.count("### CPU side"), 2)
        self.assertEqual(
            text.count("Try closing one high-CPU background app"),
            1,
        )

    def test_json_keeps_all_raw_events_and_findings(self):

        payload = json.loads(
            diagnostic_report.build_json(
                make_report(),
                "capture.csv",
            )
        )

        self.assertEqual(
            len(payload["report"]["events"]),
            8,
        )
        self.assertEqual(
            len(payload["report"]["findings"]),
            8,
        )
        self.assertTrue(
            payload["report"]["findings"][0]["evidence"]
            or payload["report"]["findings"][0]["metrics"]
        )

    def test_mixed_finding_categories_remain_separate_groups(self):

        cpu_event = make_event(
            0.0,
            "local_stutter_cpu_association",
        )
        gpu_event = make_event(
            1000.0,
            "local_stutter_gpu_association",
        )
        findings = (
            make_finding(
                cpu_event,
                "local_stutter_cpu_association",
            ),
            diagnostics.Finding(
                code="local_stutter_gpu_association",
                category="gpu",
                severity="warning",
                confidence="medium",
                claim_level="likely",
                summary="GPU work rose during this slow moment.",
                window_start_ms=gpu_event.window_start_ms,
                window_end_ms=gpu_event.window_end_ms,
                metrics={
                    "cpu_increase_ms": 1.0,
                    "gpu_increase_ms": 90.0,
                },
            ),
        )

        groups = diagnostic_text.group_findings(findings)

        self.assertEqual(len(groups), 2)
        self.assertEqual(
            [group["category"] for group in groups],
            ["cpu", "gpu"],
        )

    def test_chinese_summary_and_table_are_localized(self):

        i18n.get_manager().set_language("zh_CN")
        text = diagnostic_report.build_markdown(
            make_report(),
            "capture.csv",
        )

        self.assertIn("异常摘要", text)
        self.assertIn(
            "8 次异常中有 7 次呈现约 20.57 秒",
            text,
        )
        self.assertIn("另有 1 次异常不在该规律内", text)
        self.assertIn("异常事件表", text)
        self.assertIn("| 时间 | 持续时长 | 类型 | 规律 | 关键证据 |", text)


if __name__ == "__main__":

    unittest.main()
