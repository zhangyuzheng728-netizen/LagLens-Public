"""Headless helpers for the LagLens PresentMon capture pipeline.

This module deliberately has no Qt imports so it can be unit-tested without
creating a QApplication.  The GUI lives in main.py.
"""

from __future__ import annotations

import csv
import math
import re
import subprocess
import threading

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import frame_timebase


SESSION = "LagLensCapture"

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# CPUStartTime / CPUStartQPCTime are validated separately because
# PresentMon 2.6 emits exactly one of them depending on --qpc_time_ms.
REQUIRED_COLUMNS = frozenset(
    {
        "Application",
        "ProcessID",
        "SwapChainAddress",
        "FrameTime",
    }
)

# PresentMon writes its diagnostics as UTF-16LE, but the text itself is
# ordinary ASCII.  These patterns are applied after decoding.
ETW_LOST = re.compile(
    r"(\d[\d,]*)\s+ETW events? were lost",
    re.IGNORECASE,
)

ETW_OVERFLOWED = re.compile(
    r"(\d[\d,]*)\s+overflowed present events",
    re.IGNORECASE,
)


# A frame this long is legal data, but it is worth reporting: it is
# either a real stall or a hole caused by dropped ETW events.
LONG_FRAME_MS = 1000.0


@dataclass(frozen=True)
class CaptureInfo:
    """Result of validating a PresentMon CSV file.

    ``error`` is reserved for conditions that make the capture unusable.
    Structural damage (short/truncated rows) and data quality issues
    (NA / invalid frame values) are counted separately so the UI can
    distinguish a broken CSV from a capture that simply dropped frames.
    """

    path: Path
    exists: bool
    has_header: bool
    columns: tuple[str, ...] = ()
    rows: int = 0
    valid_frames: int = 0
    error: str = ""

    # Structure of the CSV itself.
    bad_field_rows: int = 0
    trailing_partial: bool = False

    # Rows that were readable but carried unusable frame values.
    na_rows: int = 0
    nonnumeric_rows: int = 0
    nonpositive_rows: int = 0
    nonfinite_rows: int = 0

    # Valid frames above LONG_FRAME_MS (reported, never rejected).
    long_frames: int = 0
    max_frame_ms: float = 0.0

    reason_counts: dict = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    time_column: str = ""

    @property
    def invalid_rows(self) -> int:
        """Rows that could not be used, with a truncated tail as one row."""

        return (
            self.bad_field_rows
            + (1 if self.trailing_partial else 0)
            + self.na_rows
            + self.nonnumeric_rows
            + self.nonpositive_rows
            + self.nonfinite_rows
        )

    @property
    def ok(self) -> bool:
        return self.valid_frames > 0 and not self.error

    @property
    def complete(self) -> bool:
        """True when no structural damage was found."""

        return (
            self.exists
            and self.has_header
            and not self.error
            and not self.bad_field_rows
            and not self.trailing_partial
        )


@dataclass(frozen=True)
class CaptureQuality:
    """Capture health split by cause, so ETW loss is never confused
    with a malformed CSV."""

    structural: tuple[str, ...] = ()
    data: tuple[str, ...] = ()
    etw: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        return not self.structural

    @property
    def clean(self) -> bool:
        return not (
            self.structural
            or self.data
            or self.etw
        )


@dataclass
class CaptureResult:
    """Everything the GUI needs to know about one capture attempt."""

    csv_path: str
    log_path: str
    exit_code: int = -1
    rows: int = 0
    valid_frames: int = 0
    forced_stop: bool = False
    error: str = ""
    etw_warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.valid_frames > 0 and not self.error


def is_elevated() -> bool:
    """True when the process can create an ETW trace session."""

    try:
        import ctypes

        return bool(
            ctypes.windll.shell32.IsUserAnAdmin()
        )

    except (AttributeError, OSError):
        return False


def normalize_target(target: str) -> str:
    """Return the executable name PresentMon expects."""

    return Path(
        target.strip().strip('"')
    ).name


def safe_capture_name(
    target: str,
    now: datetime | None = None,
) -> str:
    """Build a filesystem-safe, unique CSV name."""

    safe = "".join(
        char
        if char.isalnum()
        or char in "._-"
        else "_"
        for char in target
    )

    stamp = (now or datetime.now()).strftime(
        "%Y%m%d_%H%M%S_%f"
    )

    return f"{safe}_{stamp}.csv"


def build_capture_command(
    executable,
    session,
    target,
    low_overhead=False,
    qpc_time=False,
):
    """PresentMon 2.x command line used for live capture.

    LagLens reads the CSV from stdout so the live view works while the
    capture is running.  ``--output_file`` cannot be used for live data:
    PresentMon opens that file with exclusive sharing, so any read
    attempt during recording fails with "Permission denied".  LagLens
    therefore writes the CSV itself and flushes it with every batch.

    ``qpc_time`` is opt-in and appends ``--qpc_time_ms``.  The default
    command and legacy ``CPUStartTime`` CSV format stay unchanged.
    """

    command = [
        str(executable),

        # Dedicated ETW session
        "--session_name",
        session,

        # Recover an abandoned session
        "--stop_existing_session",

        # Target process
        "--process_name",
        target,

        # Live CSV on stdout; LagLens owns the output file.
        "--output_stdout",

        "--no_console_stats",
        "--v2_metrics",

        # LagLens does not use input latency, so do not pay for it.
        "--no_track_input",
    ]

    if low_overhead:
        # GPU tracking is the largest optional event source.  Disabling it
        # removes GPUBusy/GPUWait from the CSV but keeps FrameTime intact.
        command.append("--no_track_gpu")

    if qpc_time:
        # Experimental, opt-in timestamp mode.  PresentMon writes
        # CPUStartQPCTime instead of CPUStartTime; the default CSV
        # format and legacy analysis remain unchanged when this is off.
        command.append("--qpc_time_ms")

    # NOTE: PresentMon 2.6 accepts --terminate_on_proc_exit, but a
    # controlled test (both --process_name and --process_id) showed
    # that it does NOT terminate PresentMon when the target exits.
    # "Stop when target exits" is therefore implemented by LagLens
    # polling the target process instead of passing this flag.

    return command


def build_terminate_command(executable, session):
    """Ask PresentMon to close the named ETW session and exit."""

    return [
        str(executable),
        "--terminate_existing_session",
        "--session_name",
        session,
    ]


def cleanup_stale_session(
    executable,
    session=SESSION,
    timeout=5,
):
    """Terminate only LagLens' own left-over ETW session.

    Called at startup, before any capture.  Exit code 7 means there was
    no session to terminate, which is the normal case on a clean start.

    Returns the exit code, or None when PresentMon could not be run.
    """

    try:

        result = subprocess.run(
            build_terminate_command(
                executable,
                session,
            ),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            creationflags=NO_WINDOW,
        )

        return result.returncode

    except (OSError, subprocess.TimeoutExpired):

        return None


def start_stale_session_cleanup(
    executable,
    session=SESSION,
    timeout=5,
):
    """Run cleanup_stale_session on a daemon thread.

    Returns the thread so tests can join it; the GUI never blocks on it.
    """

    thread = threading.Thread(
        target=cleanup_stale_session,
        args=(executable, session, timeout),
        daemon=True,
        name="LagLensSessionCleanup",
    )

    thread.start()

    return thread


def read_capture_log(path):
    """Decode a PresentMon log regardless of its encoding."""

    try:
        data = Path(path).read_bytes()

    except OSError:
        return ""

    if data.startswith(b"\xff\xfe"):
        return data[2:].decode(
            "utf-16-le", "replace"
        )

    if data.startswith(b"\xfe\xff"):
        return data[2:].decode(
            "utf-16-be", "replace"
        )

    if data.startswith(b"\xef\xbb\xbf"):
        return data.decode(
            "utf-8-sig", "replace"
        )

    return data.decode(
        "utf-8", "replace"
    )


def etw_warnings(log_text):
    """Extract ETW health warnings reported by PresentMon."""

    warnings = []

    for pattern, label in (
        (ETW_LOST, "ETW events were lost"),
        (ETW_OVERFLOWED, "present events overflowed"),
    ):
        match = pattern.search(log_text)

        if match:
            warnings.append(
                f"{match.group(1)} {label}"
            )

    return warnings


def summarize_log(log_text):
    """Return the most useful PresentMon line for the UI."""

    lines = [
        line.strip()
        for line in log_text.splitlines()
        if line.strip()
    ]

    errors = [
        line for line in lines
        if line.lower().startswith("error:")
    ]

    if errors:
        return errors[-1]

    return lines[-1] if lines else ""


def failure_code(
    log_text,
    exit_code,
    info: CaptureInfo | None = None,
):
    """Return a stable code for a failed capture.

    The UI translates this code; the raw PresentMon log stays English
    and is never translated.
    """

    low = (log_text or "").lower()

    if (
        "access denied" in low
        or "administrative privileges" in low
        or "performance log users" in low
    ):

        return "access_denied"

    if "already running" in low:

        return "session_busy"

    if "unrecognized option" in low:

        return "bad_command"

    if "failed to start trace session" in low:

        return "trace_failed"

    if info is not None:

        if not info.exists:

            # validate_capture sets exists=False both for a missing
            # file and for a file that could not be read at all.
            if "could not be read" in (
                info.error or ""
            ).lower():

                return "csv_unusable"

            return "csv_missing"

        # ``rows == 0`` alone is ambiguous: a header-only capture is a
        # legitimate zero-frame result, while an empty, truncated or
        # unparsable file is a broken CSV.  ``validate_capture`` sets
        # ``error`` for every structural problem, so use it first.
        if info.error:

            if "no frame rows" in info.error.lower():

                return "no_frames"

            return "csv_unusable"

        if not info.has_header:

            return "csv_unusable"

        if info.rows == 0:

            return "no_frames"

        if info.valid_frames == 0:

            return "csv_unusable"

    if exit_code == 0:

        return "no_data"

    return "unknown"


def describe_failure(
    log_text,
    exit_code,
    info: CaptureInfo | None = None,
    target: str = "",
):
    """Map a PresentMon exit code / log to an actionable message."""

    low = log_text.lower()

    if (
        "access denied" in low
        or "administrative privileges" in low
        or "performance log users" in low
    ):
        return (
            "ETW access denied. PresentMon needs "
            "administrator privileges (or membership of "
            "the \"Performance Log Users\" group). "
            "Restart LagLens as administrator."
        )

    if "already running" in low:
        return (
            "The PresentMon ETW session is still in use "
            f"(exit code {exit_code}). Wait a moment and retry."
        )

    if "unrecognized option" in low:
        return (
            "PresentMon rejected the command line. "
            "Make sure the selected executable is "
            "PresentMon 2.x."
        )

    if "failed to start trace session" in low:
        return (
            "PresentMon could not start its ETW trace "
            f"session (exit code {exit_code})."
        )

    if info is not None:

        if not info.exists:
            return (
                f"PresentMon exited with code {exit_code} "
                "but did not create the CSV. Check that "
                f"{target or 'the target process'} is running "
                "and that the captures folder is writable."
            )

        if info.rows == 0:
            return (
                f"PresentMon exited with code {exit_code} "
                "but captured no frames. Check that "
                f"{target or 'the target process'} is running "
                "and presenting frames."
            )

        if info.error:
            return (
                f"PresentMon exited with code {exit_code}, "
                f"but the CSV is not usable: {info.error}"
            )

    if exit_code == 0:
        return (
            "PresentMon exited with code 0 but produced "
            "no usable frame data."
        )

    return (
        "PresentMon exited with code "
        f"{exit_code} without producing frame data."
    )


def _ends_with_newline(path):

    try:

        with path.open("rb") as file:

            file.seek(0, 2)

            if file.tell() == 0:

                return True

            file.seek(-1, 2)

            return file.read(1) in (b"\n", b"\r")

    except OSError:

        return True


def _classify_row(
    fields,
    header,
    frame_index,
    start_index,
    is_last,
    ends_with_newline,
):
    """Classify one CSV data row.

    Returns ``(reason, frame_time_ms, is_long)`` where reason is one of
    valid / bad_fields / truncated / na / non_numeric / non_positive /
    non_finite.
    """

    if len(fields) != len(header):

        # A cut-off final line is a truncated capture; a short line
        # anywhere else is file corruption.
        if is_last and not ends_with_newline:

            return "truncated", 0.0, False

        return "bad_fields", 0.0, False

    try:

        raw_frame = fields[frame_index].strip()
        raw_start = fields[start_index].strip()

    except IndexError:

        return "bad_fields", 0.0, False

    if (
        not raw_frame
        or not raw_start
        or raw_frame.upper() == "NA"
        or raw_start.upper() == "NA"
    ):

        return "na", 0.0, False

    try:

        frame_time = float(raw_frame)
        start_time = float(raw_start)

    except ValueError:

        return "non_numeric", 0.0, False

    if (
        not math.isfinite(frame_time)
        or not math.isfinite(start_time)
    ):

        return "non_finite", 0.0, False

    if frame_time <= 0:

        return "non_positive", 0.0, False

    return (
        "valid",
        frame_time,
        frame_time >= LONG_FRAME_MS,
    )


def validate_capture(
    path,
    required=REQUIRED_COLUMNS,
) -> CaptureInfo:
    """Inspect a PresentMon CSV and report whether it is usable.

    A file that merely exists is not enough: PresentMon can exit with code 0
    without creating a file, or create a header-only file when the target
    process never presents a frame.

    Rows are counted by cause so that a malformed CSV can be told apart
    from a capture that merely contains dropped (NA) frames.
    """

    path = Path(path)

    if not path.exists():
        return CaptureInfo(
            path=path,
            exists=False,
            has_header=False,
            error="CSV was not created",
        )

    try:
        if path.stat().st_size == 0:
            return CaptureInfo(
                path=path,
                exists=True,
                has_header=False,
                error="CSV is empty",
            )

    except OSError as error:
        return CaptureInfo(
            path=path,
            exists=False,
            has_header=False,
            error=f"CSV could not be read: {error}",
        )

    header = None
    time_column = ""
    rows = 0
    valid_frames = 0
    max_frame = 0.0
    long_frames = 0

    counts = {
        "bad_fields": 0,
        "truncated": 0,
        "na": 0,
        "non_numeric": 0,
        "non_positive": 0,
        "non_finite": 0,
    }

    def record(reason, frame_time, is_long):

        nonlocal rows, valid_frames, long_frames
        nonlocal max_frame

        rows += 1

        if reason == "valid":

            valid_frames += 1

            if frame_time > max_frame:

                max_frame = frame_time

            if is_long:

                long_frames += 1

            return

        counts[reason] += 1

    try:

        ends_with_newline = _ends_with_newline(path)

        with path.open(
            "r",
            encoding="utf-8-sig",
            newline="",
            errors="replace",
        ) as file:

            reader = csv.reader(file)

            pending = None
            frame_index = None
            start_index = None

            for fields in reader:

                if not fields or not any(
                    field.strip() for field in fields
                ):

                    continue

                if header is None:

                    header = [
                        field.strip()
                        for field in fields
                    ]

                    missing = (
                        set(required) - set(header)
                    )

                    time_column = (
                        frame_timebase.detect_time_column(
                            header
                        )
                    )

                    missing_labels = sorted(missing)

                    if time_column is None:

                        missing_labels.append(
                            "CPUStartTime or CPUStartQPCTime"
                        )

                    if missing_labels:

                        return CaptureInfo(
                            path=path,
                            exists=True,
                            has_header=True,
                            columns=tuple(header),
                            error=(
                                "CSV is missing required "
                                "columns: "
                                + ", ".join(
                                    missing_labels
                                )
                            ),
                        )

                    frame_index = header.index(
                        "FrameTime"
                    )

                    start_index = header.index(
                        time_column
                    )

                    continue

                # Keep one row in hand so the final row can be
                # recognised as a truncated tail.
                if pending is not None:

                    record(
                        *_classify_row(
                            pending,
                            header,
                            frame_index,
                            start_index,
                            is_last=False,
                            ends_with_newline=ends_with_newline,
                        )
                    )

                pending = fields

            if pending is not None:

                record(
                    *_classify_row(
                        pending,
                        header,
                        frame_index,
                        start_index,
                        is_last=True,
                        ends_with_newline=ends_with_newline,
                    )
                )

    except (OSError, csv.Error, UnicodeError) as error:

        return CaptureInfo(
            path=path,
            exists=True,
            has_header=header is not None,
            rows=rows,
            valid_frames=valid_frames,
            error=f"CSV could not be parsed: {error}",
        )

    if header is None:

        return CaptureInfo(
            path=path,
            exists=True,
            has_header=False,
            error="CSV header not found",
        )

    warnings = []

    if counts["truncated"]:

        warnings.append(
            "CSV ends with a truncated row "
            "(capture may have been interrupted)"
        )

    if counts["bad_fields"]:

        warnings.append(
            f"{counts['bad_fields']} row(s) have an "
            "unexpected number of fields"
        )

    if counts["na"]:

        warnings.append(
            f"{counts['na']} row(s) have NA frame metrics "
            "(frames not captured)"
        )

    if counts["non_numeric"]:

        warnings.append(
            f"{counts['non_numeric']} row(s) have "
            "non-numeric frame values"
        )

    if counts["non_positive"]:

        warnings.append(
            f"{counts['non_positive']} row(s) have "
            "non-positive frame times"
        )

    if counts["non_finite"]:

        warnings.append(
            f"{counts['non_finite']} row(s) have "
            "non-finite frame values"
        )

    if long_frames:

        warnings.append(
            f"{long_frames} frame(s) longer than "
            f"{LONG_FRAME_MS:.0f} ms (possible stall "
            "or lost events)"
        )

    reason_counts = {
        reason: count
        for reason, count in counts.items()
        if count
    }

    error = ""

    if rows == 0:

        error = "CSV contains a header but no frame rows"

    elif valid_frames == 0:

        error = (
            "CSV contains no valid FrameTime/time-base rows"
        )

    return CaptureInfo(
        path=path,
        exists=True,
        has_header=True,
        columns=tuple(header),
        rows=rows,
        valid_frames=valid_frames,
        error=error,
        bad_field_rows=counts["bad_fields"],
        trailing_partial=bool(counts["truncated"]),
        na_rows=counts["na"],
        nonnumeric_rows=counts["non_numeric"],
        nonpositive_rows=counts["non_positive"],
        nonfinite_rows=counts["non_finite"],
        long_frames=long_frames,
        max_frame_ms=max_frame,
        reason_counts=reason_counts,
        warnings=tuple(warnings),
        time_column=time_column,
    )


def capture_quality(
    info: CaptureInfo,
    log_text="",
) -> CaptureQuality:
    """Split capture health into structural, data and ETW causes.

    Structural problems mean the CSV itself is damaged.  Data problems
    mean the file is well formed but individual frames are missing or
    invalid.  ETW problems come from PresentMon's own event counters and
    can occur in a perfectly valid CSV.
    """

    structural = []
    data = []

    if not info.exists:

        structural.append("CSV was not created")

    elif not info.has_header:

        structural.append(
            info.error or "CSV header not found"
        )

    else:

        if info.trailing_partial:

            structural.append(
                "CSV ends with a truncated row "
                "(capture may have been interrupted)"
            )

        if info.bad_field_rows:

            structural.append(
                f"{info.bad_field_rows} row(s) have an "
                "unexpected number of fields"
            )

        if info.error:

            if "no valid" in info.error:

                data.append(info.error)

            elif info.error not in structural:

                structural.append(info.error)

    if info.na_rows:

        data.append(
            f"{info.na_rows} row(s) have NA frame metrics "
            "(frames not captured)"
        )

    if info.nonnumeric_rows:

        data.append(
            f"{info.nonnumeric_rows} row(s) have "
            "non-numeric frame values"
        )

    if info.nonpositive_rows:

        data.append(
            f"{info.nonpositive_rows} row(s) have "
            "non-positive frame times"
        )

    if info.nonfinite_rows:

        data.append(
            f"{info.nonfinite_rows} row(s) have "
            "non-finite frame values"
        )

    return CaptureQuality(
        structural=tuple(structural),
        data=tuple(data),
        etw=tuple(etw_warnings(log_text)),
    )


class CsvTailer:
    """Incrementally read complete rows from a growing PresentMon CSV.

    PresentMon owns the file, so LagLens only follows the bytes that have
    already been written.  A partial final line is kept until the next poll.
    """

    def __init__(self, path):

        self.path = Path(path)
        self._position = 0
        self._buffer = b""
        self._headers = None
        self._time_column = None
        self.rows_seen = 0
        self.valid_frames = 0

    @property
    def headers(self):
        return self._headers

    @property
    def time_column(self):
        return self._time_column

    def _reset(self):

        self._position = 0
        self._buffer = b""
        self._headers = None
        self._time_column = None
        self.rows_seen = 0
        self.valid_frames = 0

    def poll(self, final=False):
        """Return newly completed, valid frame rows."""

        rows = []

        try:
            size = self.path.stat().st_size

        except OSError:
            return rows

        # The file was truncated or replaced; start over.
        if size < self._position:
            self._reset()

        if size > self._position:

            try:
                with self.path.open("rb") as file:
                    file.seek(self._position)
                    data = file.read(
                        size - self._position
                    )
                    self._position = file.tell()

            except OSError:
                return rows

            self._buffer += data

        lines = self._buffer.split(b"\n")

        if final:
            self._buffer = b""
        else:
            self._buffer = lines.pop()

        for raw in lines:

            raw = raw.rstrip(b"\r")

            if not raw:
                continue

            text = raw.decode(
                "utf-8-sig", "replace"
            )

            if self._headers is None:

                if not text.startswith(
                    "Application,"
                ):
                    continue

                try:
                    self._headers = [
                        field.strip()
                        for field in next(
                            csv.reader([text])
                        )
                    ]

                except csv.Error:
                    continue

                self._time_column = (
                    frame_timebase.detect_time_column(
                        self._headers
                    )
                )

                continue

            try:
                fields = next(
                    csv.reader([text])
                )

            except csv.Error:
                continue

            if len(fields) != len(self._headers):
                continue

            row = dict(
                zip(self._headers, fields)
            )

            self.rows_seen += 1

            if self._time_column is None:

                continue

            try:
                frame_time = float(
                    row["FrameTime"]
                )

                start_time = float(
                    row[self._time_column]
                )

            except (
                KeyError,
                TypeError,
                ValueError,
            ):
                continue

            if not (
                math.isfinite(frame_time)
                and frame_time > 0
                and math.isfinite(start_time)
            ):
                continue

            self.valid_frames += 1

            rows.append(row)

        return rows
