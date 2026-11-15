"""Low-frequency Windows network probes and capture sidecar.

The sampler measures the default gateway and one configurable public
target with ICMP.  ICMP is not a game-server measurement: a timeout is
recorded as a timeout, never as 0 ms or as game packet loss.

Network sampling is independent from frame capture.  The same sampler can
run standalone from the Network page or be attached to a capture; only
samples inside the capture window are written to the sidecar.
"""

from __future__ import annotations

import ctypes
import json
import logging
import math
import os
import re
import socket
import statistics
import subprocess
import threading
import time

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from telemetry import TelemetryWriter


logger = logging.getLogger("laglens.network")
logger.addHandler(logging.NullHandler())


SCHEMA_VERSION = 1
DEFAULT_PUBLIC_TARGET = "1.1.1.1"
DEFAULT_INTERVAL_S = 1.0
DEFAULT_TIMEOUT_MS = 1000

MIN_INTERVAL_S = 0.2
MAX_INTERVAL_S = 10.0
MIN_TIMEOUT_MS = 100
MAX_TIMEOUT_MS = 5000

STATUS_OK = "ok"
STATUS_TIMEOUT = "timeout"
STATUS_UNREACHABLE = "unreachable"
STATUS_ERROR = "error"
STATUS_UNAVAILABLE = "unavailable"


def network_path(csv_path) -> Path:
    return Path(str(csv_path) + ".network.jsonl")


@dataclass(frozen=True)
class ProbeResult:
    status: str
    rtt_ms: float | None = None
    resolved: str | None = None
    error: str = ""

    @property
    def ok(self):
        return self.status == STATUS_OK and self.rtt_ms is not None

    def to_dict(self):
        return {
            "status": self.status,
            "rtt_ms": (
                round(self.rtt_ms, 2)
                if self.rtt_ms is not None
                else None
            ),
            **(
                {"error": self.error}
                if self.error
                else {}
            ),
        }


@dataclass(frozen=True)
class NetworkSample:
    monotonic_ns: int
    gateway: ProbeResult
    public: ProbeResult
    wall_ns: int | None = None

    def to_dict(self):
        return {
            "monotonic_ns": self.monotonic_ns,
            "wall_ns": self.wall_ns,
            "gateway": self.gateway.to_dict(),
            "public": self.public.to_dict(),
        }


def _is_ipv4(value):
    return bool(
        re.fullmatch(
            r"\d{1,3}(?:\.\d{1,3}){3}",
            value or "",
        )
    )


def discover_default_gateway(timeout=3.0):
    """Return the IPv4 default gateway, or ``None``.

    ``route print -4`` is numeric and avoids localized ``ipconfig``
    labels.  A short timeout prevents a broken networking stack from
    delaying startup.
    """

    if os.name != "nt":
        return None

    creationflags = getattr(
        subprocess,
        "CREATE_NO_WINDOW",
        0,
    )

    try:

        result = subprocess.run(
            ["route", "print", "-4"],
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=creationflags,
        )

        for line in result.stdout.splitlines():

            parts = line.split()

            if (
                len(parts) >= 3
                and parts[0] == "0.0.0.0"
                and parts[1] == "0.0.0.0"
                and _is_ipv4(parts[2])
                and parts[2] != "0.0.0.0"
            ):

                return parts[2]

    except (OSError, subprocess.SubprocessError):
        pass

    try:

        result = subprocess.run(
            ["ipconfig"],
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=creationflags,
        )

        match = re.search(
            r"(?:Default Gateway|默认网关)[^\d]*"
            r"(\d{1,3}(?:\.\d{1,3}){3})",
            result.stdout,
        )

        if match and match.group(1) != "0.0.0.0":
            return match.group(1)

    except (OSError, subprocess.SubprocessError):
        pass

    return None


class _IPOptionInformation(ctypes.Structure):

    _fields_ = [
        ("Ttl", ctypes.c_ubyte),
        ("Tos", ctypes.c_ubyte),
        ("Flags", ctypes.c_ubyte),
        ("OptionsSize", ctypes.c_ubyte),
        ("OptionsData", ctypes.c_void_p),
    ]


class _ICMPEchoReply(ctypes.Structure):

    _fields_ = [
        ("Address", ctypes.c_ulong),
        ("Status", ctypes.c_ulong),
        ("RoundTripTime", ctypes.c_ulong),
        ("DataSize", ctypes.c_ushort),
        ("Reserved", ctypes.c_ushort),
        ("Data", ctypes.c_void_p),
        ("Options", _IPOptionInformation),
    ]


_IP_STATUS = {
    0: STATUS_OK,
    11002: STATUS_UNREACHABLE,
    11003: STATUS_UNREACHABLE,
    11004: STATUS_UNREACHABLE,
    11005: STATUS_UNREACHABLE,
    11010: STATUS_TIMEOUT,
    11013: STATUS_UNREACHABLE,
    11014: STATUS_UNREACHABLE,
    11015: STATUS_ERROR,
    11016: STATUS_ERROR,
    11017: STATUS_ERROR,
    11018: STATUS_UNREACHABLE,
}


class IcmpProbe:
    """ICMP echo via iphlpapi; no administrator rights required."""

    def __init__(self):
        self.available = os.name == "nt"
        self._dll = None
        self.error = ""

        if not self.available:
            self.error = "not Windows"
            return

        for name in ("iphlpapi.dll", "icmp.dll"):

            try:

                dll = ctypes.WinDLL(
                    name,
                    use_last_error=True,
                )
                dll.IcmpCreateFile.restype = ctypes.c_void_p
                dll.IcmpCreateFile.argtypes = []
                dll.IcmpCloseHandle.restype = ctypes.c_int
                dll.IcmpCloseHandle.argtypes = [
                    ctypes.c_void_p
                ]
                dll.IcmpSendEcho.restype = ctypes.c_ulong
                dll.IcmpSendEcho.argtypes = [
                    ctypes.c_void_p,
                    ctypes.c_ulong,
                    ctypes.c_void_p,
                    ctypes.c_ushort,
                    ctypes.POINTER(_IPOptionInformation),
                    ctypes.c_void_p,
                    ctypes.c_ulong,
                    ctypes.c_ulong,
                ]
                self._dll = dll
                return

            except (AttributeError, OSError) as error:

                self.error = type(error).__name__

        self.available = False

    def probe(self, host, timeout_ms=DEFAULT_TIMEOUT_MS):
        host = (host or "").strip()

        if not host:
            return ProbeResult(
                STATUS_UNAVAILABLE,
                None,
                error="empty target",
            )

        if not self.available or self._dll is None:
            return ProbeResult(
                STATUS_ERROR,
                None,
                error=self.error or "ICMP unavailable",
            )

        try:
            address = socket.gethostbyname(host)
        except OSError as error:
            return ProbeResult(
                STATUS_ERROR,
                None,
                error=type(error).__name__,
            )

        try:
            packed = socket.inet_aton(address)
            destination = int.from_bytes(
                packed,
                "little",
            )
        except OSError:
            return ProbeResult(
                STATUS_ERROR,
                None,
                error="invalid address",
            )

        timeout_ms = max(
            MIN_TIMEOUT_MS,
            min(int(timeout_ms), MAX_TIMEOUT_MS),
        )
        payload = ctypes.create_string_buffer(b"laglens!")
        reply_buffer = ctypes.create_string_buffer(
            ctypes.sizeof(_ICMPEchoReply) + 64
        )
        handle = self._dll.IcmpCreateFile()

        if not handle:
            return ProbeResult(
                STATUS_ERROR,
                None,
                error="IcmpCreateFile",
            )

        try:

            count = self._dll.IcmpSendEcho(
                handle,
                destination,
                payload,
                len(payload) - 1,
                None,
                reply_buffer,
                len(reply_buffer),
                timeout_ms,
            )

            if not count:

                code = ctypes.get_last_error()
                status = _IP_STATUS.get(
                    code,
                    STATUS_TIMEOUT
                    if code == 11010
                    else STATUS_ERROR,
                )
                return ProbeResult(
                    status,
                    None,
                    address,
                    f"icmp {code}",
                )

            reply = _ICMPEchoReply.from_buffer_copy(
                reply_buffer.raw[
                    : ctypes.sizeof(_ICMPEchoReply)
                ]
            )
            status = _IP_STATUS.get(
                int(reply.Status),
                STATUS_ERROR,
            )

            if status == STATUS_OK:
                return ProbeResult(
                    STATUS_OK,
                    float(reply.RoundTripTime),
                    address,
                )

            return ProbeResult(
                status,
                None,
                address,
                f"icmp {reply.Status}",
            )

        finally:
            self._dll.IcmpCloseHandle(handle)


class NetworkSampler:
    """Background gateway/public probe thread."""

    def __init__(
        self,
        gateway=None,
        public_target=DEFAULT_PUBLIC_TARGET,
        interval_s=DEFAULT_INTERVAL_S,
        probe=None,
        gateway_resolver=None,
    ):
        self.gateway = (
            gateway
            if gateway is not None
            else (gateway_resolver or discover_default_gateway)()
        )
        self.public_target = (
            (public_target or "").strip()
            or DEFAULT_PUBLIC_TARGET
        )
        self.interval_s = max(
            MIN_INTERVAL_S,
            min(float(interval_s), MAX_INTERVAL_S),
        )
        self.probe = probe or IcmpProbe()
        self.samples = []
        self.started_monotonic_ns = None
        self.last_error = ""
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._executor = None

    @property
    def running(self):
        return bool(
            self._thread is not None
            and self._thread.is_alive()
        )

    def start(self):
        if self.running:
            return True

        self._stop.clear()
        self.started_monotonic_ns = time.monotonic_ns()
        self._thread = threading.Thread(
            target=self._run,
            name="LagLensNetworkSampler",
            daemon=True,
        )
        self._thread.start()
        return True

    def stop(self, timeout=4.0):
        self._stop.set()
        thread = self._thread

        if thread is not None:
            thread.join(timeout=max(0.1, timeout))

        executor = self._executor

        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)

        self._executor = None
        self._thread = None

    def snapshot(self):
        with self._lock:
            return list(self.samples)

    def reset_samples(self):
        with self._lock:
            self.samples.clear()

    def _probe_one(self, host):
        if not host:
            return ProbeResult(
                STATUS_UNAVAILABLE,
                None,
                error="no target",
            )

        try:
            return self.probe.probe(
                host,
                timeout_ms=int(self.interval_s * 1000),
            )
        except Exception as error:  # pragma: no cover - defensive
            return ProbeResult(
                STATUS_ERROR,
                None,
                error=type(error).__name__,
            )

    def _run(self):
        executor = ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="LagLensNetworkProbe",
        )
        self._executor = executor

        try:

            while not self._stop.is_set():

                started = time.monotonic()
                sample_ns = time.monotonic_ns()
                gateway_future = (
                    executor.submit(
                        self._probe_one,
                        self.gateway,
                    )
                    if self.gateway
                    else None
                )
                public_future = executor.submit(
                    self._probe_one,
                    self.public_target,
                )

                try:
                    gateway = (
                        gateway_future.result(timeout=4.0)
                        if gateway_future is not None
                        else ProbeResult(
                            STATUS_UNAVAILABLE,
                            None,
                            error="no gateway",
                        )
                    )
                except Exception:
                    gateway = ProbeResult(
                        STATUS_ERROR,
                        None,
                        error="probe failed",
                    )

                try:
                    public = public_future.result(timeout=4.0)
                except Exception:
                    public = ProbeResult(
                        STATUS_ERROR,
                        None,
                        error="probe failed",
                    )

                sample = NetworkSample(
                    sample_ns,
                    gateway,
                    public,
                    wall_ns=time.time_ns(),
                )

                with self._lock:
                    self.samples.append(sample)

                elapsed = time.monotonic() - started
                self._stop.wait(
                    max(0.0, self.interval_s - elapsed)
                )

        finally:
            executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None


@dataclass
class NetworkReadResult:
    available: bool = False
    complete: bool = False
    metadata: dict | None = None
    samples: list = field(default_factory=list)
    end: dict | None = None
    error: str = ""

    def sample_count(self):
        return len(self.samples)


def read_network(csv_path) -> NetworkReadResult:
    """Read a network sidecar without ever raising on bad data."""

    result = NetworkReadResult()
    path = network_path(csv_path)

    try:
        lines = path.read_text(
            encoding="utf-8",
            errors="replace",
        ).splitlines()
    except OSError:
        return result

    for line in lines:

        line = line.strip()

        if not line:
            continue

        try:
            record = json.loads(line)
        except (TypeError, ValueError):
            result.error = "corrupt network sidecar"
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
        elif kind == "end":
            result.end = record
            result.available = True

    result.complete = bool(
        result.available
        and result.metadata is not None
        and result.end is not None
    )
    result.samples.sort(
        key=lambda sample: float(
            sample.get("t_ms") or 0.0
        )
    )
    return result


def _probe_stats(samples, name):
    rtts = []
    timeouts = 0
    unreachable = 0
    errors = 0

    for sample in samples:

        if isinstance(sample, dict):
            probe = sample.get(name) or {}
        else:
            probe = getattr(sample, name, None) or {}

        if isinstance(probe, ProbeResult):
            status = probe.status
            rtt = probe.rtt_ms
        else:
            status = probe.get("status")
            rtt = probe.get("rtt_ms")

        if status == STATUS_OK and rtt is not None:
            rtts.append(float(rtt))
        elif status == STATUS_TIMEOUT:
            timeouts += 1
        elif status == STATUS_UNREACHABLE:
            unreachable += 1
        else:
            errors += 1

    if not rtts and not timeouts and not unreachable and not errors:
        return None

    if len(rtts) > 1:

        median_rtt = statistics.median(rtts)
        jitter = statistics.median(
            abs(value - median_rtt)
            for value in rtts
        )

    else:

        jitter = 0.0

    return {
        "samples": len(samples),
        "responses": len(rtts),
        "timeouts": timeouts,
        "unreachable": unreachable,
        "errors": errors,
        "latency_median_ms": (
            round(statistics.median(rtts), 2)
            if rtts
            else None
        ),
        "jitter_ms": round(jitter, 2),
        "min_ms": round(min(rtts), 2) if rtts else None,
        "max_ms": round(max(rtts), 2) if rtts else None,
    }


def summarize_samples(samples):
    """Return gateway/public stats for UI, reports and AI summaries."""

    samples = list(samples or [])

    if not samples:
        return {
            "available": False,
            "gateway": None,
            "public": None,
            "game_server": None,
        }

    times = [
        float(sample["t_ms"])
        for sample in samples
        if (
            isinstance(sample, dict)
            and sample.get("t_ms") is not None
        )
    ]

    return {
        "available": True,
        "gateway": _probe_stats(samples, "gateway"),
        "public": _probe_stats(samples, "public"),
        "coverage_start_s": (
            round(min(times) / 1000.0, 2)
            if times
            else None
        ),
        "coverage_end_s": (
            round(max(times) / 1000.0, 2)
            if times
            else None
        ),
        "coverage_s": (
            round((max(times) - min(times)) / 1000.0, 2)
            if times
            else None
        ),
        # No game-server probe exists.  Do not infer it from a public
        # target, even when the user calls the public target a game
        # server.
        "game_server": None,
    }


def summarize_result(result):
    if result is None or not getattr(result, "available", False):
        return None

    summary = summarize_samples(result.samples)
    return summary if summary["available"] else None


class NetworkRecorder:
    """Write only samples inside one capture time window."""

    def __init__(self):
        self.writer = None
        self.sample_count = 0
        self._sampler = None
        self._origin_ns = None
        self._next_index = 0
        self._stop = threading.Event()
        self._thread = None

    def start(
        self,
        csv_path,
        sampler,
        target_name="",
        origin_ns=None,
        session_id="",
    ):
        self._sampler = sampler
        self._origin_ns = int(
            origin_ns
            if origin_ns is not None
            else time.monotonic_ns()
        )
        self._next_index = 0
        self._stop.clear()
        self.writer = TelemetryWriter(network_path(csv_path))

        metadata = {
            "schema_version": SCHEMA_VERSION,
            "session_id": str(session_id or ""),
            "capture": {
                "csv_name": Path(str(csv_path)).name,
                "target_name": str(target_name or ""),
            },
            "network": {
                "gateway_available": bool(
                    getattr(sampler, "gateway", None)
                ),
                "public_target": str(
                    getattr(
                        sampler,
                        "public_target",
                        DEFAULT_PUBLIC_TARGET,
                    )
                ),
                "interval_ms": int(
                    getattr(sampler, "interval_s", 1.0)
                    * 1000
                ),
            },
        }

        if not self.writer.open(metadata):
            logger.debug(
                "network sidecar unavailable: %s",
                self.writer.error,
            )
            return False

        self._thread = threading.Thread(
            target=self._run,
            name="LagLensNetworkRecorder",
            daemon=True,
        )
        self._thread.start()
        return True

    def _drain(self):
        if self._sampler is None:
            return

        samples = self._sampler.snapshot()
        new_samples = samples[self._next_index :]
        self._next_index = len(samples)

        for sample in new_samples:

            if sample.monotonic_ns < self._origin_ns:
                continue

            t_ms = (
                sample.monotonic_ns - self._origin_ns
            ) / 1_000_000.0
            record = {
                "type": "sample",
                "t_ms": round(t_ms, 3),
                "source": "icmp",
                "interval_ms": int(
                    getattr(
                        self._sampler,
                        "interval_s",
                        0.0,
                    )
                    * 1000
                ),
                "valid": bool(
                    sample.gateway.ok
                    or sample.public.ok
                ),
                **sample.to_dict(),
            }

            if self.writer.write(record):
                self.sample_count += 1

    def _run(self):
        while not self._stop.wait(0.1):
            self._drain()

    def stop(self, reason="finished", outcome="finished"):
        self._stop.set()

        if self._thread is not None:
            self._thread.join(timeout=2.0)

        self._thread = None
        self._drain()

        if self.writer is not None:
            self.writer.write(
                {
                    "type": "end",
                    "sample_count": self.sample_count,
                    "reason": str(reason),
                    "outcome": str(outcome),
                }
            )
            self.writer.close()

        self.writer = None
        self._sampler = None


class NetworkService:
    """Own one sampler shared by standalone and capture modes."""

    def __init__(self, sampler=None):
        self._lock = threading.RLock()
        self.sampler = sampler
        self.recorder = None
        self.standalone = False
        self.capture_active = False
        self.started_for_capture = False
        self.last_error = ""

    @property
    def running(self):
        return bool(
            self.sampler is not None
            and self.sampler.running
        )

    def state(self):
        with self._lock:
            sampler = self.sampler
            return {
                "running": bool(
                    sampler is not None
                    and sampler.running
                ),
                "standalone": self.standalone,
                "capture_active": self.capture_active,
                "started_for_capture": self.started_for_capture,
                "gateway": (
                    getattr(sampler, "gateway", None)
                    if sampler is not None
                    else None
                ),
                "public_target": (
                    getattr(
                        sampler,
                        "public_target",
                        DEFAULT_PUBLIC_TARGET,
                    )
                    if sampler is not None
                    else DEFAULT_PUBLIC_TARGET
                ),
                "last_error": self.last_error,
            }

    def snapshot(self):
        with self._lock:
            sampler = self.sampler
            return sampler.snapshot() if sampler else []

    def _ensure_sampler(self, public_target):
        sampler = self.sampler

        if sampler is not None and sampler.running:
            return sampler

        try:
            if sampler is None:
                sampler = NetworkSampler(
                    public_target=public_target,
                )
            else:
                sampler.reset_samples()
            sampler.start()
            self.sampler = sampler
            self.last_error = ""
            return sampler
        except Exception as error:
            self.last_error = type(error).__name__
            logger.debug(
                "network sampler start failed: %s",
                error,
            )
            return None

    def start_standalone(self, public_target=DEFAULT_PUBLIC_TARGET):
        with self._lock:
            if self.capture_active:
                return False

            if self.running:
                self.standalone = True
                return True

            if self._ensure_sampler(public_target) is None:
                return False

            self.standalone = True
            return True

    def stop_standalone(self):
        with self._lock:
            if self.capture_active or not self.standalone:
                return False

            sampler = self.sampler
            self.standalone = False

        if sampler is not None:
            sampler.stop()
        return True

    def begin_capture(
        self,
        csv_path,
        target_name,
        origin_ns,
        public_target=DEFAULT_PUBLIC_TARGET,
        session_id="",
    ):
        with self._lock:
            if self.capture_active:
                return False

            was_running = self.running
            sampler = self._ensure_sampler(public_target)

            if sampler is None:
                return False

            recorder = NetworkRecorder()
            started = recorder.start(
                csv_path,
                sampler,
                target_name=target_name,
                origin_ns=origin_ns,
                session_id=session_id,
            )

            if not started:
                if not was_running:
                    sampler.stop()
                    self.sampler = None
                self.last_error = "sidecar"
                return False

            self.recorder = recorder
            self.capture_active = True
            self.started_for_capture = not was_running
            return True

    def end_capture(self, reason="finished", outcome="finished"):
        with self._lock:
            recorder = self.recorder
            self.recorder = None
            was_started_for_capture = (
                self.started_for_capture
            )
            self.capture_active = False
            self.started_for_capture = False
            sampler = self.sampler
            self.sampler = (
                sampler
                if self.standalone
                else None
            )

        if recorder is not None:
            recorder.stop(reason=reason, outcome=outcome)

        if was_started_for_capture and sampler is not None:
            sampler.stop()

    def shutdown(self):
        self.end_capture("closed", "closed")
        with self._lock:
            sampler = self.sampler
            self.sampler = None
            self.standalone = False

        if sampler is not None:
            sampler.stop()
