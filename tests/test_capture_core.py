import os
import tempfile
import threading
import time
import unittest

from datetime import datetime
from pathlib import Path
from unittest import mock

import capture_core


HEADER = (
    "Application,ProcessID,SwapChainAddress,"
    "CPUStartTime,FrameTime,DisplayedTime\n"
)

QPC_HEADER = (
    "Application,ProcessID,SwapChainAddress,"
    "CPUStartQPCTime,FrameTime,DisplayedTime\n"
)


def data_row(
    application="game.exe",
    pid="100",
    swap_chain="0x1",
    start="1.0",
    frame_time="16.7",
    displayed="16.0",
):
    return (
        f"{application},{pid},{swap_chain},"
        f"{start},{frame_time},{displayed}\n"
    )


class BuildCommandTests(unittest.TestCase):

    def test_capture_uses_stdout_for_live_data(self):

        # --output_file is exclusively locked by PresentMon while
        # recording, so live data must come from stdout.
        command = capture_core.build_capture_command(
            "PresentMon.exe",
            "LagLensTest",
            "game.exe",
        )

        self.assertIn("--output_stdout", command)
        self.assertNotIn("--output_file", command)
        self.assertIn("--no_track_input", command)
        self.assertNotIn("--no_track_gpu", command)
        self.assertEqual(
            command[command.index("--process_name") + 1],
            "game.exe",
        )

    def test_terminate_on_proc_exit_is_not_used(self):
        """Regression note: PresentMon 2.6 accepts this flag but a
        controlled test showed it does not terminate the capture when
        the target exits.  LagLens polls the process instead."""

        command = capture_core.build_capture_command(
            "PresentMon.exe",
            "LagLensTest",
            "game.exe",
        )

        self.assertNotIn(
            "--terminate_on_proc_exit",
            command,
        )

    def test_hyphenated_target_is_kept_verbatim(self):
        """Regression: Palworld-Win64-Shipping.exe must not be altered."""

        target = "Palworld-Win64-Shipping.exe"

        self.assertEqual(
            capture_core.normalize_target(target),
            target,
        )

        command = capture_core.build_capture_command(
            "PresentMon.exe",
            "LagLensTest",
            target,
        )

        self.assertEqual(
            command[command.index("--process_name") + 1],
            target,
        )

    def test_low_overhead_disables_gpu_tracking(self):

        command = capture_core.build_capture_command(
            "PresentMon.exe",
            "LagLensTest",
            "game.exe",
            low_overhead=True,
        )

        self.assertIn("--no_track_gpu", command)

    def test_qpc_time_flag_is_opt_in(self):

        legacy = capture_core.build_capture_command(
            "PresentMon.exe",
            "LagLensTest",
            "game.exe",
        )
        qpc = capture_core.build_capture_command(
            "PresentMon.exe",
            "LagLensTest",
            "game.exe",
            qpc_time=True,
        )

        self.assertNotIn("--qpc_time_ms", legacy)
        self.assertIn("--qpc_time_ms", qpc)
        self.assertNotIn("--qpc_time", qpc)
        self.assertIn("--output_stdout", qpc)

        combined = capture_core.build_capture_command(
            "PresentMon.exe",
            "LagLensTest",
            "game.exe",
            low_overhead=True,
            qpc_time=True,
        )

        self.assertIn("--no_track_gpu", combined)
        self.assertIn("--qpc_time_ms", combined)

    def test_terminate_command_targets_the_same_session(self):

        command = capture_core.build_terminate_command(
            "PresentMon.exe",
            "LagLensTest",
        )

        self.assertIn("--terminate_existing_session", command)
        self.assertEqual(
            command[command.index("--session_name") + 1],
            "LagLensTest",
        )

    def test_target_is_reduced_to_a_process_name(self):

        self.assertEqual(
            capture_core.normalize_target(
                '"C:\\Games\\Game.exe"'
            ),
            "Game.exe",
        )

    def test_safe_capture_name(self):

        name = capture_core.safe_capture_name(
            "my game?.exe",
            now=datetime(2026, 11, 11, 12, 30, 15, 123456),
        )

        self.assertEqual(
            name,
            "my_game_.exe_20261111_123015_123456.csv",
        )


class LogTests(unittest.TestCase):

    def test_reads_utf16le_with_bom(self):

        with tempfile.TemporaryDirectory() as folder:

            path = Path(folder) / "capture.log"

            text = "error: failed to start trace session: access denied."

            path.write_bytes(
                b"\xff\xfe" + text.encode("utf-16-le")
            )

            self.assertEqual(
                capture_core.read_capture_log(path),
                text,
            )

    def test_reads_utf8_bom_and_plain_utf8(self):

        with tempfile.TemporaryDirectory() as folder:

            path = Path(folder) / "capture.log"

            path.write_bytes(
                b"\xef\xbb\xbfwarning: 1 ETW events were lost.\n"
            )

            self.assertIn(
                "ETW events were lost",
                capture_core.read_capture_log(path),
            )

            path.write_text(
                "plain text",
                encoding="utf-8",
            )

            self.assertEqual(
                capture_core.read_capture_log(path),
                "plain text",
            )

    def test_etw_warnings_parses_commas_and_overflow(self):

        warnings = capture_core.etw_warnings(
            "warning: 80,794 ETW events were lost.\n"
            "warning: 12 overflowed present events.\n"
        )

        self.assertEqual(
            warnings,
            [
                "80,794 ETW events were lost",
                "12 present events overflowed",
            ],
        )

    def test_no_warnings(self):

        self.assertEqual(
            capture_core.etw_warnings("Started recording."),
            [],
        )

    def test_failure_messages_are_actionable(self):

        access = capture_core.describe_failure(
            "error: failed to start trace session: access denied.",
            1,
        )

        self.assertIn("administrator", access.lower())

        busy = capture_core.describe_failure(
            'a trace session named "PresentMon" is already running.',
            6,
        )

        self.assertIn("still in use", busy)

        missing = capture_core.describe_failure(
            "",
            0,
            capture_core.CaptureInfo(
                path=Path("missing.csv"),
                exists=False,
                has_header=False,
                error="CSV was not created",
            ),
            "game.exe",
        )

        self.assertIn("did not create the CSV", missing)
        self.assertIn("game.exe", missing)

    def test_summarize_log_prefers_the_last_error(self):

        text = (
            "warning: first problem\n"
            "error: real problem\n"
            "warning: noise\n"
        )

        self.assertEqual(
            capture_core.summarize_log(text),
            "error: real problem",
        )


class ValidateCaptureTests(unittest.TestCase):

    def test_valid_capture(self):

        with tempfile.TemporaryDirectory() as folder:

            path = Path(folder) / "valid.csv"

            path.write_text(
                HEADER
                + data_row()
                + data_row(start="2.0"),
                encoding="utf-8",
            )

            info = capture_core.validate_capture(path)

            self.assertTrue(info.ok)
            self.assertTrue(info.has_header)
            self.assertEqual(info.rows, 2)
            self.assertEqual(info.valid_frames, 2)
            self.assertEqual(
                info.time_column,
                "CPUStartTime",
            )
            self.assertEqual(info.error, "")

    def test_qpc_capture_is_valid_and_keeps_its_time_column(self):

        with tempfile.TemporaryDirectory() as folder:

            path = Path(folder) / "qpc.csv"

            path.write_text(
                QPC_HEADER
                + data_row(start="12405066.0427")
                + data_row(start="12405082.7"),
                encoding="utf-8",
            )

            info = capture_core.validate_capture(path)

            self.assertTrue(info.ok)
            self.assertEqual(info.rows, 2)
            self.assertEqual(info.valid_frames, 2)
            self.assertEqual(
                info.time_column,
                "CPUStartQPCTime",
            )

    def test_missing_time_column_is_reported_with_base_columns(self):

        with tempfile.TemporaryDirectory() as folder:

            path = Path(folder) / "no_time.csv"
            path.write_text(
                "Application,ProcessID,SwapChainAddress,"
                "FrameTime,DisplayedTime\n"
                "game.exe,100,0x1,16.7,16.0\n",
                encoding="utf-8",
            )

            info = capture_core.validate_capture(path)

            self.assertFalse(info.ok)
            self.assertIn("CPUStartTime", info.error)
            self.assertIn("CPUStartQPCTime", info.error)

    def test_utf8_bom_is_accepted(self):

        with tempfile.TemporaryDirectory() as folder:

            path = Path(folder) / "bom.csv"

            path.write_text(
                HEADER + data_row(),
                encoding="utf-8-sig",
            )

            info = capture_core.validate_capture(path)

            self.assertTrue(info.ok)
            self.assertEqual(info.valid_frames, 1)

    def test_missing_file_is_not_success(self):

        with tempfile.TemporaryDirectory() as folder:

            info = capture_core.validate_capture(
                Path(folder) / "missing.csv"
            )

            self.assertFalse(info.ok)
            self.assertFalse(info.exists)
            self.assertIn("not created", info.error)

    def test_empty_file_is_not_success(self):

        with tempfile.TemporaryDirectory() as folder:

            path = Path(folder) / "empty.csv"
            path.write_bytes(b"")

            info = capture_core.validate_capture(path)

            self.assertFalse(info.ok)
            self.assertIn("empty", info.error)

    def test_header_only_file_is_not_success(self):

        with tempfile.TemporaryDirectory() as folder:

            path = Path(folder) / "header.csv"
            path.write_text(HEADER, encoding="utf-8")

            info = capture_core.validate_capture(path)

            self.assertFalse(info.ok)
            self.assertEqual(info.rows, 0)
            self.assertIn("no frame rows", info.error)

    def test_missing_columns_are_reported(self):

        with tempfile.TemporaryDirectory() as folder:

            path = Path(folder) / "wrong.csv"

            path.write_text(
                "Application,FrameTime\n"
                "game.exe,16.7\n",
                encoding="utf-8",
            )

            info = capture_core.validate_capture(path)

            self.assertFalse(info.ok)
            self.assertIn(
                "CPUStartTime",
                info.error,
            )

    def test_invalid_frame_values_are_not_success(self):

        with tempfile.TemporaryDirectory() as folder:

            path = Path(folder) / "bad.csv"

            path.write_text(
                HEADER
                + data_row(frame_time="not-a-number")
                + data_row(frame_time="-1")
                + data_row(start="NA"),
                encoding="utf-8",
            )

            info = capture_core.validate_capture(path)

            self.assertFalse(info.ok)
            self.assertEqual(info.rows, 3)
            self.assertEqual(info.valid_frames, 0)
            self.assertIn("no valid", info.error)


class StaleSessionCleanupTests(unittest.TestCase):
    """P2-5 phase 1: only LagLens' own session may be cleaned up."""

    def test_cleanup_targets_only_the_laglens_session(self):

        result = mock.Mock()
        result.returncode = 7

        with mock.patch.object(
            capture_core.subprocess,
            "run",
            return_value=result,
        ) as run:

            code = capture_core.cleanup_stale_session(
                "PresentMon.exe",
                timeout=1,
            )

        self.assertEqual(code, 7)

        command = run.call_args.args[0]

        self.assertIn(
            "--terminate_existing_session",
            command,
        )
        self.assertEqual(
            command[command.index("--session_name") + 1],
            capture_core.SESSION,
        )
        self.assertEqual(
            capture_core.SESSION,
            "LagLensCapture",
        )
        self.assertNotEqual(
            capture_core.SESSION.lower(),
            "presentmon",
        )

    def test_cleanup_tolerates_missing_session_and_errors(self):

        result = mock.Mock()
        result.returncode = 7

        with mock.patch.object(
            capture_core.subprocess,
            "run",
            return_value=result,
        ):

            self.assertEqual(
                capture_core.cleanup_stale_session(
                    "PresentMon.exe",
                    timeout=1,
                ),
                7,
            )

        with mock.patch.object(
            capture_core.subprocess,
            "run",
            side_effect=OSError("missing"),
        ):

            self.assertIsNone(
                capture_core.cleanup_stale_session(
                    "PresentMon.exe",
                    timeout=1,
                )
            )

        with mock.patch.object(
            capture_core.subprocess,
            "run",
            side_effect=capture_core.subprocess.TimeoutExpired(
                "PresentMon.exe", 1
            ),
        ):

            self.assertIsNone(
                capture_core.cleanup_stale_session(
                    "PresentMon.exe",
                    timeout=1,
                )
            )

    def test_background_cleanup_returns_a_thread(self):

        result = mock.Mock()
        result.returncode = 7

        with mock.patch.object(
            capture_core.subprocess,
            "run",
            return_value=result,
        ) as run:

            thread = capture_core.start_stale_session_cleanup(
                "PresentMon.exe",
                timeout=1,
            )

            self.assertIsInstance(
                thread,
                threading.Thread,
            )

            thread.join(3)

        self.assertTrue(run.called)


class FailureCodeTests(unittest.TestCase):

    def test_access_denied(self):

        self.assertEqual(
            capture_core.failure_code(
                "error: failed to start trace session: access denied.",
                6,
            ),
            "access_denied",
        )

    def test_session_busy(self):

        self.assertEqual(
            capture_core.failure_code(
                'error: a trace session named "PresentMon" is already running.',
                6,
            ),
            "session_busy",
        )

    def test_bad_command(self):

        self.assertEqual(
            capture_core.failure_code(
                "error: unrecognized option '--nope'.",
                1,
            ),
            "bad_command",
        )

    def test_trace_start_failure(self):

        self.assertEqual(
            capture_core.failure_code(
                "error: failed to start trace session: file not found.",
                6,
            ),
            "trace_failed",
        )

    def test_csv_states(self):

        missing = capture_core.CaptureInfo(
            path=Path("missing.csv"),
            exists=False,
            has_header=False,
            error="CSV was not created",
        )

        self.assertEqual(
            capture_core.failure_code("", 0, missing),
            "csv_missing",
        )

        header_only = capture_core.CaptureInfo(
            path=Path("header.csv"),
            exists=True,
            has_header=True,
            rows=0,
            error="CSV contains a header but no frame rows",
        )

        self.assertEqual(
            capture_core.failure_code("", 0, header_only),
            "no_frames",
        )

        unusable = capture_core.CaptureInfo(
            path=Path("bad.csv"),
            exists=True,
            has_header=True,
            rows=2,
            error="CSV contains no valid FrameTime rows",
        )

        self.assertEqual(
            capture_core.failure_code("", 0, unusable),
            "csv_unusable",
        )

    def test_header_only_is_no_frames(self):

        with tempfile.TemporaryDirectory() as folder:

            path = Path(folder) / "empty_capture.csv"
            path.write_text(
                "Application,ProcessID,SwapChainAddress,"
                "CPUStartTime,FrameTime\n",
                encoding="utf-8",
            )

            info = capture_core.validate_capture(path)

            self.assertEqual(info.rows, 0)
            self.assertEqual(
                capture_core.failure_code("", 0, info),
                "no_frames",
            )

    def test_empty_file_is_unusable_not_no_frames(self):

        with tempfile.TemporaryDirectory() as folder:

            path = Path(folder) / "empty.csv"
            path.write_bytes(b"")

            info = capture_core.validate_capture(path)

            self.assertEqual(
                capture_core.failure_code("", 0, info),
                "csv_unusable",
            )

    def test_missing_columns_is_unusable_not_no_frames(self):

        with tempfile.TemporaryDirectory() as folder:

            path = Path(folder) / "columns.csv"
            path.write_text(
                "Application,FrameTime\n"
                "game.exe,16.7\n",
                encoding="utf-8",
            )

            info = capture_core.validate_capture(path)

            self.assertEqual(
                capture_core.failure_code("", 0, info),
                "csv_unusable",
            )

    def test_parse_error_is_unusable_not_no_frames(self):

        with tempfile.TemporaryDirectory() as folder:

            path = Path(folder) / "corrupt.csv"

            # A field above csv.field_size_limit() makes
            # csv.reader raise csv.Error before a data row is counted.
            path.write_text(
                "Application,ProcessID,SwapChainAddress,"
                "CPUStartTime,FrameTime\n"
                + ("x" * 200000)
                + "\n",
                encoding="utf-8",
            )

            info = capture_core.validate_capture(path)

            self.assertEqual(info.rows, 0)
            self.assertIn(
                "could not be parsed",
                info.error,
            )
            self.assertEqual(
                capture_core.failure_code("", 0, info),
                "csv_unusable",
            )

    def test_unreadable_file_is_unusable_not_missing(self):

        info = capture_core.CaptureInfo(
            path=Path("locked.csv"),
            exists=False,
            has_header=False,
            error=(
                "CSV could not be read: "
                "[Errno 13] Permission denied"
            ),
        )

        self.assertEqual(
            capture_core.failure_code("", 0, info),
            "csv_unusable",
        )

    def test_no_valid_frames_is_unusable(self):

        with tempfile.TemporaryDirectory() as folder:

            path = Path(folder) / "invalid.csv"
            path.write_text(
                "Application,ProcessID,SwapChainAddress,"
                "CPUStartTime,FrameTime\n"
                "game.exe,1,0x1,1000,NA\n",
                encoding="utf-8",
            )

            info = capture_core.validate_capture(path)

            self.assertGreater(info.rows, 0)
            self.assertEqual(
                capture_core.failure_code("", 0, info),
                "csv_unusable",
            )

    def test_no_data_and_unknown(self):

        self.assertEqual(
            capture_core.failure_code("", 0),
            "no_data",
        )
        self.assertEqual(
            capture_core.failure_code("", 42),
            "unknown",
        )


class CaptureIntegrityTests(unittest.TestCase):
    """P2-1: CSV structure and data quality must be distinguishable."""

    def _write(self, folder, text, name="capture.csv"):

        path = Path(folder) / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_truncated_tail_is_flagged_but_keeps_valid_frames(self):

        with tempfile.TemporaryDirectory() as folder:

            # Last line is cut mid-row and has no trailing newline.
            path = self._write(
                folder,
                HEADER
                + data_row(start="1.0")
                + data_row(start="2.0")
                + "game.exe,100,0x1,3.0,16.7",
            )

            info = capture_core.validate_capture(path)

            self.assertTrue(info.ok)
            self.assertEqual(info.valid_frames, 2)
            self.assertEqual(info.rows, 3)
            self.assertTrue(info.trailing_partial)
            self.assertEqual(info.bad_field_rows, 0)
            self.assertFalse(info.complete)
            self.assertEqual(info.invalid_rows, 1)
            self.assertTrue(
                any(
                    "truncated" in warning.lower()
                    for warning in info.warnings
                )
            )

    def test_mid_file_short_row_is_a_structural_defect(self):

        with tempfile.TemporaryDirectory() as folder:

            path = self._write(
                folder,
                HEADER
                + data_row(start="1.0")
                + "game.exe,100,0x1\n"
                + data_row(start="3.0"),
            )

            info = capture_core.validate_capture(path)

            self.assertTrue(info.ok)
            self.assertEqual(info.valid_frames, 2)
            self.assertEqual(info.rows, 3)
            self.assertEqual(info.bad_field_rows, 1)
            self.assertFalse(info.trailing_partial)
            self.assertEqual(info.invalid_rows, 1)

    def test_na_frame_values_are_counted_separately(self):

        with tempfile.TemporaryDirectory() as folder:

            path = self._write(
                folder,
                HEADER
                + data_row(frame_time="NA")
                + data_row(start="NA")
                + data_row(start="3.0"),
            )

            info = capture_core.validate_capture(path)

            self.assertEqual(info.valid_frames, 1)
            self.assertEqual(info.na_rows, 2)
            self.assertEqual(info.nonnumeric_rows, 0)
            self.assertEqual(info.invalid_rows, 2)
            self.assertEqual(info.reason_counts["na"], 2)

    def test_non_numeric_values_are_counted(self):

        with tempfile.TemporaryDirectory() as folder:

            path = self._write(
                folder,
                HEADER
                + data_row(frame_time="not-a-number")
                + data_row(start="3.0"),
            )

            info = capture_core.validate_capture(path)

            self.assertEqual(info.valid_frames, 1)
            self.assertEqual(info.nonnumeric_rows, 1)
            self.assertEqual(info.reason_counts["non_numeric"], 1)

    def test_non_positive_frame_times_are_rejected(self):

        with tempfile.TemporaryDirectory() as folder:

            path = self._write(
                folder,
                HEADER
                + data_row(frame_time="0")
                + data_row(frame_time="-5")
                + data_row(start="3.0"),
            )

            info = capture_core.validate_capture(path)

            self.assertEqual(info.valid_frames, 1)
            self.assertEqual(info.nonpositive_rows, 2)
            self.assertEqual(info.reason_counts["non_positive"], 2)

    def test_non_finite_values_are_rejected(self):

        with tempfile.TemporaryDirectory() as folder:

            path = self._write(
                folder,
                HEADER
                + data_row(frame_time="nan")
                + data_row(frame_time="inf")
                + data_row(start="3.0"),
            )

            info = capture_core.validate_capture(path)

            self.assertEqual(info.valid_frames, 1)
            self.assertEqual(info.nonfinite_rows, 2)
            self.assertEqual(info.reason_counts["non_finite"], 2)

    def test_long_frames_stay_valid_but_are_reported(self):

        with tempfile.TemporaryDirectory() as folder:

            path = self._write(
                folder,
                HEADER
                + data_row(frame_time="3021.9")
                + data_row(start="3.0"),
            )

            info = capture_core.validate_capture(path)

            self.assertEqual(info.valid_frames, 2)
            self.assertEqual(info.long_frames, 1)
            self.assertAlmostEqual(info.max_frame_ms, 3021.9)
            # A long frame is data, not a structural error.
            self.assertTrue(info.complete)

    def test_blank_lines_are_ignored(self):

        with tempfile.TemporaryDirectory() as folder:

            path = self._write(
                folder,
                HEADER
                + "\n"
                + data_row(start="1.0")
                + "\n"
                + data_row(start="2.0")
                + "\n\n",
            )

            info = capture_core.validate_capture(path)

            self.assertEqual(info.rows, 2)
            self.assertEqual(info.valid_frames, 2)
            self.assertEqual(info.invalid_rows, 0)

    def test_quality_report_separates_structural_from_etw(self):

        with tempfile.TemporaryDirectory() as folder:

            path = self._write(
                folder,
                HEADER
                + data_row(start="1.0")
                + "game.exe,100,0x1",
            )

            info = capture_core.validate_capture(path)

            quality = capture_core.capture_quality(
                info,
                "warning: 80,794 ETW events were lost.\n",
            )

            self.assertTrue(quality.structural)
            self.assertTrue(quality.etw)
            self.assertFalse(quality.clean)
            self.assertFalse(
                any(
                    "ETW" in item
                    for item in quality.structural
                )
            )
            self.assertIn("80,794", quality.etw[0])
            self.assertIn("truncated", quality.structural[0].lower())

    def test_clean_capture_has_empty_quality_report(self):

        with tempfile.TemporaryDirectory() as folder:

            path = self._write(
                folder,
                HEADER + data_row(),
            )

            info = capture_core.validate_capture(path)

            quality = capture_core.capture_quality(info, "")

            self.assertTrue(quality.complete)
            self.assertTrue(quality.clean)
            self.assertEqual(quality.structural, ())
            self.assertEqual(quality.data, ())
            self.assertEqual(quality.etw, ())

    def test_missing_columns_are_structural(self):

        with tempfile.TemporaryDirectory() as folder:

            path = self._write(
                folder,
                "Application,FrameTime\n"
                "game.exe,16.7\n",
            )

            info = capture_core.validate_capture(path)

            quality = capture_core.capture_quality(info, "")

            self.assertFalse(quality.complete)
            self.assertTrue(quality.structural)


class CsvTailerTests(unittest.TestCase):

    def test_follows_appended_rows_and_keeps_partial_lines(self):

        with tempfile.TemporaryDirectory() as folder:

            path = Path(folder) / "live.csv"

            path.write_text(
                HEADER + data_row(),
                encoding="utf-8",
            )

            tailer = capture_core.CsvTailer(path)

            first = tailer.poll()
            self.assertEqual(len(first), 1)
            self.assertEqual(first[0]["FrameTime"], "16.7")
            self.assertIsNotNone(tailer.headers)

            second_line = data_row(start="2.0")

            with path.open("a", encoding="utf-8") as file:
                file.write(second_line[:12])

            self.assertEqual(tailer.poll(), [])

            with path.open("a", encoding="utf-8") as file:
                file.write(second_line[12:])

            second = tailer.poll()
            self.assertEqual(len(second), 1)
            self.assertEqual(second[0]["CPUStartTime"], "2.0")

            third_line = data_row(start="3.0").rstrip("\n")

            with path.open("a", encoding="utf-8") as file:
                file.write(third_line)

            # The final line has no newline yet.
            self.assertEqual(tailer.poll(), [])
            self.assertEqual(
                len(tailer.poll(final=True)),
                1,
            )

            self.assertEqual(tailer.rows_seen, 3)
            self.assertEqual(tailer.valid_frames, 3)
            self.assertEqual(
                tailer.time_column,
                "CPUStartTime",
            )

    def test_qpc_rows_are_tailed_without_rewriting_the_header(self):

        with tempfile.TemporaryDirectory() as folder:

            path = Path(folder) / "qpc.csv"
            path.write_text(
                QPC_HEADER
                + data_row(start="12405066.0427")
                + data_row(start="12405082.7"),
                encoding="utf-8",
            )

            tailer = capture_core.CsvTailer(path)
            rows = tailer.poll()

            self.assertEqual(len(rows), 2)
            self.assertEqual(
                rows[0]["CPUStartQPCTime"],
                "12405066.0427",
            )
            self.assertEqual(
                tailer.time_column,
                "CPUStartQPCTime",
            )
            self.assertEqual(tailer.valid_frames, 2)

    def test_header_only_file(self):

        with tempfile.TemporaryDirectory() as folder:

            path = Path(folder) / "header.csv"
            path.write_text(HEADER, encoding="utf-8")

            tailer = capture_core.CsvTailer(path)

            self.assertEqual(tailer.poll(), [])
            self.assertIsNotNone(tailer.headers)

    def test_missing_file_is_tolerated(self):

        with tempfile.TemporaryDirectory() as folder:

            tailer = capture_core.CsvTailer(
                Path(folder) / "not-yet.csv"
            )

            self.assertEqual(tailer.poll(), [])


class CaptureResultTests(unittest.TestCase):

    def test_result_requires_valid_frames(self):

        result = capture_core.CaptureResult(
            csv_path="out.csv",
            log_path="out.log",
            valid_frames=10,
        )

        self.assertTrue(result.ok)

        result.valid_frames = 0
        self.assertFalse(result.ok)

        result.valid_frames = 10
        result.error = "boom"
        self.assertFalse(result.ok)


if __name__ == "__main__":
    unittest.main()
