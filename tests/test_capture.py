"""Integration tests for the capture worker and the Live Frames tab.

``test_capture_core`` covers the pure helpers (command line, log decoding,
CSV validation, tailer).  This file covers the parts that need Qt:

* CaptureWorker.run() driving a (fake) PresentMon process that writes the
  CSV itself through --output_file
* the start/stop lifecycle, including stop-before-start
* LagLens.on_capture_completed() turning a CaptureResult into UI state

No ETW session and no Administrator rights are required.

Run with:
    .venv\\Scripts\\python.exe -m unittest discover -s tests -v
"""

import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Keep the GUI tests headless.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt, Signal  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QScrollArea,
    QWidget,
)

import capture_core  # noqa: E402
import i18n  # noqa: E402
import main as laglens  # noqa: E402
import process_catalog  # noqa: E402
import settings as app_settings  # noqa: E402
from frame_viewer import load_frames  # noqa: E402


HEADER = (
    "Application,ProcessID,SwapChainAddress,PresentRuntime,"
    "SyncInterval,PresentFlags,AllowsTearing,PresentMode,"
    "CPUStartTime,FrameTime,CPUBusy,CPUWait,GPULatency,GPUTime,"
    "GPUBusy,GPUWait,DisplayLatency,DisplayedTime,AnimationError,"
    "AnimationTime,MsFlipDelay,AllInputToPhotonLatency,"
    "ClickToPhotonLatency"
)

ROW = (
    "douyin.exe,16548,0x28C709CF000,DXGI,1,256,0,"
    "Composed: Flip,5661.0396,6.1904,6.0972,0.0932,11.6614,"
    "0.9665,0.5859,0.3806,20.6872,1287.4606,NA,5661.0396,NA,NA,NA"
)

QPC_HEADER = HEADER.replace(
    "CPUStartTime",
    "CPUStartQPCTime",
)
QPC_ROW = ROW.replace(
    "5661.0396",
    "10016.7",
)
QPC_ROW_2 = ROW.replace(
    "5661.0396",
    "10033.4",
)


def write_session_capture(
    tmp,
    name,
    target,
    session_id,
    started_s=1,
    ended_s=61,
    statuses=None,
    rows=3,
):
    """Write a valid CSV plus session metadata for switcher tests."""

    path = Path(tmp) / name
    row = ROW.replace("douyin.exe", target)
    path.write_text(
        HEADER + "\n" + (row + "\n") * rows,
        encoding="utf-8",
    )
    statuses = statuses or {
        "frames": "complete",
        "telemetry": "ok",
        "network": "unmeasured",
    }
    session = {
        "schema_version": 1,
        "session_id": session_id,
        "capture": {
            "csv_name": name,
            "target_name": target,
            "started_monotonic_ns": 1,
            "started_wall_ns": int(started_s * 1e9),
            "ended_monotonic_ns": 2,
            "ended_wall_ns": int(ended_s * 1e9),
            "status": "complete",
            "reason": "",
        },
        "data": {
            key: {"status": value}
            for key, value in statuses.items()
        },
    }
    Path(str(path) + ".session.json").write_text(
        json.dumps(session),
        encoding="utf-8",
    )
    return path



class FakeProcess:
    """Minimal psutil.process_iter() entry."""

    def __init__(self, name):

        self.info = {"name": name}


class FakeWorker:
    """Minimal stand-in for a running CaptureWorker."""

    def __init__(self, running=True):

        self.running = running
        self.stopped = False
        self.wait_calls = 0
        self.deleted = False

    def isRunning(self):
        return self.running

    def stop(self):
        self.stopped = True

    def wait(self, timeout=None):
        self.wait_calls += 1
        return False

    def deleteLater(self):
        self.deleted = True


class FakePresentMon:
    """Stand-in for PresentMon streaming CSV on stdout."""

    def __init__(
        self,
        command,
        rows=3,
        with_header=True,
        exit_code=0,
        exit_immediately=True,
        extra_lines=(),
    ):

        self.command = list(command)

        lines = list(extra_lines)

        if with_header:

            lines.append(HEADER)

        lines.extend([ROW] * rows)

        # PresentMon streams its CSV and status lines on stdout.
        self.stdout = io.StringIO(
            "".join(line + "\n" for line in lines)
        )

        self.exit_code = exit_code
        self.exit_immediately = exit_immediately

        self._returncode = (
            exit_code if exit_immediately else None
        )

        self.terminated = False
        self.killed = False

    def poll(self):
        return self._returncode

    def wait(self, timeout=None):
        self._returncode = self.exit_code
        return self.exit_code

    def terminate(self):
        self.terminated = True
        self._returncode = self.exit_code

    def kill(self):
        self.killed = True
        self._returncode = self.exit_code


class EmbeddedFakeViewer(QWidget):
    """Embeddable viewer stand-in used by single-window navigation tests."""

    recheck_requested = Signal(str)
    ai_chat_requested = Signal(object)
    instances = []

    def __init__(
        self,
        frames,
        filename="capture.csv",
        index=None,
        selection=None,
        csv_path=None,
        target_fps=60,
        target_fps_explicit=False,
        embedded=False,
    ):

        super().__init__()

        self.frames = frames
        self.filename = filename
        self.index = index
        self.selection = selection
        self.csv_path = csv_path
        self.target_fps = target_fps
        self.target_fps_explicit = target_fps_explicit
        self.embedded = embedded
        EmbeddedFakeViewer.instances.append(self)

    def ai_context(self):
        return {
            "report_key": str(
                Path(str(self.csv_path)).resolve()
            ),
            "file": Path(str(self.csv_path)).name,
            "application": "game.exe",
            "language": "en",
        }


class BlockingStdout:
    """Yields lines, then blocks until the process is terminated."""

    def __init__(self, lines, release):

        self._lines = lines
        self._release = release
        self.closed = False

    def __iter__(self):

        for line in self._lines:

            yield line

        self._release.wait(10)

    def close(self):
        self.closed = True


class BlockingProcess(FakePresentMon):
    """A fake PresentMon that keeps streaming until terminated."""

    def __init__(self, lines, release):

        super().__init__(
            command=[],
            rows=0,
            with_header=False,
        )

        self.stdout = BlockingStdout(lines, release)
        self.release = release
        self._returncode = None

    def wait(self, timeout=None):

        if not (self.terminated or self.killed):

            raise subprocess.TimeoutExpired(
                "fake",
                timeout or 0,
            )

        self.release.set()
        self._returncode = 0
        return 0

    def terminate(self):

        self.terminated = True
        self.release.set()
        self._returncode = 0

    def kill(self):

        self.killed = True
        self.release.set()
        self._returncode = 0


def popen_factory(**kwargs):
    """Return a Popen replacement plus a list of created processes."""

    created = []

    def factory(command, **popen_kwargs):

        process = FakePresentMon(command, **kwargs)
        created.append(process)
        return process

    return factory, created


class QtTestCase(unittest.TestCase):

    app = None

    @classmethod
    def setUpClass(cls):

        cls.app = QApplication.instance() or QApplication([])


class RecheckHandlerTests(QtTestCase):

    def make_window(self, running=True):

        return SimpleNamespace(
            process_combo=mock.Mock(),
            tabs=mock.Mock(),
            live_page=mock.Mock(),
            is_process_running=mock.Mock(
                return_value=running
            ),
            set_status=mock.Mock(),
            show=mock.Mock(),
            raise_=mock.Mock(),
            activateWindow=mock.Mock(),
            start_capture=mock.Mock(),
        )

    def test_prepare_recheck_sets_target_and_live_tab(self):

        window = self.make_window()

        laglens.LagLens.prepare_recheck(
            window,
            r"C:\Games\Game.exe",
        )

        window.process_combo.setCurrentText.assert_called_once_with(
            "Game.exe"
        )
        window.tabs.setCurrentWidget.assert_called_once_with(
            window.live_page
        )
        window.set_status.assert_called_once_with(
            "status.recheck_ready",
            target="Game.exe",
        )
        window.show.assert_called_once()
        window.raise_.assert_called_once()
        window.activateWindow.assert_called_once()
        window.start_capture.assert_not_called()

    def test_prepare_recheck_reports_missing_running_process(self):

        window = self.make_window(running=False)

        laglens.LagLens.prepare_recheck(
            window,
            r"C:\Games\Game.exe",
        )

        window.set_status.assert_called_once_with(
            "status.recheck_not_running",
            target="Game.exe",
        )
        window.start_capture.assert_not_called()

    def test_prepare_recheck_ignores_empty_target(self):

        window = self.make_window()

        laglens.LagLens.prepare_recheck(window, "")

        window.process_combo.setCurrentText.assert_not_called()
        window.tabs.setCurrentWidget.assert_not_called()
        window.set_status.assert_not_called()


class WorkerTests(QtTestCase):

    def make_worker(self, csv_path, **kwargs):

        return laglens.CaptureWorker(
            "C:/nonexistent/PresentMon.exe",
            "douyin.exe",
            csv_path,
            **kwargs,
        )

    def test_run_records_frames_and_validates_csv(self):

        with tempfile.TemporaryDirectory() as tmp:

            csv_path = Path(tmp) / "capture.csv"
            worker = self.make_worker(csv_path)

            results = []
            worker.completed.connect(results.append)

            factory, created = popen_factory(rows=3)

            with mock.patch.object(
                laglens.subprocess,
                "Popen",
                side_effect=factory,
            ):

                worker.run()

            self.assertEqual(len(created), 1)

            self.assertEqual(len(results), 1)
            result = results[0]

            self.assertIsInstance(
                result,
                capture_core.CaptureResult,
            )
            self.assertEqual(result.exit_code, 0)
            self.assertEqual(result.valid_frames, 3)
            self.assertTrue(result.ok)
            self.assertEqual(result.etw_warnings, [])

            # C-1 timing metadata is captured without changing the CSV.
            self.assertIsNotNone(
                worker.presentmon_started_monotonic_ns
            )
            self.assertIsNotNone(
                worker.first_csv_row_monotonic_ns
            )
            self.assertIsNotNone(
                worker.last_csv_row_monotonic_ns
            )
            self.assertIsNotNone(
                worker.first_cpu_start_ms
            )
            self.assertIsNotNone(
                worker.last_cpu_start_ms
            )

            # The CSV must feed the existing analysis path unchanged.
            frames = load_frames(csv_path)
            self.assertEqual(len(frames), 3)

    def test_qpc_capture_normalizes_time_and_preserves_raw_csv(self):

        with tempfile.TemporaryDirectory() as tmp:

            csv_path = Path(tmp) / "capture.csv"
            worker = self.make_worker(
                csv_path,
                qpc_time=True,
                capture_started_monotonic_ns=10_000_000_000,
            )
            factory, created = popen_factory(
                rows=0,
                with_header=False,
                extra_lines=[
                    QPC_HEADER,
                    QPC_ROW,
                    QPC_ROW_2,
                ],
            )

            with mock.patch.object(
                laglens.frame_timebase,
                "qpc_clock_delta_ms",
                return_value=0.005,
            ), mock.patch.object(
                laglens.frame_timebase,
                "qpc_frequency_hz",
                return_value=10_000_000,
            ), mock.patch.object(
                laglens.subprocess,
                "Popen",
                side_effect=factory,
            ):

                worker.run()

            self.assertEqual(len(created), 1)
            self.assertIn(
                "--qpc_time_ms",
                created[0].command,
            )
            self.assertEqual(
                worker.time_column,
                "CPUStartQPCTime",
            )
            self.assertAlmostEqual(
                worker.first_cpu_start_ms,
                16.7,
            )
            self.assertAlmostEqual(
                worker.last_cpu_start_ms,
                33.4,
            )
            self.assertAlmostEqual(
                worker.first_raw_time_ms,
                10_016.7,
            )
            self.assertAlmostEqual(
                worker.last_raw_time_ms,
                10_033.4,
            )

            timebase = worker.frame_timebase.with_range(
                worker.first_raw_time_ms,
                worker.last_raw_time_ms,
            )

            self.assertEqual(timebase.kind, "qpc_ms")
            self.assertEqual(
                timebase.sync_quality,
                "verified_qpc",
            )
            self.assertTrue(
                timebase.absolute_mapping_trusted
            )
            self.assertAlmostEqual(
                timebase.origin_qpc_ms,
                10_000.0,
            )
            self.assertAlmostEqual(
                timebase.normalized_first_ms,
                16.7,
            )

            header = csv_path.read_text(
                encoding="utf-8"
            ).splitlines()[0]

            self.assertIn("CPUStartQPCTime", header)
            self.assertNotIn("CPUStartTime", header)

    def test_worker_notifies_telemetry_marker(self):

        class FakeTelemetry:

            def __init__(self):

                self.marker = None

            def note_presentmon_started(self, monotonic_ns):

                self.marker = monotonic_ns

        with tempfile.TemporaryDirectory() as tmp:

            csv_path = Path(tmp) / "capture.csv"
            telemetry = FakeTelemetry()
            worker = self.make_worker(
                csv_path,
                telemetry=telemetry,
            )
            factory, _ = popen_factory(rows=1)

            with mock.patch.object(
                laglens.subprocess,
                "Popen",
                side_effect=factory,
            ):

                worker.run()

            self.assertIsNotNone(telemetry.marker)
            self.assertEqual(
                telemetry.marker,
                worker.presentmon_started_monotonic_ns,
            )

    def test_header_only_capture_is_not_ok(self):

        with tempfile.TemporaryDirectory() as tmp:

            csv_path = Path(tmp) / "capture.csv"
            worker = self.make_worker(csv_path)

            results = []
            worker.completed.connect(results.append)

            factory, _ = popen_factory(rows=0)

            with mock.patch.object(
                laglens.subprocess,
                "Popen",
                side_effect=factory,
            ):

                worker.run()

            result = results[0]

            self.assertFalse(result.ok)
            self.assertEqual(result.valid_frames, 0)

    def test_etw_warning_is_read_from_utf16_log(self):

        with tempfile.TemporaryDirectory() as tmp:

            csv_path = Path(tmp) / "capture.csv"
            worker = self.make_worker(csv_path)

            results = []
            worker.completed.connect(results.append)

            factory, created = popen_factory(rows=2)

            def writing_factory(command, **kwargs):

                process = factory(command, **kwargs)

                csv_path.with_suffix(".log").write_bytes(
                    b"\xff\xfe"
                    + (
                        "warning: 80794 ETW events were lost.\n"
                    ).encode("utf-16-le")
                )

                return process

            with mock.patch.object(
                laglens.subprocess,
                "Popen",
                side_effect=writing_factory,
            ):

                worker.run()

            self.assertIn(
                "80794 ETW events were lost",
                results[0].etw_warnings,
            )

    def test_worker_assigns_presentmon_to_the_job(self):

        class FakeJob:

            def __init__(self):

                self.assigned = None
                self.error = ""

            def assign(self, process):

                self.assigned = process
                return True

        with tempfile.TemporaryDirectory() as tmp:

            csv_path = Path(tmp) / "capture.csv"
            job = FakeJob()

            worker = laglens.CaptureWorker(
                "C:/nonexistent/PresentMon.exe",
                "douyin.exe",
                csv_path,
                job=job,
            )

            factory, created = popen_factory(rows=1)

            with mock.patch.object(
                laglens.subprocess,
                "Popen",
                side_effect=factory,
            ):

                worker.run()

            self.assertIs(job.assigned, created[0])

    def test_stop_before_start_never_spawns_presentmon(self):

        with tempfile.TemporaryDirectory() as tmp:

            csv_path = Path(tmp) / "capture.csv"
            worker = self.make_worker(csv_path)

            results = []
            worker.completed.connect(results.append)

            worker.stop_event.set()

            with mock.patch.object(
                laglens.subprocess,
                "Popen",
            ) as popen:

                worker.run()

            popen.assert_not_called()

            self.assertIn(
                "cancelled",
                results[0].error.lower(),
            )

            log = capture_core.read_capture_log(
                csv_path.with_suffix(".log")
            )

            self.assertIn(
                "cancelled before presentmon started",
                log.lower(),
            )

    def test_stop_process_prefers_graceful_session_shutdown(self):

        with tempfile.TemporaryDirectory() as tmp:

            csv_path = Path(tmp) / "capture.csv"
            worker = self.make_worker(csv_path)

            process = FakePresentMon(
                ["PresentMon.exe"],
                exit_immediately=False,
            )

            # Stopping the ETW session makes PresentMon exit on its own.
            worker._terminate_session = process.terminate

            hard_kill = worker._stop_process(process)

            self.assertFalse(hard_kill)
            self.assertTrue(process.terminated)
            self.assertFalse(process.killed)

    def test_thread_stop_finishes_and_keeps_captured_rows(self):

        with tempfile.TemporaryDirectory() as tmp:

            csv_path = Path(tmp) / "capture.csv"
            worker = self.make_worker(csv_path)

            results = []
            worker.completed.connect(results.append)

            release = threading.Event()

            process = BlockingProcess(
                [
                    HEADER + "\n",
                    ROW + "\n",
                    ROW + "\n",
                ],
                release,
            )

            started = threading.Event()

            def factory(command, **kwargs):

                started.set()

                return process

            with mock.patch.object(
                laglens.subprocess,
                "Popen",
                side_effect=factory,
            ), mock.patch.object(
                worker,
                "_terminate_session",
                side_effect=process.terminate,
            ):

                worker.start()

                self.assertTrue(
                    started.wait(5),
                    "Popen was never called",
                )

                # Let the worker consume the streamed rows.
                time.sleep(0.3)

                worker.stop()

                self.assertTrue(
                    worker.wait(15000),
                    "worker did not stop in time",
                )

                # Deliver any queued signal.
                QApplication.processEvents()

            self.assertTrue(process.terminated)

            if results:

                self.assertEqual(
                    results[0].valid_frames,
                    2,
                )

            self.assertEqual(
                capture_core.validate_capture(
                    csv_path
                ).valid_frames,
                2,
            )


class WindowTests(QtTestCase):

    def setUp(self):

        import pynvml

        try:

            pynvml.nvmlInit()
            gpu = pynvml.nvmlDeviceGetHandleByIndex(0)

        except Exception:  # pragma: no cover - no NVIDIA GPU

            self.skipTest("NVML unavailable")

        self.tmpdir = tempfile.TemporaryDirectory()

        self.app_settings = app_settings.AppSettings(
            Path(self.tmpdir.name) / "test.ini"
        )
        self.app_settings.set_language_mode("en")

        i18n.get_manager().set_mode("en")

        self.window = laglens.LagLens(
            gpu,
            settings=self.app_settings,
        )
        self.window.analysis_async = False
        self.window.timer.stop()
        self.window.auto_analyze.setChecked(False)
        self.window.capture_target = "douyin.exe"

    def tearDown(self):

        # Destroy the window on the GUI thread.  Letting Python's GC
        # collect a QWidget on a worker thread aborts Qt.
        self.window.close()
        self.window.deleteLater()

        QApplication.sendPostedEvents(
            None,
            QEvent.Type.DeferredDelete,
        )
        QApplication.processEvents()

        self.window = None

        self.tmpdir.cleanup()

        import pynvml

        try:
            pynvml.nvmlShutdown()

        except Exception:  # pragma: no cover

            pass

    def make_result(
        self,
        tmp,
        csv_text,
        log_bytes=b"",
        exit_code=0,
        forced_stop=False,
    ):

        csv_path = Path(tmp) / "capture.csv"
        csv_path.write_text(csv_text, encoding="utf-8")

        log_path = Path(tmp) / "capture.log"
        log_path.write_bytes(log_bytes)

        info = capture_core.validate_capture(csv_path)

        return capture_core.CaptureResult(
            csv_path=str(csv_path),
            log_path=str(log_path),
            exit_code=exit_code,
            rows=info.rows,
            valid_frames=info.valid_frames,
            forced_stop=forced_stop,
            error=info.error,
        )

    def test_successful_capture_enables_analysis(self):

        with tempfile.TemporaryDirectory() as tmp:

            result = self.make_result(
                tmp,
                HEADER + "\n" + ROW + "\n" + ROW + "\n",
                log_bytes=(
                    b"\xff\xfe"
                    + (
                        "warning: 80794 ETW events were lost.\n"
                    ).encode("utf-16-le")
                ),
            )

            self.window.on_capture_completed(result)

            self.assertTrue(
                self.window.analyze_btn.isEnabled()
            )

            status = self.window.frame_status.text()

            self.assertIn("Saved 2 frames", status)
            self.assertIn("ETW events were lost", status)

    def test_complete_capture_auto_analysis_waits_for_worker_finished(self):

        with tempfile.TemporaryDirectory() as tmp:

            result = self.make_result(
                tmp,
                HEADER + "\n" + ROW + "\n" + ROW + "\n",
            )
            self.window.auto_analyze.setChecked(True)

            with mock.patch.object(
                self.window,
                "show_analysis",
            ) as show:

                self.window.on_capture_completed(result)
                show.assert_not_called()
                self.assertEqual(
                    self.window._pending_auto_analysis,
                    result.csv_path,
                )

                self.window.on_worker_finished()

            show.assert_called_once_with(result.csv_path)

    def test_disabled_auto_analysis_does_not_open_viewer(self):

        with tempfile.TemporaryDirectory() as tmp:

            result = self.make_result(
                tmp,
                HEADER + "\n" + ROW + "\n" + ROW + "\n",
            )
            self.window.auto_analyze.setChecked(False)

            with mock.patch.object(
                self.window,
                "show_analysis",
            ) as show:

                self.window.on_capture_completed(result)
                self.window.on_worker_finished()

            self.assertIsNone(
                self.window._pending_auto_analysis
            )
            show.assert_not_called()

    def test_incomplete_capture_does_not_auto_analyze(self):

        with tempfile.TemporaryDirectory() as tmp:

            result = self.make_result(
                tmp,
                (
                    HEADER
                    + "\n"
                    + ROW
                    + "\n"
                    + ROW
                    + "\n"
                    + "douyin.exe,16548"
                ),
            )
            info = capture_core.validate_capture(
                result.csv_path
            )

            self.assertTrue(info.ok)
            self.assertFalse(info.complete)

            self.window.auto_analyze.setChecked(True)

            with mock.patch.object(
                self.window,
                "show_analysis",
            ) as show:

                self.window.on_capture_completed(result)
                self.window.on_worker_finished()

            self.assertIsNone(
                self.window._pending_auto_analysis
            )
            show.assert_not_called()

    def test_empty_capture_does_not_auto_analyze(self):

        with tempfile.TemporaryDirectory() as tmp:

            result = self.make_result(tmp, "")
            self.window.auto_analyze.setChecked(True)

            with mock.patch.object(
                laglens.QMessageBox,
                "warning",
                return_value=None,
            ), mock.patch.object(
                self.window,
                "show_analysis",
            ) as show:

                self.window.on_capture_completed(result)
                self.window.on_worker_finished()

            self.assertIsNone(
                self.window._pending_auto_analysis
            )
            show.assert_not_called()

    def test_abnormal_exit_does_not_auto_analyze(self):

        with tempfile.TemporaryDirectory() as tmp:

            result = self.make_result(
                tmp,
                HEADER + "\n" + ROW + "\n" + ROW + "\n",
            )
            result.error = (
                "PresentMon did not exit after the capture stopped."
            )
            self.window.auto_analyze.setChecked(True)

            with mock.patch.object(
                self.window,
                "show_analysis",
            ) as show:

                self.window.on_capture_completed(result)
                self.window.on_worker_finished()

            self.assertIsNone(
                self.window._pending_auto_analysis
            )
            show.assert_not_called()

    def test_duplicate_analysis_open_reuses_embedded_viewer(self):

        with tempfile.TemporaryDirectory() as tmp:

            path = Path(tmp) / "capture.csv"
            path.write_text(
                HEADER + "\n" + ROW + "\n",
                encoding="utf-8",
            )

            viewer = mock.Mock()
            self.window.viewer = viewer
            self.window._active_analysis_path = str(
                path.resolve()
            )
            self.window._active_analysis_name = path.name
            self.window._active_analysis_target = "douyin.exe"

            with mock.patch.object(
                laglens,
                "FrameViewer",
            ) as viewer_cls:

                self.window.show_analysis(str(path))

            viewer_cls.assert_not_called()
            self.assertIs(
                self.window.tabs.currentWidget(),
                self.window.analysis_page,
            )
            self.assertIs(
                self.window.analysis_stack.currentWidget(),
                self.window.analysis_container,
            )
            self.assertFalse(
                self.window.analysis_header.isHidden()
            )
            self.assertIn(
                path.name,
                self.window.analysis_file_label.text(),
            )
            self.assertIn(
                "douyin.exe",
                self.window.analysis_target_label.text(),
            )

    def test_analysis_page_starts_empty(self):

        self.assertTrue(
            self.window.analysis_header.isHidden()
        )
        self.assertEqual(
            self.window.analysis_stack.currentIndex(),
            0,
        )
        self.assertEqual(
            self.window.tabs.tabText(3),
            "Analysis",
        )

    def test_top_level_tabs_include_ai_assistant(self):

        labels = [
            self.window.tabs.tabText(index)
            for index in range(self.window.tabs.count())
        ]

        self.assertEqual(
            labels,
            [
                "Hardware",
                "Network",
                "Live Frames",
                "Analysis",
                "AI assistant",
                "Settings",
            ],
        )

    def test_ai_assistant_can_open_ai_settings(self):

        self.assertIsNotNone(
            self.window.ai_settings_card
        )
        self.window.ai_page.open_ai_settings_requested.emit()

        self.assertIs(
            self.window.tabs.currentWidget(),
            self.window.settings_page,
        )

    def test_network_tab_and_joint_capture_start_idle(self):

        self.assertIsNotNone(self.window.network_page)
        self.assertIn(
            "frames",
            self.window.capture_note.text(),
        )
        self.assertIn(
            "network probes",
            self.window.capture_note.text(),
        )
        self.assertFalse(
            self.window.network_service.running
        )
        self.assertFalse(
            hasattr(self.window, "mode_online")
        )

    def test_capture_note_explains_default_network_capture(self):

        self.assertIn(
            "network",
            self.window.capture_note.text().lower(),
        )

    def test_ask_ai_links_active_report_without_separate_window(self):

        with tempfile.TemporaryDirectory() as tmp:

            path = Path(tmp) / "capture.csv"
            path.write_text(
                HEADER + "\n" + ROW + "\n" + ROW + "\n",
                encoding="utf-8",
            )

            with mock.patch.object(
                laglens,
                "FrameViewer",
                EmbeddedFakeViewer,
            ):

                self.window.show_analysis(str(path))

            self.window.ask_ai_about_active_report()

            self.assertIs(
                self.window.tabs.currentWidget(),
                self.window.ai_page,
            )
            self.assertIn(
                "game.exe",
                self.window.ai_page.report_label.text(),
            )
            self.assertFalse(
                self.window.ai_page.view_report_button.isHidden()
            )
            self.assertFalse(
                self.window.ai_page.isWindow()
            )

    def test_ai_page_follows_active_report(self):

        with tempfile.TemporaryDirectory() as tmp:

            path_a = Path(tmp) / "a.csv"
            path_b = Path(tmp) / "b.csv"

            for path in (path_a, path_b):
                path.write_text(
                    HEADER + "\n" + ROW + "\n" + ROW + "\n",
                    encoding="utf-8",
                )

            with mock.patch.object(
                laglens,
                "FrameViewer",
                EmbeddedFakeViewer,
            ):

                self.window.show_analysis(str(path_a))
                self.window.ask_ai_about_active_report()
                session_a = self.window.ai_page.session
                session_a.messages.append(
                    {
                        "role": "user",
                        "content": "A 的对话",
                        "kind": "chat",
                    }
                )

                self.window.show_analysis(str(path_b))

                self.assertIsNot(
                    self.window.ai_page.session,
                    session_a,
                )
                self.assertEqual(
                    self.window.ai_page.session.report_key,
                    str(path_b.resolve()),
                )
                self.assertIn(
                    "A 的对话",
                    [
                        item["content"]
                        for item in session_a.messages
                    ],
                )
                self.assertEqual(
                    self.window.ai_page.session.messages,
                    [],
                )

                self.window.ask_ai_about_active_report()

                self.assertEqual(
                    self.window.ai_page.session.report_key,
                    str(path_b.resolve()),
                )

    def test_show_analysis_embeds_viewer_in_main_window(self):

        with tempfile.TemporaryDirectory() as tmp:

            path = Path(tmp) / "capture.csv"
            path.write_text(
                HEADER + "\n" + ROW + "\n" + ROW + "\n",
                encoding="utf-8",
            )
            EmbeddedFakeViewer.instances = []

            with mock.patch.object(
                laglens,
                "FrameViewer",
                EmbeddedFakeViewer,
            ):

                self.window.show_analysis(str(path))

            viewer = self.window.viewer
            self.assertIsInstance(
                viewer,
                EmbeddedFakeViewer,
            )
            self.assertTrue(viewer.embedded)
            self.assertFalse(viewer.isWindow())
            self.assertIs(
                viewer.parentWidget(),
                self.window.analysis_container,
            )
            self.assertIs(
                self.window.tabs.currentWidget(),
                self.window.analysis_page,
            )
            self.assertIs(
                self.window.analysis_stack.currentWidget(),
                self.window.analysis_container,
            )
            self.assertFalse(
                self.window.analysis_header.isHidden()
            )
            self.assertIn(
                path.name,
                self.window.analysis_file_label.text(),
            )
            self.assertIn(
                "douyin.exe",
                self.window.analysis_target_label.text(),
            )

    def test_show_analysis_replaces_embedded_viewer_for_new_file(self):

        with tempfile.TemporaryDirectory() as tmp:

            first_path = Path(tmp) / "first.csv"
            second_path = Path(tmp) / "second.csv"
            first_path.write_text(
                HEADER + "\n" + ROW + "\n",
                encoding="utf-8",
            )
            second_path.write_text(
                HEADER + "\n" + ROW + "\n" + ROW + "\n",
                encoding="utf-8",
            )
            EmbeddedFakeViewer.instances = []

            with mock.patch.object(
                laglens,
                "FrameViewer",
                EmbeddedFakeViewer,
            ):

                self.window.show_analysis(str(first_path))
                first = self.window.viewer
                self.window.show_analysis(str(second_path))
                second = self.window.viewer

            self.assertIsNot(first, second)
            self.assertEqual(
                len(EmbeddedFakeViewer.instances),
                2,
            )
            self.assertIsNone(first.parentWidget())
            self.assertIs(
                second.parentWidget(),
                self.window.analysis_container,
            )
            self.assertEqual(
                self.window.analysis_container_layout.count(),
                1,
            )
            self.assertIn(
                second_path.name,
                self.window.analysis_file_label.text(),
            )

    def test_analysis_page_switching_does_not_stop_worker(self):

        with tempfile.TemporaryDirectory() as tmp:

            path = Path(tmp) / "capture.csv"
            path.write_text(
                HEADER + "\n" + ROW + "\n",
                encoding="utf-8",
            )
            EmbeddedFakeViewer.instances = []

            with mock.patch.object(
                laglens,
                "FrameViewer",
                EmbeddedFakeViewer,
            ):

                self.window.show_analysis(str(path))

            worker = FakeWorker()
            self.window.worker = worker

            for index in range(self.window.tabs.count()):

                self.window.tabs.setCurrentIndex(index)
                QApplication.processEvents()

            self.assertFalse(worker.stopped)
            self.assertTrue(worker.isRunning())
            self.window.worker = None

    def test_switching_away_and_back_keeps_analysis_viewer(self):

        with tempfile.TemporaryDirectory() as tmp:

            path = Path(tmp) / "capture.csv"
            path.write_text(
                HEADER + "\n" + ROW + "\n",
                encoding="utf-8",
            )
            EmbeddedFakeViewer.instances = []

            with mock.patch.object(
                laglens,
                "FrameViewer",
                EmbeddedFakeViewer,
            ):

                self.window.show_analysis(str(path))

            viewer = self.window.viewer

            self.window.tabs.setCurrentWidget(
                self.window.live_page
            )
            QApplication.processEvents()
            self.window.tabs.setCurrentWidget(
                self.window.analysis_page
            )
            QApplication.processEvents()

            self.assertIs(self.window.viewer, viewer)
            self.assertIs(
                viewer.parentWidget(),
                self.window.analysis_container,
            )
            self.assertFalse(
                self.window.analysis_header.isHidden()
            )

    def test_analysis_header_localizes_on_language_switch(self):

        with tempfile.TemporaryDirectory() as tmp:

            path = Path(tmp) / "capture.csv"
            path.write_text(
                HEADER + "\n" + ROW + "\n",
                encoding="utf-8",
            )
            EmbeddedFakeViewer.instances = []

            with mock.patch.object(
                laglens,
                "FrameViewer",
                EmbeddedFakeViewer,
            ):

                self.window.show_analysis(str(path))

            i18n.get_manager().set_language("zh_CN")
            QApplication.processEvents()

            self.assertEqual(
                self.window.tabs.tabText(3),
                "分析报告",
            )
            self.assertIn(
                "文件：",
                self.window.analysis_file_label.text(),
            )
            self.assertIn(
                "目标：",
                self.window.analysis_target_label.text(),
            )

    def test_recent_capture_opens_embedded_analysis_page(self):

        with tempfile.TemporaryDirectory() as tmp:

            path = Path(tmp) / "capture.csv"
            path.write_text(
                HEADER + "\n" + ROW + "\n",
                encoding="utf-8",
            )
            self.app_settings.set_recent_captures(
                [
                    {
                        "path": str(path),
                        "name": path.name,
                        "target": "douyin.exe",
                        "captured_at": "2026-11-12T10:00:00",
                        "frames": 1,
                        "telemetry": False,
                    }
                ]
            )
            self.window.refresh_recent_captures()
            item = self.window.recent_list.item(0)
            EmbeddedFakeViewer.instances = []

            with mock.patch.object(
                laglens,
                "FrameViewer",
                EmbeddedFakeViewer,
            ):

                self.window.open_recent_capture(item)

            self.assertIs(
                self.window.tabs.currentWidget(),
                self.window.analysis_page,
            )
            self.assertTrue(
                self.window.viewer.embedded
            )

    def test_analysis_header_has_switch_button(self):

        self.assertTrue(
            self.window.analysis_switch_button.text()
        )
        self.assertTrue(
            self.window.report_switcher.isHidden()
        )

    def _recent_record(self, path, target, captured_at):

        return {
            "path": str(path),
            "name": path.name,
            "target": target,
            "captured_at": captured_at,
            "frames": 3,
            "telemetry": True,
        }

    def test_report_switcher_lists_newest_first_with_details(self):

        with tempfile.TemporaryDirectory() as tmp:

            older = write_session_capture(
                tmp,
                "a.csv",
                "game-a.exe",
                "session-a",
                started_s=1,
                ended_s=61,
            )
            newer = write_session_capture(
                tmp,
                "b.csv",
                "game-b.exe",
                "session-b",
                started_s=100,
                ended_s=220,
            )
            self.app_settings.set_recent_captures(
                [
                    self._recent_record(
                        older,
                        "game-a.exe",
                        "2026-11-12T10:00:00",
                    ),
                    self._recent_record(
                        newer,
                        "game-b.exe",
                        "2026-11-13T10:00:00",
                    ),
                ]
            )
            self.window.show_analysis(str(older))
            self.window.toggle_report_switcher()

            table = self.window.report_switcher_table
            self.assertFalse(
                self.window.report_switcher.isHidden()
            )
            self.assertEqual(table.rowCount(), 2)
            self.assertEqual(
                table.item(0, 0).text(),
                "game-b.exe",
            )
            self.assertEqual(
                table.item(1, 0).text(),
                "game-a.exe",
            )
            self.assertEqual(
                table.item(0, 1).text(),
                "2026-11-13 10:00:00",
            )
            self.assertEqual(
                table.item(0, 2).text(),
                "120 s",
            )
            self.assertIn(
                "Frames complete",
                table.item(0, 3).text(),
            )

    def test_report_switcher_opens_selected_report_without_capture(self):

        with tempfile.TemporaryDirectory() as tmp:

            older = write_session_capture(
                tmp,
                "a.csv",
                "game-a.exe",
                "session-a",
            )
            newer = write_session_capture(
                tmp,
                "b.csv",
                "game-b.exe",
                "session-b",
            )
            self.app_settings.set_recent_captures(
                [
                    self._recent_record(
                        older,
                        "game-a.exe",
                        "2026-11-12T10:00:00",
                    ),
                    self._recent_record(
                        newer,
                        "game-b.exe",
                        "2026-11-13T10:00:00",
                    ),
                ]
            )
            self.window.show_analysis(str(older))
            self.window.toggle_report_switcher()

            with mock.patch.object(
                laglens,
                "CaptureWorker",
            ) as worker_cls, mock.patch.object(
                laglens.ai_chat.ChatSession,
                "send",
            ) as ai_send:

                self.assertTrue(
                    self.window.open_report_switcher_row(0, 0)
                )

            worker_cls.assert_not_called()
            ai_send.assert_not_called()

            context = self.window.viewer.ai_context()
            self.assertEqual(
                self.window._active_analysis_path,
                str(newer.resolve()),
            )
            self.assertEqual(
                context["report_key"],
                str(newer.resolve()),
            )
            self.assertEqual(
                context["session_id"],
                "session-b",
            )
            self.assertIsNotNone(self.window.viewer.stats)
            self.assertTrue(
                context.get("diagnosis")
            )
            self.assertIn(
                "b.csv",
                self.window.analysis_file_label.text(),
            )
            self.assertIsNone(self.window.worker)
            self.assertTrue(
                self.window.report_switcher.isHidden()
            )

    def test_report_switcher_cancel_keeps_current_report(self):

        with tempfile.TemporaryDirectory() as tmp:

            older = write_session_capture(
                tmp,
                "a.csv",
                "game-a.exe",
                "session-a",
            )
            self.window.show_analysis(str(older))
            self.window.toggle_report_switcher()
            self.window.cancel_report_switcher()

            self.assertTrue(
                self.window.report_switcher.isHidden()
            )
            self.assertEqual(
                self.window._active_analysis_path,
                str(older.resolve()),
            )

    def test_report_switcher_missing_file_keeps_current_report(self):

        with tempfile.TemporaryDirectory() as tmp:

            older = write_session_capture(
                tmp,
                "a.csv",
                "game-a.exe",
                "session-a",
            )
            missing = Path(tmp) / "missing.csv"
            self.window.show_analysis(str(older))

            with mock.patch.object(
                laglens.QMessageBox,
                "warning",
            ) as warning:

                opened = self.window._open_capture_path(
                    missing
                )

            self.assertFalse(opened)
            warning.assert_called_once()
            self.assertEqual(
                self.window._active_analysis_path,
                str(older.resolve()),
            )

    def test_report_switcher_damaged_file_keeps_current_report(self):

        with tempfile.TemporaryDirectory() as tmp:

            older = write_session_capture(
                tmp,
                "a.csv",
                "game-a.exe",
                "session-a",
            )
            damaged = Path(tmp) / "damaged.csv"
            damaged.write_text(
                "Application,FrameTime\ngame.exe,16.7\n",
                encoding="utf-8",
            )
            self.window.show_analysis(str(older))

            with mock.patch.object(
                laglens.QMessageBox,
                "warning",
            ) as warning:

                opened = self.window._open_capture_path(
                    damaged
                )

            self.assertFalse(opened)
            warning.assert_called_once()
            self.assertEqual(
                self.window._active_analysis_path,
                str(older.resolve()),
            )

    def test_report_switcher_relinks_ai_chat_to_active_report(self):

        with tempfile.TemporaryDirectory() as tmp:

            older = write_session_capture(
                tmp,
                "a.csv",
                "game-a.exe",
                "session-a",
            )
            newer = write_session_capture(
                tmp,
                "b.csv",
                "game-b.exe",
                "session-b",
            )
            self.app_settings.set_recent_captures(
                [
                    self._recent_record(
                        older,
                        "game-a.exe",
                        "2026-11-12T10:00:00",
                    ),
                    self._recent_record(
                        newer,
                        "game-b.exe",
                        "2026-11-13T10:00:00",
                    ),
                ]
            )
            self.window.show_analysis(str(older))
            self.window.ask_ai_about_active_report()

            self.assertEqual(
                self.window.ai_page.report_key,
                str(older.resolve()),
            )

            self.window.toggle_report_switcher()
            self.assertTrue(
                self.window.open_report_switcher_row(0, 0)
            )
            self.assertEqual(
                self.window.ai_page.report_key,
                str(newer.resolve()),
            )

            self.window.ask_ai_about_active_report()
            self.assertEqual(
                self.window.ai_page.report_key,
                str(newer.resolve()),
            )

    def test_report_switcher_empty_state(self):

        self.app_settings.set_recent_captures([])
        self.window.refresh_report_switcher()
        self.window.toggle_report_switcher()

        self.assertEqual(
            self.window.report_switcher_table.rowCount(),
            0,
        )
        self.assertTrue(
            self.window.report_switcher_empty.text()
        )
        self.assertFalse(
            self.window.report_switcher_open_button.isEnabled()
        )

    def test_report_switcher_discards_a_stale_load(self):

        with tempfile.TemporaryDirectory() as tmp:

            newer = write_session_capture(
                tmp,
                "b.csv",
                "game-b.exe",
                "session-b",
            )
            original = laglens.swap_chains.load_csv_rows
            calls = []

            def loader(filename):

                rows = original(filename)

                if not calls:

                    calls.append(filename)
                    self.window._analysis_generation += 1

                return rows

            with mock.patch.object(
                laglens.swap_chains,
                "load_csv_rows",
                side_effect=loader,
            ):

                opened = self.window.show_analysis(
                    str(newer)
                )

            self.assertFalse(opened)
            self.assertIsNone(self.window.viewer)

    def test_complete_capture_auto_analysis_opens_embedded_page(self):

        with tempfile.TemporaryDirectory() as tmp:

            result = self.make_result(
                tmp,
                HEADER + "\n" + ROW + "\n" + ROW + "\n",
            )
            self.window.auto_analyze.setChecked(True)
            EmbeddedFakeViewer.instances = []

            with mock.patch.object(
                laglens,
                "FrameViewer",
                EmbeddedFakeViewer,
            ):

                self.window.on_capture_completed(result)
                self.window.on_worker_finished()
                QApplication.processEvents()

            self.assertIs(
                self.window.tabs.currentWidget(),
                self.window.analysis_page,
            )
            self.assertTrue(
                self.window.viewer.embedded
            )

    def test_real_analysis_viewer_is_embedded_without_title(self):

        with tempfile.TemporaryDirectory() as tmp:

            path = Path(tmp) / "capture.csv"
            path.write_text(
                HEADER + "\n" + ROW + "\n" + ROW + "\n",
                encoding="utf-8",
            )

            self.window.show_analysis(str(path))
            viewer = self.window.viewer

            self.assertIsNotNone(viewer)
            self.assertFalse(viewer.isWindow())
            self.assertEqual(
                viewer.parentWidget(),
                self.window.analysis_container,
            )
            self.assertTrue(
                viewer.title_label.isHidden()
            )
            self.assertIsNotNone(
                viewer.findChild(QScrollArea)
            )

    def test_recent_list_empty_state(self):

        self.assertEqual(
            self.window.recent_list.count(),
            1,
        )
        self.assertFalse(
            self.window.recent_list.isEnabled()
        )
        self.assertIn(
            "No recent captures yet",
            self.window.recent_list.item(0).text(),
        )

    def test_successful_capture_populates_recent_list(self):

        with tempfile.TemporaryDirectory() as tmp:

            result = self.make_result(
                tmp,
                HEADER + "\n" + ROW + "\n" + ROW + "\n",
            )

            self.window.on_capture_completed(result)

            self.assertEqual(
                self.window.recent_list.count(),
                1,
            )
            item = self.window.recent_list.item(0)

            self.assertEqual(
                item.data(Qt.ItemDataRole.UserRole),
                result.csv_path,
            )
            self.assertIn("douyin.exe", item.text())

            with mock.patch.object(
                self.window,
                "show_analysis",
            ) as show:

                self.window.open_recent_capture(item)

            show.assert_called_once_with(result.csv_path)

    def test_recent_capture_missing_file_warns_safely(self):

        with tempfile.TemporaryDirectory() as tmp:

            missing = Path(tmp) / "missing.csv"
            self.app_settings.set_recent_captures(
                [
                    {
                        "path": str(missing),
                        "name": missing.name,
                        "target": "game.exe",
                        "captured_at": "2026-11-12T10:00:00",
                        "frames": 120,
                        "telemetry": False,
                    }
                ]
            )
            self.window.refresh_recent_captures()
            item = self.window.recent_list.item(0)

            self.assertIn("file missing", item.text())

            with mock.patch.object(
                laglens.QMessageBox,
                "warning",
            ) as warning, mock.patch.object(
                self.window,
                "show_analysis",
            ) as show:

                self.window.open_recent_capture(item)

            warning.assert_called_once()
            show.assert_not_called()

    def test_recent_capture_damaged_file_warns_safely(self):

        with tempfile.TemporaryDirectory() as tmp:

            damaged = Path(tmp) / "damaged.csv"
            damaged.write_text(
                "Application,FrameTime\ngame.exe,16.7\n",
                encoding="utf-8",
            )
            self.app_settings.set_recent_captures(
                [
                    {
                        "path": str(damaged),
                        "name": damaged.name,
                        "target": "game.exe",
                        "captured_at": "2026-11-12T10:00:00",
                        "frames": 1,
                        "telemetry": False,
                    }
                ]
            )
            self.window.refresh_recent_captures()
            item = self.window.recent_list.item(0)

            with mock.patch.object(
                laglens.QMessageBox,
                "warning",
            ) as warning, mock.patch.object(
                self.window,
                "show_analysis",
            ) as show:

                self.window.open_recent_capture(item)

            warning.assert_called_once()
            show.assert_not_called()

    def test_recent_capture_without_sidecar_opens_safely(self):

        with tempfile.TemporaryDirectory() as tmp:

            path = Path(tmp) / "capture.csv"
            path.write_text(
                HEADER + "\n" + ROW + "\n",
                encoding="utf-8",
            )
            self.app_settings.set_recent_captures(
                [
                    {
                        "path": str(path),
                        "name": path.name,
                        "target": "douyin.exe",
                        "captured_at": "2026-11-12T10:00:00",
                        "frames": 1,
                        "telemetry": False,
                    }
                ]
            )
            self.window.refresh_recent_captures()
            item = self.window.recent_list.item(0)

            self.assertIn("no telemetry", item.text())

            with mock.patch.object(
                self.window,
                "show_analysis",
            ) as show:

                self.window.open_recent_capture(item)

            show.assert_called_once_with(str(path))

    def test_onboarding_first_use_and_reopen(self):

        self.assertFalse(
            self.window.onboarding_card.isHidden()
        )
        self.assertEqual(
            len(self.window.onboarding_steps),
            3,
        )
        self.assertIn(
            "Choose the running game process",
            self.window.onboarding_steps[0].text(),
        )

        self.window.onboarding_dismiss_btn.click()

        self.assertTrue(
            self.window.onboarding_card.isHidden()
        )
        self.assertTrue(
            self.app_settings.onboarding_seen
        )

        self.window.quickstart_btn.click()

        self.assertFalse(
            self.window.onboarding_card.isHidden()
        )

    def test_onboarding_switches_language(self):

        i18n.get_manager().set_language("zh_CN")
        QApplication.processEvents()

        self.assertIn(
            "选择正在运行的游戏进程",
            self.window.onboarding_steps[0].text(),
        )
        self.assertEqual(
            self.window.onboarding_dismiss_btn.text(),
            "知道了，开始使用",
        )

    def test_recent_captures_switch_language(self):

        with tempfile.TemporaryDirectory() as tmp:

            path = Path(tmp) / "capture.csv"
            path.write_text(
                HEADER + "\n" + ROW + "\n",
                encoding="utf-8",
            )
            self.app_settings.set_recent_captures(
                [
                    {
                        "path": str(path),
                        "name": path.name,
                        "target": "douyin.exe",
                        "captured_at": "2026-11-12T10:00:00",
                        "frames": 1,
                        "telemetry": False,
                    }
                ]
            )
            self.window.refresh_recent_captures()

            i18n.get_manager().set_language("zh_CN")
            QApplication.processEvents()

            text = self.window.recent_list.item(0).text()

            self.assertIn("无遥测", text)
            self.assertIn("帧", text)

    def test_successful_capture_records_only_a_valid_target(self):

        with tempfile.TemporaryDirectory() as tmp:

            result = self.make_result(
                tmp,
                HEADER + "\n" + ROW + "\n" + ROW + "\n",
            )

            with mock.patch.object(
                laglens.process_catalog,
                "remember_capture_target",
                return_value=[
                    {
                        "path": r"<game-path>\game.exe",
                        "executable": "douyin.exe",
                        "last_success": "2026-11-12T01:00:00",
                    }
                ],
            ) as remember:

                self.window.on_capture_completed(result)

            remember.assert_called_once()

            args, kwargs = remember.call_args

            self.assertIs(args[0], self.app_settings)
            self.assertEqual(args[1], "douyin.exe")
            self.assertEqual(args[2], result.csv_path)
            self.assertIsNotNone(
                kwargs.get("created_before")
            )

    def test_damaged_csv_does_not_record_success(self):

        with tempfile.TemporaryDirectory() as tmp:

            result = self.make_result(
                tmp,
                "Application,FrameTime\ndouyin.exe,16.7\n",
            )

            with mock.patch.object(
                laglens.process_catalog,
                "remember_capture_target",
            ) as remember, mock.patch.object(
                laglens.QMessageBox,
                "warning",
                return_value=None,
            ):

                self.window.on_capture_completed(result)

            remember.assert_not_called()

    def test_failed_capture_does_not_record_success(self):

        with tempfile.TemporaryDirectory() as tmp:

            result = self.make_result(tmp, "")

            with mock.patch.object(
                laglens.process_catalog,
                "remember_capture_target",
            ) as remember, mock.patch.object(
                laglens.QMessageBox,
                "warning",
                return_value=None,
            ):

                self.window.on_capture_completed(result)

            remember.assert_not_called()

    def test_target_controls_are_blocked_while_the_worker_runs(self):

        class RunningWorker:

            def isRunning(self):

                return True

        self.window.worker = RunningWorker()
        self.window.set_target_controls_enabled(False)

        self.assertFalse(
            self.window.process_combo.isEnabled()
        )
        self.assertFalse(
            self.window.choose_process_btn.isEnabled()
        )
        self.assertFalse(
            self.window.refresh_processes_btn.isEnabled()
        )

        with mock.patch.object(
            laglens,
            "ProcessDialog",
        ) as dialog, mock.patch.object(
            laglens.psutil,
            "process_iter",
        ) as process_iter:

            self.window.choose_process()
            self.window.refresh_processes()

        dialog.assert_not_called()
        process_iter.assert_not_called()

        self.window.on_worker_finished()
        self.app.processEvents()

        self.assertTrue(
            self.window.process_combo.isEnabled()
        )
        self.assertTrue(
            self.window.choose_process_btn.isEnabled()
        )
        self.assertTrue(
            self.window.refresh_processes_btn.isEnabled()
        )
        self.assertIsNone(self.window.worker)

    def test_telemetry_start_uses_configured_interval(self):

        captured = {}

        class FakeSampler:

            def __init__(self, **kwargs):

                captured.update(kwargs)
                self.stopped = []

            def start(self):

                return True

            def stop(self, reason, capture_outcome):

                self.stopped.append(
                    (reason, capture_outcome)
                )

        self.app_settings.set_telemetry_interval_ms(500)

        with mock.patch.object(
            laglens,
            "HardwareSampler",
            FakeSampler,
        ), tempfile.TemporaryDirectory() as folder:

            csv_path = Path(folder) / "capture.csv"
            sampler = self.window._start_telemetry(
                csv_path,
                "Game.exe",
                False,
            )

            self.assertIsNotNone(sampler)
            self.assertEqual(
                captured["interval_s"],
                0.5,
            )
            self.assertEqual(
                captured["target_name"],
                "Game.exe",
            )
            self.assertFalse(captured["low_overhead"])
            self.assertFalse(captured["qpc_time"])
            self.assertIs(
                self.window.sampler,
                sampler,
            )

            self.window._stop_telemetry(
                "finished",
                "valid",
            )

            self.assertEqual(
                sampler.stopped,
                [("finished", "valid")],
            )
            self.assertIsNone(self.window.sampler)

    def test_low_overhead_telemetry_uses_slow_profile(self):

        captured = {}

        class FakeSampler:

            def __init__(self, **kwargs):

                captured.update(kwargs)

            def start(self):

                return True

            def stop(self, reason, capture_outcome):

                pass

        self.app_settings.set_telemetry_interval_ms(250)

        with mock.patch.object(
            laglens,
            "HardwareSampler",
            FakeSampler,
        ), tempfile.TemporaryDirectory() as folder:

            sampler = self.window._start_telemetry(
                Path(folder) / "capture.csv",
                "Game.exe",
                True,
            )

            self.assertIsNotNone(sampler)
            self.assertEqual(
                captured["interval_s"],
                1.0,
            )
            self.assertTrue(captured["low_overhead"])

            self.window._stop_telemetry("finished")

    def test_qpc_telemetry_option_is_passed_to_sampler(self):

        captured = {}

        class FakeSampler:

            def __init__(self, **kwargs):

                captured.update(kwargs)

            def start(self):

                return True

            def stop(self, reason, capture_outcome):

                pass

        self.window.qpc_time.setChecked(True)

        with mock.patch.object(
            laglens,
            "HardwareSampler",
            FakeSampler,
        ), tempfile.TemporaryDirectory() as folder:

            sampler = self.window._start_telemetry(
                Path(folder) / "capture.csv",
                "Game.exe",
                False,
                qpc_time=True,
            )

            self.assertIsNotNone(sampler)
            self.assertTrue(captured["qpc_time"])

            self.window._stop_telemetry("finished")

    def test_start_capture_passes_qpc_option_and_capture_start(self):

        captured_sampler = {}
        captured_worker = {}

        class FakeSignal:

            def connect(self, slot):

                pass

        class FakeSampler:

            def __init__(self, **kwargs):

                captured_sampler.update(kwargs)
                self.started_monotonic_ns = 123_000
                self.write_error = ""

            def start(self):

                return True

            def stop(self, reason, capture_outcome):

                pass

        class FakeWorker:

            batch = FakeSignal()
            completed = FakeSignal()
            finished = FakeSignal()

            def __init__(self, *args, **kwargs):

                captured_worker.update(kwargs)

            def isRunning(self):

                return False

            def start(self):

                pass

        with mock.patch.object(
            laglens,
            "HardwareSampler",
            FakeSampler,
        ), mock.patch.object(
            laglens,
            "CaptureWorker",
            FakeWorker,
        ), mock.patch.object(
            laglens,
            "is_elevated",
            return_value=True,
        ), mock.patch.object(
            laglens,
            "CAPTURES",
            Path(self.tmpdir.name) / "captures",
        ), mock.patch.object(
            self.window,
            "is_process_running",
            return_value=True,
        ), mock.patch.object(
            self.window,
            "confirm_similar_target",
            return_value=True,
        ), mock.patch.object(
            self.window,
            "similar_targets",
            return_value=[],
        ), mock.patch.object(
            self.window.network_service,
            "begin_capture",
            return_value=True,
        ) as begin_network:

            exe = Path(self.tmpdir.name) / "PresentMon.exe"
            exe.write_bytes(b"")

            self.window.exe_input.setText(str(exe))
            self.window.process_combo.setCurrentText(
                "douyin.exe"
            )
            self.window.qpc_time.setChecked(True)

            self.window.start_capture()

            begin_network.assert_called_once()
            self.assertEqual(
                begin_network.call_args.args[2],
                self.window.capture_session.started_monotonic_ns,
            )
            self.assertTrue(
                begin_network.call_args.kwargs["session_id"]
            )
            session_files = list(
                (Path(self.tmpdir.name) / "captures").glob(
                    "*.session.json"
                )
            )
            self.assertTrue(session_files)
            session_data = json.loads(
                session_files[0].read_text(encoding="utf-8")
            )
            self.assertEqual(
                session_data["session_id"],
                begin_network.call_args.kwargs["session_id"],
            )
            self.assertEqual(
                session_data["data"]["network"]["status"],
                "captured",
            )
            self.assertTrue(
                captured_sampler["qpc_time"]
            )
            self.assertTrue(
                captured_worker["qpc_time"]
            )
            self.assertEqual(
                captured_worker[
                    "capture_started_monotonic_ns"
                ],
                self.window.capture_session.started_monotonic_ns,
            )

            self.window._stop_telemetry("finished")

    def test_telemetry_note_uses_worker_timings(self):

        timings = {}

        class FakeSampler:

            def note_capture_timing(self, **kwargs):

                timings.update(kwargs)

            def stop(self, reason, capture_outcome):

                pass

        self.window.sampler = FakeSampler()
        worker = SimpleNamespace(
            first_csv_row_monotonic_ns=1_000_000_000,
            last_csv_row_monotonic_ns=2_000_000_000,
            first_cpu_start_ms=900.0,
            last_cpu_start_ms=1900.0,
            first_raw_time_ms=10_900.0,
            last_raw_time_ms=11_900.0,
            frame_timebase=(
                laglens.frame_timebase.qpc_timebase_for_capture(
                    10_000_000_000,
                    qpc_clock_delta_ms_value=0.005,
                )
            ),
        )
        info = SimpleNamespace(
            ok=True,
            valid_frames=60,
        )

        self.window._note_telemetry(info, worker)

        self.assertEqual(
            timings["first_row_monotonic_ns"],
            1_000_000_000,
        )
        self.assertEqual(
            timings["last_cpu_start_ms"],
            1900.0,
        )
        self.assertEqual(timings["valid_frames"], 60)
        self.assertEqual(
            timings["capture_outcome"],
            "valid",
        )
        self.assertEqual(
            timings["frame_timebase"]["kind"],
            "qpc_ms",
        )
        self.assertEqual(
            timings["frame_timebase"]["sync_quality"],
            "verified_qpc",
        )
        self.assertTrue(
            timings["frame_timebase"][
                "absolute_mapping_trusted"
            ]
        )
        self.assertAlmostEqual(
            timings["frame_timebase"]["normalized_first_ms"],
            900.0,
        )

    def test_telemetry_failure_does_not_raise(self):

        class FailingSampler:

            def __init__(self, **kwargs):

                self.write_error = "OSError"

            def start(self):

                return False

        with mock.patch.object(
            laglens,
            "HardwareSampler",
            FailingSampler,
        ), tempfile.TemporaryDirectory() as folder:

            sampler = self.window._start_telemetry(
                Path(folder) / "capture.csv",
                "Game.exe",
                False,
            )

            self.assertIsNone(sampler)
            self.assertIsNone(self.window.sampler)

    def test_show_analysis_preserves_qpc_timebase_from_sidecar(self):

        captured = {}

        class FakeViewer(QWidget):

            recheck_requested = SimpleNamespace(
                connect=lambda slot: captured.update(
                    recheck_slot=slot
                )
            )
            ai_chat_requested = SimpleNamespace(
                connect=lambda slot: captured.update(
                    chat_slot=slot
                )
            )

            def __init__(
                self,
                frames,
                filename,
                index=None,
                selection=None,
                csv_path=None,
                target_fps=60,
                target_fps_explicit=False,
                embedded=False,
            ):

                super().__init__()
                captured["frames"] = frames
                captured["index"] = index
                captured["selection"] = selection
                captured["csv_path"] = csv_path
                captured["target_fps"] = target_fps
                captured["embedded"] = embedded

            def close(self):

                pass

        with tempfile.TemporaryDirectory() as folder:

            csv_path = Path(folder) / "qpc.csv"
            csv_path.write_text(
                "Application,ProcessID,SwapChainAddress,"
                "CPUStartQPCTime,FrameTime,DisplayedTime\n"
                "game.exe,100,0x1,10016.7,16.7,16.0\n"
                "game.exe,100,0x1,10033.4,16.7,16.0\n"
                "game.exe,100,0x1,10050.1,16.7,16.0\n",
                encoding="utf-8",
            )
            Path(
                str(csv_path) + ".telemetry.jsonl"
            ).write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "type": "metadata",
                                "schema_version": 1,
                                "capture": {
                                    "csv_name": csv_path.name,
                                    "started_monotonic_ns": (
                                        10_000_000_000
                                    ),
                                },
                            }
                        ),
                        json.dumps(
                            {
                                "type": "timebase",
                                "frame_timebase": {
                                    "kind": "qpc_ms",
                                    "raw_column": (
                                        "CPUStartQPCTime"
                                    ),
                                    "origin_kind": (
                                        "capture_start"
                                    ),
                                    "origin_qpc_ms": 10_000.0,
                                    "capture_started_monotonic_ns": (
                                        10_000_000_000
                                    ),
                                    "sync_quality": (
                                        "verified_qpc"
                                    ),
                                },
                            }
                        ),
                        json.dumps(
                            {
                                "type": "end",
                                "reason": "finished",
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            with mock.patch.object(
                laglens,
                "FrameViewer",
                FakeViewer,
            ):

                self.window.show_analysis(str(csv_path))

        self.assertEqual(captured["target_fps"], 60)
        self.assertTrue(captured["embedded"])
        self.assertEqual(
            captured["index"].timebase.kind,
            "qpc_ms",
        )
        self.assertTrue(
            captured["index"].timebase.absolute_mapping_trusted
        )
        self.assertAlmostEqual(
            captured["frames"][0]["time"],
            16.7,
        )
        self.assertEqual(
            captured["frames"][0]["sync_quality"],
            "verified_qpc",
        )
        self.assertEqual(
            captured["recheck_slot"],
            self.window.prepare_recheck,
        )

    def test_prepare_recheck_switches_to_live_tab(self):

        self.window.prepare_recheck(
            r"C:\Games\Game.exe"
        )

        self.assertEqual(
            self.window.process_combo.currentText(),
            "Game.exe",
        )
        self.assertEqual(
            self.window.tabs.currentIndex(),
            2,
        )
        self.assertIs(
            self.window.tabs.currentWidget(),
            self.window.live_page,
        )
        self.assertIn(
            "Game.exe",
            self.window.frame_status.text(),
        )

    def test_choose_process_passes_settings_memory(self):

        self.app_settings.set_successful_targets(
            [
                {
                    "path": r"D:\Games\Game.exe",
                    "executable": "Game.exe",
                    "last_success": "2026-11-12T01:00:00",
                }
            ]
        )

        captured = {}

        class FakeDialog:

            def __init__(
                self,
                parent=None,
                remembered_targets=(),
            ):

                captured["remembered"] = (
                    remembered_targets
                )

            def exec(self):

                return laglens.QDialog.DialogCode.Rejected

        with mock.patch.object(
            laglens,
            "ProcessDialog",
            FakeDialog,
        ):

            self.window.choose_process()

        self.assertEqual(
            captured["remembered"],
            self.app_settings.successful_targets,
        )

    def test_launcher_hint_uses_collected_processes(self):

        entries = [
            process_catalog.ProcessEntry(
                pid=1,
                name="Palworld.exe",
                exe=r"D:\Games\Palworld.exe",
            ),
            process_catalog.ProcessEntry(
                pid=2,
                name="Palworld-Win64-Shipping.exe",
                exe=(
                    r"D:\Games"
                    r"\Palworld-Win64-Shipping.exe"
                ),
                has_window=True,
                window_title="Palworld",
                memory_bytes=4 * 1024**3,
            ),
        ]

        with mock.patch.object(
            laglens.process_catalog,
            "collect_processes",
            return_value=entries,
        ):

            hint = self.window.launcher_hint(
                "Palworld.exe",
                ["Palworld-Win64-Shipping.exe"],
            )

        self.assertTrue(hint.suspected)
        self.assertEqual(
            hint.suggested,
            "Palworld-Win64-Shipping.exe",
        )

    def test_missing_csv_is_reported_even_with_exit_code_zero(self):

        with tempfile.TemporaryDirectory() as tmp:

            csv_path = Path(tmp) / "never-created.csv"
            log_path = Path(tmp) / "never-created.log"
            log_path.write_bytes(b"")

            result = capture_core.CaptureResult(
                csv_path=str(csv_path),
                log_path=str(log_path),
                exit_code=0,
                rows=0,
                valid_frames=0,
                error="CSV was not created",
            )

            with mock.patch.object(
                laglens.QMessageBox,
                "warning",
                return_value=None,
            ) as warning:

                self.window.on_capture_completed(result)

            warning.assert_called_once()

            self.assertIn(
                "did not create the csv",
                self.window.frame_status.text().lower(),
            )

            self.assertFalse(
                self.window.analyze_btn.isEnabled()
            )

    def test_access_denied_log_shows_privilege_advice(self):

        with tempfile.TemporaryDirectory() as tmp:

            result = self.make_result(
                tmp,
                "",
                log_bytes=(
                    b"\xff\xfe"
                    + (
                        "error: failed to start trace session: "
                        "access denied.\n"
                    ).encode("utf-16-le")
                ),
                exit_code=6,
            )

            with mock.patch.object(
                laglens.QMessageBox,
                "warning",
                return_value=None,
            ):

                self.window.on_capture_completed(result)

            self.assertIn(
                "administrator",
                self.window.frame_status.text().lower(),
            )

    def test_cancelled_capture_does_not_warn(self):

        with tempfile.TemporaryDirectory() as tmp:

            log_path = Path(tmp) / "cancel.log"
            log_path.write_bytes(
                b"LagLens: capture cancelled before "
                b"PresentMon started.\n"
            )

            result = capture_core.CaptureResult(
                csv_path=str(Path(tmp) / "cancel.csv"),
                log_path=str(log_path),
                exit_code=-1,
                error=(
                    "Capture cancelled before PresentMon started."
                ),
            )

            with mock.patch.object(
                laglens.QMessageBox,
                "warning",
                return_value=None,
            ) as warning:

                self.window.on_capture_completed(result)

            warning.assert_not_called()

            self.assertIn(
                "cancelled",
                self.window.frame_status.text().lower(),
            )

    def test_truncated_capture_is_usable_and_reported(self):

        with tempfile.TemporaryDirectory() as tmp:

            csv_path = Path(tmp) / "capture.csv"

            csv_path.write_text(
                HEADER
                + "\n"
                + ROW
                + "\n"
                + ROW
                + "\n"
                + ROW[:40],
                encoding="utf-8",
            )

            log_path = Path(tmp) / "truncated.log"
            log_path.write_bytes(b"")

            result = capture_core.CaptureResult(
                csv_path=str(csv_path),
                log_path=str(log_path),
                exit_code=0,
                rows=3,
                valid_frames=2,
            )

            self.window.on_capture_completed(result)

            self.assertTrue(
                self.window.analyze_btn.isEnabled()
            )

            status = self.window.frame_status.text().lower()

            self.assertIn("saved 2 frames", status)
            self.assertIn("truncated", status)

    def test_close_while_capturing_does_not_block_the_gui(self):

        self.window.show()

        worker = FakeWorker()
        self.window.worker = worker

        started = time.monotonic()
        self.window.close()
        elapsed = time.monotonic() - started

        self.assertLess(elapsed, 0.5)
        self.assertTrue(worker.stopped)

        # The window stays open until the worker has really stopped.
        self.assertTrue(self.window.isVisible())
        self.assertIn(
            "stopping",
            self.window.frame_status.text().lower(),
        )

        worker.running = False
        self.window.on_worker_finished()
        QApplication.processEvents()

        self.assertFalse(self.window.isVisible())

    def test_force_close_after_watchdog_kills_the_wait(self):

        self.window.show()

        worker = FakeWorker()
        self.window.worker = worker
        self.window._closing = True

        self.window.force_close()

        self.assertTrue(worker.stopped)
        self.assertGreaterEqual(worker.wait_calls, 1)
        self.assertTrue(self.window._close_done)
        self.assertFalse(self.window.isVisible())

    def test_close_without_capture_is_immediate(self):

        self.window.show()

        self.window.close()

        self.assertFalse(self.window.isVisible())
        self.assertTrue(self.window._close_done)

    def test_stop_on_exit_is_off_by_default(self):

        self.assertFalse(
            self.window.stop_on_exit.isChecked()
        )

    def test_target_watcher_stops_after_the_target_exits(self):

        worker = FakeWorker()
        self.window.worker = worker
        self.window.capture_target = "douyin.exe"
        self.window._target_seen = False

        with mock.patch.object(
            self.window,
            "is_process_running",
            return_value=True,
        ):

            self.window.check_target_alive()

        self.assertTrue(self.window._target_seen)
        self.assertFalse(worker.stopped)

        with mock.patch.object(
            self.window,
            "is_process_running",
            return_value=False,
        ), mock.patch.object(
            self.window,
            "stop_capture",
        ) as stop:

            self.window.check_target_alive()

        stop.assert_called_once()

        self.assertIn(
            "exited",
            self.window.frame_status.text().lower(),
        )

        self.window.worker = None

    def test_target_watcher_ignores_a_target_never_seen(self):

        self.window.worker = FakeWorker()
        self.window.capture_target = "douyin.exe"
        self.window._target_seen = False

        with mock.patch.object(
            self.window,
            "is_process_running",
            return_value=False,
        ), mock.patch.object(
            self.window,
            "stop_capture",
        ) as stop:

            self.window.check_target_alive()

        stop.assert_not_called()

        self.window.worker = None

    def test_live_status_shows_elapsed_and_size(self):

        with tempfile.TemporaryDirectory() as tmp:

            csv_path = Path(tmp) / "live.csv"
            csv_path.write_bytes(b"x" * 2048)

            self.window.worker = mock.Mock(
                csv_path=csv_path
            )
            self.window.capture_started = (
                time.monotonic() - 65
            )

            self.window.on_batch(
                ([10.0, 16.0], 42)
            )

            status = self.window.frame_status.text()

            self.assertIn("42 frames", status)
            self.assertIn("min", status)
            self.assertIn("MB", status)

            self.window.worker = None

    def test_large_capture_file_is_warned_once(self):

        with tempfile.TemporaryDirectory() as tmp:

            csv_path = Path(tmp) / "live.csv"
            csv_path.write_bytes(b"x" * 2048)

            self.window.worker = mock.Mock(
                csv_path=csv_path
            )
            self.window.capture_started = time.monotonic()

            with mock.patch.object(
                laglens,
                "CAPTURE_SIZE_WARN_BYTES",
                100,
            ), self.assertLogs(
                "laglens",
                level="WARNING",
            ):

                self.window.on_batch(
                    ([10.0], 1)
                )

                first = self.window.frame_status.text()

                self.window.on_batch(
                    ([11.0], 2)
                )

                second = self.window.frame_status.text()

            self.assertIn(
                "large capture",
                first.lower(),
            )
            self.assertNotIn(
                "large capture",
                second.lower(),
            )

            self.window.worker = None

    def test_low_disk_space_is_reported_without_deleting(self):

        with tempfile.TemporaryDirectory() as tmp:

            csv_path = Path(tmp) / "live.csv"
            csv_path.write_bytes(b"x" * 2048)

            self.window.worker = mock.Mock(
                csv_path=csv_path
            )
            self.window.capture_started = time.monotonic()

            with mock.patch.object(
                laglens.shutil,
                "disk_usage",
                return_value=mock.Mock(
                    free=100 * 1024**2
                ),
            ), self.assertLogs(
                "laglens",
                level="WARNING",
            ):

                self.window.on_batch(
                    ([10.0], 1)
                )

            status = self.window.frame_status.text()

            self.assertIn("low disk", status.lower())
            self.assertIn(
                "deleted automatically",
                status.lower(),
            )
            self.assertTrue(csv_path.exists())

            self.window.worker = None

    def _mock_process_names(self, names):

        return mock.patch.object(
            laglens.psutil,
            "process_iter",
            return_value=[
                FakeProcess(name)
                for name in names
            ],
        )

    def test_refresh_processes_drops_a_stale_selection(self):

        self.window.process_combo.setCurrentText(
            "Palworld.exe"
        )

        with self._mock_process_names(
            ["Palworld-Win64-Shipping.exe"]
        ):

            self.window.refresh_processes()

        self.assertEqual(
            self.window.process_combo.currentText(),
            "",
        )
        self.assertEqual(
            self.window.process_combo.currentIndex(),
            -1,
        )

    def test_refresh_processes_keeps_a_running_selection(self):

        self.window.process_combo.setCurrentText(
            "Palworld.exe"
        )

        with self._mock_process_names(
            [
                "Palworld.exe",
                "Palworld-Win64-Shipping.exe",
            ]
        ):

            self.window.refresh_processes()

        self.assertEqual(
            self.window.process_combo.currentText(),
            "Palworld.exe",
        )
        self.assertGreaterEqual(
            self.window.process_combo.currentIndex(),
            0,
        )

    def test_refresh_processes_does_not_invent_a_target(self):

        self.window.process_combo.setCurrentText(
            "Stale.exe"
        )

        with self._mock_process_names(
            ["Palworld.exe"]
        ):

            self.window.refresh_processes()

        self.assertEqual(
            self.window.process_combo.currentText(),
            "",
        )

    def test_similar_process_names(self):

        names = [
            "Palworld.exe",
            "Palworld-Win64-Shipping.exe",
            "explorer.exe",
        ]

        self.assertEqual(
            laglens.similar_process_names(
                "Palworld.exe",
                names,
            ),
            ["Palworld-Win64-Shipping.exe"],
        )

        self.assertEqual(
            laglens.similar_process_names(
                "palworld.exe",
                names,
            ),
            ["Palworld-Win64-Shipping.exe"],
        )

        self.assertEqual(
            laglens.similar_process_names(
                "explorer.exe",
                names,
            ),
            [],
        )

    def test_similar_target_confirmation_can_cancel(self):

        hint = process_catalog.RendererHint(
            target="Palworld.exe",
            similar=("Palworld-Win64-Shipping.exe",),
            suggested="Palworld-Win64-Shipping.exe",
            target_visible=False,
            suspected=True,
        )

        with mock.patch.object(
            self.window,
            "similar_targets",
            return_value=[
                "Palworld-Win64-Shipping.exe"
            ],
        ), mock.patch.object(
            self.window,
            "launcher_hint",
            return_value=hint,
        ), mock.patch.object(
            laglens.QMessageBox,
            "question",
            return_value=(
                laglens.QMessageBox.StandardButton.Cancel
            ),
        ) as question:

            self.assertFalse(
                self.window.confirm_similar_target(
                    "Palworld.exe"
                )
            )

        question.assert_called_once()

        text = question.call_args.args[2]

        self.assertIn(
            "Palworld-Win64-Shipping.exe",
            text,
        )
        self.assertIn("Possible renderer", text)
        self.assertIn("launcher", text.lower())

    def test_similar_target_confirmation_can_continue(self):

        hint = process_catalog.RendererHint(
            target="Palworld.exe",
            similar=("Palworld-Win64-Shipping.exe",),
            suggested="Palworld-Win64-Shipping.exe",
            target_visible=False,
            suspected=True,
        )

        with mock.patch.object(
            self.window,
            "similar_targets",
            return_value=[
                "Palworld-Win64-Shipping.exe"
            ],
        ), mock.patch.object(
            self.window,
            "launcher_hint",
            return_value=hint,
        ), mock.patch.object(
            laglens.QMessageBox,
            "question",
            return_value=(
                laglens.QMessageBox.StandardButton.Yes
            ),
        ):

            self.assertTrue(
                self.window.confirm_similar_target(
                    "Palworld.exe"
                )
            )

    def test_renderer_target_skips_confirmation(self):

        hint = process_catalog.RendererHint(
            target="Palworld-Win64-Shipping.exe",
            similar=("Palworld.exe",),
            suggested="",
            target_visible=True,
            suspected=False,
        )

        with mock.patch.object(
            self.window,
            "similar_targets",
            return_value=["Palworld.exe"],
        ), mock.patch.object(
            self.window,
            "launcher_hint",
            return_value=hint,
        ), mock.patch.object(
            laglens.QMessageBox,
            "question",
        ) as question:

            self.assertTrue(
                self.window.confirm_similar_target(
                    "Palworld-Win64-Shipping.exe"
                )
            )

        question.assert_not_called()

    def test_similar_target_without_suggestion_uses_no_hint_message(self):

        hint = process_catalog.RendererHint(
            target="Palworld.exe",
            similar=("Palworld-Win64-Shipping.exe",),
            suggested="",
            target_visible=False,
            suspected=True,
        )

        with mock.patch.object(
            self.window,
            "similar_targets",
            return_value=[
                "Palworld-Win64-Shipping.exe"
            ],
        ), mock.patch.object(
            self.window,
            "launcher_hint",
            return_value=hint,
        ), mock.patch.object(
            laglens.QMessageBox,
            "question",
            return_value=(
                laglens.QMessageBox.StandardButton.Cancel
            ),
        ) as question:

            self.window.confirm_similar_target(
                "Palworld.exe"
            )

        text = question.call_args.args[2]

        self.assertIn(
            "Palworld-Win64-Shipping.exe",
            text,
        )
        self.assertNotIn("Possible renderer", text)

    def test_no_similar_target_skips_confirmation(self):

        with mock.patch.object(
            self.window,
            "similar_targets",
            return_value=[],
        ), mock.patch.object(
            laglens.QMessageBox,
            "question",
        ) as question:

            self.assertTrue(
                self.window.confirm_similar_target(
                    "Palworld.exe"
                )
            )

        question.assert_not_called()

    def test_no_frames_hint_lists_similar_processes(self):

        self.window.worker = object()
        self.window.frames_received = False
        self.window.capture_target = "Palworld.exe"

        with mock.patch.object(
            self.window,
            "similar_targets",
            return_value=[
                "Palworld-Win64-Shipping.exe"
            ],
        ):

            self.window.on_no_frames_yet()

        status = self.window.frame_status.text()

        self.assertIn("Palworld.exe", status)
        self.assertIn(
            "Palworld-Win64-Shipping.exe",
            status,
        )

        self.window.worker = None

    def test_zero_frame_failure_mentions_similar_processes(self):

        with tempfile.TemporaryDirectory() as tmp:

            csv_path = Path(tmp) / "capture.csv"
            csv_path.write_text(HEADER + "\n", encoding="utf-8")

            log_path = Path(tmp) / "capture.log"
            log_path.write_bytes(b"")

            result = capture_core.CaptureResult(
                csv_path=str(csv_path),
                log_path=str(log_path),
                exit_code=0,
                rows=0,
                valid_frames=0,
                error="CSV contains a header but no frame rows",
            )

            self.window.capture_target = "Palworld.exe"

            hint = process_catalog.RendererHint(
                target="Palworld.exe",
                similar=(
                    "Palworld-Win64-Shipping.exe",
                ),
                suggested="Palworld-Win64-Shipping.exe",
                target_visible=False,
                suspected=True,
            )

            with mock.patch.object(
                self.window,
                "similar_targets",
                return_value=[
                    "Palworld-Win64-Shipping.exe"
                ],
            ), mock.patch.object(
                self.window,
                "launcher_hint",
                return_value=hint,
            ), mock.patch.object(
                laglens.QMessageBox,
                "warning",
                return_value=None,
            ) as warning:

                self.window.on_capture_completed(result)

            message = warning.call_args.args[2]

            self.assertIn(
                "Palworld-Win64-Shipping.exe",
                message,
            )
            self.assertIn("Possible renderer", message)
            self.assertIn(
                "launcher",
                message.lower(),
            )

    def test_no_frames_hint_until_first_batch(self):

        self.window.worker = object()
        self.window.frames_received = False
        self.window.capture_target = "douyin.exe"

        self.window.on_no_frames_yet()

        self.assertIn(
            "No frames from douyin.exe",
            self.window.frame_status.text(),
        )

        # Once a frame arrived the hint must not overwrite LIVE.
        self.window.frames_received = True
        self.window.frame_status.setText("LIVE - 10 captured frame records")

        self.window.on_no_frames_yet()

        self.assertIn(
            "LIVE",
            self.window.frame_status.text(),
        )

        self.window.worker = None

    def test_forced_stop_is_mentioned(self):

        with tempfile.TemporaryDirectory() as tmp:

            result = self.make_result(
                tmp,
                HEADER + "\n" + ROW + "\n",
                forced_stop=True,
            )

            self.window.on_capture_completed(result)

            status = self.window.frame_status.text()

            self.assertIn("Saved 1 frames", status)
            self.assertIn("forced stop", status)


if __name__ == "__main__":

    unittest.main(verbosity=2)
