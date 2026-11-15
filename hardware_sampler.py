"""C-1 hardware telemetry sampler.

The sampler runs outside the PresentMon capture worker, records
timestamped samples to a JSONL sidecar and never blocks the CSV
pipeline.  Sampling failures are recorded as missing values; stale
values are never reused.
"""

from __future__ import annotations

import logging
import threading
import time

from pathlib import Path

import psutil
import pynvml

from telemetry import (
    DEFAULT_INTERVAL_MS,
    GpuDevice,
    LOW_OVERHEAD_INTERVAL_MS,
    SCHEMA_VERSION,
    TimebaseCalibration,
    TelemetryWriter,
    calibrate_timebase,
    telemetry_path,
)


logger = logging.getLogger("laglens.hardware_sampler")
logger.addHandler(logging.NullHandler())


DEFAULT_INTERVAL_S = DEFAULT_INTERVAL_MS / 1000.0
LOW_OVERHEAD_INTERVAL_S = LOW_OVERHEAD_INTERVAL_MS / 1000.0
TARGET_REFRESH_INTERVAL_S = 5.0


def _decode_nvml(value):

    if isinstance(value, bytes):

        return value.decode(
            "utf-8",
            "replace",
        ).strip()

    return str(value or "").strip()


class NvmlGpuProvider:
    """Best-effort NVML reader for one selected GPU handle.

    The provider records the sampled device identity and marks the
    target-to-GPU association as unknown.  It does not claim that GPU
    index 0 is the game's GPU.
    """

    def __init__(
        self,
        handle=None,
        index=None,
        module=pynvml,
    ):

        self.handle = handle
        self.index = index
        self.module = module

    def describe(self):

        if self.handle is None:

            return {
                "available": False,
                "status": "unavailable",
                "devices": [],
                "sampled_device": None,
                "multi_gpu": False,
                "association": "unknown",
            }

        devices = []

        try:

            count = int(
                self.module.nvmlDeviceGetCount()
            )

        except (
            AttributeError,
            OSError,
            pynvml.NVMLError,
            TypeError,
            ValueError,
        ) as error:

            return {
                "available": False,
                "status": "unavailable",
                "devices": [],
                "sampled_device": None,
                "multi_gpu": False,
                "association": "unknown",
                "error": type(error).__name__,
            }

        if count <= 0:

            return {
                "available": False,
                "status": "unavailable",
                "devices": [],
                "sampled_device": None,
                "multi_gpu": False,
                "association": "unknown",
            }

        for device_index in range(count):

            try:

                handle = self.module.nvmlDeviceGetHandleByIndex(
                    device_index
                )

            except (
                AttributeError,
                OSError,
                pynvml.NVMLError,
                TypeError,
                ValueError,
            ):

                continue

            name = ""
            uuid = ""
            bus_id = ""

            try:

                name = _decode_nvml(
                    self.module.nvmlDeviceGetName(handle)
                )

            except (
                AttributeError,
                OSError,
                pynvml.NVMLError,
                TypeError,
                ValueError,
            ):

                pass

            try:

                uuid = _decode_nvml(
                    self.module.nvmlDeviceGetUUID(handle)
                )

            except (
                AttributeError,
                OSError,
                pynvml.NVMLError,
                TypeError,
                ValueError,
            ):

                pass

            try:

                bus_id = _decode_nvml(
                    self.module.nvmlDeviceGetBusId(handle)
                )

            except (
                AttributeError,
                OSError,
                pynvml.NVMLError,
                TypeError,
                ValueError,
            ):

                pass

            devices.append(
                GpuDevice(
                    index=device_index,
                    name=name,
                    uuid=uuid,
                    bus_id=bus_id,
                    association="unknown",
                ).to_dict()
            )

        sampled = None

        if (
            self.index is not None
            and 0 <= int(self.index) < len(devices)
        ):

            sampled = devices[int(self.index)]

        return {
            "available": True,
            "status": "ok",
            "devices": devices,
            "sampled_device": sampled,
            "multi_gpu": len(devices) > 1,
            "association": "unknown",
            "note": (
                "sampled NVML device identity is recorded; association "
                "with the captured process is unknown"
            ),
        }

    def read(self):

        if self.handle is None:

            return {
                "status": "unavailable",
                "util_percent": None,
                "vram_used_bytes": None,
                "vram_total_bytes": None,
                "temperature_c": None,
                "association": "unknown",
            }

        try:

            usage = int(
                self.module.nvmlDeviceGetUtilizationRates(
                    self.handle
                ).gpu
            )
            memory = self.module.nvmlDeviceGetMemoryInfo(
                self.handle
            )
            temperature = int(
                self.module.nvmlDeviceGetTemperature(
                    self.handle,
                    self.module.NVML_TEMPERATURE_GPU,
                )
            )

            return {
                "status": "ok",
                "util_percent": usage,
                "vram_used_bytes": int(memory.used),
                "vram_total_bytes": int(memory.total),
                "temperature_c": temperature,
                "association": "unknown",
            }

        except (
            AttributeError,
            OSError,
            pynvml.NVMLError,
            TypeError,
            ValueError,
        ) as error:

            return {
                "status": "unavailable",
                "util_percent": None,
                "vram_used_bytes": None,
                "vram_total_bytes": None,
                "temperature_c": None,
                "association": "unknown",
                "error": type(error).__name__,
            }


class TargetProcessTracker:
    """Track target PIDs without reusing a PID after process restart.

    Process objects are kept alive across samples.  This is required for
    ``psutil.Process.cpu_percent(interval=None)``: a new object would
    return ``0.0`` as its first-call baseline on every sample.
    """

    def __init__(
        self,
        target_name,
        process_iter_factory=None,
        process_factory=None,
        refresh_interval_s=TARGET_REFRESH_INTERVAL_S,
        monotonic_ns=None,
    ):

        self.target_name = (target_name or "").strip()
        self._process_iter = (
            process_iter_factory
            or psutil.process_iter
        )
        self._process_factory = (
            process_factory
            or psutil.Process
        )
        self._refresh_interval_s = refresh_interval_s
        self._monotonic_ns = (
            monotonic_ns or time.perf_counter_ns
        )

        self._known = {}
        self._processes = {}
        self._primed = set()
        self._last_refresh_ns = None
        self._had_target = False
        self.pid_reuse_detected = False
        self.target_exited = False
        self.last_error = ""

    def _matches(self, name):

        return (
            bool(name)
            and name.casefold()
            == self.target_name.casefold()
        )

    def refresh(self, force=False):

        if not self.target_name:

            self._known.clear()
            self._processes.clear()
            self._primed.clear()
            self.target_exited = True
            return

        now = self._monotonic_ns()

        if (
            not force
            and self._last_refresh_ns is not None
            and (now - self._last_refresh_ns) / 1e9
            < self._refresh_interval_s
        ):

            return

        self._last_refresh_ns = now
        current = {}

        try:

            # Only query create_time for name matches.  Asking psutil
            # for create_time on every process takes ~0.8 s on this
            # machine and dominates the sampler's startup cost.
            for process in self._process_iter(
                ["pid", "name"]
            ):

                try:

                    info = process.info
                    pid = int(info.get("pid"))
                    name = str(
                        info.get("name") or ""
                    )

                except (
                    OSError,
                    TypeError,
                    ValueError,
                    psutil.Error,
                ):

                    continue

                if not self._matches(name):

                    continue

                try:

                    create_time = float(
                        process.create_time()
                    )

                except (
                    OSError,
                    TypeError,
                    ValueError,
                    psutil.Error,
                ):

                    continue

                current[pid] = create_time

        except (
            OSError,
            TypeError,
            ValueError,
            psutil.Error,
        ) as error:

            self.last_error = type(error).__name__
            return

        for pid, create_time in current.items():

            previous = self._known.get(pid)

            if (
                previous is not None
                and abs(previous - create_time) > 0.5
            ):

                self.pid_reuse_detected = True
                self._primed.discard(pid)
                self._processes.pop(pid, None)

            if pid not in self._processes:

                try:

                    self._processes[pid] = (
                        self._process_factory(pid)
                    )

                except (
                    OSError,
                    TypeError,
                    ValueError,
                    psutil.Error,
                ):

                    self._known.pop(pid, None)
                    self._processes.pop(pid, None)
                    self._primed.discard(pid)
                    continue

            self._known[pid] = create_time

        for pid in list(self._known):

            if pid not in current:

                self._known.pop(pid, None)
                self._processes.pop(pid, None)
                self._primed.discard(pid)

        if current:

            self._had_target = True

        self.target_exited = (
            self._had_target and not self._known
        )

    def sample(self):

        self.refresh()

        processes = []
        cpu_total = 0.0
        rss_total = 0
        cpu_seen = False
        rss_seen = False

        for pid, expected_create_time in list(
            self._known.items()
        ):

            process = self._processes.get(pid)

            if process is None:

                try:

                    process = self._process_factory(pid)
                    self._processes[pid] = process

                except (
                    OSError,
                    TypeError,
                    ValueError,
                    psutil.Error,
                ):

                    self._known.pop(pid, None)
                    self._processes.pop(pid, None)
                    self._primed.discard(pid)
                    continue

            try:

                create_time = float(
                    process.create_time()
                )

            except psutil.NoSuchProcess:

                self._known.pop(pid, None)
                self._processes.pop(pid, None)
                self._primed.discard(pid)
                continue

            except (
                OSError,
                TypeError,
                ValueError,
                psutil.Error,
            ):

                self._known.pop(pid, None)
                self._processes.pop(pid, None)
                self._primed.discard(pid)
                continue

            if abs(create_time - expected_create_time) > 0.5:

                self.pid_reuse_detected = True
                self._known.pop(pid, None)
                self._processes.pop(pid, None)
                self._primed.discard(pid)
                continue

            try:

                cpu = process.cpu_percent(
                    interval=None
                )

            except psutil.NoSuchProcess:

                self._known.pop(pid, None)
                self._processes.pop(pid, None)
                self._primed.discard(pid)
                continue

            except (
                OSError,
                TypeError,
                ValueError,
                psutil.Error,
            ):

                cpu = None

            if cpu is not None and pid in self._primed:

                cpu_total += float(cpu)
                cpu_seen = True

            elif cpu is not None:

                self._primed.add(pid)

            try:

                memory = process.memory_info()
                rss = int(memory.rss)

            except psutil.NoSuchProcess:

                self._known.pop(pid, None)
                self._processes.pop(pid, None)
                self._primed.discard(pid)
                continue

            except (
                OSError,
                TypeError,
                ValueError,
                psutil.Error,
            ):

                rss = None

            if rss is not None:

                rss_total += rss
                rss_seen = True

            processes.append(
                {
                    "pid": pid,
                    "create_time": expected_create_time,
                    "cpu_percent": (
                        float(cpu)
                        if cpu is not None
                        else None
                    ),
                    "rss_bytes": rss,
                    "status": (
                        "ok"
                        if cpu is not None or rss is not None
                        else "unavailable"
                    ),
                }
            )

        if self.target_name and self._had_target and not self._known:

            self.target_exited = True

        if not self.target_name:

            status = "unavailable"

        elif self.pid_reuse_detected and not processes:

            status = "pid_reused"

        elif self.target_exited:

            status = "target_exited"

        elif processes:

            status = "ok"

        else:

            status = "unavailable"

        return {
            "status": status,
            "pids": [
                {
                    "pid": pid,
                    "create_time": create_time,
                }
                for pid, create_time in self._known.items()
            ],
            "cpu_percent": (
                cpu_total if cpu_seen else None
            ),
            "rss_bytes": (
                rss_total if rss_seen else None
            ),
            "processes": processes,
            "pid_reuse_detected": (
                self.pid_reuse_detected
            ),
        }


class HardwareSampler:
    """Timestamped hardware sampler with a JSONL sidecar."""

    def __init__(
        self,
        csv_path,
        target_name,
        interval_s=DEFAULT_INTERVAL_S,
        low_overhead=False,
        qpc_time=False,
        gpu_handle=None,
        gpu_index=None,
        gpu_provider=None,
        tracker=None,
        cpu_percent=None,
        per_cpu_percent=None,
        virtual_memory=None,
        monotonic_ns=None,
        wall_ns=None,
        writer_factory=None,
        session_id="",
        origin_monotonic_ns=None,
    ):

        self.csv_path = Path(csv_path)
        self.session_id = str(session_id or "")
        self._origin_monotonic_ns = (
            None
            if origin_monotonic_ns is None
            else int(origin_monotonic_ns)
        )
        self.target_name = (target_name or "").strip()
        self.interval_s = max(0.05, float(interval_s))
        self.low_overhead = bool(low_overhead)
        self.qpc_time = bool(qpc_time)
        self.profile = (
            "low_overhead"
            if self.low_overhead
            else "default"
        )

        self._gpu = (
            gpu_provider
            or NvmlGpuProvider(
                handle=gpu_handle,
                index=gpu_index,
            )
        )
        self._tracker = (
            tracker
            or TargetProcessTracker(
                self.target_name,
                monotonic_ns=monotonic_ns,
            )
        )
        self._cpu_percent = (
            cpu_percent
            or psutil.cpu_percent
        )
        self._per_cpu_percent = (
            per_cpu_percent
            or (
                lambda: psutil.cpu_percent(
                    interval=None,
                    percpu=True,
                )
            )
        )
        self._virtual_memory = (
            virtual_memory
            or psutil.virtual_memory
        )
        self._monotonic_ns = (
            monotonic_ns or time.perf_counter_ns
        )
        self._wall_ns = wall_ns or time.time_ns
        self._writer = (
            writer_factory
            or TelemetryWriter
        )(telemetry_path(self.csv_path))

        self.sidecar_path = self._writer.path

        self._thread = None
        self._stop_event = threading.Event()
        self._started = False
        self._stopped = False
        self._started_monotonic_ns = None
        self._started_wall_ns = None
        self._presentmon_started_ns = None
        self._sample_count = 0
        self._sampling_errors = []
        self._timebase = None
        self._timebase_written = False
        self._frame_timebase = None
        self._capture_outcome = "unknown"
        self._valid_frames = 0
        self._last_sample = None

    @property
    def write_error(self):

        return self._writer.error

    @property
    def sampling_errors(self):

        return tuple(self._sampling_errors)

    @property
    def timebase(self):

        return self._timebase

    @property
    def started(self):

        return self._started

    @property
    def started_monotonic_ns(self):

        return self._started_monotonic_ns

    @property
    def running(self):

        return (
            self._thread is not None
            and self._thread.is_alive()
        )

    def start(self):

        if self._started:

            return True

        self._started_monotonic_ns = (
            self._origin_monotonic_ns
            if self._origin_monotonic_ns is not None
            else self._monotonic_ns()
        )
        self._started_wall_ns = self._wall_ns()

        try:

            gpu_description = self._gpu.describe()

        except Exception as error:  # pragma: no cover - defensive

            gpu_description = {
                "available": False,
                "status": "unavailable",
                "devices": [],
                "sampled_device": None,
                "multi_gpu": False,
                "association": "unknown",
                "error": type(error).__name__,
            }

        metadata = {
            "schema_version": SCHEMA_VERSION,
            "capture": {
                "csv_name": self.csv_path.name,
                "target_name": self.target_name,
                "profile": self.profile,
                "session_id": self.session_id,
                "started_monotonic_ns": (
                    self._started_monotonic_ns
                ),
                "started_wall_ns": self._started_wall_ns,
                "sample_interval_ms": int(
                    round(self.interval_s * 1000)
                ),
                "presentmon_gpu_tracking": (
                    "disabled"
                    if self.low_overhead
                    else "enabled"
                ),
                "qpc_time_requested": self.qpc_time,
                "timebase_kind": (
                    "qpc_ms"
                    if self.qpc_time
                    else "relative"
                ),
                "expected_time_column": (
                    "CPUStartQPCTime"
                    if self.qpc_time
                    else "CPUStartTime"
                ),
            },
            "gpu": gpu_description,
            "sampling": {
                "interval_ms": int(
                    round(self.interval_s * 1000)
                ),
                "low_overhead": self.low_overhead,
            },
        }

        if not self._writer.open(metadata):

            logger.debug(
                "telemetry sidecar could not be created: %s",
                self._writer.error,
            )

            return False

        try:

            self._tracker.refresh(force=True)

        except Exception as error:  # pragma: no cover - defensive

            self._sampling_errors.append(
                type(error).__name__
            )

        # Prime psutil so the first sample is not a misleading zero.
        try:

            self._cpu_percent(interval=None)
            self._per_cpu_percent()

        except Exception:  # pragma: no cover - defensive

            pass

        self._thread = threading.Thread(
            target=self._run,
            name="LagLensTelemetry",
            daemon=True,
        )
        self._thread.start()
        self._started = True

        return True

    def note_presentmon_started(self, monotonic_ns=None):

        self._presentmon_started_ns = (
            monotonic_ns
            if monotonic_ns is not None
            else self._monotonic_ns()
        )

        if self._started:

            self._writer.write(
                {
                    "type": "marker",
                    "name": "presentmon_started",
                    "monotonic_ns": (
                        self._presentmon_started_ns
                    ),
                    "wall_ns": self._wall_ns(),
                }
            )

    def note_capture_timing(
        self,
        first_row_monotonic_ns,
        last_row_monotonic_ns,
        first_cpu_start_ms,
        last_cpu_start_ms,
        valid_frames=0,
        capture_outcome="unknown",
        frame_timebase=None,
    ):

        self._capture_outcome = capture_outcome
        self._valid_frames = int(valid_frames or 0)
        self._frame_timebase = frame_timebase

        calibration = calibrate_timebase(
            self._started_monotonic_ns,
            self._presentmon_started_ns,
            first_row_monotonic_ns,
            last_row_monotonic_ns,
            first_cpu_start_ms,
            last_cpu_start_ms,
            sample_interval_ms=self.interval_s * 1000,
        )

        if (
            isinstance(frame_timebase, dict)
            and frame_timebase.get("kind") == "qpc_ms"
            and self._valid_frames > 0
        ):

            quality = frame_timebase.get("sync_quality")

            if frame_timebase.get(
                "absolute_mapping_trusted"
            ):

                calibration.status = "qpc_verified"

            elif quality == "inferred_qpc":

                calibration.status = "qpc_inferred"

            else:

                calibration.status = "qpc_unverified"

            calibration.note = (
                "QPC frame timestamps are embedded in the CSV; "
                "the row-arrival span check is not used for QPC "
                "mapping. See frame_timebase for sync quality."
            )

        self._timebase = calibration

        if not self._started:

            return calibration

        if self._writer.write(
            {
                "type": "timebase",
                "capture_outcome": self._capture_outcome,
                "valid_frames": self._valid_frames,
                "frame_timebase": self._frame_timebase,
                **calibration.to_dict(),
            }
        ):

            self._timebase_written = True

        return calibration

    def _collect_sample(self):

        try:

            cpu = float(
                self._cpu_percent(interval=None)
            )
            per_core = [
                float(value)
                for value in self._per_cpu_percent()
            ]
            cpu_status = "ok"

        except Exception as error:  # pragma: no cover - defensive

            cpu = None
            per_core = None
            cpu_status = "unavailable"
            self._sampling_errors.append(
                type(error).__name__
            )

        try:

            memory = self._virtual_memory()

            ram = {
                "status": "ok",
                "used_bytes": int(memory.used),
                "total_bytes": int(memory.total),
                "percent": float(memory.percent),
                "available_bytes": int(
                    getattr(memory, "available", 0)
                ),
            }

        except Exception as error:  # pragma: no cover - defensive

            ram = {
                "status": "unavailable",
                "used_bytes": None,
                "total_bytes": None,
                "percent": None,
                "available_bytes": None,
                "error": type(error).__name__,
            }
            self._sampling_errors.append(
                type(error).__name__
            )

        try:

            target = self._tracker.sample()

        except Exception as error:  # pragma: no cover - defensive

            target = {
                "status": "unavailable",
                "error": type(error).__name__,
            }
            self._sampling_errors.append(
                type(error).__name__
            )

        try:

            gpu = self._gpu.read()

        except Exception as error:  # pragma: no cover - defensive

            gpu = {
                "status": "unavailable",
                "util_percent": None,
                "vram_used_bytes": None,
                "vram_total_bytes": None,
                "temperature_c": None,
                "association": "unknown",
                "error": type(error).__name__,
            }
            self._sampling_errors.append(
                type(error).__name__
            )

        return {
            "cpu": {
                "status": cpu_status,
                "system_percent": cpu,
                "per_core_percent": per_core,
            },
            "ram": ram,
            "target": target,
            "gpu": gpu,
        }

    def _run(self):

        while not self._stop_event.is_set():

            started_ns = self._monotonic_ns()

            try:

                sample = self._collect_sample()

            except Exception as error:  # pragma: no cover - defensive

                sample = {
                    "status": "error",
                    "error": type(error).__name__,
                }
                self._sampling_errors.append(
                    type(error).__name__
                )

            sample.update(
                {
                    "type": "sample",
                    "t_ms": (
                        started_ns
                        - self._started_monotonic_ns
                    )
                    / 1_000_000.0,
                    "wall_ns": self._wall_ns(),
                    "sample_cost_ms": (
                        self._monotonic_ns() - started_ns
                    )
                    / 1_000_000.0,
                }
            )

            self._last_sample = sample

            if not self._writer.write(sample):

                logger.debug(
                    "telemetry write stopped: %s",
                    self._writer.error,
                )

                break

            self._sample_count += 1

            elapsed_s = (
                self._monotonic_ns() - started_ns
            ) / 1_000_000_000.0

            self._stop_event.wait(
                max(0.0, self.interval_s - elapsed_s)
            )

    def stop(
        self,
        reason="stopped",
        capture_outcome=None,
        valid_frames=None,
    ):

        if self._stopped:

            return

        if capture_outcome is not None:

            self._capture_outcome = capture_outcome

        if valid_frames is not None:

            self._valid_frames = int(valid_frames)

        self._stop_event.set()

        if self._thread is not None:

            self._thread.join(timeout=2.0)

            if self._thread.is_alive():

                self._sampling_errors.append(
                    "thread_stop_timeout"
                )

        if self._started and not self._timebase_written:

            if self._timebase is None:

                self._timebase = calibrate_timebase(
                    self._started_monotonic_ns,
                    self._presentmon_started_ns,
                    None,
                    None,
                    None,
                    None,
                    sample_interval_ms=(
                        self.interval_s * 1000
                    ),
                )

            if self._writer.write(
                {
                    "type": "timebase",
                    "capture_outcome": (
                        self._capture_outcome
                    ),
                    "valid_frames": self._valid_frames,
                    "frame_timebase": (
                        self._frame_timebase
                        or {
                            "kind": (
                                "qpc_ms"
                                if self.qpc_time
                                else "relative"
                            ),
                            "raw_column": (
                                "CPUStartQPCTime"
                                if self.qpc_time
                                else "CPUStartTime"
                            ),
                            "sync_quality": "untrusted",
                            "applicability": "none",
                            "absolute_mapping_trusted": False,
                            "note": "no valid frame timing",
                        }
                    ),
                    **self._timebase.to_dict(),
                }
            ):

                self._timebase_written = True

        if self._started:

            self._writer.write(
                {
                    "type": "end",
                    "reason": reason,
                    "ended_monotonic_ns": (
                        self._monotonic_ns()
                    ),
                    "ended_wall_ns": self._wall_ns(),
                    "duration_ms": (
                        self._monotonic_ns()
                        - self._started_monotonic_ns
                    )
                    / 1_000_000.0,
                    "sample_count": self._sample_count,
                    "sampling_errors": (
                        self._sampling_errors[-20:]
                    ),
                    "write_error": self._writer.error,
                    "capture_outcome": (
                        self._capture_outcome
                    ),
                    "valid_frames": self._valid_frames,
                }
            )

        self._writer.close()
        self._stopped = True

    def close(self):

        self.stop("closed")
