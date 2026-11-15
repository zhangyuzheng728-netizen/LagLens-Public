"""Local stutter detection must keep its exact results after optimization."""

import statistics
import sys
import unittest

from bisect import bisect_left
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import diagnostics  # noqa: E402


def metrics_from(durations, interval=16.0):

    result = []
    time_ms = 0.0

    for duration in durations:

        result.append(
            SimpleNamespace(
                time_ms=time_ms,
                duration_ms=float(duration),
            )
        )
        time_ms += interval

    return result


def reference_detect(metrics, config):

    if len(metrics) < config.min_frames:
        return []

    times = [item.time_ms for item in metrics]
    events = []

    for index, item in enumerate(metrics):

        left = bisect_left(
            times,
            item.time_ms - config.local_baseline_ms,
        )
        right = bisect_left(
            times,
            item.time_ms - config.local_baseline_gap_ms,
        )
        baseline = metrics[left:right]

        if len(baseline) < config.min_baseline_frames:
            continue

        durations = [base.duration_ms for base in baseline]
        median = statistics.median(durations)
        deviations = sorted(
            abs(value - median) for value in durations
        )
        mad = statistics.median(deviations)
        threshold = max(
            median * config.local_stutter_ratio,
            median
            + config.local_stutter_mad_k * 1.4826 * mad,
            config.local_stutter_floor_ms,
        )

        if item.duration_ms > threshold:

            events.append(
                diagnostics._StutterEvent(
                    index=index,
                    time_ms=item.time_ms,
                    duration_ms=item.duration_ms,
                    baseline_median_ms=median,
                    threshold_ms=threshold,
                )
            )

    if not events:
        return []

    merged = []
    gap = max(
        config.event_merge_ms,
        config.event_window_before_ms
        + config.event_window_after_ms,
    )

    for event in events:

        if merged and event.time_ms - merged[-1].time_ms <= gap:

            if event.duration_ms > merged[-1].duration_ms:
                merged[-1] = event

            continue

        merged.append(event)

    if len(merged) > config.max_events:

        merged = sorted(
            merged,
            key=lambda event: event.duration_ms,
            reverse=True,
        )[: config.max_events]
        merged.sort(key=lambda event: event.time_ms)

    return merged


def event_key(event):

    return (
        event.index,
        round(event.time_ms, 6),
        round(event.duration_ms, 6),
        round(event.baseline_median_ms, 6),
        round(event.threshold_ms, 6),
    )


class LocalStutterOptimizationTests(unittest.TestCase):

    def config(self):

        return diagnostics.DiagnosticConfig(
            min_frames=1,
            local_baseline_ms=80.0,
            local_baseline_gap_ms=16.0,
            min_baseline_frames=3,
            local_stutter_ratio=2.0,
            local_stutter_floor_ms=5.0,
            local_stutter_mad_k=3.0,
            event_merge_ms=0.0,
            event_window_before_ms=0.0,
            event_window_after_ms=0.0,
            max_events=100,
        )

    def test_new_window_matches_reference(self):

        durations = [16.0] * 60
        durations[10] = 40.0
        durations[11] = 38.0
        durations[30] = 90.0
        durations[31] = 20.0
        durations[45] = 60.0
        metrics = metrics_from(durations)
        config = self.config()

        expected = reference_detect(metrics, config)
        actual = diagnostics._detect_local_stutters(
            metrics,
            config,
        )

        self.assertEqual(
            [event_key(event) for event in actual],
            [event_key(event) for event in expected],
        )

    def test_spikes_are_not_hidden_by_window_updates(self):

        durations = [16.0] * 40
        durations[20] = 200.0
        metrics = metrics_from(durations)
        config = self.config()

        events = diagnostics._detect_local_stutters(
            metrics,
            config,
        )

        self.assertTrue(
            any(event.index == 20 for event in events)
        )


if __name__ == "__main__":
    unittest.main()
