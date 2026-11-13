"""C-2.0 frame timebase detection and normalization tests."""

import json
import tempfile
import unittest

from pathlib import Path

import frame_timebase
import telemetry


LEGACY_HEADER = (
    "Application",
    "ProcessID",
    "SwapChainAddress",
    "CPUStartTime",
    "FrameTime",
)

QPC_HEADER = (
    "Application",
    "ProcessID",
    "SwapChainAddress",
    "CPUStartQPCTime",
    "FrameTime",
)


class TimebaseDetectionTests(unittest.TestCase):

    def test_legacy_column_is_capture_relative(self):

        timebase = frame_timebase.resolve_timebase(
            LEGACY_HEADER
        )

        self.assertEqual(timebase.kind, "relative")
        self.assertEqual(
            timebase.raw_column,
            frame_timebase.LEGACY_TIME_COLUMN,
        )
        self.assertEqual(
            timebase.sync_quality,
            "exact_relative",
        )
        self.assertEqual(
            timebase.applicability,
            "capture_relative",
        )
        self.assertFalse(
            timebase.absolute_mapping_trusted
        )
        self.assertEqual(timebase.normalize(1234.5), 1234.5)

    def test_prefers_legacy_when_both_columns_exist(self):

        timebase = frame_timebase.resolve_timebase(
            LEGACY_HEADER + ("CPUStartQPCTime",)
        )

        self.assertEqual(timebase.kind, "relative")
        self.assertEqual(
            timebase.raw_column,
            "CPUStartTime",
        )

    def test_missing_time_column_is_untrusted(self):

        timebase = frame_timebase.resolve_timebase(
            ("Application", "ProcessID", "FrameTime")
        )

        self.assertEqual(timebase.kind, "unknown")
        self.assertEqual(
            timebase.sync_quality,
            "untrusted",
        )
        self.assertEqual(timebase.applicability, "none")
        self.assertFalse(
            timebase.absolute_mapping_trusted
        )

        with self.assertRaises(ValueError):
            timebase.normalize(1.0)


class QpcTimebaseTests(unittest.TestCase):

    def test_qpc_capture_start_origin_is_subtracted(self):

        timebase = frame_timebase.qpc_timebase_for_capture(
            capture_started_monotonic_ns=10_000_000_000,
            qpc_clock_delta_ms_value=0.008,
            qpc_frequency_hz_value=10_000_000,
        )

        self.assertEqual(timebase.kind, "qpc_ms")
        self.assertEqual(
            timebase.origin_kind,
            "capture_start",
        )
        self.assertAlmostEqual(
            timebase.origin_qpc_ms,
            10_000.0,
        )
        self.assertEqual(
            timebase.sync_quality,
            "verified_qpc",
        )
        self.assertTrue(
            timebase.absolute_mapping_trusted
        )
        self.assertEqual(
            timebase.applicability,
            "absolute_frame_time",
        )
        self.assertAlmostEqual(
            timebase.normalize(10_016.7),
            16.7,
        )

    def test_qpc_clock_mismatch_is_not_absolute_trusted(self):

        timebase = frame_timebase.qpc_timebase_for_capture(
            capture_started_monotonic_ns=10_000_000_000,
            qpc_clock_delta_ms_value=10.0,
        )

        self.assertEqual(
            timebase.sync_quality,
            "unverified_qpc",
        )
        self.assertFalse(
            timebase.absolute_mapping_trusted
        )
        self.assertEqual(
            timebase.applicability,
            "frame_relative_only",
        )

    def test_missing_qpc_clock_measurement_is_not_absolute_trusted(self):

        timebase = frame_timebase.qpc_timebase_for_capture(
            capture_started_monotonic_ns=10_000_000_000,
            qpc_clock_delta_ms_value=None,
        )

        self.assertEqual(
            timebase.sync_quality,
            "unverified_qpc",
        )
        self.assertFalse(
            timebase.absolute_mapping_trusted
        )
        self.assertEqual(
            timebase.applicability,
            "frame_relative_only",
        )

    def test_qpc_without_capture_start_needs_a_first_frame_origin(self):

        timebase = frame_timebase.qpc_timebase_for_capture(
            capture_started_monotonic_ns=None,
        )

        self.assertEqual(
            timebase.origin_kind,
            "first_frame",
        )
        self.assertEqual(
            timebase.sync_quality,
            "inferred_qpc",
        )
        self.assertFalse(
            timebase.absolute_mapping_trusted
        )

        with self.assertRaises(ValueError):
            timebase.normalize(10_016.7)

        timebase = timebase.with_origin(
            10_000.0,
            "first_frame",
            "inferred_qpc",
        )

        self.assertAlmostEqual(
            timebase.normalize(10_016.7),
            16.7,
        )
        self.assertFalse(
            timebase.absolute_mapping_trusted
        )

    def test_with_range_preserves_raw_and_normalized_values(self):

        timebase = frame_timebase.qpc_timebase_for_capture(
            10_000_000_000,
            qpc_clock_delta_ms_value=0.008,
        ).with_range(10_016.7, 10_033.4)

        self.assertAlmostEqual(
            timebase.raw_first_time_ms,
            10_016.7,
        )
        self.assertAlmostEqual(
            timebase.raw_last_time_ms,
            10_033.4,
        )
        self.assertAlmostEqual(
            timebase.normalized_first_ms,
            16.7,
        )
        self.assertAlmostEqual(
            timebase.normalized_last_ms,
            33.4,
        )

        restored = frame_timebase.FrameTimebase.from_dict(
            timebase.to_dict()
        )

        self.assertEqual(restored.kind, "qpc_ms")
        self.assertAlmostEqual(
            restored.origin_qpc_ms,
            10_000.0,
        )
        self.assertTrue(
            restored.absolute_mapping_trusted
        )


class SidecarTimebaseTests(unittest.TestCase):

    def _write_sidecar(self, csv_path, started_ns, frame_info):

        path = telemetry.telemetry_path(csv_path)
        records = [
            {
                "type": "metadata",
                "schema_version": 1,
                "capture": {
                    "csv_name": csv_path.name,
                    "started_monotonic_ns": started_ns,
                },
            },
            {
                "type": "timebase",
                "frame_timebase": frame_info,
            },
            {
                "type": "end",
                "reason": "finished",
            },
        ]
        path.write_text(
            "".join(
                json.dumps(record) + "\n"
                for record in records
            ),
            encoding="utf-8",
        )
        return path

    def test_sidecar_origin_is_used_for_historical_qpc(self):

        with tempfile.TemporaryDirectory() as folder:

            csv_path = Path(folder) / "capture.csv"
            self._write_sidecar(
                csv_path,
                10_000_000_000,
                {
                    "kind": "qpc_ms",
                    "raw_column": "CPUStartQPCTime",
                    "origin_kind": "capture_start",
                    "origin_qpc_ms": 10_000.0,
                    "capture_started_monotonic_ns": 10_000_000_000,
                    "sync_quality": "verified_qpc",
                },
            )

            timebase = frame_timebase.resolve_timebase(
                QPC_HEADER,
                csv_path=csv_path,
            )

            self.assertEqual(timebase.kind, "qpc_ms")
            self.assertEqual(
                timebase.origin_kind,
                "capture_start",
            )
            self.assertEqual(
                timebase.sync_quality,
                "verified_qpc",
            )
            self.assertTrue(
                timebase.absolute_mapping_trusted
            )
            self.assertAlmostEqual(
                timebase.normalize(10_016.7),
                16.7,
            )

    def test_corrupt_sidecar_falls_back_to_first_frame(self):

        with tempfile.TemporaryDirectory() as folder:

            csv_path = Path(folder) / "capture.csv"
            telemetry.telemetry_path(csv_path).write_text(
                "{broken\n",
                encoding="utf-8",
            )

            timebase = frame_timebase.resolve_timebase(
                QPC_HEADER,
                csv_path=csv_path,
            )

            self.assertEqual(
                timebase.origin_kind,
                "first_frame",
            )
            self.assertEqual(
                timebase.sync_quality,
                "inferred_qpc",
            )
            self.assertFalse(
                timebase.absolute_mapping_trusted
            )

    def test_sidecar_with_wrong_capture_shape_is_ignored(self):

        with tempfile.TemporaryDirectory() as folder:

            csv_path = Path(folder) / "capture.csv"
            telemetry.telemetry_path(csv_path).write_text(
                json.dumps(
                    {
                        "type": "metadata",
                        "capture": "not-a-dict",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            timebase = frame_timebase.resolve_timebase(
                QPC_HEADER,
                csv_path=csv_path,
            )

            self.assertEqual(
                timebase.origin_kind,
                "first_frame",
            )
            self.assertFalse(
                timebase.absolute_mapping_trusted
            )


if __name__ == "__main__":

    unittest.main()
