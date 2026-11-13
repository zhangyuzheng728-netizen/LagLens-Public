
"""LagLens v0.4.1 - Live Performance Monitor."""

import csv
import logging
import math
import os
import shutil
import statistics
import subprocess
import sys
import threading
import time

from collections import defaultdict, deque
from logging.handlers import RotatingFileHandler
from pathlib import Path

import psutil
import pynvml

from PySide6.QtCore import (
    QPointF,
    QRectF,
    Qt,
    QThread,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from capture_core import (
    CaptureResult,
    CsvTailer,
    LONG_FRAME_MS,
    NO_WINDOW,
    SESSION,
    build_capture_command,
    build_terminate_command,
    etw_warnings,
    failure_code,
    is_elevated,
    normalize_target,
    read_capture_log,
    safe_capture_name,
    start_stale_session_cleanup,
    summarize_log,
    validate_capture,
)
import frame_timebase
import process_catalog
import runtime_paths
import swap_chains
import ui_theme
from hardware_sampler import (  # noqa: E402
    HardwareSampler,
    LOW_OVERHEAD_INTERVAL_S,
)
from frame_viewer import FrameViewer
from process_dialog import ProcessDialog
from i18n import (
    detect_system_language,
    get_manager,
    install_qt_translator,
    tr,
)
from settings import AppSettings, user_data_dir
from win32_support import (
    ProcessJob,
    SingleInstanceGuard,
)


logger = logging.getLogger("laglens")


def similar_process_names(target, names):
    """Return executables whose name extends the selected stem.

    Example: ``Palworld.exe`` and ``Palworld-Win64-Shipping.exe`` are
    two different processes; selecting the launcher produces an empty
    capture.  Only the longer, separated name is reported.
    """

    target_name = (target or "").strip().lower()

    if not target_name:

        return []

    if not target_name.endswith(".exe"):

        target_name += ".exe"

    stem = target_name[:-4]

    similar = []

    for name in names:

        candidate = (name or "").strip()

        if not candidate:

            continue

        lower = candidate.lower()

        if not lower.endswith(".exe") or lower == target_name:

            continue

        candidate_stem = lower[:-4]

        if any(
            candidate_stem.startswith(
                stem + separator
            )
            for separator in ("-", "_", ".")
        ):

            similar.append(candidate)

    return sorted(similar, key=str.lower)


# ==========================================
# Configuration
# ==========================================

ROOT = runtime_paths.app_dir()
CAPTURES = (
    user_data_dir() / "captures"
    if runtime_paths.is_frozen()
    else ROOT / "captures"
)
LOGS = (
    user_data_dir() / "logs"
    if runtime_paths.is_frozen()
    else CAPTURES
)

# Long-session hints only; LagLens never deletes capture data.
CAPTURE_SIZE_WARN_BYTES = 2 * 1024**3
DISK_FREE_WARN_BYTES = 1 * 1024**3


def default_presentmon_path():
    """Return the bundled PresentMon path, with an environment override."""

    override = os.environ.get("LAGLENS_PRESENTMON")

    if override:

        return Path(override)

    base = ROOT if runtime_paths.is_frozen() else ROOT / "vendor"

    return (
        base
        / "presentmon"
        / "PresentMon-2.6.0-x64.exe"
    )


DEFAULT_PRESENTMON = default_presentmon_path()

# ==========================================
# Reusable live chart
# ==========================================

class LiveChart(QWidget):

    def __init__(
        self,
        unit="%",
        length=60,
        ceiling=None
    ):
        super().__init__()

        self.unit = unit
        self.samples = deque(maxlen=length)
        self.ceiling = ceiling

        ui_theme.apply_chart_typography(self)

        self.setMinimumHeight(230)

    def add(self, value, alert=False):

        self.samples.append(
            (float(value), bool(alert))
        )

        self.update()

    def reset(self):

        self.samples.clear()
        self.update()

    def paintEvent(self, event):

        painter = QPainter(self)

        painter.setRenderHint(
            QPainter.RenderHint.Antialiasing,
            True,
        )
        painter.setRenderHint(
            QPainter.RenderHint.TextAntialiasing,
            True,
        )

        metrics = QFontMetrics(self.font())
        line_height = metrics.height()

        peak = max(
            (value for value, _ in self.samples),
            default=0.0
        )

        scale = self.ceiling or max(
            50,
            math.ceil(peak * 1.15 / 25) * 25
        )

        labels = [
            f"{scale * n / 4:.0f}{self.unit}"
            for n in range(5)
        ]

        left = max(
            metrics.horizontalAdvance(text)
            for text in labels
        ) + 14

        top = line_height + 8

        right = max(
            left + 1,
            self.width() - 16
        )

        bottom = max(
            top + 1,
            self.height() - line_height - 8
        )

        width = right - left
        height = bottom - top

        # 1px grid lines stay crisp: no antialiasing and integer y.
        painter.save()
        painter.setRenderHint(
            QPainter.RenderHint.Antialiasing,
            False,
        )
        grid_pen = QPen(
            QColor(ui_theme.CHART["grid"]),
            1,
        )
        grid_pen.setCosmetic(True)
        painter.setPen(grid_pen)

        for n in range(5):

            y = round(
                bottom - n * height / 4
            )

            painter.drawLine(
                QPointF(left, y),
                QPointF(right, y),
            )

        painter.restore()

        # Axis labels use the same font metrics as the gutter.
        painter.setPen(QColor(ui_theme.CHART["axis"]))

        for n, text in enumerate(labels):

            y = bottom - n * height / 4
            rect = QRectF(
                0,
                y - line_height / 2,
                max(1, left - 10),
                line_height,
            )

            painter.drawText(
                rect,
                Qt.AlignmentFlag.AlignRight
                | Qt.AlignmentFlag.AlignVCenter,
                text,
            )

        x_rect = QRectF(
            left,
            bottom + 4,
            width,
            line_height,
        )

        painter.drawText(
            x_rect,
            Qt.AlignmentFlag.AlignLeft
            | Qt.AlignmentFlag.AlignVCenter,
            tr("chart.older"),
        )
        painter.drawText(
            x_rect,
            Qt.AlignmentFlag.AlignRight
            | Qt.AlignmentFlag.AlignVCenter,
            tr("chart.now"),
        )

        # Calculate curve coordinates
        points = []

        for i, (value, _) in enumerate(
            self.samples
        ):

            x = (
                right
                - (len(self.samples) - 1 - i)
                * width
                / max(1, self.samples.maxlen - 1)
            )

            y = (
                bottom
                - min(value, scale)
                / scale * height
            )

            points.append(
                QPointF(x, y)
            )

        # Curves stay antialiased; cosmetic pens ignore DPR scaling.
        if len(points) > 1:

            line_pen = QPen(
                QColor(ui_theme.CHART["line"]),
                2,
            )
            line_pen.setCosmetic(True)
            painter.setPen(line_pen)

            painter.drawPolyline(
                QPolygonF(points)
            )

        # Draw dots
        painter.setPen(
            Qt.PenStyle.NoPen
        )

        for point, (_, alert) in zip(
            points,
            self.samples
        ):

            painter.setBrush(
                QColor(
                    ui_theme.CHART["alert"]
                    if alert
                    else ui_theme.CHART["line"]
                )
            )

            radius = 5 if alert else 3

            painter.drawEllipse(
                point,
                radius,
                radius
            )

        painter.end()


class CardGrid(QWidget):
    """Responsive grid for KPI cards."""

    def __init__(
        self,
        minimum_card_width=210,
        parent=None,
    ):

        super().__init__(parent)

        self._minimum_card_width = minimum_card_width
        self._cards = []
        self._columns = 0

        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(ui_theme.SPACE["md"])

    def add_card(self, card):

        card.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        self._cards.append(card)
        self._reflow(force=True)

    def column_count(self):

        if not self._cards:

            return 0

        return max(
            1,
            min(
                len(self._cards),
                max(1, self.width())
                // self._minimum_card_width,
            ),
        )

    def _reflow(self, force=False):

        columns = self.column_count()

        if not force and columns == self._columns:

            return

        self._columns = columns

        for card in self._cards:

            self.grid.removeWidget(card)

        for index, card in enumerate(self._cards):

            self.grid.addWidget(
                card,
                index // columns,
                index % columns,
            )

        for column in range(len(self._cards)):

            self.grid.setColumnStretch(
                column,
                1 if column < columns else 0,
            )

    def resizeEvent(self, event):

        super().resizeEvent(event)
        self._reflow()


# ==========================================
# PresentMon background worker
# ==========================================

class CaptureWorker(QThread):

    batch = Signal(object)

    # CaptureResult carries the CSV path, exit code, row counts, ETW
    # warnings and any forced-stop/error state in one object.
    completed = Signal(object)

    def __init__(
        self,
        executable,
        target,
        csv_path,
        low_overhead=False,
        job=None,
        telemetry=None,
        qpc_time=False,
        capture_started_monotonic_ns=None,
    ):
        super().__init__()

        self.executable = str(executable)
        self.target = target
        self.csv_path = Path(csv_path)
        self.low_overhead = bool(low_overhead)
        self.qpc_time = bool(qpc_time)
        self.capture_started_monotonic_ns = (
            capture_started_monotonic_ns
        )

        # Optional ProcessJob: kills PresentMon if LagLens crashes.
        self.job = job

        # Optional C-1 sampler.  Timing attributes stay on the worker so
        # the main thread can hand them to the sidecar after completion.
        self.telemetry = telemetry
        self.presentmon_started_monotonic_ns = None
        self.first_csv_row_monotonic_ns = None
        self.last_csv_row_monotonic_ns = None
        self.first_cpu_start_ms = None
        self.last_cpu_start_ms = None
        self.first_raw_time_ms = None
        self.last_raw_time_ms = None
        self.time_column = None
        self.frame_timebase = None
        self.qpc_clock_delta_ms = None
        self.qpc_frequency_hz = None

        self.session = SESSION

        # Guards the PresentMon process handle.
        self._lock = threading.Lock()
        self._process = None

        self.stop_event = threading.Event()
        self._forced_stop = False

    @property
    def process(self):

        with self._lock:

            return self._process

    # --------------------------------------
    # Request graceful shutdown
    # --------------------------------------

    def stop(self):
        """Ask the capture to stop.

        The worker may be blocked reading PresentMon's stdout, so the
        process is terminated from this helper thread instead.
        """

        self.stop_event.set()

        threading.Thread(
            target=self._request_stop,
            daemon=True,
            name="LagLensCaptureStop",
        ).start()

    def _wait_for_process(self, timeout):

        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:

            proc = self.process

            if proc is not None:

                return proc

            if self.isFinished():

                return None

            time.sleep(0.05)

        return self.process

    def _request_stop(self):

        process = self._wait_for_process(6.0)

        if (
            process is None
            or process.poll() is not None
        ):

            return

        self._forced_stop = self._stop_process(
            process
        )

    def _terminate_session(self):
        """Ask PresentMon to close its own ETW session."""

        try:

            subprocess.run(
                build_terminate_command(
                    self.executable,
                    self.session,
                ),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=3,
                creationflags=NO_WINDOW,
            )

        except (
            OSError,
            subprocess.TimeoutExpired
        ):

            logger.warning(
                "Could not terminate ETW session %s",
                self.session,
                exc_info=True,
            )

    def _wait_for_exit(self, process, timeout):
        """Poll a process for up to timeout seconds."""

        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:

            code = process.poll()

            if code is not None:

                return code

            time.sleep(0.1)

        return None

    def _stop_process(self, process):
        """Stop PresentMon, returning True if a hard kill was needed."""

        if process.poll() is not None:

            return False

        # Preferred path: stop the ETW session so PresentMon can flush
        # and close its CSV cleanly.
        self._terminate_session()

        if self._wait_for_exit(process, 4) is not None:

            return False

        logger.warning(
            "PresentMon did not exit after session termination; "
            "terminating process"
        )

        try:

            process.terminate()

        except OSError:

            pass

        if self._wait_for_exit(process, 2) is not None:

            return True

        logger.warning("PresentMon did not terminate; killing process")

        try:

            process.kill()

        except OSError:

            pass

        self._wait_for_exit(process, 1)

        return True

    # --------------------------------------
    # Start capture and follow the CSV file
    # --------------------------------------

    def run(self):

        result = CaptureResult(
            csv_path=str(self.csv_path),
            log_path=str(
                self.csv_path.with_suffix(".log")
            ),
        )

        log_path = Path(result.log_path)

        log_handle = None
        process = None
        headers = None

        chunks = defaultdict(list)
        last_emit = time.monotonic()
        count = 0

        if self.capture_started_monotonic_ns is None:

            self.capture_started_monotonic_ns = (
                time.perf_counter_ns()
            )

        try:

            self.csv_path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            if self.stop_event.is_set():

                log_path.write_bytes(
                    b"LagLens: capture cancelled before "
                    b"PresentMon started.\n"
                )

                result.error = (
                    "Capture cancelled before "
                    "PresentMon started."
                )

                return

            # A stale file must never be mistaken for this capture's
            # output.  PresentMon creates the file itself.
            try:

                self.csv_path.unlink(
                    missing_ok=True
                )

            except OSError:

                pass

            command = build_capture_command(
                self.executable,
                self.session,
                self.target,
                self.low_overhead,
                qpc_time=self.qpc_time,
            )

            logger.info(
                "Starting PresentMon: %s",
                command,
            )

            log_handle = log_path.open("wb")

            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=log_handle,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=NO_WINDOW,
            )

            self.presentmon_started_monotonic_ns = (
                time.perf_counter_ns()
            )

            if self.qpc_time:

                self.qpc_clock_delta_ms = (
                    frame_timebase.qpc_clock_delta_ms()
                )
                self.qpc_frequency_hz = (
                    frame_timebase.qpc_frequency_hz()
                )

            if self.telemetry is not None:

                try:

                    self.telemetry.note_presentmon_started(
                        self.presentmon_started_monotonic_ns
                    )

                except Exception as error:  # pragma: no cover - defensive

                    logger.debug(
                        "telemetry PresentMon marker failed: %s",
                        type(error).__name__,
                    )

            with self._lock:

                self._process = process

            if self.job is not None:

                if self.job.assign(process):

                    logger.info(
                        "PresentMon assigned to job object"
                    )

                else:

                    logger.warning(
                        "Could not assign PresentMon to the job "
                        "object (job error: %s); continuing "
                        "without crash protection",
                        getattr(self.job, "error", ""),
                    )

            # Read stdout directly.  Starting a helper Python thread
            # inside a QThread run() deadlocked under the test suite,
            # so stop() owns that thread instead: it terminates the
            # ETW session/process, which closes the pipe and ends this
            # loop naturally.
            with self.csv_path.open(
                "w",
                newline="",
                encoding="utf-8",
            ) as output:

                for raw in process.stdout:

                    line = raw.lstrip("\ufeff").strip()

                    if line and headers is None:

                        if line.startswith(
                            "Application,"
                        ):

                            headers = next(
                                csv.reader([line])
                            )

                            self.time_column = (
                                frame_timebase.detect_time_column(
                                    headers
                                )
                            )

                            if (
                                self.time_column
                                == frame_timebase.QPC_MS_COLUMN
                            ):

                                self.frame_timebase = (
                                    frame_timebase
                                    .qpc_timebase_for_capture(
                                        self.capture_started_monotonic_ns,
                                        self.qpc_clock_delta_ms,
                                        self.qpc_frequency_hz,
                                    )
                                )

                            elif (
                                self.time_column
                                == frame_timebase.LEGACY_TIME_COLUMN
                            ):

                                self.frame_timebase = (
                                    frame_timebase.legacy_timebase()
                                )

                            else:

                                self.frame_timebase = (
                                    frame_timebase.unknown_timebase(
                                        "PresentMon CSV has no "
                                        "supported time column"
                                    )
                                )

                            output.write(line + "\n")

                        continue

                    if line and headers is not None:

                        try:

                            fields = next(
                                csv.reader([line])
                            )

                        except csv.Error:

                            fields = None

                        if (
                            fields is not None
                            and len(fields) == len(headers)
                        ):

                            row = dict(
                                zip(headers, fields)
                            )

                            try:

                                frame_time = float(
                                    row["FrameTime"]
                                )

                                raw_start_time = float(
                                    row[self.time_column]
                                )

                            except (
                                KeyError,
                                TypeError,
                                ValueError,
                            ):

                                frame_time = None
                                raw_start_time = None

                            start_time = None

                            if (
                                raw_start_time is not None
                                and self.frame_timebase is not None
                            ):

                                try:

                                    if (
                                        self.frame_timebase.kind
                                        == "qpc_ms"
                                        and self.frame_timebase
                                        .origin_qpc_ms is None
                                    ):

                                        self.frame_timebase = (
                                            self.frame_timebase
                                            .with_origin(
                                                raw_start_time,
                                                "first_frame",
                                                "inferred_qpc",
                                                note=(
                                                    frame_timebase
                                                    .QPC_FIRST_FRAME_NOTE
                                                ),
                                            )
                                        )

                                    start_time = (
                                        self.frame_timebase
                                        .normalize(
                                            raw_start_time
                                        )
                                    )

                                except (TypeError, ValueError):

                                    start_time = None

                            if (
                                frame_time is not None
                                and math.isfinite(
                                    frame_time
                                )
                                and frame_time > 0
                                and start_time is not None
                                and math.isfinite(
                                    start_time
                                )
                            ):

                                row_now_ns = (
                                    time.perf_counter_ns()
                                )

                                if (
                                    self.first_csv_row_monotonic_ns
                                    is None
                                ):

                                    self.first_csv_row_monotonic_ns = (
                                        row_now_ns
                                    )
                                    self.first_cpu_start_ms = (
                                        start_time
                                    )
                                    self.first_raw_time_ms = (
                                        raw_start_time
                                    )

                                self.last_csv_row_monotonic_ns = (
                                    row_now_ns
                                )
                                self.last_cpu_start_ms = start_time
                                self.last_raw_time_ms = (
                                    raw_start_time
                                )

                                output.write(
                                    line + "\n"
                                )

                                count += 1

                                chunks[
                                    (
                                        row.get("ProcessID"),
                                        row.get(
                                            "SwapChainAddress"
                                        ),
                                    )
                                ].append(frame_time)

                    now = time.monotonic()

                    if now - last_emit >= 0.5:

                        if chunks:

                            values = max(
                                chunks.values(),
                                key=len,
                            )

                            self.batch.emit(
                                (values[:], count)
                            )

                            chunks.clear()

                            output.flush()

                        last_emit = now

                if chunks:

                    self.batch.emit(
                        (
                            max(
                                chunks.values(),
                                key=len,
                            )[:],
                            count,
                        )
                    )

                output.flush()

            try:

                result.exit_code = process.wait(
                    timeout=5
                )

            except subprocess.TimeoutExpired:

                result.error = (
                    "PresentMon did not exit after the "
                    "capture stopped."
                )

            if log_handle is not None:

                log_handle.close()
                log_handle = None

            info = validate_capture(
                self.csv_path
            )

            result.rows = info.rows
            result.valid_frames = (
                info.valid_frames
            )
            result.forced_stop = self._forced_stop

            if result.exit_code is None:

                result.exit_code = -1

            if info.error and not result.error:

                result.error = info.error

            result.etw_warnings = etw_warnings(
                read_capture_log(log_path)
            )

            logger.info(
                "Capture finished: exit=%s rows=%s valid=%s "
                "forced=%s warnings=%s",
                result.exit_code,
                result.rows,
                result.valid_frames,
                result.forced_stop,
                result.etw_warnings,
            )

        except Exception as error:

            result.error = (
                f"{type(error).__name__}: {error}"
            )

            logger.exception(
                "Capture worker failed"
            )

        finally:

            if (
                process is not None
                and process.poll() is None
            ):

                try:

                    process.kill()
                    process.wait(timeout=2)

                except (
                    OSError,
                    subprocess.TimeoutExpired
                ):

                    pass

            with self._lock:

                self._process = None

            if log_handle is not None:

                try:

                    log_handle.close()

                except OSError:

                    pass

            self.completed.emit(result)


# ==========================================
# Main application window
# ==========================================

class LagLens(QWidget):

    def __init__(self, gpu, job=None, settings=None):

        super().__init__()

        ui_theme.ensure_application_theme()

        self.gpu = gpu

        # Optional ProcessJob shared by every capture worker.
        self.job = job

        self.settings = (
            settings
            if settings is not None
            else AppSettings()
        )

        # Widgets registered for language re-translation.
        self._bindings = []

        self._tab_keys = (
            "tab.hardware",
            "tab.live",
            "tab.analysis",
            "tab.settings",
        )

        self._status_spec = None
        self._hw_status_spec = None
        self._last_count = 0
        self._last_success = None
        self._last_failure = None
        self._card_labels = {}

        self.worker = None
        self.viewer = None
        self.last_csv = None
        self.capture_target = None
        self._pending_auto_analysis = None
        self._active_analysis_path = None
        self._active_analysis_name = ""
        self._active_analysis_target = ""
        self.live_page = None
        self.analysis_page = None
        self.analysis_stack = None
        self.analysis_container = None
        self.analysis_container_layout = None
        self.live_scroll = None
        self.onboarding_card = None
        self.onboarding_steps = []
        self.recent_list = None

        # C-1 telemetry state.  Failure to create a sidecar never blocks
        # the PresentMon capture.
        self.sampler = None
        self._telemetry_outcome = "unknown"
        self._telemetry_reason = "finished"

        # True as soon as the current capture has produced a frame.
        self.frames_received = False

        # Asynchronous close state.
        self._closing = False
        self._close_done = False

        self.spikes = 0

        self.capture_started = None
        self._size_warned = False
        self._disk_warned = False

        # Target watcher for "Stop when target exits".  PresentMon
        # 2.6's --terminate_on_proc_exit does not work (verified), so
        # LagLens polls the process itself.
        self._target_seen = False

        self.frame_history = deque(
            maxlen=180
        )

        self.setObjectName("root")

        self.setWindowTitle(tr("app.title"))

        self.resize(1180, 900)
        self.setMinimumSize(980, 760)

        root = QVBoxLayout(self)

        root.setContentsMargins(
            ui_theme.SPACE["xl"],
            ui_theme.SPACE["xl"],
            ui_theme.SPACE["xl"],
            ui_theme.SPACE["xl"],
        )

        # Application title
        self.heading = QLabel()

        self.heading.setObjectName(
            "brand"
        )

        self._bind(self.heading, "app.brand")

        ui_theme.apply_font(self.heading, "display")

        root.addWidget(self.heading)

        # Tabs
        self.tabs = QTabWidget()

        self.tabs.tabBar().setFont(
            ui_theme.font("label")
        )

        root.addWidget(
            self.tabs
        )

        self.build_hardware_tab()
        self.build_frames_tab()
        self.build_analysis_tab()
        self.build_settings_tab()

        ui_theme.apply_muted_labels(self)

        self._status_spec = (
            (
                "status.ready_admin"
                if is_elevated()
                else "status.ready_no_admin"
            ),
            {},
        )

        self._apply_status()

        get_manager().language_changed.connect(
            self.retranslate
        )

        # Hardware monitoring timer
        psutil.cpu_percent(
            interval=None
        )

        self.timer = QTimer(self)

        self.timer.timeout.connect(
            self.update_hardware
        )

        self.timer.start(1000)

        # Warn once when a capture has started but the target has
        # not presented anything yet (PresentMon writes no CSV row
        # until the first present event).
        self.no_frame_timer = QTimer(self)

        self.no_frame_timer.setSingleShot(True)

        self.no_frame_timer.timeout.connect(
            self.on_no_frames_yet
        )

        # Last-resort timer: never let closing hang forever if a
        # worker refuses to stop.
        self.close_watchdog = QTimer(self)

        self.close_watchdog.setSingleShot(True)

        self.close_watchdog.timeout.connect(
            self.force_close
        )

        self.target_watch_timer = QTimer(self)

        self.target_watch_timer.setInterval(1000)

        self.target_watch_timer.timeout.connect(
            self.check_target_alive
        )

        self.update_hardware()

    # --------------------------------------
    # Create metric card
    # --------------------------------------

    def card(self, name_key):

        frame = QFrame()

        frame.setObjectName(
            "card"
        )

        box = QVBoxLayout(frame)

        box.setContentsMargins(
            ui_theme.SPACE["lg"],
            ui_theme.SPACE["lg"],
            ui_theme.SPACE["lg"],
            ui_theme.SPACE["lg"],
        )

        label = QLabel()

        label.setObjectName(
            "muted"
        )

        self._bind(label, name_key)

        ui_theme.apply_font(label, "caption")

        self._card_labels[name_key] = label

        value = QLabel("--")

        value.setObjectName(
            "value"
        )

        ui_theme.apply_font(value, "metric")

        box.addWidget(label)
        box.addWidget(value)
        box.addStretch()

        return frame, value

    # --------------------------------------
    # Page/card helpers
    # --------------------------------------

    def make_card(self, title_key=None, subtitle_key=None):

        frame = QFrame()
        frame.setObjectName("card")

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(
            ui_theme.SPACE["lg"],
            ui_theme.SPACE["lg"],
            ui_theme.SPACE["lg"],
            ui_theme.SPACE["lg"],
        )
        layout.setSpacing(ui_theme.SPACE["md"])

        if title_key is not None:

            title = QLabel()
            self._bind(title, title_key)
            ui_theme.apply_font(title, "subheading")
            layout.addWidget(title)

        if subtitle_key is not None:

            subtitle = QLabel()
            self._bind(subtitle, subtitle_key)
            subtitle.setObjectName("muted")
            subtitle.setWordWrap(True)
            ui_theme.apply_font(subtitle, "caption")
            layout.addWidget(subtitle)

        return frame, layout

    def page_with_scroll(self, content, footer=None):

        content.setObjectName("pageContent")

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(ui_theme.SPACE["lg"])
        layout.addWidget(scroll, 1)

        if footer is not None:

            layout.addWidget(footer)

        return page

    # --------------------------------------
    # Hardware tab
    # --------------------------------------

    def build_hardware_tab(self):

        content = QWidget()
        body = QVBoxLayout(content)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(ui_theme.SPACE["xl"])

        title = QLabel()
        self._bind(title, "hardware.metrics.title")
        ui_theme.apply_font(title, "subheading")
        body.addWidget(title)

        grid = CardGrid(210)
        self.hardware_grid = grid
        self.hw = {}

        metrics = [
            ("gpu", "hardware.card.gpu"),
            ("cpu", "hardware.card.cpu"),
            ("vram", "hardware.card.vram"),
            ("ram", "hardware.card.ram"),
            ("temp", "hardware.card.temp"),
        ]

        for key, name_key in metrics:

            frame, value = self.card(name_key)
            self.hw[key] = value
            grid.add_card(frame)

        body.addWidget(grid)

        chart_frame, chart_box = self.make_card(
            "hardware.chart_title"
        )

        self.gpu_chart = LiveChart(
            "%",
            length=60,
            ceiling=100
        )

        chart_box.addWidget(self.gpu_chart, 1)
        body.addWidget(chart_frame, 1)

        footer = QWidget()
        bottom = QHBoxLayout(footer)
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.setSpacing(ui_theme.SPACE["sm"])

        self.hw_status = QLabel()
        self.hw_status.setObjectName("muted")
        self.set_hw_status("hardware.loading")
        bottom.addWidget(self.hw_status, 1)

        open_csv = QPushButton()
        self._bind(open_csv, "common.open_csv")
        ui_theme.set_button_variant(open_csv, "secondary")
        open_csv.clicked.connect(self.open_csv)
        bottom.addWidget(open_csv)

        page = self.page_with_scroll(content, footer)

        self.tabs.addTab(
            page, tr("tab.hardware")
        )

    # --------------------------------------
    # Live Frames tab
    # --------------------------------------

    def build_frames_tab(self):

        content = QWidget()
        body = QVBoxLayout(content)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(ui_theme.SPACE["xl"])

        self.onboarding_card = self.build_onboarding_card()

        try:

            onboarding_seen = self.settings.onboarding_seen

        except Exception:  # pragma: no cover - defensive UI

            onboarding_seen = False

        self.onboarding_card.setVisible(
            not onboarding_seen
        )
        body.addWidget(self.onboarding_card)

        capture_frame, capture_layout = self.make_card(
            "live.capture.title",
            "live.capture.subtitle",
        )

        # Process picker
        picker = QHBoxLayout()
        picker.setSpacing(ui_theme.SPACE["sm"])

        target_label = QLabel()
        self._bind(target_label, "live.target_process")
        picker.addWidget(target_label)

        self.process_combo = QComboBox()
        self.process_combo.setEditable(True)
        picker.addWidget(self.process_combo, 1)
        target_label.setBuddy(self.process_combo)

        self.choose_process_btn = QPushButton()
        self._bind(self.choose_process_btn, "live.choose_process")
        self._bind(
            self.choose_process_btn,
            "live.choose_process.tip",
            method="setToolTip",
        )
        self.choose_process_btn.clicked.connect(self.choose_process)

        self.refresh_processes_btn = QPushButton()
        self._bind(
            self.refresh_processes_btn,
            "common.refresh_processes",
        )
        self.refresh_processes_btn.clicked.connect(
            self.refresh_processes
        )
        ui_theme.set_button_variant(
            self.refresh_processes_btn,
            "ghost",
        )
        capture_layout.addLayout(picker)

        # PresentMon path
        path_row = QHBoxLayout()
        path_row.setSpacing(ui_theme.SPACE["sm"])

        presentmon_label = QLabel()
        self._bind(presentmon_label, "live.presentmon")
        path_row.addWidget(presentmon_label)

        self.exe_input = QLineEdit(str(DEFAULT_PRESENTMON))
        path_row.addWidget(self.exe_input, 1)
        presentmon_label.setBuddy(self.exe_input)

        browse = QPushButton()
        self._bind(browse, "common.browse")
        browse.clicked.connect(self.browse_exe)
        path_row.addWidget(browse)
        capture_layout.addLayout(path_row)

        # Capture controls
        controls = QHBoxLayout()
        controls.setSpacing(ui_theme.SPACE["sm"])

        self.start_btn = QPushButton()
        self._bind(self.start_btn, "common.start")
        ui_theme.set_button_variant(self.start_btn, "primary")

        self.stop_btn = QPushButton()
        self._bind(self.stop_btn, "common.stop")

        self.analyze_btn = QPushButton()
        self._bind(self.analyze_btn, "common.analyze")

        self.stop_btn.setEnabled(False)
        self.analyze_btn.setEnabled(False)

        self.start_btn.clicked.connect(self.start_capture)
        self.stop_btn.clicked.connect(self.stop_capture)
        self.analyze_btn.clicked.connect(self.analyze_last)

        for widget in (
            self.start_btn,
            self.stop_btn,
            self.analyze_btn,
        ):
            controls.addWidget(widget)

        self.quickstart_btn = QPushButton()
        self._bind(
            self.quickstart_btn,
            "onboarding.show",
        )
        ui_theme.set_button_variant(
            self.quickstart_btn,
            "ghost",
        )
        self.quickstart_btn.clicked.connect(
            self.show_onboarding
        )

        controls.addStretch()
        controls.addWidget(self.quickstart_btn)
        capture_layout.addLayout(controls)

        selection_controls = QHBoxLayout()
        selection_controls.setSpacing(ui_theme.SPACE["sm"])
        selection_controls.addWidget(self.choose_process_btn)
        selection_controls.addWidget(self.refresh_processes_btn)
        selection_controls.addStretch()
        capture_layout.addLayout(selection_controls)

        options = QHBoxLayout()
        options.setSpacing(ui_theme.SPACE["lg"])

        self.auto_analyze = QCheckBox()
        self._bind(self.auto_analyze, "live.auto_analyze")
        self._bind(
            self.auto_analyze,
            "live.auto_analyze.tip",
            method="setToolTip",
        )
        self.auto_analyze.setChecked(True)
        options.addWidget(self.auto_analyze)

        self.low_overhead = QCheckBox()
        self._bind(self.low_overhead, "live.low_overhead")
        self._bind(
            self.low_overhead,
            "live.low_overhead.tip",
            method="setToolTip",
        )
        options.addWidget(self.low_overhead)

        self.stop_on_exit = QCheckBox()
        self._bind(self.stop_on_exit, "live.stop_on_exit")
        self._bind(
            self.stop_on_exit,
            "live.stop_on_exit.tip",
            method="setToolTip",
        )
        options.addWidget(self.stop_on_exit)

        options.addStretch()
        capture_layout.addLayout(options)

        qpc_options = QHBoxLayout()
        qpc_options.setSpacing(ui_theme.SPACE["lg"])

        self.qpc_time = QCheckBox()
        self._bind(self.qpc_time, "live.qpc_time")
        self._bind(
            self.qpc_time,
            "live.qpc_time.tip",
            method="setToolTip",
        )
        qpc_options.addWidget(self.qpc_time)
        qpc_options.addStretch()
        capture_layout.addLayout(qpc_options)

        body.addWidget(capture_frame)

        recent_frame, recent_layout = self.make_card(
            "recent.title",
            "recent.subtitle",
        )

        self.recent_list = QListWidget()
        self.recent_list.setWordWrap(True)
        self.recent_list.setSpacing(2)
        self.recent_list.setMinimumHeight(0)
        self.recent_list.setMaximumHeight(260)
        self.recent_list.setResizeMode(
            QListView.ResizeMode.Adjust
        )
        self.recent_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        ui_theme.apply_font(self.recent_list, "body")
        self.recent_list.itemClicked.connect(
            self.open_recent_capture
        )
        recent_layout.addWidget(self.recent_list)
        body.addWidget(recent_frame)

        metrics_title = QLabel()
        self._bind(metrics_title, "live.metrics.title")
        ui_theme.apply_font(metrics_title, "subheading")
        body.addWidget(metrics_title)

        grid = CardGrid(210)
        self.live_metric_grid = grid
        self.fm = {}

        metrics = [
            ("fps", "metric.fps"),
            ("mean", "metric.mean"),
            ("peak", "metric.peak"),
            ("spikes", "metric.spikes"),
        ]

        for key, name_key in metrics:

            frame, value = self.card(name_key)
            self.fm[key] = value
            grid.add_card(frame)

        body.addWidget(grid)

        chart_frame, chart_box = self.make_card(
            "live.chart_title"
        )

        self.frame_chart = LiveChart(" ms", length=100)
        chart_box.addWidget(self.frame_chart, 1)
        body.addWidget(chart_frame, 1)

        self.frame_status = QLabel()
        self.frame_status.setObjectName("muted")
        self.frame_status.setWordWrap(True)

        disclaimer = QLabel()
        self._bind(disclaimer, "live.disclaimer")
        disclaimer.setObjectName("muted")
        disclaimer.setWordWrap(True)

        footer = QWidget()
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.setSpacing(ui_theme.SPACE["xs"])
        footer_layout.addWidget(self.frame_status)
        footer_layout.addWidget(disclaimer)

        page = self.page_with_scroll(content, footer)

        self.live_scroll = page.findChild(QScrollArea)
        self.live_page = page

        self.tabs.addTab(
            page, tr("tab.live")
        )

        self.refresh_recent_captures()
        self.refresh_processes()

    def build_onboarding_card(self):

        frame, layout = self.make_card(
            "onboarding.title",
            "onboarding.subtitle",
        )

        self.onboarding_steps = []

        for key in (
            "onboarding.step1",
            "onboarding.step2",
            "onboarding.step3",
        ):

            label = QLabel()
            self._bind(label, key)
            label.setWordWrap(True)
            ui_theme.apply_font(label, "body")
            self.onboarding_steps.append(label)
            layout.addWidget(label)

        actions = QHBoxLayout()
        actions.addStretch()

        self.onboarding_dismiss_btn = QPushButton()
        self._bind(
            self.onboarding_dismiss_btn,
            "onboarding.dismiss",
        )
        ui_theme.set_button_variant(
            self.onboarding_dismiss_btn,
            "secondary",
        )
        self.onboarding_dismiss_btn.clicked.connect(
            self.dismiss_onboarding
        )
        actions.addWidget(self.onboarding_dismiss_btn)
        layout.addLayout(actions)

        return frame

    def show_onboarding(self):

        if self.onboarding_card is None:

            return

        self.onboarding_card.setVisible(True)

        if self.live_scroll is not None:

            self.live_scroll.ensureWidgetVisible(
                self.onboarding_card
            )

    def dismiss_onboarding(self):

        if self.onboarding_card is not None:

            self.onboarding_card.setVisible(False)

        try:

            self.settings.set_onboarding_seen(True)

        except Exception as error:  # pragma: no cover - defensive UI

            logger.debug(
                "cannot save onboarding state: %s",
                error,
            )

    def _recent_capture_text(self, record):

        path = Path(record["path"])
        captured = record.get("captured_at", "") or ""

        if "T" in captured:

            captured = captured.replace("T", " ")[:19]

        text = tr(
            "recent.item",
            target=record.get("target") or path.stem,
            time=captured or tr("recent.unknown_time"),
            frames=record.get("frames", 0),
        )
        flags = []

        if not path.is_file():

            flags.append(tr("recent.missing"))

        elif not Path(
            str(path) + ".telemetry.jsonl"
        ).is_file():

            flags.append(tr("recent.no_telemetry"))

        if flags:

            text += " · " + " · ".join(flags)

        return f"{record.get('name') or path.name}\n{text}"

    def _fit_recent_list_height(self):

        count = self.recent_list.count()

        if count <= 0:

            height = 36

        else:

            self.recent_list.doItemsLayout()
            row_height = max(
                max(
                    self.recent_list.sizeHintForRow(index),
                    self.recent_list.visualItemRect(
                        self.recent_list.item(index)
                    ).height(),
                )
                for index in range(count)
            )

            if row_height <= 0:

                row_height = (
                    self.recent_list.fontMetrics().height()
                    + 8
                )

            height = (
                row_height * count
                + 2 * self.recent_list.frameWidth()
                + 8
            )

        self.recent_list.setFixedHeight(
            max(36, min(height, 260))
        )

    def refresh_recent_captures(self):

        if self.recent_list is None:

            return

        self.recent_list.blockSignals(True)
        self.recent_list.clear()

        try:

            records = self.settings.recent_captures

        except Exception as error:  # pragma: no cover - defensive UI

            logger.debug(
                "cannot read recent captures: %s",
                error,
            )
            records = []

        if not records:

            self.recent_list.addItem(
                tr("recent.empty")
            )
            self.recent_list.setEnabled(False)

        else:

            self.recent_list.setEnabled(True)

            for record in records:

                self.recent_list.addItem(
                    self._recent_capture_text(record)
                )
                item = self.recent_list.item(
                    self.recent_list.count() - 1
                )
                item.setData(
                    Qt.ItemDataRole.UserRole,
                    record["path"],
                )

        self._fit_recent_list_height()
        self.recent_list.blockSignals(False)

    def open_recent_capture(self, item):

        path = item.data(Qt.ItemDataRole.UserRole)

        if not path:

            return

        capture_path = Path(path)

        if not capture_path.is_file():

            QMessageBox.warning(
                self,
                tr("recent.missing.title"),
                tr(
                    "recent.missing.message",
                    name=capture_path.name,
                ),
            )
            self.refresh_recent_captures()
            return

        info = validate_capture(capture_path)

        if not info.ok:

            QMessageBox.warning(
                self,
                tr("recent.invalid.title"),
                tr(
                    "recent.invalid.message",
                    name=capture_path.name,
                ),
            )
            self.refresh_recent_captures()
            return

        self.show_analysis(str(capture_path))

    # --------------------------------------
    # Embedded analysis page
    # --------------------------------------

    def build_analysis_tab(self):

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(ui_theme.SPACE["md"])

        self.analysis_header = QWidget()
        header_layout = QHBoxLayout(
            self.analysis_header
        )
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(
            ui_theme.SPACE["md"]
        )

        self.analysis_file_label = QLabel()
        self.analysis_file_label.setWordWrap(True)
        ui_theme.apply_font(
            self.analysis_file_label,
            "label",
            weight=QFont.Weight.DemiBold,
        )
        header_layout.addWidget(
            self.analysis_file_label,
            1,
        )

        self.analysis_target_label = QLabel()
        self.analysis_target_label.setObjectName("muted")
        self.analysis_target_label.setWordWrap(True)
        ui_theme.apply_font(
            self.analysis_target_label,
            "caption",
        )
        header_layout.addWidget(
            self.analysis_target_label
        )

        self.analysis_header.setVisible(False)
        layout.addWidget(self.analysis_header)

        self.analysis_stack = QStackedWidget()
        layout.addWidget(self.analysis_stack, 1)

        empty = QWidget()
        empty_layout = QVBoxLayout(empty)
        empty_layout.setContentsMargins(
            ui_theme.SPACE["xl"],
            ui_theme.SPACE["xl"],
            ui_theme.SPACE["xl"],
            ui_theme.SPACE["xl"],
        )
        empty_layout.setSpacing(ui_theme.SPACE["md"])
        empty_layout.addStretch()

        empty_label = QLabel()
        self._bind(
            empty_label,
            "analysis.page.empty",
        )
        empty_label.setWordWrap(True)
        empty_label.setAlignment(
            Qt.AlignmentFlag.AlignHCenter
        )
        empty_label.setObjectName("muted")
        ui_theme.apply_font(empty_label, "body")
        empty_layout.addWidget(empty_label)

        empty_actions = QHBoxLayout()
        empty_actions.setSpacing(
            ui_theme.SPACE["sm"]
        )
        empty_actions.addStretch()

        open_analysis_csv = QPushButton()
        self._bind(
            open_analysis_csv,
            "analysis.page.open_csv",
        )
        ui_theme.set_button_variant(
            open_analysis_csv,
            "secondary",
        )
        open_analysis_csv.clicked.connect(
            self.open_csv
        )
        empty_actions.addWidget(open_analysis_csv)

        go_live = QPushButton()
        self._bind(
            go_live,
            "analysis.page.go_live",
        )
        ui_theme.set_button_variant(go_live, "ghost")
        go_live.clicked.connect(
            lambda: self.tabs.setCurrentWidget(
                self.live_page
            )
        )
        empty_actions.addWidget(go_live)
        empty_actions.addStretch()
        empty_layout.addLayout(empty_actions)
        empty_layout.addStretch()
        self.analysis_stack.addWidget(empty)

        self.analysis_container = QWidget()
        self.analysis_container_layout = QVBoxLayout(
            self.analysis_container
        )
        self.analysis_container_layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )
        self.analysis_container_layout.setSpacing(0)
        self.analysis_stack.addWidget(
            self.analysis_container
        )
        self.analysis_stack.setCurrentWidget(empty)

        self.analysis_page = page
        self.tabs.addTab(
            page, tr("tab.analysis")
        )

    # --------------------------------------
    # Settings tab and language switching
    # --------------------------------------

    def build_settings_tab(self):

        content = QWidget()
        outer = QHBoxLayout(content)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(1)

        column = QWidget()
        column.setFixedWidth(780)
        column.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Preferred,
        )

        body = QVBoxLayout(column)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(ui_theme.SPACE["xl"])

        title = QLabel()
        self._bind(title, "settings.title")
        ui_theme.apply_font(title, "heading")
        title.setObjectName("settingsHeading")
        body.addWidget(title)

        appearance, appearance_layout = self.make_card(
            "settings.appearance.title"
        )

        row = QHBoxLayout()
        row.setSpacing(ui_theme.SPACE["sm"])

        language_label = QLabel()
        self._bind(language_label, "settings.language")
        row.addWidget(language_label)

        self.language_combo = QComboBox()
        self.language_combo.addItem(
            tr("settings.language.system"),
            "system",
        )
        self.language_combo.addItem("简体中文", "zh_CN")
        self.language_combo.addItem("English", "en")
        self.language_combo.currentIndexChanged.connect(
            self.on_language_changed
        )
        self.language_combo.setMaximumWidth(360)
        language_label.setBuddy(self.language_combo)
        row.addWidget(self.language_combo)
        row.addStretch()

        appearance_layout.addLayout(row)

        note = QLabel()
        self._bind(note, "settings.language.note")
        note.setObjectName("muted")
        note.setWordWrap(True)
        appearance_layout.addWidget(note)

        body.addWidget(appearance)

        data_card, data_layout = self.make_card(
            "settings.data.title"
        )

        data_rows = QVBoxLayout()
        data_rows.setContentsMargins(0, 0, 0, 0)
        data_rows.setSpacing(ui_theme.SPACE["md"])

        for label_key, value_text, object_name in (
            (
                "settings.data.settings",
                str(self.settings.path),
                "settingsPathValue",
            ),
            (
                "settings.data.captures",
                str(CAPTURES),
                "capturesPathValue",
            ),
        ):

            row_widget = QWidget()
            row_widget.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Preferred,
            )
            row_layout = QVBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(ui_theme.SPACE["xs"])

            label = QLabel()
            self._bind(label, label_key)
            ui_theme.apply_font(label, "label")
            row_layout.addWidget(label)

            value = QLabel(value_text)
            value.setObjectName(object_name)
            value.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Preferred,
            )

            if object_name == "settingsPathValue":

                self.settings_path_value = value

            else:

                self.captures_path_value = value

            value.setWordWrap(False)
            value.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            ui_theme.apply_font(value, "mono_caption")
            value.setProperty("tone", "muted")
            value.setToolTip(value_text)
            row_layout.addWidget(value)

            data_rows.addWidget(row_widget)

        data_layout.addLayout(data_rows)

        body.addWidget(data_card)
        body.addStretch()

        outer.addWidget(column)
        outer.addStretch(1)

        page = self.page_with_scroll(content)

        self.tabs.addTab(
            page, tr("tab.settings")
        )

        self._sync_language_combo()

    def _sync_language_combo(self):

        if not hasattr(self, "language_combo"):

            return

        mode = self.settings.language_mode

        index = self.language_combo.findData(mode)

        if index < 0:

            index = 0

        # These three labels are fixed identifiers; only the system
        # option is translated (the other two are native names).
        self.language_combo.blockSignals(True)

        self.language_combo.setItemText(
            0,
            tr("settings.language.system"),
        )
        self.language_combo.setItemText(1, "简体中文")
        self.language_combo.setItemText(2, "English")
        self.language_combo.setCurrentIndex(index)

        self.language_combo.blockSignals(False)

    def on_language_changed(self, _index):

        mode = self.language_combo.currentData()

        if mode not in ("system", "zh_CN", "en"):

            return

        self.settings.set_language_mode(mode)

        get_manager().set_mode(
            mode,
            system_locale=detect_system_language(),
        )

        # No signal is emitted when the resolved language did not
        # change (for example system -> zh_CN on Chinese Windows).
        self._sync_language_combo()

    def _bind(
        self,
        widget,
        key,
        method="setText",
        **kwargs,
    ):

        self._bindings.append(
            (widget, key, method, kwargs)
        )

        getattr(widget, method)(
            tr(key, **kwargs)
        )

        return widget

    def set_status(self, key, **kwargs):

        self._status_spec = (key, kwargs)

        self.frame_status.setText(
            tr(key, **kwargs)
        )

    def _apply_status(self):

        if self._status_spec is None:

            return

        key, kwargs = self._status_spec

        self.frame_status.setText(
            tr(key, **kwargs)
        )

    def set_hw_status(self, key, **kwargs):

        self._hw_status_spec = (key, kwargs)

        self.hw_status.setText(
            tr(key, **kwargs)
        )

    def _render_hw_status(self):

        if self._hw_status_spec is None:

            return

        key, kwargs = self._hw_status_spec

        self.hw_status.setText(
            tr(key, **kwargs)
        )

    def retranslate(self):
        """Refresh text only; never touch capture state or data."""

        self.setWindowTitle(tr("app.title"))

        for widget, key, method, kwargs in self._bindings:

            getattr(widget, method)(
                tr(key, **kwargs)
            )

        for index, key in enumerate(self._tab_keys):

            if index < self.tabs.count():

                self.tabs.setTabText(
                    index,
                    tr(key),
                )

        self._sync_language_combo()
        self._render_hw_status()

        if self.viewer is not None:

            self._update_analysis_header()

        if (
            self.worker is not None
            and self.worker.isRunning()
        ):

            self.update_capture_status(
                self._last_count
            )

        elif self._last_success is not None:

            self._render_success()

        elif self._last_failure is not None:

            result, info = self._last_failure

            message = self._build_failure_message(
                result,
                info,
            )

            self.frame_status.setText(
                message.split("\n\n")[0]
            )

        else:

            self._apply_status()

        self.refresh_recent_captures()
        self.gpu_chart.update()
        self.frame_chart.update()

    def _localized_warnings(self, info):

        warnings = []

        if info.trailing_partial:

            warnings.append(tr("quality.truncated"))

        if info.bad_field_rows:

            warnings.append(
                tr(
                    "quality.bad_fields",
                    count=info.bad_field_rows,
                )
            )

        if info.na_rows:

            warnings.append(
                tr("quality.na", count=info.na_rows)
            )

        if info.nonnumeric_rows:

            warnings.append(
                tr(
                    "quality.non_numeric",
                    count=info.nonnumeric_rows,
                )
            )

        if info.nonpositive_rows:

            warnings.append(
                tr(
                    "quality.non_positive",
                    count=info.nonpositive_rows,
                )
            )

        if info.nonfinite_rows:

            warnings.append(
                tr(
                    "quality.non_finite",
                    count=info.nonfinite_rows,
                )
            )

        if info.long_frames:

            warnings.append(
                tr(
                    "quality.long_frames",
                    count=info.long_frames,
                    threshold=int(LONG_FRAME_MS),
                )
            )

        return warnings

    def _render_success(self):

        if self._last_success is None:

            return

        result, info = self._last_success

        message = tr(
            "status.saved",
            frames=info.valid_frames,
            name=Path(result.csv_path).name,
        )

        separator = tr("status.separator")

        if result.forced_stop:

            message += separator + tr(
                "status.forced_stop"
            )

        if result.error:

            message += separator + tr(
                "status.warning",
                detail=result.error,
            )

        warnings = self._localized_warnings(info)

        if warnings:

            message += separator + tr(
                "status.csv_warning",
                detail="; ".join(warnings),
            )

        etw = (
            result.etw_warnings
            or etw_warnings(
                read_capture_log(result.log_path)
            )
        )

        if etw:

            message += separator + tr(
                "status.etw_warning",
                detail="; ".join(etw),
            )

        self.frame_status.setText(message)

    def _build_failure_message(self, result, info):

        log = read_capture_log(result.log_path)

        target = (
            self.capture_target
            or tr("failure.target_default")
        )

        code = failure_code(
            log,
            result.exit_code,
            info,
        )

        message = tr(
            "failure." + code,
            exit_code=result.exit_code,
            target=target,
            detail=info.error or "",
        )

        if (
            result.error
            and result.error not in message
        ):

            message += "\n\n" + tr(
                "failure.detail",
                detail=result.error,
            )

        detail = summarize_log(log)

        if detail:

            message += "\n\n" + tr(
                "failure.presentmon",
                detail=detail,
            )

        warnings = (
            result.etw_warnings
            or etw_warnings(log)
        )

        if warnings:

            message += "\n\n" + tr(
                "status.etw_warning",
                detail="; ".join(warnings),
            )

        # Palworld-style failure: the selected executable (launcher)
        # is running but does not present.  Name the candidates and
        # suggest a likely renderer without switching silently.
        target = self.capture_target or ""
        similar = self.similar_targets(target)

        if similar:

            hint = self.launcher_hint(target, similar)

            if hint.suggested:

                message += "\n\n" + tr(
                    "failure.similar_suggested",
                    similar=", ".join(hint.similar),
                    suggested=hint.suggested,
                )

            else:

                message += "\n\n" + tr(
                    "failure.similar",
                    similar=", ".join(hint.similar),
                )

        return message

    # --------------------------------------
    # Process picker dialog (B-2/B-3)
    # --------------------------------------

    def set_target_controls_enabled(self, enabled):
        """Keep the target picker consistent with the worker state."""

        self.process_combo.setEnabled(enabled)
        self.choose_process_btn.setEnabled(enabled)
        self.refresh_processes_btn.setEnabled(enabled)

    def choose_process(self):
        """Open the selection dialog; only the target text changes."""

        if (
            self.worker
            and self.worker.isRunning()
        ):

            return

        remembered = ()

        try:

            remembered = self.settings.successful_targets

        except Exception as error:  # pragma: no cover - defensive UI

            logger.debug(
                "cannot read successful targets: %s",
                error,
            )

        dialog = ProcessDialog(
            self,
            remembered_targets=remembered,
        )

        if (
            dialog.exec()
            != QDialog.DialogCode.Accepted
        ):

            return

        entry = dialog.selected_entry()

        if entry is not None:

            self.process_combo.setCurrentText(
                entry.name
            )

    # --------------------------------------
    # Refresh process list
    # --------------------------------------

    def refresh_processes(self):

        if (
            self.worker
            and self.worker.isRunning()
        ):

            return

        previous = (
            self.process_combo.currentText()
            .strip()
        )

        names = set()

        for process in psutil.process_iter(
            ["name"]
        ):

            try:

                name = process.info["name"]

                if (
                    name
                    and name.lower().endswith(".exe")
                ):
                    names.add(name)

            except (
                psutil.NoSuchProcess,
                psutil.AccessDenied
            ):
                pass

        self.process_combo.clear()

        self.process_combo.addItems(
            sorted(names, key=str.lower)
        )

        # Keep the previous selection only if it still exists.  An
        # editable combo would otherwise keep displaying a stale name
        # while the list shows the currently running processes.
        previous = next(
            (
                name for name in names
                if name.lower() == previous.lower()
            ),
            "",
        ) if previous else ""

        if previous:

            self.process_combo.setCurrentText(previous)

            return

        # Do not invent a process name.  Leave the field empty and
        # let the user choose from the refreshed list.
        self.process_combo.setCurrentIndex(-1)
        self.process_combo.setCurrentText("")

    @staticmethod
    def is_process_running(target):

        wanted = target.lower()

        for process in psutil.process_iter(
            ["name"]
        ):

            try:

                name = process.info["name"]

                if (
                    name
                    and name.lower() == wanted
                ):

                    return True

            except (
                psutil.NoSuchProcess,
                psutil.AccessDenied
            ):

                pass

        return False

    @staticmethod
    def similar_targets(target):

        names = []

        for process in psutil.process_iter(
            ["name"]
        ):

            try:

                name = process.info["name"]

            except (
                psutil.NoSuchProcess,
                psutil.AccessDenied
            ):

                continue

            if name:

                names.append(name)

        return similar_process_names(target, names)

    def launcher_hint(self, target, similar):
        """Return a renderer hint without changing the target."""

        try:

            entries = process_catalog.collect_processes()

        except Exception as error:  # pragma: no cover - defensive UI

            logger.debug(
                "cannot build launcher hint: %s",
                error,
                exc_info=True,
            )

            entries = []

        return process_catalog.renderer_hint(
            target,
            similar,
            entries,
        )

    def confirm_similar_target(self, target):
        """Ask before capturing a process with a similarly named sibling.

        Launchers such as Palworld.exe run alongside the rendering
        Palworld-Win64-Shipping.exe and produce no frames.  The dialog
        names both and suggests a likely renderer; it never switches
        the target silently.
        """

        similar = self.similar_targets(target)

        if not similar:

            return True

        hint = self.launcher_hint(target, similar)

        if not hint.suspected:

            return True

        if hint.suggested:

            message = tr(
                "dialog.similar.message",
                target=target,
                similar=", ".join(hint.similar),
                suggested=hint.suggested,
            )

        else:

            message = tr(
                "dialog.similar.message_no_hint",
                target=target,
                similar=", ".join(hint.similar),
            )

        answer = QMessageBox.question(
            self,
            tr("dialog.similar.title"),
            message,
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )

        return (
            answer
            == QMessageBox.StandardButton.Yes
        )

    # --------------------------------------
    # Browse PresentMon
    # --------------------------------------

    def browse_exe(self):

        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("dialog.choose_presentmon"),
            str(
                DEFAULT_PRESENTMON.parent
                if DEFAULT_PRESENTMON.parent.is_dir()
                else ROOT
            ),
            tr("dialog.filter.executable"),
        )

        if path:
            self.exe_input.setText(path)

    # --------------------------------------
    # Restart with an elevated token
    # --------------------------------------

    def relaunch_as_admin(self):

        try:

            import ctypes

            if getattr(sys, "frozen", False):

                executable = sys.executable
                arguments = ""

            else:

                executable = sys.executable
                arguments = (
                    f'"{Path(sys.argv[0]).resolve()}"'
                )

            result = ctypes.windll.shell32.ShellExecuteW(
                None,
                "runas",
                executable,
                arguments,
                str(ROOT),
                1,
            )

        except (
            AttributeError,
            OSError
        ) as error:

            QMessageBox.warning(
                self,
                tr("dialog.restart_failed.title"),
                tr(
                    "dialog.restart_failed.message",
                    detail=str(error),
                ),
            )

            return

        if result <= 32:

            QMessageBox.warning(
                self,
                tr("dialog.restart_failed.title"),
                tr(
                    "dialog.restart_failed.refused",
                    code=result,
                ),
            )

            return

        self.close()

    # --------------------------------------
    # C-1 telemetry lifecycle
    # --------------------------------------

    def _start_telemetry(
        self,
        csv_path,
        target,
        low_overhead,
        qpc_time=False,
    ):

        try:

            interval_ms = (
                self.settings.telemetry_interval_ms
            )

        except Exception:  # pragma: no cover - defensive

            interval_ms = 250

        if low_overhead:

            interval_ms = max(
                interval_ms,
                int(LOW_OVERHEAD_INTERVAL_S * 1000),
            )

        try:

            sampler = HardwareSampler(
                csv_path=csv_path,
                target_name=target,
                interval_s=interval_ms / 1000.0,
                low_overhead=low_overhead,
                qpc_time=qpc_time,
                gpu_handle=self.gpu,
                gpu_index=0,
            )

            if not sampler.start():

                logger.debug(
                    "telemetry unavailable for %s: %s",
                    Path(csv_path).name,
                    sampler.write_error,
                )

                return None

            self.sampler = sampler
            self._telemetry_outcome = "unknown"
            self._telemetry_reason = "finished"

            return sampler

        except Exception as error:  # pragma: no cover - defensive

            logger.debug(
                "telemetry start failed for %s: %s",
                Path(csv_path).name,
                type(error).__name__,
            )

            return None

    def _note_telemetry(self, info, worker):

        if self.sampler is None or worker is None:

            return

        outcome = (
            "valid"
            if info is not None and info.ok
            else (
                "invalid"
                if info is not None
                else "cancelled"
            )
        )

        valid_frames = (
            info.valid_frames
            if info is not None
            else 0
        )

        frame_timebase_info = None
        worker_timebase = getattr(
            worker,
            "frame_timebase",
            None,
        )

        if worker_timebase is not None:

            try:

                frame_timebase_info = (
                    worker_timebase.with_range(
                        getattr(
                            worker,
                            "first_raw_time_ms",
                            None,
                        ),
                        getattr(
                            worker,
                            "last_raw_time_ms",
                            None,
                        ),
                    ).to_dict()
                )

            except Exception as error:  # pragma: no cover - defensive

                logger.debug(
                    "frame timebase serialization failed: %s",
                    type(error).__name__,
                )

        try:

            self.sampler.note_capture_timing(
                first_row_monotonic_ns=getattr(
                    worker,
                    "first_csv_row_monotonic_ns",
                    None,
                ),
                last_row_monotonic_ns=getattr(
                    worker,
                    "last_csv_row_monotonic_ns",
                    None,
                ),
                first_cpu_start_ms=getattr(
                    worker,
                    "first_cpu_start_ms",
                    None,
                ),
                last_cpu_start_ms=getattr(
                    worker,
                    "last_cpu_start_ms",
                    None,
                ),
                valid_frames=valid_frames,
                capture_outcome=outcome,
                frame_timebase=frame_timebase_info,
            )

            self._telemetry_outcome = outcome

        except Exception as error:  # pragma: no cover - defensive

            logger.debug(
                "telemetry timing update failed: %s",
                type(error).__name__,
            )

    def _stop_telemetry(self, reason, outcome=None):

        sampler = self.sampler

        if sampler is None:

            return

        self.sampler = None

        if outcome is not None:

            self._telemetry_outcome = outcome

        try:

            sampler.stop(
                reason=reason,
                capture_outcome=self._telemetry_outcome,
            )

        except Exception as error:  # pragma: no cover - defensive

            logger.debug(
                "telemetry stop failed: %s",
                type(error).__name__,
            )

    # --------------------------------------
    # Start capture
    # --------------------------------------

    def start_capture(self):

        if (
            self.worker
            and self.worker.isRunning()
        ):
            return

        self._pending_auto_analysis = None

        target = normalize_target(
            self.process_combo.currentText()
        )

        exe = Path(
            self.exe_input.text()
            .strip()
            .strip('"')
        )

        if not target:

            QMessageBox.warning(
                self,
                tr("dialog.target_process.title"),
                tr("dialog.target_process.empty"),
            )

            return

        if not target.lower().endswith(
            ".exe"
        ):

            QMessageBox.warning(
                self,
                tr("dialog.target_process.title"),
                tr("dialog.target_process.invalid"),
            )

            return

        if not exe.is_file():

            QMessageBox.warning(
                self,
                tr("dialog.presentmon.title"),
                tr("dialog.presentmon.invalid"),
            )

            return

        # A very common cause of a zero-frame capture is simply
        # targeting a process that is not running.  PresentMon can
        # wait for it, so make the choice explicit instead of
        # silently producing an empty CSV.
        self._target_seen = self.is_process_running(
            target
        )

        if not self._target_seen:

            answer = QMessageBox.question(
                self,
                tr("dialog.target_not_running.title"),
                tr(
                    "dialog.target_not_running.message",
                    target=target,
                ),
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )

            if (
                answer
                != QMessageBox.StandardButton.Yes
            ):

                return

        # The selected process is running, but a sibling such as a
        # launcher may be the wrong choice.  Never switch silently.
        if (
            self._target_seen
            and not self.confirm_similar_target(target)
        ):

            return

        # PresentMon cannot create an ETW session
        # without elevation. Offer to restart once,
        # up front, instead of failing silently later.
        if not is_elevated():

            answer = QMessageBox.question(
                self,
                tr("dialog.elevation.title"),
                tr("dialog.elevation.message"),
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes
            )

            if (
                answer
                == QMessageBox.StandardButton.Yes
            ):

                self.relaunch_as_admin()

                return

        self.capture_target = target

        CAPTURES.mkdir(
            exist_ok=True
        )

        csv_path = CAPTURES / safe_capture_name(
            target
        )

        # Reset the live view, but keep the last successful
        # capture available for analysis if this attempt fails.
        self.frame_history.clear()
        self.frame_chart.reset()

        self.spikes = 0
        self.capture_started = time.monotonic()
        self._size_warned = False
        self._disk_warned = False

        for value in self.fm.values():
            value.setText("--")

        self.analyze_btn.setEnabled(
            bool(self.last_csv)
        )

        low_overhead = self.low_overhead.isChecked()
        qpc_time = self.qpc_time.isChecked()

        telemetry = self._start_telemetry(
            csv_path,
            target,
            low_overhead,
            qpc_time=qpc_time,
        )

        # Start worker
        try:

            self.worker = CaptureWorker(
                exe,
                target,
                csv_path,
                low_overhead=low_overhead,
                job=self.job,
                telemetry=telemetry,
                qpc_time=qpc_time,
                capture_started_monotonic_ns=(
                    telemetry.started_monotonic_ns
                    if telemetry is not None
                    else None
                ),
            )

        except Exception:

            self._stop_telemetry(
                "start_failed",
                "failed",
            )
            raise

        self.worker.batch.connect(
            self.on_batch
        )

        self.worker.completed.connect(
            self.on_capture_completed
        )

        self.worker.finished.connect(
            self.on_worker_finished
        )

        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.set_target_controls_enabled(False)

        self._last_success = None
        self._last_failure = None
        self._last_count = 0

        similar = self.similar_targets(target)

        if similar:

            logger.warning(
                "Target %s has similarly named processes "
                "running: %s",
                target,
                ", ".join(similar),
            )

            self.set_status(
                "status.starting_similar",
                target=target,
                similar=", ".join(similar),
            )

        else:

            self.set_status(
                "status.starting",
                target=target,
            )

        self.frames_received = False

        try:

            self.worker.start()

        except Exception:

            self._stop_telemetry(
                "start_failed",
                "failed",
            )
            raise

        self.no_frame_timer.start(6000)

        if self.stop_on_exit.isChecked():

            self.target_watch_timer.start()

    # --------------------------------------
    # Stop capture
    # --------------------------------------

    def stop_capture(self):

        if (
            self.worker
            and self.worker.isRunning()
        ):

            self.stop_btn.setEnabled(False)

            self._telemetry_reason = "requested_stop"

            self.set_status("status.stopping_session")

            self.worker.stop()

    def check_target_alive(self):
        """Stop the capture once the target process has exited."""

        if (
            self.worker is None
            or not self.worker.isRunning()
        ):

            self.target_watch_timer.stop()

            return

        target = self.capture_target

        if not target:

            return

        if self.is_process_running(target):

            self._target_seen = True

            return

        # Never stop before the target was seen at least once: the
        # user may deliberately start the capture first.
        if not self._target_seen:

            return

        self.target_watch_timer.stop()

        self._telemetry_reason = "target_exited"

        self.stop_capture()

        self.set_status(
            "status.target_exited",
            target=target,
        )

    # --------------------------------------
    # Receive live frames
    # --------------------------------------

    def on_no_frames_yet(self):

        if (
            self.worker is None
            or self.frames_received
        ):

            return

        target = (
            self.capture_target
            or "the target process"
        )

        similar = self.similar_targets(target)

        if similar:

            self.set_status(
                "status.no_frames_similar",
                target=target,
                similar=", ".join(similar),
            )

        else:

            self.set_status(
                "status.no_frames",
                target=target,
            )

    def on_batch(self, data):

        worker = self.sender()

        if (
            worker is not None
            and worker is not self.worker
        ):

            return

        values, count = data

        if not values:
            return

        self.frames_received = True

        self.no_frame_timer.stop()

        self.frame_history.extend(
            values
        )

        mean = statistics.mean(
            self.frame_history
        )

        baseline = statistics.median(
            self.frame_history
        )

        # Preliminary anomaly threshold
        threshold = max(
            50.0,
            baseline * 2
        )

        peaks = [
            value for value in values
            if value > threshold
        ]

        self.spikes += len(peaks)

        # Update cards
        self.fm["fps"].setText(
            f"{1000 / mean:.1f}"
        )

        self.fm["mean"].setText(
            f"{mean:.2f} ms"
        )

        self.fm["peak"].setText(
            f"{max(values):.2f} ms"
        )

        self.fm["spikes"].setText(
            str(self.spikes)
        )

        # Update chart
        self.frame_chart.add(
            max(values),
            bool(peaks)
        )

        self.update_capture_status(count)

    def update_capture_status(self, count):
        """Show live size/elapsed and warn about long sessions.

        Only text is refreshed; this never touches capture data or the
        worker.
        """

        self._last_count = count
        self._status_spec = None

        size = 0
        csv_path = None
        worker = self.worker

        if worker is not None:

            csv_path = getattr(worker, "csv_path", None)

            if csv_path is not None:

                try:
                    size = csv_path.stat().st_size
                except OSError:
                    size = 0

        elapsed = 0.0

        if self.capture_started is not None:

            elapsed = (
                time.monotonic() - self.capture_started
            )

        text = tr(
            "status.live",
            frames=count,
            minutes=elapsed / 60.0,
            size=size / 1024**2,
        )

        if (
            size >= CAPTURE_SIZE_WARN_BYTES
            and not self._size_warned
        ):

            self._size_warned = True

            logger.warning(
                "Capture file exceeded %.1f GB: %s",
                CAPTURE_SIZE_WARN_BYTES / 1024**3,
                csv_path,
            )

            text += (
                tr("status.separator")
                + tr("status.large_capture")
            )

        if (
            size
            and csv_path is not None
            and not self._disk_warned
        ):

            try:

                free = shutil.disk_usage(
                    csv_path.parent
                ).free

            except OSError:

                free = None

            if (
                free is not None
                and free < DISK_FREE_WARN_BYTES
            ):

                self._disk_warned = True

                logger.warning(
                    "Low disk space on the capture drive: "
                    "%.1f GB free",
                    free / 1024**3,
                )

                text += (
                    tr("status.separator")
                    + tr("status.low_disk")
                )

        self.frame_status.setText(text)

    # --------------------------------------
    # Capture finished / errors
    # --------------------------------------

    def _remember_success(self, result, info):
        """Record a verified target path after a genuinely usable capture."""

        if not info.ok:

            return []

        target = (self.capture_target or "").strip()

        if not target:

            return []

        try:

            created_before = Path(
                result.csv_path
            ).stat().st_mtime

        except OSError:

            created_before = time.time()

        try:

            return process_catalog.remember_capture_target(
                self.settings,
                target,
                result.csv_path,
                created_before=created_before,
            )

        except Exception as error:  # pragma: no cover - defensive UI

            logger.debug(
                "cannot remember successful target: %s",
                error,
                exc_info=True,
            )

            return []

    def _remember_recent_capture(self, result, info):
        """Store a local recent-capture record; never raise into the UI."""

        if not info.ok:

            return

        path = Path(result.csv_path)
        target = normalize_target(
            self.capture_target
            or self.process_combo.currentText()
            or ""
        )

        record = {
            "path": str(path),
            "name": path.name,
            "target": target,
            "captured_at": time.strftime(
                "%Y-%m-%dT%H:%M:%S"
            ),
            "frames": info.valid_frames,
            "telemetry": Path(
                str(path) + ".telemetry.jsonl"
            ).is_file(),
        }

        try:

            records = self.settings.recent_captures
            records = [
                item
                for item in records
                if item.get("path", "").lower()
                != str(path).lower()
            ]
            self.settings.set_recent_captures(
                [record] + records
            )

        except Exception as error:  # pragma: no cover - defensive UI

            logger.debug(
                "cannot remember recent capture: %s",
                error,
                exc_info=True,
            )

        self.refresh_recent_captures()

    def on_capture_completed(self, result):

        worker = self.sender() or self.worker

        # Ignore a late result from an older worker.  The
        # current worker is cleared only after finished().
        if (
            worker is not None
            and worker is not self.worker
        ):

            return

        self.stop_btn.setEnabled(False)

        self.no_frame_timer.stop()
        self.target_watch_timer.stop()

        if not isinstance(result, CaptureResult):

            self._pending_auto_analysis = None
            self.set_status("status.unexpected_result")

            return

        # PresentMon's console output is UTF-16LE, so always
        # decode it before looking for diagnostics.
        log = read_capture_log(result.log_path)

        if (
            "capture cancelled before presentmon started"
            in log.lower()
        ):

            self._telemetry_reason = "cancelled"
            self._telemetry_outcome = "cancelled"
            self._note_telemetry(None, worker)
            self._pending_auto_analysis = None

            self.set_status("status.cancelled")

            return

        # Never trust the exit code alone: PresentMon can
        # exit with 0 without writing a single CSV record.
        info = validate_capture(result.csv_path)

        self._note_telemetry(info, worker)

        if info.ok:

            self.last_csv = result.csv_path

            self.analyze_btn.setEnabled(True)

            self._last_success = (result, info)
            self._status_spec = None

            self._remember_success(result, info)
            self._remember_recent_capture(result, info)
            self._render_success()

            self._pending_auto_analysis = None

            if (
                self.auto_analyze.isChecked()
                and info.complete
                and info.valid_frames >= 2
                and not result.error
                and not self._closing
            ):

                self._pending_auto_analysis = (
                    result.csv_path
                )

            return

        self._last_success = None
        self._last_failure = (result, info)
        self._pending_auto_analysis = None
        self._status_spec = None

        message = self._build_failure_message(
            result,
            info,
        )

        self.frame_status.setText(
            message.split("\n\n")[0]
        )

        self.analyze_btn.setEnabled(
            bool(self.last_csv)
        )

        # Never open a modal dialog while the window is closing.
        if self._closing:

            return

        QMessageBox.warning(
            self,
            tr("dialog.capture_failed.title"),
            f"{message}\n\nLog: {result.log_path}",
        )

    def on_worker_finished(self):

        worker = self.sender()

        # Ignore the tail of an older worker so it cannot
        # re-enable Start while a newer capture is running.
        if (
            worker is not None
            and worker is not self.worker
        ):

            worker.deleteLater()

            return

        self.no_frame_timer.stop()
        self.target_watch_timer.stop()

        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.set_target_controls_enabled(True)

        self._stop_telemetry(
            self._telemetry_reason,
            self._telemetry_outcome,
        )

        self.worker = None

        if worker is not None:

            worker.deleteLater()

        pending_analysis = self._pending_auto_analysis
        self._pending_auto_analysis = None

        if pending_analysis and not self._closing:

            self.show_analysis(pending_analysis)

        # The window was waiting for this worker; finish closing now
        # that the QThread has really stopped.
        if self._closing:

            self._finish_close()

    # --------------------------------------
    # Historical frame analysis
    # --------------------------------------

    def open_csv(self):

        filename, _ = QFileDialog.getOpenFileName(
            self,
            tr("dialog.open_csv"),
            str(CAPTURES),
            tr("dialog.filter.csv"),
        )

        if filename:
            self.show_analysis(filename)

    def analyze_last(self):

        if self.last_csv:

            self.show_analysis(
                self.last_csv
            )

    def prepare_recheck(self, target):
        """Reuse the normal capture flow without starting it."""

        target = normalize_target(target or "")

        if not target:

            return

        self.process_combo.setCurrentText(target)
        self.tabs.setCurrentWidget(self.live_page)
        self.set_status(
            (
                "status.recheck_ready"
                if self.is_process_running(target)
                else "status.recheck_not_running"
            ),
            target=target,
        )
        self.show()
        self.raise_()
        self.activateWindow()

    def _update_analysis_header(self):

        self.analysis_file_label.setText(
            tr(
                "analysis.page.file",
                name=(
                    self._active_analysis_name
                    or "n/a"
                ),
            )
        )
        self.analysis_target_label.setText(
            tr(
                "analysis.page.target",
                target=(
                    self._active_analysis_target
                    or "n/a"
                ),
            )
        )

    def _show_analysis_page(self):

        self.analysis_header.setVisible(True)
        self.analysis_stack.setCurrentWidget(
            self.analysis_container
        )
        self.tabs.setCurrentWidget(self.analysis_page)

    def show_analysis(self, filename):

        normalized = str(
            Path(filename).resolve()
        )

        if (
            self.viewer is not None
            and self._active_analysis_path == normalized
        ):

            self._update_analysis_header()
            self._show_analysis_page()
            return

        try:

            rows = swap_chains.load_csv_rows(filename)

            timebase = frame_timebase.resolve_timebase(
                rows[0].keys() if rows else (),
                csv_path=filename,
            )

            index = swap_chains.build_index(
                rows,
                session=str(filename),
                timebase=timebase,
            )

            selection = swap_chains.recommend(index)
            frames = selection.legacy_frames()
            target_name = ""

            if frames:

                target_name = (
                    (frames[0].get("row") or {}).get(
                        "Application",
                        "",
                    )
                )

            viewer = FrameViewer(
                frames,
                Path(filename).name,
                index=index,
                selection=selection,
                csv_path=filename,
                target_fps=self.settings.target_fps,
                embedded=True,
            )
            viewer.recheck_requested.connect(
                self.prepare_recheck
            )

        except (
            OSError,
            ValueError,
            KeyError,
            csv.Error,
            UnicodeError,
        ) as error:

            QMessageBox.warning(
                self,
                tr("dialog.analysis_error.title"),
                str(error),
            )

            return

        previous = self.viewer

        if previous is not None:

            try:

                previous.recheck_requested.disconnect(
                    self.prepare_recheck
                )

            except (RuntimeError, TypeError):

                pass

            self.analysis_container_layout.removeWidget(
                previous
            )
            previous.setParent(None)
            previous.deleteLater()

        viewer.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        self.analysis_container_layout.addWidget(
            viewer
        )
        self.viewer = viewer
        self._active_analysis_path = normalized
        self._active_analysis_name = Path(
            filename
        ).name
        self._active_analysis_target = target_name
        self._update_analysis_header()
        self._show_analysis_page()

    # --------------------------------------
    # Update hardware monitoring
    # --------------------------------------

    def update_hardware(self):

        cpu = psutil.cpu_percent(
            interval=None
        )

        ram = psutil.virtual_memory()

        self.hw["cpu"].setText(
            f"{cpu:.1f}%"
        )

        self.hw["ram"].setText(
            f"{ram.percent:.1f}%"
        )

        if self.gpu is None:

            for key in (
                "gpu",
                "vram",
                "temp",
            ):

                self.hw[key].setText("--")

            self.set_hw_status(
                "hardware.nvml_unavailable"
            )

            return

        try:

            usage = (
                pynvml.nvmlDeviceGetUtilizationRates(
                    self.gpu
                ).gpu
            )

            memory = (
                pynvml.nvmlDeviceGetMemoryInfo(
                    self.gpu
                )
            )

            temperature = (
                pynvml.nvmlDeviceGetTemperature(
                    self.gpu,
                    pynvml.NVML_TEMPERATURE_GPU
                )
            )

            used = memory.used / 1024**2
            total = memory.total / 1024**2

            self.hw["gpu"].setText(
                f"{usage}%"
            )

            self.hw["vram"].setText(
                f"{used:.0f} MiB"
            )

            self.hw["temp"].setText(
                f"{temperature}°C"
            )

            self.gpu_chart.add(
                usage
            )

            self.set_hw_status(
                "hardware.vram_status",
                used=used,
                total=total,
            )

        except (
            pynvml.NVMLError,
            OSError
        ) as error:

            self.set_hw_status(
                "hardware.error",
                error=error,
            )

    # --------------------------------------
    # Safe application shutdown
    # --------------------------------------

    def closeEvent(self, event):

        if self._close_done:

            super().closeEvent(event)

            return

        if (
            self.worker
            and self.worker.isRunning()
        ):

            # Do not block the GUI thread: ask the worker to stop and
            # finish closing from on_worker_finished().  The watchdog
            # guarantees the window can always be closed.
            if not self._closing:

                self._closing = True
                self._telemetry_reason = "closed"

                self.start_btn.setEnabled(False)
                self.stop_btn.setEnabled(False)

                self.set_status("status.stopping")

                self.worker.stop()

                self.close_watchdog.start(15000)

            event.ignore()

            return

        self._finish_close(event)

    def _finish_close(self, event=None):

        self.close_watchdog.stop()

        self._stop_telemetry("closed", "closed")

        self._closing = False
        self._close_done = True

        if self.viewer is not None:

            self.viewer.close()

        self.no_frame_timer.stop()
        self.target_watch_timer.stop()
        self.timer.stop()

        if event is not None:

            super().closeEvent(event)

        else:

            self.close()

    def force_close(self):

        # Last resort after the watchdog fired: give the worker a
        # short, bounded chance to exit, then close regardless.
        worker = self.worker

        if worker is not None:

            try:

                worker.stop()

            except (AttributeError, RuntimeError):

                pass

            if worker.isRunning():

                try:

                    worker.wait(2000)

                except (AttributeError, RuntimeError):

                    pass

        self._stop_telemetry("closed", "closed")
        self.worker = None

        self._finish_close()


# ==========================================
# Entry point
# ==========================================

def configure_logging():

    try:

        LOGS.mkdir(
            parents=True,
            exist_ok=True,
        )
        handler = RotatingFileHandler(
            LOGS / "laglens.log",
            maxBytes=1_000_000,
            backupCount=3,
            encoding="utf-8",
        )

    except OSError:

        return

    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s "
            "%(name)s: %(message)s"
        )
    )

    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def main():

    configure_logging()

    # Hold a named mutex for the whole run.  A second instance must
    # not clean up the ETW session of a capture that is still alive.
    guard = SingleInstanceGuard()

    if guard.already_running:

        logger.warning(
            "Another LagLens instance is running; "
            "skipping stale ETW session cleanup"
        )

    elif DEFAULT_PRESENTMON.is_file():

        start_stale_session_cleanup(
            str(DEFAULT_PRESENTMON)
        )

    # Kill-on-close job: PresentMon must never outlive LagLens, even
    # if LagLens is terminated or crashes.
    job = ProcessJob()

    if not job.available:

        logger.warning(
            "Job object unavailable (%s); crash protection is "
            "disabled",
            job.error,
        )

    gpu = None
    nvml_ready = False

    try:

        pynvml.nvmlInit()
        nvml_ready = True

        gpu = (
            pynvml.nvmlDeviceGetHandleByIndex(0)
        )

    except (
        pynvml.NVMLError,
        OSError,
    ) as error:

        logger.warning(
            "NVML initialization failed: %s",
            error,
        )

    try:

        ui_theme.configure_high_dpi()

        app = QApplication(sys.argv)

        ui_theme.ensure_application_theme(app)

        user_settings = AppSettings()
        manager = get_manager()

        manager.set_mode(
            user_settings.language_mode,
            system_locale=detect_system_language(),
        )

        install_qt_translator(
            app,
            manager.language,
        )

        manager.language_changed.connect(
            lambda language: install_qt_translator(
                app,
                language,
            )
        )

        window = LagLens(gpu, job, user_settings)
        window.show()

        return app.exec()

    finally:

        # The window has stopped its worker, so closing the job now
        # only affects a genuinely orphaned PresentMon.
        job.close()

        guard.close()

        if nvml_ready:

            try:

                pynvml.nvmlShutdown()

            except (
                pynvml.NVMLError,
                OSError,
            ):

                pass


if __name__ == "__main__":
    sys.exit(main())
