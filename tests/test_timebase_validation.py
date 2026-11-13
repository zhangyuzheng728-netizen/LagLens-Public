"""C-1.1 timebase validation tests.

These tests do not run PresentMon.  They lock in the two facts the
real C-1.1 validation depends on:

* Python's perf_counter and Windows QPC are the same clock epoch;
* stdout buffering can make CSV row arrival span much shorter than the
  CSV's own time span, so that condition must remain explicitly
  untrusted rather than being "corrected" by a guess.
"""

import ctypes
import sys
import time
import unittest

import telemetry


class QpcClockTests(unittest.TestCase):

    @unittest.skipUnless(
        sys.platform == "win32",
        "Windows QPC is required",
    )
    def test_perf_counter_and_qpc_share_the_same_epoch(self):

        frequency = ctypes.c_longlong()
        self.assertNotEqual(
            ctypes.windll.kernel32.QueryPerformanceFrequency(
                ctypes.byref(frequency)
            ),
            0,
        )
        self.assertGreater(frequency.value, 0)

        for _ in range(5):

            perf_ns = time.perf_counter_ns()
            counter = ctypes.c_longlong()
            self.assertNotEqual(
                ctypes.windll.kernel32.QueryPerformanceCounter(
                    ctypes.byref(counter)
                ),
                0,
            )
            qpc_ns = int(
                counter.value * 1_000_000_000 / frequency.value
            )

            # The two reads are sequential and may be separated by
            # scheduling; 5 ms is a generous bound for the epoch check.
            self.assertLess(
                abs(perf_ns - qpc_ns),
                5_000_000,
            )
            time.sleep(0.01)

    @unittest.skipUnless(
        sys.platform == "win32",
        "Windows QPC is required",
    )
    def test_qpc_tick_and_millisecond_output_match_same_formula(self):

        frequency = 10_000_000
        ticks = 124_475_517_029

        milliseconds = ticks * 1000.0 / frequency

        self.assertAlmostEqual(
            milliseconds,
            12_447_551.7029,
            places=4,
        )
        self.assertEqual(
            int(round(milliseconds * 1_000_000.0)),
            ticks * 100,
        )


class StdoutBufferingTests(unittest.TestCase):

    def test_row_arrival_span_shorter_than_csv_span_is_untrusted(self):

        # Real C-1.1 capture shape: the CSV spans ~7.96 s but the
        # stdout reader observes only ~5.88 s of arrivals because
        # PresentMon's first output block is buffered.
        calibration = telemetry.calibrate_timebase(
            capture_started_monotonic_ns=0,
            presentmon_started_monotonic_ns=20_000_000,
            first_row_monotonic_ns=2_241_000_000,
            last_row_monotonic_ns=8_120_000_000,
            first_cpu_start_ms=1.4587,
            last_cpu_start_ms=7959.2818,
            sample_interval_ms=250,
        )

        self.assertAlmostEqual(
            calibration.row_span_ms,
            5879.0,
            places=6,
        )
        self.assertAlmostEqual(
            calibration.csv_span_ms,
            7957.8231,
            places=4,
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


if __name__ == "__main__":

    unittest.main()
