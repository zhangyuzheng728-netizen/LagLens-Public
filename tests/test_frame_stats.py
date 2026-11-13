"""P2-2: statistics engine tests.

Definitions under test (also documented in frame_stats.py):

* Average FPS = 1000 / mean(frame_time_ms).  It is deliberately based on
  frame times, not frame_count / wall_time, so gaps in the capture do
  not inflate it.
* P50/P95/P99 use linear interpolation between closest ranks (the same
  method as numpy's default and Excel's PERCENTILE.INC).
* 1% Low FPS = 1000 / mean(slowest ceil(N * 1%) frame times).  It is the
  average of the slowest frames, not the 1st percentile of FPS.
"""

import math
import unittest

import frame_stats


def make_frames(durations, starts=None):

    if starts is None:

        starts = []
        t = 0.0

        for duration in durations:

            starts.append(t)
            t += duration

    return [
        {
            "time": start,
            "duration": duration,
            "displayed": True,
            "row": {},
        }
        for start, duration in zip(starts, durations)
    ]


class PercentileTests(unittest.TestCase):

    def test_linear_interpolation(self):

        values = [1, 2, 3, 4]

        self.assertEqual(frame_stats.percentile(values, 0), 1.0)
        self.assertEqual(frame_stats.percentile(values, 50), 2.5)
        self.assertAlmostEqual(
            frame_stats.percentile(values, 95), 3.85
        )
        self.assertAlmostEqual(
            frame_stats.percentile(values, 99), 3.97
        )
        self.assertEqual(frame_stats.percentile(values, 100), 4.0)

    def test_single_value(self):

        self.assertEqual(
            frame_stats.percentile([7.5], 99),
            7.5,
        )

    def test_empty_raises(self):

        with self.assertRaises(ValueError):
            frame_stats.percentile([], 95)

    def test_out_of_range_raises(self):

        with self.assertRaises(ValueError):
            frame_stats.percentile([1, 2], 101)

        with self.assertRaises(ValueError):
            frame_stats.percentile([1, 2], -1)


class ComputeStatsTests(unittest.TestCase):

    def test_constant_frame_times(self):

        stats = frame_stats.compute_stats(
            make_frames([10.0] * 4)
        )

        self.assertEqual(stats.frame_count, 4)
        self.assertAlmostEqual(stats.duration_s, 0.04)
        self.assertAlmostEqual(stats.mean_frame_ms, 10.0)
        self.assertAlmostEqual(stats.median_frame_ms, 10.0)
        self.assertAlmostEqual(stats.p95_frame_ms, 10.0)
        self.assertAlmostEqual(stats.p99_frame_ms, 10.0)
        self.assertAlmostEqual(stats.average_fps, 100.0)
        self.assertAlmostEqual(
            stats.one_percent_low_fps, 100.0
        )
        self.assertEqual(stats.stutter_count, 0)

    def test_average_fps_uses_mean_frame_time(self):

        # A 90 ms hole between frames: frame_count / span would give
        # 16.7 FPS, but the mean-frame-time definition gives 66.7 FPS.
        stats = frame_stats.compute_stats(
            make_frames(
                [10.0, 20.0],
                starts=[0.0, 100.0],
            )
        )

        self.assertAlmostEqual(stats.mean_frame_ms, 15.0)
        self.assertAlmostEqual(stats.average_fps, 1000 / 15)
        self.assertAlmostEqual(stats.duration_s, 0.12)

    def test_one_percent_low_slowest_average(self):

        # 100 frames -> 1 slow frame is the slowest 1%.
        stats = frame_stats.compute_stats(
            make_frames([10.0] * 99 + [100.0])
        )

        self.assertEqual(stats.one_percent_low_fps, 10.0)

    def test_one_percent_low_uses_ceil(self):

        # 101 frames -> ceil(1.01) = 2 slow frames are averaged.
        stats = frame_stats.compute_stats(
            make_frames([10.0] * 100 + [100.0])
        )

        self.assertAlmostEqual(
            stats.one_percent_low_fps,
            1000 / 55.0,
        )

    def test_single_frame(self):

        stats = frame_stats.compute_stats(
            make_frames([16.0])
        )

        self.assertEqual(stats.frame_count, 1)
        self.assertAlmostEqual(stats.duration_s, 0.016)
        self.assertAlmostEqual(stats.average_fps, 62.5)
        self.assertAlmostEqual(
            stats.one_percent_low_fps, 62.5
        )
        self.assertAlmostEqual(stats.p99_frame_ms, 16.0)

    def test_invalid_durations_are_skipped(self):

        stats = frame_stats.compute_stats(
            make_frames(
                [10.0, math.nan, -5.0, math.inf, 20.0],
                starts=[0.0, 10.0, 20.0, 30.0, 40.0],
            )
        )

        self.assertEqual(stats.frame_count, 2)
        self.assertEqual(stats.skipped_frames, 3)

    def test_empty_input_raises(self):

        with self.assertRaises(ValueError):
            frame_stats.compute_stats([])

    def test_only_invalid_input_raises(self):

        with self.assertRaises(ValueError):
            frame_stats.compute_stats(
                make_frames([0.0, -1.0])
            )

    def test_long_frames_are_counted(self):

        stats = frame_stats.compute_stats(
            make_frames([10.0, 1200.0, 16.0])
        )

        self.assertEqual(stats.long_frame_count, 1)
        self.assertAlmostEqual(stats.max_frame_ms, 1200.0)


class StutterTests(unittest.TestCase):

    def test_auto_threshold_uses_max_of_floor_and_median(self):

        stats = frame_stats.compute_stats(
            make_frames([10.0] * 99 + [60.0])
        )

        # median 10 -> max(50, 2 * 10) = 50
        self.assertAlmostEqual(
            stats.stutter_threshold_ms, 50.0
        )
        self.assertEqual(stats.stutter_count, 1)

    def test_threshold_multiplier(self):

        stats = frame_stats.compute_stats(
            make_frames([40.0] * 10),
        )

        # median 40 -> max(50, 80) = 80
        self.assertAlmostEqual(
            stats.stutter_threshold_ms, 80.0
        )

    def test_threshold_is_strictly_greater(self):

        # median 10 -> threshold 50; 50 ms itself is not a stutter.
        stats = frame_stats.compute_stats(
            make_frames([10.0] * 9 + [50.0, 50.1])
        )

        self.assertAlmostEqual(
            stats.stutter_threshold_ms, 50.0
        )
        self.assertEqual(stats.stutter_count, 1)

    def test_custom_absolute_threshold(self):

        stats = frame_stats.compute_stats(
            make_frames([10.0, 20.0, 40.0]),
            threshold_ms=30.0,
        )

        self.assertAlmostEqual(
            stats.stutter_threshold_ms, 30.0
        )
        self.assertEqual(stats.stutter_count, 1)
        self.assertAlmostEqual(stats.stutter_total_ms, 40.0)

    def test_stutter_percent(self):

        stats = frame_stats.compute_stats(
            make_frames([10.0] * 8 + [100.0, 200.0]),
            threshold_ms=50.0,
        )

        self.assertEqual(stats.stutter_count, 2)
        self.assertAlmostEqual(stats.stutter_percent, 20.0)

    def test_worst_frames_sorted_and_capped(self):

        stats = frame_stats.compute_stats(
            make_frames(
                [10, 50, 30, 70, 20, 60, 40],
            ),
            threshold_ms=25.0,
            worst_limit=3,
        )

        durations = [
            item.duration_ms
            for item in stats.worst_frames
        ]

        self.assertEqual(durations, [70.0, 60.0, 50.0])
        self.assertTrue(
            all(
                item.duration_ms > 25.0
                for item in stats.worst_frames
            )
        )


if __name__ == "__main__":
    unittest.main()
