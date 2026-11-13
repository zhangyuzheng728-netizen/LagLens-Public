"""C-2.1 evidence-based diagnostic engine tests.

All fixtures are synthetic and reproducible.  They exercise the rule
semantics; the real Palworld run is reported separately in the C-2.1
documentation and is not treated as a confirmed cause.
"""

import json
import tempfile
import unittest

from pathlib import Path

from frame_stats import compute_stats
from telemetry import TelemetryReadResult

import diagnostic_report
import diagnostics
import i18n


def make_frame(
    time_ms,
    duration_ms,
    cpu_busy=8.0,
    cpu_wait=8.7,
    gpu_busy=8.0,
    gpu_wait=8.7,
    displayed=True,
    display_latency=32.0,
    gpu_fields=True,
    timebase_kind="qpc_ms",
    sync_quality="verified_qpc",
    absolute_mapping_trusted=True,
):
    row = {
        "CPUBusy": str(cpu_busy),
        "CPUWait": str(cpu_wait),
        "DisplayedTime": "16.0" if displayed else "NA",
        "DisplayLatency": (
            str(display_latency) if displayed else "NA"
        ),
    }

    if gpu_fields:

        row.update(
            {
                "GPUBusy": str(gpu_busy),
                "GPUWait": str(gpu_wait),
                "GPUTime": str(gpu_busy + gpu_wait),
            }
        )

    return {
        "time": time_ms,
        "duration": duration_ms,
        "displayed": displayed,
        "row": row,
        "timebase_kind": timebase_kind,
        "sync_quality": sync_quality,
        "absolute_mapping_trusted": (
            absolute_mapping_trusted
        ),
    }


def make_series(
    count=300,
    frame_ms=16.7,
    cpu_busy=16.2,
    cpu_wait=0.5,
    gpu_busy=6.0,
    gpu_wait=10.7,
    events=None,
    gpu_fields=True,
    displayed=True,
    timebase_kind="qpc_ms",
    sync_quality="verified_qpc",
    absolute_mapping_trusted=True,
):
    """Build cumulative-time frames with optional index overrides."""

    events = events or {}
    frames = []
    time_ms = 0.0

    for index in range(count):

        overrides = events.get(index, {})
        duration_ms = float(
            overrides.get("duration_ms", frame_ms)
        )
        frames.append(
            make_frame(
                time_ms,
                duration_ms,
                cpu_busy=float(
                    overrides.get("cpu_busy", cpu_busy)
                ),
                cpu_wait=float(
                    overrides.get("cpu_wait", cpu_wait)
                ),
                gpu_busy=float(
                    overrides.get("gpu_busy", gpu_busy)
                ),
                gpu_wait=float(
                    overrides.get("gpu_wait", gpu_wait)
                ),
                displayed=bool(
                    overrides.get("displayed", displayed)
                ),
                gpu_fields=gpu_fields,
                timebase_kind=timebase_kind,
                sync_quality=sync_quality,
                absolute_mapping_trusted=(
                    absolute_mapping_trusted
                ),
            )
        )
        time_ms += duration_ms

    return frames


def make_control(**overrides):
    values = {
        "target": "cpu",
        "factor": "resolution",
        "baseline_capture": "capture-A",
        "treatment_capture": "capture-B",
        "metric": "p95_frame_ms",
        "baseline_value": 40.0,
        "treatment_value": 20.0,
        "baseline_scenario": "Palworld same route and build",
        "treatment_scenario": "Palworld same route and build",
        "baseline_settings": {
            "resolution": "1920x1080",
            "graphics_preset": "high",
            "frame_cap": "off",
        },
        "treatment_settings": {
            "resolution": "1280x720",
            "graphics_preset": "high",
            "frame_cap": "off",
        },
        "baseline_duration_s": 60.0,
        "treatment_duration_s": 60.0,
        "baseline_frames": 3600,
        "treatment_frames": 3600,
    }
    values.update(overrides)
    return diagnostics.ControlExperiment(**values)


def make_telemetry(
    samples=40,
    ram=65.0,
    target_cpu=50.0,
    rss_start=2_000_000_000,
    rss_step=0,
    gpu_util=99.0,
    complete=True,
):
    data = []

    for index in range(samples):

        data.append(
            {
                "type": "sample",
                "t_ms": index * 250.0,
                "cpu": {
                    "system_percent": 30.0,
                },
                "ram": {
                    "percent": ram,
                },
                "target": {
                    "cpu_percent": target_cpu,
                    "rss_bytes": (
                        rss_start + index * rss_step
                    ),
                },
                "gpu": {
                    "util_percent": gpu_util,
                    "association": "unknown",
                },
            }
        )

    return TelemetryReadResult(
        available=True,
        complete=complete,
        metadata={
            "type": "metadata",
            "capture": {
                "started_monotonic_ns": 0,
            },
        },
        samples=data,
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


ALLOW_CONTROLS = diagnostics.DiagnosticConfig(
    allow_confirmed_by_control=True,
)


CPU_EVENTS = {
    120: {
        "duration_ms": 40.0,
        "cpu_busy": 39.0,
        "cpu_wait": 1.0,
        "gpu_busy": 7.0,
        "gpu_wait": 10.0,
    },
    260: {
        "duration_ms": 40.0,
        "cpu_busy": 39.0,
        "cpu_wait": 1.0,
        "gpu_busy": 7.0,
        "gpu_wait": 10.0,
    },
}

GPU_EVENTS = {
    120: {
        "duration_ms": 40.0,
        "cpu_busy": 5.0,
        "cpu_wait": 1.0,
        "gpu_busy": 39.0,
        "gpu_wait": 1.0,
    },
    260: {
        "duration_ms": 40.0,
        "cpu_busy": 5.0,
        "cpu_wait": 1.0,
        "gpu_busy": 39.0,
        "gpu_wait": 1.0,
    },
}


class RuleTests(unittest.TestCase):

    def test_cpu_bound_global_and_repeated_local_events_are_likely(self):

        frames = make_series(events=CPU_EVENTS)
        report = diagnostics.analyze(
            frames,
            target_fps=60,
        )

        global_cpu = [
            finding for finding in report.findings
            if finding.code == "global_cpu_bottleneck_candidate"
        ]
        local_cpu = [
            finding for finding in report.findings
            if finding.code == "local_stutter_cpu_association"
        ]

        self.assertEqual(len(global_cpu), 1)
        self.assertGreaterEqual(len(local_cpu), 2)
        self.assertEqual(
            global_cpu[0].claim_level,
            "likely",
        )
        self.assertFalse(
            any(
                finding.claim_level
                == "confirmed_by_control"
                for finding in report.findings
            )
        )
        self.assertFalse(
            any(
                finding.code
                == "global_gpu_bottleneck_candidate"
                for finding in report.findings
            )
        )
        self.assertTrue(
            any(
                "CPUBusy" in evidence
                for evidence in global_cpu[0].evidence
            )
        )

    def test_gpu_bound_global_and_repeated_local_events_are_likely(self):

        frames = make_series(
            cpu_busy=5.0,
            cpu_wait=11.7,
            gpu_busy=16.0,
            gpu_wait=0.7,
            events=GPU_EVENTS,
        )
        report = diagnostics.analyze(
            frames,
            target_fps=60,
        )

        global_gpu = [
            finding for finding in report.findings
            if finding.code == "global_gpu_bottleneck_candidate"
        ]
        local_gpu = [
            finding for finding in report.findings
            if finding.code == "local_stutter_gpu_association"
        ]

        self.assertEqual(len(global_gpu), 1)
        self.assertGreaterEqual(len(local_gpu), 2)
        self.assertEqual(
            global_gpu[0].claim_level,
            "likely",
        )
        self.assertFalse(
            any(
                finding.code
                == "global_cpu_bottleneck_candidate"
                for finding in report.findings
            )
        )

    def test_overlapping_event_windows_are_not_counted_as_independent(self):

        frames = make_series(
            events={
                120: CPU_EVENTS[120],
                156: CPU_EVENTS[120],
            },
        )
        report = diagnostics.analyze(
            frames,
            target_fps=60,
        )

        self.assertEqual(report.event_count, 1)
        self.assertFalse(
            any(
                finding.claim_level == "likely"
                for finding in report.findings
                if finding.category == "cpu"
            )
        )

    def test_single_local_event_is_not_promoted_to_likely(self):

        frames = make_series(
            events={120: CPU_EVENTS[120]},
        )
        report = diagnostics.analyze(
            frames,
            target_fps=60,
        )

        cpu_findings = [
            finding for finding in report.findings
            if finding.category == "cpu"
        ]

        self.assertTrue(cpu_findings)
        self.assertFalse(
            any(
                finding.claim_level == "likely"
                for finding in cpu_findings
            )
        )

    def test_mixed_pressure_keeps_multiple_candidates(self):

        frames = make_series(
            frame_ms=15.6,
            cpu_busy=15.55,
            cpu_wait=0.05,
            gpu_busy=15.4,
            gpu_wait=0.1,
        )
        report = diagnostics.analyze(
            frames,
            target_fps=60,
        )

        mixed = [
            finding for finding in report.findings
            if finding.code == "mixed_frame_pressure"
        ]

        self.assertEqual(len(mixed), 1)
        self.assertEqual(mixed[0].category, "mixed")
        self.assertEqual(
            mixed[0].claim_level,
            "observed_association",
        )
        self.assertFalse(
            any(
                finding.code
                in (
                    "global_cpu_bottleneck_candidate",
                    "global_gpu_bottleneck_candidate",
                )
                for finding in report.findings
            )
        )

    def test_local_baseline_catches_spike_that_global_floor_would_miss(self):

        frames = make_series(
            count=300,
            frame_ms=5.0,
            cpu_busy=4.5,
            cpu_wait=0.5,
            gpu_busy=3.0,
            gpu_wait=2.0,
            events={
                200: {
                    "duration_ms": 25.0,
                    "cpu_busy": 24.0,
                    "cpu_wait": 1.0,
                    "gpu_busy": 4.0,
                    "gpu_wait": 21.0,
                },
            },
        )

        report = diagnostics.analyze(
            frames,
            target_fps=240,
        )

        self.assertGreaterEqual(report.event_count, 1)
        self.assertTrue(
            any(
                finding.code
                == "local_stutter_cpu_association"
                for finding in report.findings
            )
        )

    def test_high_frame_rate_under_budget_is_not_global_pressure(self):

        frames = make_series(
            frame_ms=8.33,
            cpu_busy=7.5,
            cpu_wait=0.8,
            gpu_busy=4.0,
            gpu_wait=4.3,
        )
        report = diagnostics.analyze(
            frames,
            target_fps=60,
        )

        self.assertFalse(
            any(
                finding.code
                in (
                    "global_cpu_bottleneck_candidate",
                    "global_gpu_bottleneck_candidate",
                    "mixed_frame_pressure",
                )
                for finding in report.findings
            )
        )

    def test_vsync_like_cpu_wait_is_not_cpu_bottleneck(self):

        frames = make_series(
            cpu_busy=2.0,
            cpu_wait=14.7,
            gpu_busy=2.0,
            gpu_wait=14.7,
        )
        report = diagnostics.analyze(
            frames,
            target_fps=60,
        )

        self.assertFalse(
            any(
                finding.code
                in (
                    "global_cpu_bottleneck_candidate",
                    "global_gpu_bottleneck_candidate",
                    "mixed_frame_pressure",
                )
                for finding in report.findings
            )
        )

    def test_exact_local_threshold_is_not_a_stutter(self):

        frames = make_series(
            count=80,
            frame_ms=10.0,
            cpu_busy=9.0,
            cpu_wait=1.0,
            gpu_busy=5.0,
            gpu_wait=5.0,
            events={
                60: {
                    "duration_ms": 20.0,
                    "cpu_busy": 18.0,
                    "cpu_wait": 2.0,
                    "gpu_busy": 8.0,
                    "gpu_wait": 12.0,
                },
            },
        )
        report = diagnostics.analyze(
            frames,
            target_fps=60,
        )

        self.assertEqual(report.event_count, 0)

    def test_abnormal_frames_are_skipped_without_crashing(self):

        frames = make_series(count=40)
        frames.append(
            {
                "time": 1000.0,
                "duration": 0.0,
                "displayed": False,
                "row": {},
            }
        )
        frames.append(
            {
                "time": float("nan"),
                "duration": 16.0,
                "displayed": False,
                "row": {},
            }
        )
        frames.append(
            {
                "time": 2000.0,
                "duration": 16.0,
                "displayed": False,
                "row": {
                    "CPUBusy": "NA",
                    "CPUWait": "NA",
                    "GPUBusy": "NA",
                    "GPUWait": "NA",
                    "GPUTime": "NA",
                    "DisplayedTime": "NA",
                },
            }
        )

        report = diagnostics.analyze(
            frames,
            target_fps=60,
        )

        # The third row has a valid time/duration but no metrics; it is
        # retained as frame context rather than crashing or inventing
        # CPU/GPU values.
        self.assertEqual(report.frame_count, 41)

    def test_fully_displayed_capture_has_no_presentation_warning(self):

        report = diagnostics.analyze(
            make_series(count=120),
            target_fps=60,
        )

        self.assertFalse(
            any(
                finding.code == "displayed_frames_missing"
                for finding in report.findings
            )
        )

    def test_high_cpu_wait_prevents_cpu_candidate(self):

        frames = make_series(
            cpu_busy=16.0,
            cpu_wait=0.7,
            gpu_busy=2.0,
            gpu_wait=14.7,
        )
        # Make CPUWait high and GPU active low; neither side should be
        # selected as a strong candidate.
        for frame in frames:

            frame["row"]["CPUWait"] = "10.0"
            frame["row"]["CPUBusy"] = "6.7"

        report = diagnostics.analyze(
            frames,
            target_fps=60,
        )

        self.assertFalse(
            any(
                finding.code
                == "global_cpu_bottleneck_candidate"
                for finding in report.findings
            )
        )
        self.assertFalse(
            any(
                finding.code
                == "global_gpu_bottleneck_candidate"
                for finding in report.findings
            )
        )

    def test_local_stutter_without_matching_signal_is_unclassified(self):

        frames = make_series(
            events={
                200: {
                    "duration_ms": 40.0,
                    "cpu_busy": 8.0,
                    "cpu_wait": 32.0,
                    "gpu_busy": 8.0,
                    "gpu_wait": 32.0,
                },
            }
        )
        report = diagnostics.analyze(
            frames,
            target_fps=60,
        )

        self.assertTrue(
            any(
                finding.code == "local_stutter_unclassified"
                and finding.claim_level
                == "insufficient_evidence"
                for finding in report.findings
            )
        )


class TelemetryAndTimebaseTests(unittest.TestCase):

    def test_memory_association_requires_aligned_qpc(self):

        frames = make_series(
            cpu_busy=8.0,
            cpu_wait=8.7,
            gpu_busy=8.0,
            gpu_wait=8.7,
            events={
                120: {
                    "duration_ms": 40.0,
                    "cpu_busy": 20.0,
                    "cpu_wait": 20.0,
                    "gpu_busy": 20.0,
                    "gpu_wait": 20.0,
                },
                260: {
                    "duration_ms": 40.0,
                    "cpu_busy": 20.0,
                    "cpu_wait": 20.0,
                    "gpu_busy": 20.0,
                    "gpu_wait": 20.0,
                },
            },
        )
        telemetry = make_telemetry(
            ram=92.0,
            target_cpu=50.0,
            rss_step=100_000_000,
        )

        aligned = diagnostics.analyze(
            frames,
            target_fps=60,
            telemetry=telemetry,
        )

        self.assertTrue(aligned.telemetry_aligned)
        self.assertTrue(
            any(
                finding.code.startswith(
                    "local_stutter_memory"
                )
                or finding.code
                == "global_memory_pressure_association"
                for finding in aligned.findings
            )
        )

        legacy = make_series(
            cpu_busy=8.0,
            cpu_wait=8.7,
            gpu_busy=8.0,
            gpu_wait=8.7,
            events={
                120: {
                    "duration_ms": 40.0,
                    "cpu_busy": 20.0,
                    "cpu_wait": 20.0,
                    "gpu_busy": 20.0,
                    "gpu_wait": 20.0,
                },
            },
            timebase_kind="relative",
            sync_quality="exact_relative",
            absolute_mapping_trusted=False,
        )
        legacy_report = diagnostics.analyze(
            legacy,
            target_fps=60,
            telemetry=telemetry,
        )

        self.assertFalse(legacy_report.telemetry_aligned)
        self.assertFalse(
            any(
                finding.category == "memory"
                for finding in legacy_report.findings
            )
        )
        self.assertTrue(
            any(
                finding.code
                == "telemetry_timebase_untrusted"
                for finding in legacy_report.findings
            )
        )

    def test_cpu_and_memory_associations_can_coexist(self):

        frames = make_series(events=CPU_EVENTS)
        telemetry = make_telemetry(
            ram=92.0,
            rss_step=100_000_000,
        )
        report = diagnostics.analyze(
            frames,
            target_fps=60,
            telemetry=telemetry,
        )

        categories = {
            finding.category
            for finding in report.findings
        }

        self.assertIn("cpu", categories)
        self.assertIn("memory", categories)

    def test_memory_association_requires_high_ram(self):

        frames = make_series(
            cpu_busy=8.0,
            cpu_wait=8.7,
            gpu_busy=8.0,
            gpu_wait=8.7,
            events={
                120: {
                    "duration_ms": 40.0,
                    "cpu_busy": 20.0,
                    "cpu_wait": 20.0,
                    "gpu_busy": 20.0,
                    "gpu_wait": 20.0,
                },
            },
        )
        report = diagnostics.analyze(
            frames,
            target_fps=60,
            telemetry=make_telemetry(
                ram=50.0,
                rss_step=100_000_000,
            ),
        )

        self.assertFalse(
            any(
                finding.category == "memory"
                for finding in report.findings
            )
        )

    def test_nvml_gpu_util_is_not_used_as_process_gpu_usage(self):

        frames = make_series(
            cpu_busy=16.2,
            cpu_wait=0.5,
            gpu_busy=2.0,
            gpu_wait=14.7,
        )
        telemetry = make_telemetry(
            gpu_util=100.0,
        )

        report = diagnostics.analyze(
            frames,
            target_fps=60,
            telemetry=telemetry,
        )

        self.assertFalse(
            any(
                finding.category == "gpu"
                for finding in report.findings
            )
        )

    def test_missing_gpu_fields_disables_gpu_diagnosis(self):

        frames = make_series(
            events=CPU_EVENTS,
            gpu_fields=False,
        )
        report = diagnostics.analyze(
            frames,
            target_fps=60,
        )

        self.assertTrue(
            any(
                finding.code == "gpu_fields_unavailable"
                for finding in report.findings
            )
        )
        self.assertFalse(
            any(
                finding.category == "gpu"
                for finding in report.findings
            )
        )
        self.assertFalse(
            any(
                finding.claim_level == "likely"
                for finding in report.findings
            )
        )

    def test_target_cpu_zero_is_reported_as_unusable(self):

        frames = make_series(events=CPU_EVENTS)
        telemetry = make_telemetry(
            target_cpu=0.0,
        )

        report = diagnostics.analyze(
            frames,
            target_fps=60,
            telemetry=telemetry,
        )

        self.assertTrue(
            any(
                finding.code == "target_cpu_unusable"
                for finding in report.findings
            )
        )

    def test_displayed_time_na_is_presentation_observation(self):

        frames = make_series(count=120)

        for index in range(0, 120, 12):

            frames[index]["displayed"] = False
            frames[index]["row"]["DisplayedTime"] = "NA"
            frames[index]["row"]["DisplayLatency"] = "NA"

        report = diagnostics.analyze(
            frames,
            target_fps=60,
        )

        finding = [
            item for item in report.findings
            if item.code == "displayed_frames_missing"
        ]

        self.assertEqual(len(finding), 1)
        self.assertEqual(finding[0].category, "presentation")
        self.assertEqual(
            finding[0].claim_level,
            "observed_association",
        )


class InsufficientAndControlTests(unittest.TestCase):

    def test_too_few_frames_returns_insufficient_evidence(self):

        frames = make_series(count=10)
        report = diagnostics.analyze(
            frames,
            target_fps=60,
        )

        self.assertEqual(len(report.findings), 1)
        self.assertEqual(
            report.findings[0].code,
            "insufficient_evidence",
        )
        self.assertEqual(
            report.findings[0].claim_level,
            "insufficient_evidence",
        )

    def test_missing_timebase_disables_hardware_association(self):

        frames = make_series(
            events=CPU_EVENTS,
            timebase_kind="unknown",
            sync_quality="untrusted",
            absolute_mapping_trusted=False,
        )
        report = diagnostics.analyze(
            frames,
            target_fps=60,
            telemetry=make_telemetry(ram=92.0),
        )

        self.assertFalse(report.telemetry_aligned)
        self.assertTrue(
            any(
                finding.code == "telemetry_timebase_untrusted"
                for finding in report.findings
            )
        )
        self.assertFalse(
            any(
                finding.category == "memory"
                for finding in report.findings
            )
        )

    def test_valid_control_experiment_is_required_for_confirmation(self):

        frames = make_series(events=CPU_EVENTS)
        valid = make_control()

        default_report = diagnostics.analyze(
            frames,
            target_fps=60,
            control_experiments=[valid],
        )

        self.assertFalse(
            any(
                finding.claim_level
                == "confirmed_by_control"
                for finding in default_report.findings
            )
        )
        self.assertTrue(default_report.control_rejections)

        report = diagnostics.analyze(
            frames,
            target_fps=60,
            control_experiments=[valid],
            config=diagnostics.DiagnosticConfig(
                allow_confirmed_by_control=True,
            ),
        )

        self.assertTrue(
            any(
                finding.claim_level
                == "confirmed_by_control"
                for finding in report.findings
            )
        )
        self.assertEqual(report.control_rejections, ())

    def test_invalid_control_does_not_confirm(self):

        frames = make_series(events=CPU_EVENTS)
        invalid = make_control(
            baseline_capture="same",
            treatment_capture="same",
        )
        report = diagnostics.analyze(
            frames,
            target_fps=60,
            control_experiments=[invalid],
            config=ALLOW_CONTROLS,
        )

        self.assertFalse(
            any(
                finding.claim_level
                == "confirmed_by_control"
                for finding in report.findings
            )
        )
        self.assertTrue(report.control_rejections)

    def test_control_with_insufficient_improvement_does_not_confirm(self):

        frames = make_series(events=CPU_EVENTS)
        control = make_control(
            treatment_value=35.0,
        )
        report = diagnostics.analyze(
            frames,
            target_fps=60,
            control_experiments=[control],
            config=ALLOW_CONTROLS,
        )

        self.assertFalse(
            any(
                finding.claim_level
                == "confirmed_by_control"
                for finding in report.findings
            )
        )
        self.assertTrue(report.control_rejections)

    def test_control_requires_comparable_scenarios_and_settings(self):

        frames = make_series(events=CPU_EVENTS)
        cases = [
            make_control(
                treatment_scenario="different route",
            ),
            make_control(
                treatment_settings={
                    "resolution": "1280x720",
                    "graphics_preset": "low",
                    "frame_cap": "off",
                },
            ),
            make_control(
                baseline_duration_s=10.0,
                treatment_duration_s=60.0,
            ),
            make_control(
                baseline_frames=100,
                treatment_frames=100,
            ),
        ]

        for control in cases:

            report = diagnostics.analyze(
                frames,
                target_fps=60,
                control_experiments=[control],
                config=ALLOW_CONTROLS,
            )

            self.assertFalse(
                any(
                    finding.claim_level
                    == "confirmed_by_control"
                    for finding in report.findings
                )
            )
            self.assertTrue(report.control_rejections)

    def test_control_with_wrong_target_does_not_confirm_cpu(self):

        frames = make_series(events=CPU_EVENTS)
        control = make_control(
            target="gpu",
        )
        report = diagnostics.analyze(
            frames,
            target_fps=60,
            control_experiments=[control],
            config=ALLOW_CONTROLS,
        )

        self.assertFalse(
            any(
                finding.claim_level
                == "confirmed_by_control"
                for finding in report.findings
                if finding.category == "cpu"
            )
        )

    def test_report_and_findings_are_json_serializable(self):

        report = diagnostics.analyze(
            make_series(events=CPU_EVENTS),
            target_fps=60,
        )

        text = json.dumps(report.to_dict())

        self.assertIn("findings", text)
        self.assertIn("target_fps", text)

    def test_target_fps_is_validated(self):

        with self.assertRaises(ValueError):

            diagnostics.analyze(
                make_series(count=1),
                target_fps=0,
            )

        with self.assertRaises(ValueError):

            diagnostics.analyze(
                make_series(count=1),
                target_fps=1001,
            )


class SyntheticReliabilityMatrixTests(unittest.TestCase):

    def test_synthetic_false_positive_negative_matrix(self):

        cases = []

        cpu_report = diagnostics.analyze(
            make_series(events=CPU_EVENTS),
            target_fps=60,
        )
        cases.append(
            (
                "cpu-bound",
                cpu_report,
                {"global_cpu_bottleneck_candidate"},
                {"global_gpu_bottleneck_candidate"},
            )
        )

        gpu_report = diagnostics.analyze(
            make_series(
                cpu_busy=5.0,
                cpu_wait=11.7,
                gpu_busy=16.0,
                gpu_wait=0.7,
                events=GPU_EVENTS,
            ),
            target_fps=60,
        )
        cases.append(
            (
                "gpu-bound",
                gpu_report,
                {"global_gpu_bottleneck_candidate"},
                {"global_cpu_bottleneck_candidate"},
            )
        )

        mixed_report = diagnostics.analyze(
            make_series(
                frame_ms=15.6,
                cpu_busy=15.55,
                cpu_wait=0.05,
                gpu_busy=15.4,
                gpu_wait=0.1,
            ),
            target_fps=60,
        )
        cases.append(
            (
                "mixed",
                mixed_report,
                {"mixed_frame_pressure"},
                {
                    "global_cpu_bottleneck_candidate",
                    "global_gpu_bottleneck_candidate",
                },
            )
        )

        for label, frames in (
            (
                "frame-cap",
                make_series(
                    frame_ms=8.33,
                    cpu_busy=7.5,
                    cpu_wait=0.8,
                    gpu_busy=4.0,
                    gpu_wait=4.3,
                ),
            ),
            (
                "vsync",
                make_series(
                    cpu_busy=2.0,
                    cpu_wait=14.7,
                    gpu_busy=2.0,
                    gpu_wait=14.7,
                ),
            ),
        ):
            cases.append(
                (
                    label,
                    diagnostics.analyze(
                        frames,
                        target_fps=60,
                    ),
                    set(),
                    {
                        "global_cpu_bottleneck_candidate",
                        "global_gpu_bottleneck_candidate",
                        "mixed_frame_pressure",
                    },
                )
            )

        memory_frames = make_series(
            cpu_busy=8.0,
            cpu_wait=8.7,
            gpu_busy=8.0,
            gpu_wait=8.7,
            events={
                120: {
                    "duration_ms": 40.0,
                    "cpu_busy": 20.0,
                    "cpu_wait": 20.0,
                    "gpu_busy": 20.0,
                    "gpu_wait": 20.0,
                },
            },
        )
        memory_report = diagnostics.analyze(
            memory_frames,
            target_fps=60,
            telemetry=make_telemetry(
                ram=92.0,
                rss_step=100_000_000,
            ),
        )
        cases.append(
            (
                "memory-pressure",
                memory_report,
                set(),
                {
                    "global_cpu_bottleneck_candidate",
                    "global_gpu_bottleneck_candidate",
                },
            )
        )
        self.assertTrue(
            any(
                finding.category == "memory"
                for finding in memory_report.findings
            )
        )

        legacy_report = diagnostics.analyze(
            make_series(
                events=CPU_EVENTS,
                timebase_kind="relative",
                sync_quality="exact_relative",
                absolute_mapping_trusted=False,
            ),
            target_fps=60,
            telemetry=make_telemetry(ram=92.0),
        )
        cases.append(
            (
                "legacy-timebase",
                legacy_report,
                {"telemetry_timebase_untrusted"},
                set(),
            )
        )
        self.assertFalse(
            any(
                finding.category == "memory"
                for finding in legacy_report.findings
            )
        )

        missing_gpu = diagnostics.analyze(
            make_series(events=CPU_EVENTS, gpu_fields=False),
            target_fps=60,
        )
        cases.append(
            (
                "missing-gpu-fields",
                missing_gpu,
                {"gpu_fields_unavailable"},
                set(),
            )
        )
        self.assertFalse(
            any(
                finding.category == "gpu"
                for finding in missing_gpu.findings
            )
        )

        display_frames = make_series(count=120)
        for index in range(0, 120, 12):

            display_frames[index]["displayed"] = False
            display_frames[index]["row"]["DisplayedTime"] = "NA"
            display_frames[index]["row"]["DisplayLatency"] = "NA"

        display_report = diagnostics.analyze(
            display_frames,
            target_fps=60,
        )
        cases.append(
            (
                "display-na",
                display_report,
                {"displayed_frames_missing"},
                set(),
            )
        )

        nvml_report = diagnostics.analyze(
            make_series(
                cpu_busy=16.2,
                cpu_wait=0.5,
                gpu_busy=2.0,
                gpu_wait=14.7,
            ),
            target_fps=60,
            telemetry=make_telemetry(gpu_util=100.0),
        )
        self.assertFalse(
            any(
                finding.category == "gpu"
                for finding in nvml_report.findings
            )
        )

        single_report = diagnostics.analyze(
            make_series(events={120: CPU_EVENTS[120]}),
            target_fps=60,
        )
        self.assertFalse(
            any(
                finding.claim_level == "likely"
                for finding in single_report.findings
            )
        )

        overlapping_report = diagnostics.analyze(
            make_series(
                events={
                    120: CPU_EVENTS[120],
                    156: CPU_EVENTS[120],
                },
            ),
            target_fps=60,
        )
        self.assertEqual(overlapping_report.event_count, 1)

        failures = []

        for label, report, required_codes, forbidden_codes in cases:

            codes = {
                finding.code
                for finding in report.findings
            }

            for code in required_codes:

                if code not in codes:

                    failures.append(
                        f"{label}: missing {code}"
                    )

            for code in forbidden_codes:

                if code in codes:

                    failures.append(
                        f"{label}: unexpected {code}"
                    )

        self.assertEqual(failures, [])


class ReportStructureTests(unittest.TestCase):

    def test_report_exposes_structured_events_and_telemetry_coverage(self):

        frames = make_series(events=CPU_EVENTS)
        telemetry = make_telemetry()
        report = diagnostics.analyze(
            frames,
            target_fps=60,
            telemetry=telemetry,
        )

        self.assertTrue(report.telemetry_available)
        self.assertTrue(report.telemetry_complete)
        self.assertEqual(
            report.telemetry_sample_count,
            40,
        )
        self.assertGreaterEqual(report.event_count, 2)
        self.assertEqual(
            report.event_count,
            len(report.events),
        )

        event = report.events[0]

        self.assertGreater(event.duration_ms, 0)
        self.assertGreater(event.baseline_median_ms, 0)
        self.assertIn(
            event.frame_index,
            range(len(frames)),
        )
        self.assertTrue(event.finding_codes)

        payload = report.to_dict()

        self.assertIn("events", payload)
        self.assertTrue(payload["events"])
        self.assertTrue(payload["telemetry_available"])


class ReportExportTests(unittest.TestCase):

    def setUp(self):

        i18n.get_manager().set_language("en")

    def tearDown(self):

        i18n.get_manager().set_language("en")

    def _report(self):

        return diagnostics.analyze(
            make_series(events=CPU_EVENTS),
            target_fps=60,
        )

    def test_markdown_report_is_localized_and_path_safe(self):

        i18n.get_manager().set_language("zh_CN")
        report = self._report()
        text = diagnostic_report.build_markdown(
            report,
            r"D:\Users\alice\capture.csv",
            target_name=r"D:\Games\game.exe",
        )

        self.assertIn("LagLens 诊断报告", text)
        self.assertIn("诊断发现", text)
        self.assertIn("异常摘要", text)
        self.assertIn("异常事件表", text)
        self.assertIn("发现了什么", text)
        self.assertIn("为什么这样判断", text)
        self.assertIn("判断有多确定", text)
        self.assertIn("这不能说明什么", text)
        self.assertIn("下一步可以做什么", text)
        self.assertIn("专业数据", text)
        self.assertIn("不是已确认的原因", text)
        self.assertNotIn("Users", text)
        self.assertNotIn(r"D:\Games", text)
        self.assertNotIn("alice", text)

    def test_markdown_report_keeps_plain_and_technical_sections(self):

        report = self._report()
        text = diagnostic_report.build_markdown(
            report,
            "capture.csv",
            target_name="game.exe",
        )

        self.assertIn("What we found", text)
        self.assertIn("Why this appears", text)
        self.assertIn("How certain", text)
        self.assertIn(
            "not a confirmed cause",
            text,
        )
        self.assertIn("What you can do next", text)
        self.assertIn("Technical details", text)
        self.assertIn("Median CPUBusy", text)
        self.assertIn("Claim", text)
        self.assertIn("Confidence", text)

    def test_markdown_report_explains_missing_telemetry(self):

        report = self._report()
        text = diagnostic_report.build_markdown(
            report,
            "capture.csv",
        )

        self.assertIn("Data limitation", text)
        self.assertIn(
            "No telemetry sidecar was found",
            text,
        )

    def test_json_report_has_structured_events_and_no_paths(self):

        report = self._report()
        text = diagnostic_report.build_json(
            report,
            r"D:\Users\alice\capture.csv",
            target_name=r"D:\Games\game.exe",
        )
        payload = json.loads(text)

        self.assertEqual(
            payload["capture"]["file"],
            "capture.csv",
        )
        self.assertEqual(
            payload["capture"]["target"],
            "game.exe",
        )
        self.assertTrue(payload["report"]["events"])
        findings_with_evidence = [
            finding
            for finding in payload["report"]["findings"]
            if finding["evidence"]
        ]

        self.assertTrue(findings_with_evidence)
        finding = findings_with_evidence[0]

        self.assertIn("claim_level", finding)
        self.assertIn("caveats", finding)
        self.assertNotIn("Users", text)
        self.assertNotIn("alice", text)

    def test_write_report_uses_extension(self):

        report = self._report()

        with tempfile.TemporaryDirectory() as folder:

            markdown = Path(folder) / "report.md"
            json_path = Path(folder) / "report.json"

            diagnostic_report.write_report(
                report,
                markdown,
                "capture.csv",
                target_name="game.exe",
            )
            diagnostic_report.write_report(
                report,
                json_path,
                "capture.csv",
                target_name="game.exe",
            )

            self.assertIn(
                "# ",
                markdown.read_text(encoding="utf-8"),
            )
            self.assertIn(
                "schema_version",
                json_path.read_text(encoding="utf-8"),
            )

    def test_default_engine_never_confirms_control_claims(self):

        report = diagnostics.analyze(
            make_series(events=CPU_EVENTS),
            target_fps=60,
            control_experiments=[make_control()],
        )

        self.assertFalse(
            any(
                finding.claim_level == "confirmed_by_control"
                for finding in report.findings
            )
        )
        self.assertTrue(report.control_rejections)


class ComputeStatsCompatibilityTests(unittest.TestCase):

    def test_diagnostics_accepts_existing_frame_stats(self):

        frames = make_series(events=CPU_EVENTS)
        stats = compute_stats(frames)

        report = diagnostics.analyze(
            frames,
            stats=stats,
            target_fps=60,
        )

        self.assertEqual(
            report.frame_count,
            stats.frame_count,
        )
        self.assertAlmostEqual(
            report.duration_s,
            stats.duration_s,
        )


if __name__ == "__main__":

    unittest.main()
