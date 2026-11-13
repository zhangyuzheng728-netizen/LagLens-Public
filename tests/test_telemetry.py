"""C-1 telemetry schema, sampler and timebase tests."""

import tempfile
import time
import unittest

from pathlib import Path
from types import SimpleNamespace

import hardware_sampler
import telemetry


class InfoProcess:

    def __init__(self, pid, name, create_time):

        self._create_time = create_time
        self.info = {
            "pid": pid,
            "name": name,
            "create_time": create_time,
        }

    def create_time(self):

        return self._create_time


class LiveProcess:

    def __init__(self, create_time, cpu=10.0, rss=12345):

        self._create_time = create_time
        self._cpu = cpu
        self._rss = rss

    def create_time(self):

        return self._create_time

    def cpu_percent(self, interval=None):

        return self._cpu

    def memory_info(self):

        return SimpleNamespace(rss=self._rss)


class DeltaProcess:
    """A process-like object whose first cpu_percent call is a baseline."""

    def __init__(self, create_time, rss=4096):

        self._create_time = create_time
        self._rss = rss
        self.cpu_calls = 0

    def create_time(self):

        return self._create_time

    def cpu_percent(self, interval=None):

        self.cpu_calls += 1

        if self.cpu_calls == 1:

            return 0.0

        return 25.0

    def memory_info(self):

        return SimpleNamespace(rss=self._rss)


class FakeGpuProvider:

    def __init__(self, devices=None, read=None):

        self.devices = devices or []
        self._read = read or {}

    def describe(self):

        if not self.devices:

            return {
                "available": False,
                "status": "unavailable",
                "devices": [],
                "sampled_device": None,
                "multi_gpu": False,
                "association": "unknown",
            }

        return {
            "available": True,
            "status": "ok",
            "devices": self.devices,
            "sampled_device": self.devices[0],
            "multi_gpu": len(self.devices) > 1,
            "association": "unknown",
        }

    def read(self):

        return dict(self._read)


class StaticTracker:

    def __init__(self, sample=None):

        self._sample = sample or {
            "status": "ok",
            "pids": [],
            "cpu_percent": 5.0,
            "rss_bytes": 1000,
            "processes": [],
            "pid_reuse_detected": False,
        }

    def refresh(self, force=False):

        pass

    def sample(self):

        return dict(self._sample)


class WriteFailWriter(telemetry.TelemetryWriter):

    def write(self, record):

        if record.get("type") == "sample":

            self.error = "OSError"
            return False

        return super().write(record)


class OpenFailWriter(telemetry.TelemetryWriter):

    def open(self, metadata):

        self.error = "OSError"
        return False


class TelemetryIOTests(unittest.TestCase):

    def test_sidecar_path_is_next_to_csv(self):

        csv_path = Path(r"D:\captures\game.csv")

        self.assertEqual(
            telemetry.telemetry_path(csv_path),
            Path(r"D:\captures\game.csv.telemetry.jsonl"),
        )

    def test_reader_handles_missing_file(self):

        with tempfile.TemporaryDirectory() as folder:

            result = telemetry.read_telemetry(
                Path(folder) / "missing.csv"
            )

            self.assertFalse(result.available)
            self.assertFalse(result.complete)
            self.assertEqual(result.samples, [])

    def test_writer_and_reader_round_trip(self):

        with tempfile.TemporaryDirectory() as folder:

            csv_path = Path(folder) / "game.csv"
            writer = telemetry.TelemetryWriter(
                telemetry.telemetry_path(csv_path)
            )

            self.assertTrue(
                writer.open(
                    {
                        "schema_version": 1,
                        "capture": {"csv_name": "game.csv"},
                    }
                )
            )
            self.assertTrue(
                writer.write(
                    {
                        "type": "sample",
                        "t_ms": 0.0,
                        "cpu": {"status": "ok"},
                    }
                )
            )
            self.assertTrue(
                writer.write(
                    {
                        "type": "end",
                        "reason": "finished",
                    }
                )
            )
            writer.close()

            result = telemetry.read_telemetry(csv_path)

            self.assertTrue(result.available)
            self.assertTrue(result.complete)
            self.assertEqual(result.sample_count(), 1)
            self.assertEqual(
                result.metadata["capture"]["csv_name"],
                "game.csv",
            )
            self.assertEqual(
                result.end["reason"],
                "finished",
            )

    def test_metadata_does_not_contain_full_paths(self):

        with tempfile.TemporaryDirectory() as folder:

            csv_path = Path(folder) / "game.csv"
            writer = telemetry.TelemetryWriter(
                telemetry.telemetry_path(csv_path)
            )
            writer.open(
                {
                    "schema_version": 1,
                    "capture": {"csv_name": csv_path.name},
                }
            )
            writer.write(
                {"type": "end", "reason": "finished"}
            )
            writer.close()

            text = telemetry.telemetry_path(
                csv_path
            ).read_text(encoding="utf-8")

            self.assertNotIn(str(Path(folder)), text)
            self.assertIn('"csv_name":"game.csv"', text)

    def test_partial_sidecar_is_reported(self):

        with tempfile.TemporaryDirectory() as folder:

            csv_path = Path(folder) / "game.csv"
            path = telemetry.telemetry_path(csv_path)
            path.write_text(
                '{"type":"metadata","schema_version":1}\n'
                '{"type":"sample","t_ms":0}\n',
                encoding="utf-8",
            )

            result = telemetry.read_telemetry(csv_path)

            self.assertTrue(result.available)
            self.assertFalse(result.complete)
            self.assertIn("incomplete", result.error)

    def test_corrupt_sidecar_does_not_raise(self):

        with tempfile.TemporaryDirectory() as folder:

            csv_path = Path(folder) / "game.csv"
            telemetry.telemetry_path(csv_path).write_text(
                "{broken\n",
                encoding="utf-8",
            )

            result = telemetry.read_telemetry(csv_path)

            self.assertFalse(result.available)
            self.assertIn("corrupt", result.error)


class TimebaseTests(unittest.TestCase):

    def test_consistent_spans_are_relative_verified(self):

        calibration = telemetry.calibrate_timebase(
            capture_started_monotonic_ns=0,
            presentmon_started_monotonic_ns=5_000_000,
            first_row_monotonic_ns=1_000_000_000,
            last_row_monotonic_ns=3_000_000_000,
            first_cpu_start_ms=1000.0,
            last_cpu_start_ms=3000.0,
            sample_interval_ms=250,
        )

        self.assertEqual(calibration.row_span_ms, 2000.0)
        self.assertEqual(calibration.csv_span_ms, 2000.0)
        self.assertEqual(calibration.span_error_ms, 0.0)
        self.assertEqual(
            calibration.presentmon_start_offset_ms,
            5.0,
        )
        self.assertTrue(
            calibration.relative_scale_trusted
        )
        self.assertFalse(
            calibration.absolute_offset_trusted
        )
        self.assertEqual(
            calibration.status,
            "relative_verified",
        )
        self.assertIsNotNone(
            calibration.offset_estimate_ms
        )
        self.assertGreaterEqual(
            calibration.uncertainty_ms,
            500.0,
        )

    def test_inconsistent_spans_are_untrusted(self):

        calibration = telemetry.calibrate_timebase(
            capture_started_monotonic_ns=0,
            presentmon_started_monotonic_ns=0,
            first_row_monotonic_ns=1_000_000_000,
            last_row_monotonic_ns=3_000_000_000,
            first_cpu_start_ms=1000.0,
            last_cpu_start_ms=2500.0,
        )

        self.assertFalse(
            calibration.relative_scale_trusted
        )
        self.assertFalse(
            calibration.absolute_offset_trusted
        )
        self.assertEqual(
            calibration.status,
            "untrusted",
        )
        self.assertIn("differ", calibration.note)

    def test_missing_timing_is_untrusted(self):

        calibration = telemetry.calibrate_timebase(
            capture_started_monotonic_ns=0,
            presentmon_started_monotonic_ns=None,
            first_row_monotonic_ns=None,
            last_row_monotonic_ns=None,
            first_cpu_start_ms=None,
            last_cpu_start_ms=None,
        )

        self.assertFalse(
            calibration.relative_scale_trusted
        )
        self.assertFalse(
            calibration.absolute_offset_trusted
        )
        self.assertEqual(
            calibration.status,
            "untrusted",
        )

    def test_offset_estimate_includes_first_row_delay(self):

        calibration = telemetry.calibrate_timebase(
            capture_started_monotonic_ns=0,
            presentmon_started_monotonic_ns=0,
            first_row_monotonic_ns=6_000_000_000,
            last_row_monotonic_ns=8_000_000_000,
            first_cpu_start_ms=5924.0,
            last_cpu_start_ms=7924.0,
        )

        self.assertEqual(
            calibration.offset_estimate_ms,
            76.0,
        )
        self.assertTrue(
            calibration.relative_scale_trusted
        )
        self.assertFalse(
            calibration.absolute_offset_trusted
        )


class TargetTrackerTests(unittest.TestCase):

    def make_tracker(self, infos, processes):

        tracker = hardware_sampler.TargetProcessTracker(
            "Game.exe",
            process_iter_factory=lambda attrs: iter(infos),
            process_factory=lambda pid: processes[pid],
            refresh_interval_s=0.0,
        )
        tracker.refresh(force=True)
        return tracker

    def test_target_cpu_is_primed_and_rss_is_sampled(self):

        infos = [
            InfoProcess(10, "Game.exe", 100.0),
        ]
        processes = {
            10: LiveProcess(100.0, cpu=12.5, rss=4096),
        }
        tracker = self.make_tracker(infos, processes)

        first = tracker.sample()
        second = tracker.sample()

        self.assertEqual(first["status"], "ok")
        self.assertIsNone(first["cpu_percent"])
        self.assertEqual(first["rss_bytes"], 4096)
        self.assertEqual(second["cpu_percent"], 12.5)
        self.assertEqual(second["rss_bytes"], 4096)

    def test_cpu_percent_uses_the_same_process_object_across_samples(self):

        infos = [
            InfoProcess(10, "Game.exe", 100.0),
        ]
        process = DeltaProcess(100.0)
        created = []

        def factory(pid):

            created.append(pid)
            return process

        tracker = hardware_sampler.TargetProcessTracker(
            "Game.exe",
            process_iter_factory=lambda attrs: iter(infos),
            process_factory=factory,
            refresh_interval_s=0.0,
        )
        tracker.refresh(force=True)

        first = tracker.sample()
        second = tracker.sample()

        self.assertEqual(created, [10])
        self.assertIsNone(first["cpu_percent"])
        self.assertEqual(second["cpu_percent"], 25.0)
        self.assertEqual(process.cpu_calls, 2)

    def test_pid_reuse_is_detected_and_not_attributed(self):

        infos = [
            InfoProcess(10, "Game.exe", 100.0),
        ]
        processes = {
            10: LiveProcess(100.0, cpu=12.5, rss=4096),
        }
        tracker = self.make_tracker(infos, processes)
        tracker.sample()

        infos[0] = InfoProcess(10, "Game.exe", 200.0)
        processes[10] = LiveProcess(
            200.0,
            cpu=99.0,
            rss=8192,
        )

        tracker.refresh(force=True)
        sample = tracker.sample()

        self.assertTrue(tracker.pid_reuse_detected)
        self.assertEqual(sample["status"], "ok")
        self.assertEqual(
            sample["pids"][0]["create_time"],
            200.0,
        )
        self.assertEqual(sample["rss_bytes"], 8192)
        self.assertIsNone(sample["cpu_percent"])

    def test_target_exit_is_reported(self):

        infos = [
            InfoProcess(10, "Game.exe", 100.0),
        ]
        processes = {
            10: LiveProcess(100.0),
        }
        tracker = self.make_tracker(infos, processes)
        tracker.sample()

        infos.clear()
        processes.clear()
        tracker.refresh(force=True)
        sample = tracker.sample()

        self.assertTrue(tracker.target_exited)
        self.assertEqual(sample["status"], "target_exited")
        self.assertIsNone(sample["cpu_percent"])
        self.assertIsNone(sample["rss_bytes"])

    def test_no_target_name_is_unavailable(self):

        tracker = hardware_sampler.TargetProcessTracker(
            "",
            process_iter_factory=lambda attrs: iter([]),
            process_factory=lambda pid: None,
        )
        tracker.refresh(force=True)

        self.assertEqual(
            tracker.sample()["status"],
            "unavailable",
        )


class NvmlProviderTests(unittest.TestCase):

    class FakeNvml:

        NVML_TEMPERATURE_GPU = 0

        def __init__(self, fail=False):

            self.fail = fail

        def _check(self):

            if self.fail:

                raise OSError("nvml unavailable")

        def nvmlDeviceGetCount(self):

            self._check()
            return 2

        def nvmlDeviceGetHandleByIndex(self, index):

            self._check()
            return f"handle-{index}"

        def nvmlDeviceGetName(self, handle):

            self._check()
            return f"GPU {handle}".encode()

        def nvmlDeviceGetUUID(self, handle):

            self._check()
            return f"uuid-{handle}".encode()

        def nvmlDeviceGetBusId(self, handle):

            self._check()
            return f"bus-{handle}".encode()

        def nvmlDeviceGetUtilizationRates(self, handle):

            self._check()
            return SimpleNamespace(gpu=37)

        def nvmlDeviceGetMemoryInfo(self, handle):

            self._check()
            return SimpleNamespace(
                used=2048,
                total=8192,
            )

        def nvmlDeviceGetTemperature(self, handle, sensor):

            self._check()
            return 55

    def test_provider_records_all_devices_and_unknown_association(self):

        provider = hardware_sampler.NvmlGpuProvider(
            handle="handle-1",
            index=1,
            module=self.FakeNvml(),
        )

        description = provider.describe()

        self.assertTrue(description["available"])
        self.assertTrue(description["multi_gpu"])
        self.assertEqual(
            len(description["devices"]),
            2,
        )
        self.assertEqual(
            description["sampled_device"]["uuid"],
            "uuid-handle-1",
        )
        self.assertEqual(
            description["association"],
            "unknown",
        )

        sample = provider.read()

        self.assertEqual(sample["status"], "ok")
        self.assertEqual(sample["util_percent"], 37)
        self.assertEqual(sample["vram_used_bytes"], 2048)
        self.assertEqual(sample["temperature_c"], 55)

    def test_provider_failure_returns_null_values(self):

        provider = hardware_sampler.NvmlGpuProvider(
            handle="handle-0",
            index=0,
            module=self.FakeNvml(fail=True),
        )

        description = provider.describe()

        self.assertFalse(description["available"])
        self.assertEqual(
            description["status"],
            "unavailable",
        )
        self.assertEqual(description["devices"], [])

        sample = provider.read()

        self.assertEqual(sample["status"], "unavailable")
        self.assertIsNone(sample["util_percent"])
        self.assertIsNone(sample["vram_used_bytes"])
        self.assertIsNone(sample["temperature_c"])

    def test_no_handle_is_unavailable(self):

        provider = hardware_sampler.NvmlGpuProvider()

        self.assertFalse(provider.describe()["available"])
        self.assertEqual(
            provider.read()["status"],
            "unavailable",
        )


class HardwareSamplerTests(unittest.TestCase):

    def make_sampler(
        self,
        csv_path,
        gpu=None,
        writer_factory=None,
        interval_s=0.02,
        low_overhead=False,
        qpc_time=False,
    ):

        return hardware_sampler.HardwareSampler(
            csv_path=csv_path,
            target_name="Game.exe",
            interval_s=interval_s,
            low_overhead=low_overhead,
            qpc_time=qpc_time,
            gpu_provider=gpu or FakeGpuProvider(
                devices=[
                    {
                        "index": 0,
                        "name": "Fake GPU",
                        "uuid": "GPU-0",
                        "bus_id": "0000:01:00.0",
                        "association": "unknown",
                    }
                ],
                read={
                    "status": "ok",
                    "util_percent": 42,
                    "vram_used_bytes": 1024,
                    "vram_total_bytes": 8192,
                    "temperature_c": 60,
                    "association": "unknown",
                },
            ),
            tracker=StaticTracker(),
            cpu_percent=lambda interval=None: 12.5,
            per_cpu_percent=lambda: [10.0, 15.0],
            virtual_memory=lambda: SimpleNamespace(
                used=1024,
                total=8192,
                percent=12.5,
                available=7168,
            ),
            writer_factory=writer_factory,
        )

    def test_sampler_writes_timestamped_complete_sidecar(self):

        with tempfile.TemporaryDirectory() as folder:

            csv_path = Path(folder) / "game.csv"
            sampler = self.make_sampler(csv_path)

            self.assertTrue(sampler.start())
            time.sleep(0.12)
            sampler.stop("finished", "valid", 2)

            result = telemetry.read_telemetry(csv_path)

            self.assertTrue(result.available)
            self.assertTrue(result.complete)
            self.assertGreaterEqual(result.sample_count(), 2)
            self.assertEqual(
                result.metadata["capture"]["csv_name"],
                "game.csv",
            )
            self.assertEqual(
                result.metadata["capture"]["target_name"],
                "Game.exe",
            )
            self.assertFalse(sampler.running)

            sample = result.samples[0]

            self.assertIn("t_ms", sample)
            self.assertIn("sample_cost_ms", sample)
            self.assertEqual(
                sample["cpu"]["status"],
                "ok",
            )
            self.assertEqual(
                sample["gpu"]["util_percent"],
                42,
            )
            self.assertEqual(
                result.end["reason"],
                "finished",
            )
            self.assertEqual(
                result.end["capture_outcome"],
                "valid",
            )

    def test_multi_gpu_identity_and_unknown_association(self):

        with tempfile.TemporaryDirectory() as folder:

            gpu = FakeGpuProvider(
                devices=[
                    {
                        "index": 0,
                        "name": "GPU A",
                        "uuid": "A",
                        "bus_id": "0000:01:00.0",
                        "association": "unknown",
                    },
                    {
                        "index": 1,
                        "name": "GPU B",
                        "uuid": "B",
                        "bus_id": "0000:02:00.0",
                        "association": "unknown",
                    },
                ],
                read={
                    "status": "ok",
                    "util_percent": 1,
                    "vram_used_bytes": 1,
                    "vram_total_bytes": 2,
                    "temperature_c": 30,
                    "association": "unknown",
                },
            )
            sampler = self.make_sampler(
                Path(folder) / "game.csv",
                gpu=gpu,
            )

            sampler.start()
            time.sleep(0.06)
            sampler.stop("finished")

            result = telemetry.read_telemetry(
                Path(folder) / "game.csv"
            )

            self.assertTrue(
                result.metadata["gpu"]["multi_gpu"]
            )
            self.assertEqual(
                result.metadata["gpu"]["association"],
                "unknown",
            )
            self.assertEqual(
                result.metadata["gpu"]["sampled_device"][
                    "uuid"
                ],
                "A",
            )

    def test_missing_gpu_writes_null_not_stale_values(self):

        with tempfile.TemporaryDirectory() as folder:

            gpu = FakeGpuProvider(
                read={
                    "status": "unavailable",
                    "util_percent": None,
                    "vram_used_bytes": None,
                    "vram_total_bytes": None,
                    "temperature_c": None,
                    "association": "unknown",
                }
            )
            sampler = self.make_sampler(
                Path(folder) / "game.csv",
                gpu=gpu,
            )

            sampler.start()
            time.sleep(0.06)
            sampler.stop("finished")

            result = telemetry.read_telemetry(
                Path(folder) / "game.csv"
            )

            self.assertGreaterEqual(result.sample_count(), 1)
            for sample in result.samples:

                self.assertEqual(
                    sample["gpu"]["status"],
                    "unavailable",
                )
                self.assertIsNone(
                    sample["gpu"]["util_percent"]
                )
                self.assertIsNone(
                    sample["gpu"]["vram_used_bytes"]
                )

    def test_write_failure_does_not_escape(self):

        with tempfile.TemporaryDirectory() as folder:

            sampler = self.make_sampler(
                Path(folder) / "game.csv",
                writer_factory=WriteFailWriter,
            )

            self.assertTrue(sampler.start())
            time.sleep(0.06)

            sampler.stop("finished")

            self.assertFalse(sampler.running)
            self.assertTrue(sampler.write_error)

    def test_open_failure_makes_start_fail_without_thread(self):

        with tempfile.TemporaryDirectory() as folder:

            sampler = self.make_sampler(
                Path(folder) / "game.csv",
                writer_factory=OpenFailWriter,
            )

            self.assertFalse(sampler.start())
            self.assertFalse(sampler.started)
            self.assertFalse(sampler.running)

    def test_stop_is_idempotent_and_thread_is_gone(self):

        with tempfile.TemporaryDirectory() as folder:

            sampler = self.make_sampler(
                Path(folder) / "game.csv"
            )
            sampler.start()
            time.sleep(0.05)
            sampler.stop("finished")
            sampler.stop("finished")

            self.assertFalse(sampler.running)

    def test_low_overhead_metadata_is_recorded(self):

        with tempfile.TemporaryDirectory() as folder:

            sampler = self.make_sampler(
                Path(folder) / "game.csv",
                interval_s=1.0,
                low_overhead=True,
            )
            sampler.start()
            time.sleep(0.05)
            sampler.stop("finished")

            result = telemetry.read_telemetry(
                Path(folder) / "game.csv"
            )

            self.assertEqual(
                result.metadata["capture"]["profile"],
                "low_overhead",
            )
            self.assertEqual(
                result.metadata["capture"][
                    "presentmon_gpu_tracking"
                ],
                "disabled",
            )

    def test_sampler_records_presentmon_marker_and_timebase(self):

        with tempfile.TemporaryDirectory() as folder:

            csv_path = Path(folder) / "game.csv"
            sampler = self.make_sampler(csv_path)

            sampler.start()
            sampler.note_presentmon_started(50_000_000)
            sampler.note_capture_timing(
                first_row_monotonic_ns=1_000_000_000,
                last_row_monotonic_ns=2_000_000_000,
                first_cpu_start_ms=900.0,
                last_cpu_start_ms=1900.0,
                valid_frames=60,
                capture_outcome="valid",
            )
            sampler.stop("finished", "valid", 60)

            result = telemetry.read_telemetry(csv_path)

            self.assertIsNotNone(result.timebase)
            self.assertTrue(
                result.timebase["relative_scale_trusted"]
            )
            self.assertFalse(
                result.timebase["absolute_offset_trusted"]
            )
            self.assertEqual(
                result.timebase["valid_frames"],
                60,
            )

    def test_qpc_request_is_recorded_in_metadata(self):

        with tempfile.TemporaryDirectory() as folder:

            csv_path = Path(folder) / "game.csv"
            sampler = self.make_sampler(
                csv_path,
                qpc_time=True,
            )

            sampler.start()
            time.sleep(0.05)
            sampler.stop("finished")

            result = telemetry.read_telemetry(csv_path)

            self.assertTrue(
                result.metadata["capture"][
                    "qpc_time_requested"
                ]
            )
            self.assertEqual(
                result.metadata["capture"]["timebase_kind"],
                "qpc_ms",
            )
            self.assertEqual(
                result.metadata["capture"][
                    "expected_time_column"
                ],
                "CPUStartQPCTime",
            )

    def test_frame_timebase_is_written_to_the_sidecar(self):

        with tempfile.TemporaryDirectory() as folder:

            csv_path = Path(folder) / "game.csv"
            sampler = self.make_sampler(
                csv_path,
                qpc_time=True,
            )
            frame_timebase = {
                "kind": "qpc_ms",
                "raw_column": "CPUStartQPCTime",
                "origin_kind": "capture_start",
                "origin_qpc_ms": 10000.0,
                "sync_quality": "verified_qpc",
                "absolute_mapping_trusted": True,
                "applicability": "absolute_frame_time",
            }

            sampler.start()
            sampler.note_capture_timing(
                first_row_monotonic_ns=2_000_000_000,
                last_row_monotonic_ns=2_500_000_000,
                first_cpu_start_ms=16.7,
                last_cpu_start_ms=1016.7,
                valid_frames=60,
                capture_outcome="valid",
                frame_timebase=frame_timebase,
            )
            sampler.stop("finished", "valid", 60)

            result = telemetry.read_telemetry(csv_path)

            self.assertEqual(
                result.timebase["frame_timebase"],
                frame_timebase,
            )
            self.assertEqual(
                result.timebase["status"],
                "qpc_verified",
            )
            self.assertFalse(
                result.timebase["relative_scale_trusted"]
            )

    def test_metadata_does_not_include_csv_full_path(self):

        with tempfile.TemporaryDirectory() as folder:

            csv_path = Path(folder) / "game.csv"
            sampler = self.make_sampler(csv_path)
            sampler.start()
            time.sleep(0.05)
            sampler.stop("finished")

            text = telemetry.telemetry_path(
                csv_path
            ).read_text(encoding="utf-8")

            self.assertNotIn(str(Path(folder)), text)
            self.assertIn('"csv_name":"game.csv"', text)


if __name__ == "__main__":

    unittest.main()
