"""Frame-time statistics for LagLens.

Definitions
===========

Average FPS
    ``1000 / mean(frame_time_ms)``.  This is the reciprocal of the mean
    frame interval, not ``frame_count / wall_clock_span``.  The two
    differ when the capture contains gaps (for example when the target
    stopped presenting, or ETW dropped events): a capture with one 90 ms
    hole still has a meaningful mean frame time, while frame_count/span
    would report a misleadingly low FPS.  LagLens reports the
    mean-frame-time value and labels it as such.

P50 / P95 / P99 frame time
    Percentiles of the frame-time distribution using linear
    interpolation between closest ranks (the same method as numpy's
    default ``percentile`` and Excel's ``PERCENTILE.INC``).  P95 means
    95% of frames were at least this fast; it is a tail-latency measure,
    not an FPS.

1% Low FPS
    Sort the frame times from slowest to fastest, take the slowest
    ``ceil(N * 1%)`` frames (at least one), average them, and convert
    that average back to FPS::

        1% Low FPS = 1000 / mean(slowest ceil(N * 0.01) frame times)

    This is the common benchmarking definition (the average of the
    slowest 1% of frames), **not** the 1st percentile of instantaneous
    FPS.  For captures shorter than 100 frames the single slowest frame
    is used, which makes the value conservative and easy to explain.

Stutter threshold
    A frame is a stutter candidate when its frame time is strictly
    greater than the threshold.  By default the threshold is::

        max(floor_ms, median_frame_time * multiplier)

    with ``floor_ms = 50`` and ``multiplier = 2``.  A caller may pass an
    absolute ``threshold_ms`` instead; the report always includes the
    value that was used so the result is reproducible.

Long frames
    Frames of at least 1000 ms are counted separately.  They are valid
    data (a real hitch or a hole left by lost events), so they are
    reported, never discarded.
"""

from __future__ import annotations

import math
import statistics

from dataclasses import dataclass
from typing import Sequence


DEFAULT_STUTTER_FLOOR_MS = 50.0
DEFAULT_STUTTER_MULTIPLIER = 2.0
DEFAULT_WORST_LIMIT = 5

LONG_FRAME_MS = 1000.0


@dataclass(frozen=True)
class Stutter:
    """One frame above the stutter threshold."""

    index: int
    start_ms: float
    duration_ms: float


@dataclass(frozen=True)
class FrameStats:
    frame_count: int
    skipped_frames: int
    duration_s: float

    average_fps: float
    mean_frame_ms: float
    median_frame_ms: float
    p95_frame_ms: float
    p99_frame_ms: float
    min_frame_ms: float
    max_frame_ms: float
    one_percent_low_fps: float

    stutter_threshold_ms: float
    stutter_count: int
    stutter_percent: float
    stutter_total_ms: float

    long_frame_count: int
    worst_frames: tuple[Stutter, ...]


def percentile(values, percent):
    """Percentile with linear interpolation between closest ranks.

    ``percent`` is in [0, 100].  Uses the R-7 definition (numpy's
    default, Excel PERCENTILE.INC).
    """

    if not 0 <= percent <= 100:

        raise ValueError(
            "percent must be between 0 and 100"
        )

    ordered = sorted(
        float(value)
        for value in values
    )

    if not ordered:

        raise ValueError(
            "percentile requires at least one value"
        )

    if len(ordered) == 1:

        return ordered[0]

    rank = (
        (len(ordered) - 1)
        * percent
        / 100.0
    )

    lower = math.floor(rank)
    upper = math.ceil(rank)

    if lower == upper:

        return ordered[int(rank)]

    fraction = rank - lower

    return (
        ordered[lower]
        + (ordered[upper] - ordered[lower])
        * fraction
    )


def stutter_threshold(
    durations,
    threshold_ms=None,
    multiplier=DEFAULT_STUTTER_MULTIPLIER,
    floor_ms=DEFAULT_STUTTER_FLOOR_MS,
):
    """Resolve the stutter threshold in milliseconds."""

    if threshold_ms is not None:

        threshold_ms = float(threshold_ms)

        if not math.isfinite(threshold_ms):

            raise ValueError(
                "threshold_ms must be finite"
            )

        if threshold_ms <= 0:

            raise ValueError(
                "threshold_ms must be positive"
            )

        return threshold_ms

    if multiplier <= 0:

        raise ValueError(
            "multiplier must be positive"
        )

    if floor_ms < 0:

        raise ValueError(
            "floor_ms must not be negative"
        )

    median = percentile(durations, 50)

    return max(floor_ms, median * multiplier)


def compute_stats(
    frames: Sequence,
    threshold_ms=None,
    multiplier=DEFAULT_STUTTER_MULTIPLIER,
    floor_ms=DEFAULT_STUTTER_FLOOR_MS,
    worst_limit=DEFAULT_WORST_LIMIT,
):
    """Compute all reported statistics for a list of frame dicts.

    ``frames`` is the list returned by ``frame_viewer.load_frames``:
    each item needs ``time`` (normalized capture-relative ms),
    ``duration`` (FrameTime, ms) and is assumed to be sorted by
    ``time``.  The original CSV timestamp and its timebase are preserved
    in the same dict as ``raw_time`` / ``timebase_kind`` but are not
    needed for these statistics.

    Frames with non-finite or non-positive durations are skipped and
    counted in ``skipped_frames``.  Raises ``ValueError`` when no valid
    frame remains.
    """

    pairs = []
    skipped = 0

    for frame in frames:

        try:

            start = float(frame["time"])
            duration = float(frame["duration"])

        except (KeyError, TypeError, ValueError):

            skipped += 1
            continue

        if (
            not math.isfinite(start)
            or not math.isfinite(duration)
            or duration <= 0
        ):

            skipped += 1
            continue

        pairs.append((start, duration))

    if not pairs:

        raise ValueError(
            "no valid frames to analyse"
        )

    pairs.sort(key=lambda item: item[0])

    starts = [item[0] for item in pairs]
    durations = [item[1] for item in pairs]

    if len(pairs) == 1:

        duration_s = durations[0] / 1000.0

    else:

        duration_s = (
            starts[-1]
            - starts[0]
            + durations[-1]
        ) / 1000.0

    mean_ms = statistics.fmean(durations)
    average_fps = 1000.0 / mean_ms

    # 1% Low: average of the slowest ceil(N * 1%) frames.
    slow_count = max(
        1,
        math.ceil(len(durations) * 0.01),
    )

    slowest = sorted(
        durations,
        reverse=True,
    )[:slow_count]

    one_percent_low_fps = (
        1000.0 / statistics.fmean(slowest)
    )

    threshold = stutter_threshold(
        durations,
        threshold_ms=threshold_ms,
        multiplier=multiplier,
        floor_ms=floor_ms,
    )

    stutters = [
        Stutter(
            index=index,
            start_ms=start,
            duration_ms=duration,
        )
        for index, (start, duration)
        in enumerate(pairs)
        if duration > threshold
    ]

    stutter_total_ms = sum(
        item.duration_ms
        for item in stutters
    )

    stutter_percent = (
        100.0 * len(stutters) / len(durations)
    )

    worst = sorted(
        (
            Stutter(
                index=index,
                start_ms=start,
                duration_ms=duration,
            )
            for index, (start, duration)
            in enumerate(pairs)
        ),
        key=lambda item: item.duration_ms,
        reverse=True,
    )[: max(0, int(worst_limit))]

    return FrameStats(
        frame_count=len(durations),
        skipped_frames=skipped,
        duration_s=duration_s,
        average_fps=average_fps,
        mean_frame_ms=mean_ms,
        median_frame_ms=percentile(durations, 50),
        p95_frame_ms=percentile(durations, 95),
        p99_frame_ms=percentile(durations, 99),
        min_frame_ms=min(durations),
        max_frame_ms=max(durations),
        one_percent_low_fps=one_percent_low_fps,
        stutter_threshold_ms=threshold,
        stutter_count=len(stutters),
        stutter_percent=stutter_percent,
        stutter_total_ms=stutter_total_ms,
        long_frame_count=sum(
            1
            for duration in durations
            if duration >= LONG_FRAME_MS
        ),
        worst_frames=tuple(worst),
    )
