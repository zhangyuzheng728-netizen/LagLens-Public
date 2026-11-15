"""Network sampler, capture recorder and service lifecycle tests."""

import json
import sys
import tempfile
import time
import unittest

from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import network_sampler  # noqa: E402


class FakeProbe:

    def __init__(self, gateway, public):

        self.gateway = gateway
        self.public = public
        self.calls = []

    def probe(self, host, timeout_ms=1000):

        self.calls.append((host, timeout_ms))
        return (
            self.gateway
            if host == "192.168.1.1"
            else self.public
        )


class FakeSampler:

    def __init__(self):

        self.gateway = "192.168.1.1"
        self.public_target = "1.1.1.1"
        self.interval_s = 0.2
        self.samples = []
        self.running = False
        self.started = 0
        self.stopped = 0

    def start(self):

        self.running = True
        self.started += 1
        return True

    def stop(self, timeout=4.0):

        self.running = False
        self.stopped += 1

    def snapshot(self):

        return list(self.samples)

    def reset_samples(self):

        self.samples.clear()


def ok_sample(monotonic_ns, gateway=5.0, public=20.0):

    return network_sampler.NetworkSample(
        monotonic_ns,
        network_sampler.ProbeResult(
            "ok",
            gateway,
        ),
        network_sampler.ProbeResult(
            "ok",
            public,
        ),
    )


class SamplerTests(unittest.TestCase):

    def test_timeout_is_not_zero_latency(self):

        probe = FakeProbe(
            network_sampler.ProbeResult("timeout"),
            network_sampler.ProbeResult("timeout"),
        )
        sampler = network_sampler.NetworkSampler(
            gateway="192.168.1.1",
            public_target="1.1.1.1",
            interval_s=0.2,
            probe=probe,
        )
        sampler.start()
        time.sleep(0.3)
        sampler.stop()
        samples = sampler.snapshot()
        summary = network_sampler.summarize_samples(samples)

        self.assertTrue(samples)
        self.assertIsNone(
            summary["gateway"]["latency_median_ms"]
        )
        self.assertGreater(
            summary["gateway"]["timeouts"],
            0,
        )
        self.assertIsNone(samples[0].gateway.rtt_ms)

    def test_gateway_missing_does_not_block_public_probe(self):

        probe = FakeProbe(
            network_sampler.ProbeResult(
                "unavailable",
                error="no gateway",
            ),
            network_sampler.ProbeResult("ok", 30.0),
        )
        sampler = network_sampler.NetworkSampler(
            gateway=None,
            gateway_resolver=lambda: None,
            public_target="1.1.1.1",
            interval_s=0.2,
            probe=probe,
        )
        sampler.start()
        time.sleep(0.3)
        sampler.stop()
        summary = network_sampler.summarize_samples(
            sampler.snapshot()
        )

        self.assertGreater(
            summary["public"]["responses"],
            0,
        )
        self.assertEqual(
            summary["gateway"]["responses"],
            0,
        )

    def test_gateway_discovery_parses_route_print(self):

        class Result:

            stdout = (
                "          0.0.0.0          0.0.0.0"
                "      192.168.50.1      192.168.50.10     25\n"
            )

        with mock.patch(
            "network_sampler.subprocess.run",
            return_value=Result(),
        ):

            self.assertEqual(
                network_sampler.discover_default_gateway(),
                "192.168.50.1",
            )


class RecorderTests(unittest.TestCase):

    def test_recorder_excludes_samples_before_capture_origin(self):

        sampler = FakeSampler()
        origin = 1_000_000_000
        sampler.samples.extend(
            [
                ok_sample(500_000_000, gateway=999),
                ok_sample(1_500_000_000, gateway=5),
            ]
        )

        with tempfile.TemporaryDirectory() as tmp:

            csv_path = Path(tmp) / "capture.csv"
            csv_path.write_text("", encoding="utf-8")
            recorder = network_sampler.NetworkRecorder()

            self.assertTrue(
                recorder.start(
                    csv_path,
                    sampler,
                    target_name="game.exe",
                    origin_ns=origin,
                    session_id="session-1",
                )
            )
            sampler.samples.append(
                ok_sample(2_000_000_000, gateway=7)
            )
            recorder.stop("finished", "valid")
            result = network_sampler.read_network(csv_path)

            self.assertTrue(result.available)
            self.assertTrue(result.complete)
            self.assertEqual(
                result.metadata["session_id"],
                "session-1",
            )
            self.assertEqual(result.sample_count(), 2)
            self.assertEqual(
                result.samples[0]["t_ms"],
                500.0,
            )
            self.assertEqual(
                result.samples[0]["gateway"]["rtt_ms"],
                5.0,
            )
            self.assertNotIn(
                "999",
                json.dumps(result.samples),
            )


class ServiceTests(unittest.TestCase):

    def test_standalone_then_capture_reuses_sampler(self):

        sampler = FakeSampler()
        service = network_sampler.NetworkService(
            sampler=sampler
        )

        self.assertTrue(
            service.start_standalone("1.1.1.1")
        )
        self.assertEqual(sampler.started, 1)

        with tempfile.TemporaryDirectory() as tmp:

            csv_path = Path(tmp) / "capture.csv"

            self.assertTrue(
                service.begin_capture(
                    csv_path,
                    "game.exe",
                    1_000_000_000,
                    "1.1.1.1",
                )
            )
            self.assertTrue(
                service.state()["capture_active"]
            )
            self.assertTrue(
                service.state()["standalone"]
            )
            service.end_capture("finished", "valid")
            self.assertTrue(
                service.state()["standalone"]
            )
            self.assertTrue(
                service.state()["running"]
            )
            service.stop_standalone()
            self.assertFalse(service.state()["running"])

    def test_shutdown_stops_standalone_sampler(self):

        sampler = FakeSampler()
        service = network_sampler.NetworkService(
            sampler=sampler
        )
        service.start_standalone("1.1.1.1")
        service.shutdown()

        self.assertFalse(service.state()["running"])
        self.assertGreaterEqual(sampler.stopped, 1)

    def test_capture_started_network_stops_with_capture(self):

        sampler = FakeSampler()
        service = network_sampler.NetworkService(
            sampler=sampler
        )

        with tempfile.TemporaryDirectory() as tmp:

            csv_path = Path(tmp) / "capture.csv"

            self.assertTrue(
                service.begin_capture(
                    csv_path,
                    "game.exe",
                    1_000_000_000,
                    "1.1.1.1",
                )
            )
            self.assertTrue(
                service.state()["started_for_capture"]
            )
            service.end_capture("finished", "valid")
            self.assertFalse(
                service.state()["running"]
            )


if __name__ == "__main__":

    unittest.main()
