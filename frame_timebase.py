"""Frame timestamp normalization for PresentMon CSV files.

PresentMon 2.6 can emit one of two time columns:

* ``CPUStartTime``: capture-relative milliseconds (legacy default);
* ``CPUStartQPCTime``: absolute Windows QPC milliseconds since boot.

The rest of LagLens needs a capture-relative ``time`` value for frame
statistics and charting.  This module keeps the raw value and an explicit
timebase description so callers can tell the two apart.

QPC milliseconds are never treated as relative milliseconds.  A QPC
timebase is normalized by subtracting a capture-start QPC origin.  The
origin comes from the recorded Python ``perf_counter_ns`` capture start
when available, or from the first frame as a clearly labelled fallback.
"""

from __future__ import annotations

import ctypes
import sys
import time

from dataclasses import dataclass, replace

from telemetry import read_telemetry


LEGACY_TIME_COLUMN = "CPUStartTime"
QPC_MS_COLUMN = "CPUStartQPCTime"
TIME_COLUMNS = (LEGACY_TIME_COLUMN, QPC_MS_COLUMN)

# A verified QPC mapping should agree with Python's QPC-derived
# perf_counter much more closely than this.  The measured C-1.1
# difference was below 0.01 ms.
QPC_CLOCK_TOLERANCE_MS = 5.0

LEGACY_NOTE = (
    "CPUStartTime is capture-relative milliseconds; no absolute "
    "QPC mapping is claimed"
)
QPC_CAPTURE_NOTE = (
    "CPUStartQPCTime is absolute QPC milliseconds; normalized by "
    "subtracting the recorded capture-start QPC origin"
)
QPC_FIRST_FRAME_NOTE = (
    "CPUStartQPCTime is absolute QPC milliseconds; no capture-start "
    "origin was available, so the first frame is the relative origin"
)


def detect_time_column(header) -> str | None:
    """Return the CSV time column, preferring legacy compatibility."""

    columns = set(header)

    if LEGACY_TIME_COLUMN in columns:

        return LEGACY_TIME_COLUMN

    if QPC_MS_COLUMN in columns:

        return QPC_MS_COLUMN

    return None


def qpc_frequency_hz() -> int | None:
    """Return the Windows QPC frequency, or None off Windows."""

    if sys.platform != "win32":

        return None

    try:

        frequency = ctypes.c_longlong()
        ok = ctypes.windll.kernel32.QueryPerformanceFrequency(
            ctypes.byref(frequency)
        )

    except (
        AttributeError,
        OSError,
        TypeError,
        ValueError,
    ):

        return None

    if not ok or frequency.value <= 0:

        return None

    return int(frequency.value)


def qpc_clock_delta_ms() -> float | None:
    """Measure Python perf_counter minus direct Windows QPC.

    Both are QPC-derived on Windows.  This is a clock-read check, not a
    capture or row-arrival measurement.
    """

    frequency = qpc_frequency_hz()

    if not frequency:

        return None

    try:

        perf_ns = time.perf_counter_ns()
        counter = ctypes.c_longlong()
        ok = ctypes.windll.kernel32.QueryPerformanceCounter(
            ctypes.byref(counter)
        )

    except (
        AttributeError,
        OSError,
        TypeError,
        ValueError,
    ):

        return None

    if not ok:

        return None

    qpc_ns = int(
        counter.value * 1_000_000_000 / frequency
    )

    return (perf_ns - qpc_ns) / 1_000_000.0


def legacy_timebase() -> "FrameTimebase":

    return FrameTimebase(
        kind="relative",
        raw_column=LEGACY_TIME_COLUMN,
        origin_kind="capture_relative",
        sync_quality="exact_relative",
        note=LEGACY_NOTE,
    )


def unknown_timebase(note="no supported time column"):

    return FrameTimebase(
        kind="unknown",
        raw_column="",
        origin_kind="none",
        sync_quality="untrusted",
        note=note,
    )


def qpc_timebase_for_capture(
    capture_started_monotonic_ns,
    qpc_clock_delta_ms_value=None,
    qpc_frequency_hz_value=None,
) -> "FrameTimebase":
    """Build a QPC timebase for a live capture.

    ``capture_started_monotonic_ns`` is Python's perf_counter value at
    capture start.  On Windows it shares the QPC epoch, so it is also
    the QPC origin in nanoseconds.
    """

    try:

        started_ns = (
            None
            if capture_started_monotonic_ns is None
            else int(capture_started_monotonic_ns)
        )

    except (TypeError, ValueError):

        started_ns = None

    if started_ns is None:

        return FrameTimebase(
            kind="qpc_ms",
            raw_column=QPC_MS_COLUMN,
            origin_kind="first_frame",
            sync_quality="inferred_qpc",
            qpc_clock_delta_ms=(
                None
                if qpc_clock_delta_ms_value is None
                else qpc_clock_delta_ms_value
            ),
            qpc_frequency_hz=qpc_frequency_hz_value,
            note=QPC_FIRST_FRAME_NOTE,
        )

    try:

        delta = (
            None
            if qpc_clock_delta_ms_value is None
            else float(qpc_clock_delta_ms_value)
        )

    except (TypeError, ValueError):

        delta = None

    if delta is None:

        quality = "unverified_qpc"
        note = (
            QPC_CAPTURE_NOTE
            + "; QPC/perf_counter clock delta was not measured"
        )

    elif abs(delta) <= QPC_CLOCK_TOLERANCE_MS:

        quality = "verified_qpc"
        note = (
            QPC_CAPTURE_NOTE
            + f"; QPC/perf_counter delta {delta:.6f} ms"
        )

    else:

        quality = "unverified_qpc"
        note = (
            QPC_CAPTURE_NOTE
            + f"; QPC/perf_counter delta {delta:.6f} ms exceeds "
            f"{QPC_CLOCK_TOLERANCE_MS:.1f} ms"
        )

    return FrameTimebase(
        kind="qpc_ms",
        raw_column=QPC_MS_COLUMN,
        origin_kind="capture_start",
        origin_qpc_ms=started_ns / 1_000_000.0,
        capture_started_monotonic_ns=started_ns,
        qpc_clock_delta_ms=delta,
        qpc_frequency_hz=qpc_frequency_hz_value,
        sync_quality=quality,
        note=note,
    )


def _sidecar_timebase(csv_path) -> "FrameTimebase | None":
    """Read QPC origin metadata from a C-1 sidecar, if present."""

    if csv_path is None:

        return None

    try:

        result = read_telemetry(csv_path)

    except Exception:

        return None

    if not result.available:

        return None

    metadata = result.metadata or {}

    if not isinstance(metadata, dict):

        return None

    capture = metadata.get("capture", {})

    if not isinstance(capture, dict):

        return None

    started = capture.get("started_monotonic_ns")
    timebase = result.timebase or {}

    if not isinstance(timebase, dict):

        timebase = {}

    if started is not None:

        try:

            started = int(started)

        except (TypeError, ValueError):

            started = None

    info = timebase.get("frame_timebase")

    if isinstance(info, dict):

        parsed = FrameTimebase.from_dict(info)

        if parsed is not None and parsed.kind == "qpc_ms":

            if (
                parsed.origin_qpc_ms is None
                and started is not None
            ):

                parsed = replace(
                    parsed,
                    origin_qpc_ms=int(started) / 1_000_000.0,
                    origin_kind="capture_start",
                    capture_started_monotonic_ns=int(started),
                )

            if parsed.origin_qpc_ms is not None:

                return parsed

    if started is not None:

        return qpc_timebase_for_capture(
            started,
            qpc_clock_delta_ms_value=(
                timebase.get("qpc_clock_delta_ms")
                if isinstance(timebase, dict)
                else None
            ),
        )

    return None


def resolve_timebase(
    header,
    csv_path=None,
) -> "FrameTimebase":
    """Resolve a timebase for historical CSV parsing.

    For QPC CSV files, the sidecar is used when available.  Without a
    sidecar the first frame becomes the origin and the result is marked
    ``inferred_qpc``; frame statistics remain valid, but no absolute
    hardware/frame correlation may be claimed.
    """

    column = detect_time_column(header)

    if column is None:

        return unknown_timebase()

    if column == LEGACY_TIME_COLUMN:

        return legacy_timebase()

    sidecar = _sidecar_timebase(csv_path)

    if sidecar is not None:

        return sidecar

    return FrameTimebase(
        kind="qpc_ms",
        raw_column=QPC_MS_COLUMN,
        origin_kind="first_frame",
        sync_quality="inferred_qpc",
        note=QPC_FIRST_FRAME_NOTE,
    )


@dataclass(frozen=True)
class FrameTimebase:
    """Description of the frame timestamp column and its normalization."""

    kind: str
    raw_column: str = ""
    origin_kind: str = "none"
    origin_qpc_ms: float | None = None
    capture_started_monotonic_ns: int | None = None
    qpc_clock_delta_ms: float | None = None
    qpc_frequency_hz: int | None = None
    sync_quality: str = "untrusted"
    note: str = ""
    raw_first_time_ms: float | None = None
    raw_last_time_ms: float | None = None
    normalized_first_ms: float | None = None
    normalized_last_ms: float | None = None

    @property
    def absolute_mapping_trusted(self) -> bool:
        """True only for a capture-start QPC origin with measured trust."""

        return (
            self.kind == "qpc_ms"
            and self.origin_kind == "capture_start"
            and self.origin_qpc_ms is not None
            and self.sync_quality
            in ("verified_qpc", "sidecar_qpc")
        )

    @property
    def applicability(self) -> str:

        if self.kind == "relative":

            return "capture_relative"

        if self.absolute_mapping_trusted:

            return "absolute_frame_time"

        if self.kind == "qpc_ms":

            return "frame_relative_only"

        return "none"

    def normalize(self, raw_time_ms) -> float:
        """Convert a raw CSV time value to capture-relative ms."""

        value = float(raw_time_ms)

        if self.kind == "relative":

            return value

        if self.kind == "qpc_ms":

            if self.origin_qpc_ms is None:

                raise ValueError(
                    "QPC timebase has no origin"
                )

            return value - self.origin_qpc_ms

        raise ValueError("unknown timebase")

    def with_origin(
        self,
        origin_qpc_ms,
        origin_kind,
        sync_quality,
        note=None,
    ) -> "FrameTimebase":

        return replace(
            self,
            origin_qpc_ms=float(origin_qpc_ms),
            origin_kind=origin_kind,
            sync_quality=sync_quality,
            note=self.note if note is None else note,
        )

    def with_range(
        self,
        first_raw_time_ms,
        last_raw_time_ms,
    ) -> "FrameTimebase":

        first_normalized = None
        last_normalized = None

        if first_raw_time_ms is not None:

            try:

                first_normalized = self.normalize(
                    first_raw_time_ms
                )

            except (TypeError, ValueError):

                pass

        if last_raw_time_ms is not None:

            try:

                last_normalized = self.normalize(
                    last_raw_time_ms
                )

            except (TypeError, ValueError):

                pass

        return replace(
            self,
            raw_first_time_ms=(
                None
                if first_raw_time_ms is None
                else float(first_raw_time_ms)
            ),
            raw_last_time_ms=(
                None
                if last_raw_time_ms is None
                else float(last_raw_time_ms)
            ),
            normalized_first_ms=first_normalized,
            normalized_last_ms=last_normalized,
        )

    def to_dict(self):

        return {
            "kind": self.kind,
            "raw_column": self.raw_column,
            "origin_kind": self.origin_kind,
            "origin_qpc_ms": self.origin_qpc_ms,
            "capture_started_monotonic_ns": (
                self.capture_started_monotonic_ns
            ),
            "qpc_clock_delta_ms": self.qpc_clock_delta_ms,
            "qpc_frequency_hz": self.qpc_frequency_hz,
            "sync_quality": self.sync_quality,
            "applicability": self.applicability,
            "absolute_mapping_trusted": (
                self.absolute_mapping_trusted
            ),
            "raw_first_time_ms": self.raw_first_time_ms,
            "raw_last_time_ms": self.raw_last_time_ms,
            "normalized_first_ms": self.normalized_first_ms,
            "normalized_last_ms": self.normalized_last_ms,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data):

        if not isinstance(data, dict):

            return None

        kind = str(data.get("kind") or "unknown")

        if kind not in ("relative", "qpc_ms", "unknown"):

            return None

        def optional_float(key):

            value = data.get(key)

            if value is None:

                return None

            try:

                return float(value)

            except (TypeError, ValueError):

                return None

        def optional_int(key):

            value = data.get(key)

            if value is None:

                return None

            try:

                return int(value)

            except (TypeError, ValueError):

                return None

        return cls(
            kind=kind,
            raw_column=str(data.get("raw_column") or ""),
            origin_kind=str(
                data.get("origin_kind") or "none"
            ),
            origin_qpc_ms=optional_float("origin_qpc_ms"),
            capture_started_monotonic_ns=optional_int(
                "capture_started_monotonic_ns"
            ),
            qpc_clock_delta_ms=optional_float(
                "qpc_clock_delta_ms"
            ),
            qpc_frequency_hz=optional_int("qpc_frequency_hz"),
            sync_quality=str(
                data.get("sync_quality") or "untrusted"
            ),
            note=str(data.get("note") or ""),
            raw_first_time_ms=optional_float(
                "raw_first_time_ms"
            ),
            raw_last_time_ms=optional_float(
                "raw_last_time_ms"
            ),
            normalized_first_ms=optional_float(
                "normalized_first_ms"
            ),
            normalized_last_ms=optional_float(
                "normalized_last_ms"
            ),
        )
