"""C-1 telemetry schema, JSONL sidecar and timebase calibration.

The sidecar is deliberately independent from the PresentMon CSV.  If it
is missing, incomplete or corrupt, the existing CSV analysis must still
work.

Records are JSON objects, one per line:

* ``metadata``: schema version, capture identity and sampling profile;
* ``marker``: optional capture marker such as PresentMon start;
* ``sample``: one timestamped hardware sample;
* ``timebase``: the measured PresentMon/sampler relationship;
* ``end``: stop reason, sample count and capture outcome.

No full user paths are written.  The sidecar sits next to the CSV and
only records the CSV basename, target executable name and device
identity.
"""

from __future__ import annotations

import json
import logging
import threading
import time

from dataclasses import dataclass, field
from pathlib import Path


logger = logging.getLogger("laglens.telemetry")
logger.addHandler(logging.NullHandler())


SCHEMA_VERSION = 1

DEFAULT_INTERVAL_MS = 250
MIN_INTERVAL_MS = 100
MAX_INTERVAL_MS = 5000

LOW_OVERHEAD_INTERVAL_MS = 1000

RELATIVE_SPAN_TOLERANCE_MS = 250.0
RELATIVE_SPAN_TOLERANCE_RATIO = 0.01


def telemetry_path(csv_path) -> Path:
    """Return the sidecar path for a capture CSV."""

    return Path(str(csv_path) + ".telemetry.jsonl")


def _json_line(record) -> str:

    return json.dumps(
        record,
        ensure_ascii=False,
        separators=(",", ":"),
    )


@dataclass(frozen=True)
class GpuDevice:
    index: int
    name: str = ""
    uuid: str = ""
    bus_id: str = ""
    association: str = "unknown"

    def to_dict(self):

        return {
            "index": self.index,
            "name": self.name,
            "uuid": self.uuid,
            "bus_id": self.bus_id,
            "association": self.association,
        }


@dataclass
class TimebaseCalibration:
    capture_started_monotonic_ns: int | None = None
    presentmon_started_monotonic_ns: int | None = None
    first_row_monotonic_ns: int | None = None
    last_row_monotonic_ns: int | None = None
    first_cpu_start_ms: float | None = None
    last_cpu_start_ms: float | None = None
    presentmon_start_offset_ms: float | None = None
    row_span_ms: float | None = None
    csv_span_ms: float | None = None
    span_error_ms: float | None = None
    offset_estimate_ms: float | None = None
    uncertainty_ms: float | None = None
    relative_scale_trusted: bool = False
    absolute_offset_trusted: bool = False
    status: str = "untrusted"
    note: str = ""

    def to_dict(self):

        return {
            "capture_started_monotonic_ns": (
                self.capture_started_monotonic_ns
            ),
            "presentmon_started_monotonic_ns": (
                self.presentmon_started_monotonic_ns
            ),
            "first_row_monotonic_ns": (
                self.first_row_monotonic_ns
            ),
            "last_row_monotonic_ns": (
                self.last_row_monotonic_ns
            ),
            "first_cpu_start_ms": self.first_cpu_start_ms,
            "last_cpu_start_ms": self.last_cpu_start_ms,
            "presentmon_start_offset_ms": (
                self.presentmon_start_offset_ms
            ),
            "row_span_ms": self.row_span_ms,
            "csv_span_ms": self.csv_span_ms,
            "span_error_ms": self.span_error_ms,
            "offset_estimate_ms": self.offset_estimate_ms,
            "uncertainty_ms": self.uncertainty_ms,
            "relative_scale_trusted": (
                self.relative_scale_trusted
            ),
            "absolute_offset_trusted": (
                self.absolute_offset_trusted
            ),
            "status": self.status,
            "note": self.note,
        }


def calibrate_timebase(
    capture_started_monotonic_ns,
    presentmon_started_monotonic_ns,
    first_row_monotonic_ns,
    last_row_monotonic_ns,
    first_cpu_start_ms,
    last_cpu_start_ms,
    sample_interval_ms=DEFAULT_INTERVAL_MS,
) -> TimebaseCalibration:
    """Measure scale consistency without inventing absolute alignment.

    A CSV row is observed when the reader loop receives it, not at the
    exact present instant.  The offset estimate therefore carries row
    read/buffering uncertainty.  Relative scale can be verified by
    comparing the CSV span with the observed row span; absolute offset
    is not marked trusted by this method alone.
    """

    result = TimebaseCalibration(
        capture_started_monotonic_ns=(
            capture_started_monotonic_ns
        ),
        presentmon_started_monotonic_ns=(
            presentmon_started_monotonic_ns
        ),
        first_row_monotonic_ns=first_row_monotonic_ns,
        last_row_monotonic_ns=last_row_monotonic_ns,
        first_cpu_start_ms=first_cpu_start_ms,
        last_cpu_start_ms=last_cpu_start_ms,
    )

    required = (
        capture_started_monotonic_ns,
        first_row_monotonic_ns,
        last_row_monotonic_ns,
        first_cpu_start_ms,
        last_cpu_start_ms,
    )

    if any(value is None for value in required):

        result.status = "untrusted"
        result.note = "missing capture or CSV row timing"
        return result

    try:

        first_row = int(first_row_monotonic_ns)
        last_row = int(last_row_monotonic_ns)
        capture_start = int(
            capture_started_monotonic_ns
        )
        first_cpu = float(first_cpu_start_ms)
        last_cpu = float(last_cpu_start_ms)

    except (TypeError, ValueError):

        result.status = "untrusted"
        result.note = "invalid timing values"
        return result

    row_span_ms = (last_row - first_row) / 1_000_000.0
    csv_span_ms = last_cpu - first_cpu

    result.row_span_ms = row_span_ms
    result.csv_span_ms = csv_span_ms

    if presentmon_started_monotonic_ns is not None:

        try:

            result.presentmon_start_offset_ms = (
                int(presentmon_started_monotonic_ns)
                - capture_start
            ) / 1_000_000.0

        except (TypeError, ValueError):

            result.presentmon_start_offset_ms = None

    if row_span_ms <= 0 or csv_span_ms <= 0:

        result.status = "untrusted"
        result.note = "non-positive timing span"
        return result

    span_error_ms = abs(row_span_ms - csv_span_ms)

    result.span_error_ms = span_error_ms

    tolerance_ms = max(
        RELATIVE_SPAN_TOLERANCE_MS,
        row_span_ms * RELATIVE_SPAN_TOLERANCE_RATIO,
    )

    result.relative_scale_trusted = (
        span_error_ms <= tolerance_ms
    )

    result.offset_estimate_ms = (
        (first_row - capture_start) / 1_000_000.0
        - first_cpu
    )

    result.uncertainty_ms = max(
        250.0,
        float(sample_interval_ms) * 2.0,
        span_error_ms,
    )

    if result.relative_scale_trusted:

        result.status = "relative_verified"
        result.note = (
            "CSV and row spans are consistent; absolute offset still "
            "includes CSV read/buffering latency and is not trusted"
        )

    else:

        result.status = "untrusted"
        result.note = (
            "CSV span and observed row span differ beyond tolerance"
        )

    # A future dedicated calibration experiment may set this true.
    result.absolute_offset_trusted = False

    return result


@dataclass
class TelemetryReadResult:
    available: bool = False
    complete: bool = False
    metadata: dict | None = None
    samples: list = field(default_factory=list)
    timebase: dict | None = None
    end: dict | None = None
    error: str = ""

    def sample_count(self):

        return len(self.samples)


def read_telemetry(csv_path) -> TelemetryReadResult:
    """Read a sidecar without ever raising on missing/corrupt data."""

    result = TelemetryReadResult()
    path = telemetry_path(csv_path)

    try:

        lines = path.read_text(
            encoding="utf-8",
            errors="replace",
        ).splitlines()

    except OSError as error:

        result.error = (
            f"telemetry unavailable: {type(error).__name__}"
        )
        return result

    if not lines:

        result.error = "telemetry is empty"
        return result

    for line in lines:

        line = line.strip()

        if not line:

            continue

        try:

            record = json.loads(line)

        except (TypeError, ValueError) as error:

            if not result.available:

                result.error = (
                    "telemetry is corrupt: "
                    f"{type(error).__name__}"
                )

                return result

            result.error = (
                "partial telemetry: "
                f"{type(error).__name__}"
            )
            continue

        if not isinstance(record, dict):

            continue

        kind = record.get("type")

        if kind == "metadata":

            result.metadata = record
            result.available = True

        elif kind == "sample":

            result.samples.append(record)
            result.available = True

        elif kind == "timebase":

            result.timebase = record
            result.available = True

        elif kind == "end":

            result.end = record
            result.available = True

    result.complete = bool(
        result.available
        and result.metadata is not None
        and result.end is not None
    )

    if result.available and not result.complete:

        result.error = result.error or "telemetry is incomplete"

    return result


class TelemetryWriter:
    """Thread-safe JSONL writer with explicit failure state."""

    def __init__(self, path):

        self.path = Path(path)
        self.error = ""
        self.sample_count = 0
        self._file = None
        self._lock = threading.Lock()
        self._last_flush = 0.0
        self._flush_interval_s = 1.0

    def open(self, metadata) -> bool:

        try:

            self.path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )
            self._file = self.path.open(
                "w",
                encoding="utf-8",
                newline="\n",
            )
            return self.write(
                {
                    "type": "metadata",
                    **metadata,
                }
            )

        except OSError as error:

            self.error = type(error).__name__
            return False

    def write(self, record) -> bool:

        with self._lock:

            if self._file is None or self.error:

                return False

            try:

                self._file.write(
                    _json_line(record) + "\n"
                )

                now = time.monotonic()

                if (
                    record.get("type") != "sample"
                    or now - self._last_flush
                    >= self._flush_interval_s
                ):

                    self._file.flush()
                    self._last_flush = now

            except OSError as error:

                self.error = type(error).__name__
                return False

        if record.get("type") == "sample":

            self.sample_count += 1

        return True

    def close(self):

        with self._lock:

            if self._file is None:

                return

            try:

                self._file.flush()
                self._file.close()

            except OSError:

                pass

            self._file = None
