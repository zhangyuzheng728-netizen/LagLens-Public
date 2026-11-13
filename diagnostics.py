"""C-2.1 evidence-based diagnostic engine.

Pure Python: no Qt, no capture I/O, no machine learning.  The engine
consumes frames from ``frame_viewer.load_frames``, optional
``frame_stats.FrameStats``, an optional C-1 telemetry result, and the
target FPS.  It returns structured :class:`Finding` objects with
evidence, caveats, confidence and claim level.

The first rule set is deliberately conservative.  Missing GPU fields,
an untrusted timebase, or 4 Hz telemetry must not be turned into a
precise frame/hardware causal claim.
"""

from __future__ import annotations

import math
import statistics

from bisect import bisect_left
from dataclasses import dataclass, field, replace

from frame_stats import compute_stats, percentile


CLAIM_OBSERVED = "observed_association"
CLAIM_LIKELY = "likely"
CLAIM_CONFIRMED = "confirmed_by_control"
CLAIM_INSUFFICIENT = "insufficient_evidence"

SEVERITY_INFO = "info"
SEVERITY_WARNING = "warning"
SEVERITY_CRITICAL = "critical"

CONFIDENCE_LOW = "low"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_HIGH = "high"

CATEGORY_CPU = "cpu"
CATEGORY_GPU = "gpu"
CATEGORY_MEMORY = "memory"
CATEGORY_PRESENTATION = "presentation"
CATEGORY_MIXED = "mixed"
CATEGORY_DATA_QUALITY = "data_quality"
CATEGORY_UNKNOWN = "unknown"

CAUSE_CATEGORIES = frozenset(
    {
        CATEGORY_CPU,
        CATEGORY_GPU,
        CATEGORY_MEMORY,
        CATEGORY_PRESENTATION,
        CATEGORY_MIXED,
    }
)

CONTROL_METRICS = {
    # metric: higher_is_better
    "average_fps": True,
    "one_percent_low_fps": True,
    "p95_frame_ms": False,
    "p99_frame_ms": False,
    "stutter_percent": False,
    "stutter_total_ms": False,
}

COMMON_CAVEATS = (
    "Findings are observational associations, not proof of causality.",
    "PresentMon v2 FrameTime is CPUBusy + CPUWait, so "
    "CPUBusy/FrameTime alone is not a CPU-bound discriminator.",
    "GPUBusy is target-process GPU-engine activity, not device-wide "
    "GPU utilization.",
    "4 Hz telemetry is window context, not a per-frame measurement.",
)


@dataclass(frozen=True)
class DiagnosticConfig:
    """Thresholds for the initial rule set.

    These are testable hypotheses, not universal truths.  They are kept
    in one object so C-2.2/UI can calibrate them without rewriting rules.
    """

    cpu_wait_low_ratio: float = 0.15
    cpu_wait_high_ratio: float = 0.30
    gpu_active_high: float = 0.85
    gpu_wait_low_ratio: float = 0.15
    busy_margin_ms: float = 1.5
    busy_margin_ratio: float = 0.08
    frame_budget_ratio: float = 0.90
    p95_budget_ratio: float = 1.15

    local_baseline_ms: float = 5000.0
    local_baseline_gap_ms: float = 500.0
    event_window_before_ms: float = 500.0
    event_window_after_ms: float = 1000.0
    local_stutter_ratio: float = 2.0
    local_stutter_floor_ms: float = 20.0
    local_stutter_mad_k: float = 3.0
    # Events whose context windows overlap are not independent.  The
    # effective gap is at least the before+after window span below.
    event_merge_ms: float = 1500.0
    max_events: int = 12

    min_frames: int = 30
    min_baseline_frames: int = 10
    min_window_frames: int = 3
    min_events_for_likely: int = 2
    min_telemetry_samples: int = 2

    ram_high_percent: float = 85.0
    rss_growth_bytes: int = 256 * 1024 * 1024
    rss_window_growth_ratio: float = 0.10

    control_min_improvement: float = 0.20
    control_min_duration_s: float = 30.0
    control_min_frames: int = 300
    control_max_duration_ratio: float = 1.20

    # C-3 safety policy: caller-supplied A/B metadata is not enough for
    # a normal UI/client to claim a confirmed cause.  A future controlled
    # validator may explicitly enable this.
    allow_confirmed_by_control: bool = False


@dataclass(frozen=True)
class Finding:
    code: str
    category: str
    severity: str
    confidence: str
    claim_level: str
    summary: str
    window_start_ms: float | None = None
    window_end_ms: float | None = None
    evidence: tuple[str, ...] = ()
    caveats: tuple[str, ...] = ()
    metrics: dict = field(default_factory=dict)

    def to_dict(self):

        return {
            "code": self.code,
            "category": self.category,
            "severity": self.severity,
            "confidence": self.confidence,
            "claim_level": self.claim_level,
            "summary": self.summary,
            "window_start_ms": self.window_start_ms,
            "window_end_ms": self.window_end_ms,
            "evidence": list(self.evidence),
            "caveats": list(self.caveats),
            "metrics": dict(self.metrics),
        }


@dataclass(frozen=True)
class DiagnosticEvent:
    """Structured local-stutter event for UI and reports."""

    time_ms: float
    duration_ms: float
    baseline_median_ms: float
    threshold_ms: float
    window_start_ms: float
    window_end_ms: float
    frame_index: int
    finding_codes: tuple[str, ...] = ()

    def to_dict(self):

        return {
            "time_ms": self.time_ms,
            "duration_ms": self.duration_ms,
            "baseline_median_ms": self.baseline_median_ms,
            "threshold_ms": self.threshold_ms,
            "window_start_ms": self.window_start_ms,
            "window_end_ms": self.window_end_ms,
            "frame_index": self.frame_index,
            "finding_codes": list(self.finding_codes),
        }


@dataclass(frozen=True)
class ControlExperiment:
    """User-supplied A/B evidence for a confirmed_by_control claim.

    The engine validates the metadata but does not re-analyse the two
    captures.  A valid experiment must target a finding/category, name
    a changed factor, use two different captures, use a recognized
    metric, and show a sufficient relative improvement.
    """

    target: str
    factor: str
    baseline_capture: str
    treatment_capture: str
    metric: str
    baseline_value: float
    treatment_value: float
    baseline_scenario: str = ""
    treatment_scenario: str = ""
    baseline_settings: dict = field(default_factory=dict)
    treatment_settings: dict = field(default_factory=dict)
    baseline_duration_s: float | None = None
    treatment_duration_s: float | None = None
    baseline_frames: int | None = None
    treatment_frames: int | None = None
    minimum_improvement: float | None = None
    notes: str = ""


@dataclass(frozen=True)
class DiagnosticReport:
    findings: tuple[Finding, ...]
    frame_count: int
    duration_s: float
    target_fps: int
    target_budget_ms: float
    timebase: dict
    telemetry_aligned: bool
    event_count: int
    events: tuple[DiagnosticEvent, ...] = ()
    telemetry_available: bool = False
    telemetry_complete: bool = False
    telemetry_sample_count: int = 0
    control_rejections: tuple[str, ...] = ()

    def to_dict(self):

        return {
            "findings": [
                finding.to_dict()
                for finding in self.findings
            ],
            "frame_count": self.frame_count,
            "duration_s": self.duration_s,
            "target_fps": self.target_fps,
            "target_budget_ms": self.target_budget_ms,
            "timebase": dict(self.timebase),
            "telemetry_aligned": self.telemetry_aligned,
            "telemetry_available": self.telemetry_available,
            "telemetry_complete": self.telemetry_complete,
            "telemetry_sample_count": (
                self.telemetry_sample_count
            ),
            "event_count": self.event_count,
            "events": [
                event.to_dict()
                for event in self.events
            ],
            "control_rejections": list(
                self.control_rejections
            ),
        }


@dataclass(frozen=True)
class _FrameMetric:
    index: int
    time_ms: float
    duration_ms: float
    cpu_busy_ms: float | None
    cpu_wait_ms: float | None
    gpu_latency_ms: float | None
    gpu_time_ms: float | None
    gpu_busy_ms: float | None
    gpu_wait_ms: float | None
    display_latency_ms: float | None
    displayed: bool

    @property
    def cpu_wait_ratio(self):

        if self.cpu_wait_ms is None:

            return None

        return self.cpu_wait_ms / self.duration_ms

    @property
    def gpu_active_ratio(self):

        if (
            self.gpu_busy_ms is None
            or self.gpu_time_ms is None
            or self.gpu_time_ms <= 0
        ):

            return None

        return self.gpu_busy_ms / self.gpu_time_ms

    @property
    def gpu_wait_ratio(self):

        if (
            self.gpu_wait_ms is None
            or self.gpu_time_ms is None
            or self.gpu_time_ms <= 0
        ):

            return None

        return self.gpu_wait_ms / self.gpu_time_ms

    @property
    def display_latency_ratio(self):

        if self.display_latency_ms is None:

            return None

        return self.display_latency_ms / self.duration_ms


@dataclass(frozen=True)
class _StutterEvent:
    index: int
    time_ms: float
    duration_ms: float
    baseline_median_ms: float
    threshold_ms: float


def _number(value):

    if value is None:

        return None

    text = str(value).strip()

    if not text or text.upper() == "NA":

        return None

    try:

        number = float(text)

    except (TypeError, ValueError):

        return None

    if not math.isfinite(number):

        return None

    return number


def _row_number(row, key):

    if not isinstance(row, dict):

        return None

    return _number(row.get(key))


def _median(values):

    if not values:

        return None

    return statistics.median(values)


def _p95(values):

    if not values:

        return None

    return percentile(values, 95)


def _format_number(value, digits=2):

    if value is None:

        return "n/a"

    return f"{value:.{digits}f}"


def _timebase_from_frames(frames):

    if not frames:

        return {
            "kind": "unknown",
            "sync_quality": "untrusted",
            "absolute_mapping_trusted": False,
            "raw_column": "",
        }

    first = frames[0]

    return {
        "kind": first.get("timebase_kind", "unknown"),
        "sync_quality": first.get(
            "sync_quality",
            "untrusted",
        ),
        "absolute_mapping_trusted": bool(
            first.get("absolute_mapping_trusted", False)
        ),
        "raw_column": first.get("time_column", ""),
    }


def _build_metrics(frames):

    metrics = []

    for index, frame in enumerate(frames):

        try:

            time_ms = float(frame["time"])
            duration_ms = float(frame["duration"])

        except (KeyError, TypeError, ValueError):

            continue

        if (
            not math.isfinite(time_ms)
            or not math.isfinite(duration_ms)
            or duration_ms <= 0
        ):

            continue

        row = frame.get("row") or {}

        gpu_busy = _row_number(row, "GPUBusy")
        gpu_wait = _row_number(row, "GPUWait")
        gpu_time = _row_number(row, "GPUTime")

        if (
            gpu_time is None
            and gpu_busy is not None
            and gpu_wait is not None
        ):

            gpu_time = gpu_busy + gpu_wait

        displayed = bool(
            frame.get("displayed", False)
        )

        metrics.append(
            _FrameMetric(
                index=index,
                time_ms=time_ms,
                duration_ms=duration_ms,
                cpu_busy_ms=_row_number(
                    row,
                    "CPUBusy",
                ),
                cpu_wait_ms=_row_number(
                    row,
                    "CPUWait",
                ),
                gpu_latency_ms=_row_number(
                    row,
                    "GPULatency",
                ),
                gpu_time_ms=gpu_time,
                gpu_busy_ms=gpu_busy,
                gpu_wait_ms=gpu_wait,
                display_latency_ms=_row_number(
                    row,
                    "DisplayLatency",
                ),
                displayed=displayed,
            )
        )

    metrics.sort(key=lambda item: item.time_ms)

    return metrics


def _summary(metrics):

    durations = [
        item.duration_ms for item in metrics
    ]
    cpu_busy = [
        item.cpu_busy_ms
        for item in metrics
        if item.cpu_busy_ms is not None
    ]
    cpu_wait = [
        item.cpu_wait_ratio
        for item in metrics
        if item.cpu_wait_ratio is not None
    ]
    gpu_busy = [
        item.gpu_busy_ms
        for item in metrics
        if item.gpu_busy_ms is not None
    ]
    gpu_active = [
        item.gpu_active_ratio
        for item in metrics
        if item.gpu_active_ratio is not None
    ]
    gpu_wait = [
        item.gpu_wait_ratio
        for item in metrics
        if item.gpu_wait_ratio is not None
    ]
    display_latency = [
        item.display_latency_ratio
        for item in metrics
        if item.display_latency_ratio is not None
    ]

    return {
        "count": len(metrics),
        "median_frame_ms": _median(durations),
        "p95_frame_ms": _p95(durations),
        "cpu_count": len(cpu_busy),
        "cpu_busy_median_ms": _median(cpu_busy),
        "cpu_wait_ratio_median": _median(cpu_wait),
        "gpu_count": len(gpu_active),
        "gpu_busy_median_ms": _median(gpu_busy),
        "gpu_active_median": _median(gpu_active),
        "gpu_wait_ratio_median": _median(gpu_wait),
        "display_count": len(display_latency),
        "displayed_fraction": (
            sum(1 for item in metrics if item.displayed)
            / len(metrics)
            if metrics
            else 0.0
        ),
        "display_latency_ratio_median": _median(
            display_latency
        ),
    }


def _telemetry_summary(samples, start_ms=None, end_ms=None):

    if not samples:

        return None

    window = []

    for sample in samples:

        t_ms = _number(sample.get("t_ms"))

        if t_ms is None:

            continue

        if start_ms is not None and t_ms < start_ms:

            continue

        if end_ms is not None and t_ms > end_ms:

            continue

        window.append(sample)

    if not window:

        return None

    ram = []
    target_cpu = []
    system_cpu = []
    target_rss = []
    gpu_util = []

    for sample in window:

        ram_value = _number(
            (sample.get("ram") or {}).get("percent")
        )

        if ram_value is not None:

            ram.append(ram_value)

        target = sample.get("target") or {}

        cpu_value = _number(target.get("cpu_percent"))

        if cpu_value is not None:

            target_cpu.append(cpu_value)

        system_value = _number(
            (sample.get("cpu") or {}).get(
                "system_percent"
            )
        )

        if system_value is not None:

            system_cpu.append(system_value)

        rss_value = _number(target.get("rss_bytes"))

        if rss_value is not None:

            target_rss.append(rss_value)

        gpu_value = _number(
            (sample.get("gpu") or {}).get(
                "util_percent"
            )
        )

        if gpu_value is not None:

            gpu_util.append(gpu_value)

    rss_growth = (
        max(target_rss) - min(target_rss)
        if target_rss
        else None
    )

    return {
        "count": len(window),
        "ram_median": _median(ram),
        "ram_max": max(ram) if ram else None,
        "target_cpu_median": _median(target_cpu),
        "target_cpu_all_zero": (
            bool(target_cpu)
            and all(value == 0.0 for value in target_cpu)
        ),
        "system_cpu_median": _median(system_cpu),
        "target_rss_median": _median(target_rss),
        "target_rss_min": min(target_rss) if target_rss else None,
        "target_rss_max": max(target_rss) if target_rss else None,
        "target_rss_growth": rss_growth,
        "gpu_util_median": _median(gpu_util),
    }


def _detect_local_stutters(metrics, config):

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

        durations = [
            base.duration_ms for base in baseline
        ]
        median = statistics.median(durations)
        deviations = sorted(
            abs(value - median)
            for value in durations
        )
        mad = statistics.median(deviations)
        robust_sigma = 1.4826 * mad
        threshold = max(
            median * config.local_stutter_ratio,
            median + config.local_stutter_mad_k * robust_sigma,
            config.local_stutter_floor_ms,
        )

        if item.duration_ms > threshold:

            events.append(
                _StutterEvent(
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
    merge_gap_ms = max(
        config.event_merge_ms,
        config.event_window_before_ms
        + config.event_window_after_ms,
    )

    for event in events:

        if (
            merged
            and event.time_ms - merged[-1].time_ms
            <= merge_gap_ms
        ):

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


def _window_metrics(metrics, start_ms, end_ms):

    return [
        item for item in metrics
        if start_ms <= item.time_ms <= end_ms
    ]


def _finding(
    code,
    category,
    severity,
    confidence,
    claim_level,
    summary,
    window_start_ms=None,
    window_end_ms=None,
    evidence=(),
    caveats=COMMON_CAVEATS,
    metrics=None,
):

    return Finding(
        code=code,
        category=category,
        severity=severity,
        confidence=confidence,
        claim_level=claim_level,
        summary=summary,
        window_start_ms=window_start_ms,
        window_end_ms=window_end_ms,
        evidence=tuple(evidence),
        caveats=tuple(caveats),
        metrics=dict(metrics or {}),
    )


def _budget_evidence(target_fps, stats, budget_ms):

    return (
        f"Target {target_fps} FPS gives a {budget_ms:.2f} ms "
        f"frame budget; mean {stats.mean_frame_ms:.2f} ms, "
        f"P95 {stats.p95_frame_ms:.2f} ms, "
        f"1% low {stats.one_percent_low_fps:.2f} FPS."
    )


def _telemetry_evidence(
    telemetry_summary,
    window_label="capture",
):

    if not telemetry_summary:

        return []

    evidence = [
        f"Telemetry ({window_label}) has "
        f"{telemetry_summary['count']} 4 Hz samples."
    ]

    if telemetry_summary["ram_median"] is not None:

        evidence.append(
            f"System RAM median {telemetry_summary['ram_median']:.1f}%"
            + (
                f", max {telemetry_summary['ram_max']:.1f}%"
                if telemetry_summary["ram_max"] is not None
                else ""
            )
            + "."
        )

    if telemetry_summary["target_rss_growth"] is not None:

        evidence.append(
            "Target working-set range "
            f"{telemetry_summary['target_rss_min'] / 1024**2:.0f}–"
            f"{telemetry_summary['target_rss_max'] / 1024**2:.0f} MiB "
            f"(range {telemetry_summary['target_rss_growth'] / 1024**2:.0f} MiB)."
        )

    if (
        telemetry_summary["target_cpu_median"] is not None
        and not telemetry_summary["target_cpu_all_zero"]
    ):

        evidence.append(
            "Target CPU median "
            f"{telemetry_summary['target_cpu_median']:.1f}%."
        )

    return evidence


def _global_pressure_findings(
    metrics,
    stats,
    summary,
    target_fps,
    config,
    telemetry_aligned,
    telemetry_global,
):

    budget_ms = 1000.0 / target_fps
    median_frame = summary["median_frame_ms"]

    frame_pressure = (
        median_frame is not None
        and (
            median_frame
            >= budget_ms * config.frame_budget_ratio
            or stats.p95_frame_ms
            > budget_ms * config.p95_budget_ratio
        )
    )

    if not frame_pressure:

        return []

    cpu_available = (
        summary["cpu_count"] >= config.min_frames
    )
    gpu_available = (
        summary["gpu_count"] >= config.min_frames
    )

    if not cpu_available and not gpu_available:

        return []

    margin_ms = max(
        config.busy_margin_ms,
        median_frame * config.busy_margin_ratio,
    )

    cpu_wait = summary["cpu_wait_ratio_median"]
    gpu_active = summary["gpu_active_median"]
    gpu_wait = summary["gpu_wait_ratio_median"]
    cpu_busy = summary["cpu_busy_median_ms"]
    gpu_busy = summary["gpu_busy_median_ms"]

    cpu_dominates = (
        cpu_available
        and cpu_busy is not None
        and (
            not gpu_available
            or gpu_busy is None
            or cpu_busy >= gpu_busy + margin_ms
        )
    )
    gpu_dominates = (
        gpu_available
        and gpu_busy is not None
        and (
            not cpu_available
            or cpu_busy is None
            or gpu_busy >= cpu_busy + margin_ms
        )
    )

    cpu_candidate = (
        cpu_available
        and cpu_wait is not None
        and cpu_wait <= config.cpu_wait_low_ratio
        and cpu_dominates
    )
    gpu_candidate = (
        gpu_available
        and gpu_active is not None
        and gpu_wait is not None
        and gpu_active >= config.gpu_active_high
        and gpu_wait <= config.gpu_wait_low_ratio
        and (
            gpu_dominates
            or (
                cpu_wait is not None
                and cpu_wait >= config.cpu_wait_high_ratio
            )
        )
    )

    findings = []

    telemetry_evidence = (
        _telemetry_evidence(telemetry_global)
        if telemetry_aligned
        else []
    )

    if cpu_candidate and gpu_candidate:

        findings.append(
            _finding(
                "mixed_cpu_gpu_pressure",
                CATEGORY_MIXED,
                SEVERITY_WARNING,
                CONFIDENCE_LOW,
                CLAIM_OBSERVED,
                "Both CPU and GPU frame metrics show sustained "
                "pressure; the data cannot choose one cause.",
                metrics[0].time_ms,
                metrics[-1].time_ms,
                evidence=(
                    _budget_evidence(
                        target_fps,
                        stats,
                        budget_ms,
                    ),
                    f"Median CPUBusy {cpu_busy:.2f} ms, "
                    f"GPUBusy {gpu_busy:.2f} ms, "
                    f"margin threshold {margin_ms:.2f} ms.",
                )
                + tuple(telemetry_evidence),
                caveats=COMMON_CAVEATS
                + (
                    "Multiple candidate explanations are retained.",
                ),
                metrics={
                    "cpu_busy_median_ms": cpu_busy,
                    "gpu_busy_median_ms": gpu_busy,
                    "margin_ms": margin_ms,
                },
            )
        )

        return findings

    if cpu_candidate:

        confidence = (
            CONFIDENCE_MEDIUM
            if gpu_available
            else CONFIDENCE_LOW
        )
        caveats = list(COMMON_CAVEATS)

        if not gpu_available:

            caveats.append(
                "GPU frame fields are unavailable; a GPU-side "
                "explanation cannot be excluded."
            )

        findings.append(
            _finding(
                "global_cpu_bottleneck_candidate",
                CATEGORY_CPU,
                SEVERITY_WARNING,
                confidence,
                CLAIM_OBSERVED,
                "CPU-side frame work is the dominant observed "
                "pressure; GPU-side fields do not show a stronger "
                "candidate.",
                metrics[0].time_ms,
                metrics[-1].time_ms,
                evidence=(
                    _budget_evidence(
                        target_fps,
                        stats,
                        budget_ms,
                    ),
                    f"Median CPUWait/FrameTime {cpu_wait:.4f} "
                    f"(low: CPU is not waiting for another stage).",
                    f"Median CPUBusy {cpu_busy:.2f} ms"
                    + (
                        f" vs GPUBusy {gpu_busy:.2f} ms"
                        if gpu_busy is not None
                        else "; GPUBusy unavailable"
                    )
                    + f" (margin threshold {margin_ms:.2f} ms).",
                )
                + tuple(telemetry_evidence),
                caveats=tuple(caveats),
                metrics={
                    "cpu_busy_median_ms": cpu_busy,
                    "cpu_wait_ratio_median": cpu_wait,
                    "gpu_busy_median_ms": gpu_busy,
                    "margin_ms": margin_ms,
                },
            )
        )

    elif gpu_candidate:

        confidence = (
            CONFIDENCE_MEDIUM
            if cpu_available
            else CONFIDENCE_LOW
        )
        caveats = list(COMMON_CAVEATS)

        if not cpu_available:

            caveats.append(
                "CPU frame fields are unavailable; a CPU-side "
                "explanation cannot be excluded."
            )

        findings.append(
            _finding(
                "global_gpu_bottleneck_candidate",
                CATEGORY_GPU,
                SEVERITY_WARNING,
                confidence,
                CLAIM_OBSERVED,
                "GPU frame work is the dominant observed pressure; "
                "CPU-side fields do not show a stronger candidate.",
                metrics[0].time_ms,
                metrics[-1].time_ms,
                evidence=(
                    _budget_evidence(
                        target_fps,
                        stats,
                        budget_ms,
                    ),
                    f"Median GPUBusy/GPUTime {gpu_active:.3f} "
                    f"(high), GPUWait/GPUTime {gpu_wait:.3f} "
                    "(low).",
                    f"Median GPUBusy {gpu_busy:.2f} ms"
                    + (
                        f" vs CPUBusy {cpu_busy:.2f} ms"
                        if cpu_busy is not None
                        else "; CPUBusy unavailable"
                    )
                    + f" (margin threshold {margin_ms:.2f} ms).",
                )
                + tuple(telemetry_evidence),
                caveats=tuple(caveats)
                + (
                    "NVML device utilization is not attributed to "
                    "the target process and was not used here.",
                ),
                metrics={
                    "gpu_busy_median_ms": gpu_busy,
                    "gpu_active_median": gpu_active,
                    "gpu_wait_ratio_median": gpu_wait,
                    "cpu_busy_median_ms": cpu_busy,
                    "margin_ms": margin_ms,
                },
            )
        )

    elif (
        cpu_available
        and gpu_available
        and cpu_busy is not None
        and gpu_busy is not None
        and cpu_busy >= budget_ms * 0.80
        and gpu_active is not None
        and gpu_active >= config.gpu_active_high
        and gpu_wait is not None
        and gpu_wait <= config.gpu_wait_low_ratio
        and abs(cpu_busy - gpu_busy) <= margin_ms
    ):

        findings.append(
            _finding(
                "mixed_frame_pressure",
                CATEGORY_MIXED,
                SEVERITY_WARNING,
                CONFIDENCE_LOW,
                CLAIM_OBSERVED,
                "CPU and GPU busy times are both close to the frame "
                "interval and to each other; no unique bottleneck "
                "can be selected.",
                metrics[0].time_ms,
                metrics[-1].time_ms,
                evidence=(
                    _budget_evidence(
                        target_fps,
                        stats,
                        budget_ms,
                    ),
                    f"Median CPUBusy {cpu_busy:.2f} ms, "
                    f"GPUBusy {gpu_busy:.2f} ms; difference is "
                    f"within the {margin_ms:.2f} ms margin.",
                    f"CPUWait/FrameTime median {cpu_wait:.4f}; "
                    f"GPUWait/GPUTime median {gpu_wait:.4f}.",
                )
                + tuple(telemetry_evidence),
                caveats=COMMON_CAVEATS
                + (
                    "Multiple candidate explanations are retained.",
                ),
                metrics={
                    "cpu_busy_median_ms": cpu_busy,
                    "gpu_busy_median_ms": gpu_busy,
                    "cpu_wait_ratio_median": cpu_wait,
                    "gpu_active_median": gpu_active,
                    "gpu_wait_ratio_median": gpu_wait,
                    "margin_ms": margin_ms,
                },
            )
        )

    return findings


def _event_findings(
    metrics,
    events,
    stats,
    target_fps,
    config,
    telemetry,
    telemetry_aligned,
    display_available,
):

    budget_ms = 1000.0 / target_fps
    findings = []

    for event in events:

        window_start = (
            event.time_ms - config.event_window_before_ms
        )
        window_end = (
            event.time_ms + config.event_window_after_ms
        )

        window = _window_metrics(
            metrics,
            window_start,
            window_end,
        )
        baseline = [
            item for item in metrics
            if (
                event.time_ms - config.local_baseline_ms
                <= item.time_ms
                < event.time_ms - config.local_baseline_gap_ms
            )
        ]

        if (
            len(window) < config.min_window_frames
            or len(baseline) < config.min_baseline_frames
        ):

            continue

        window_summary = _summary(window)
        baseline_summary = _summary(baseline)
        event_frame = metrics[event.index]

        window_cpu = event_frame.cpu_busy_ms
        baseline_cpu = baseline_summary["cpu_busy_median_ms"]
        window_gpu = event_frame.gpu_busy_ms
        baseline_gpu = baseline_summary["gpu_busy_median_ms"]

        cpu_increase = (
            window_cpu - baseline_cpu
            if (
                window_cpu is not None
                and baseline_cpu is not None
            )
            else None
        )
        gpu_increase = (
            window_gpu - baseline_gpu
            if (
                window_gpu is not None
                and baseline_gpu is not None
            )
            else None
        )

        margin_ms = max(
            config.busy_margin_ms,
            (baseline_summary["median_frame_ms"] or 0.0)
            * config.busy_margin_ratio,
        )

        cpu_association = (
            cpu_increase is not None
            and cpu_increase >= margin_ms
            and event_frame.cpu_wait_ratio is not None
            and event_frame.cpu_wait_ratio
            <= config.cpu_wait_low_ratio
            and (
                gpu_increase is None
                or cpu_increase
                >= gpu_increase + margin_ms
            )
        )
        gpu_association = (
            gpu_increase is not None
            and gpu_increase >= margin_ms
            and event_frame.gpu_active_ratio is not None
            and event_frame.gpu_active_ratio
            >= config.gpu_active_high
            and event_frame.gpu_wait_ratio is not None
            and event_frame.gpu_wait_ratio
            <= config.gpu_wait_low_ratio
            and (
                cpu_increase is None
                or gpu_increase
                >= cpu_increase + margin_ms
            )
        )

        event_evidence = [
            f"Local stutter at {event.time_ms:.1f} ms lasts "
            f"{event.duration_ms:.2f} ms; preceding local median "
            f"{event.baseline_median_ms:.2f} ms, local threshold "
            f"{event.threshold_ms:.2f} ms.",
            _budget_evidence(target_fps, stats, budget_ms),
            f"Event frame CPUBusy "
            f"{_format_number(window_cpu)} ms vs baseline "
            f"median {_format_number(baseline_cpu)} ms; "
            f"event frame GPUBusy "
            f"{_format_number(window_gpu)} ms vs baseline "
            f"median {_format_number(baseline_gpu)} ms.",
        ]

        event_caveats = COMMON_CAVEATS + (
            "A local stutter can be caused by work outside the "
            "captured process or by ETW loss; the event window is "
            "context, not a proof.",
        )

        if cpu_association and gpu_association:

            findings.append(
                _finding(
                    "local_stutter_mixed_pressure",
                    CATEGORY_MIXED,
                    SEVERITY_WARNING,
                    CONFIDENCE_LOW,
                    CLAIM_OBSERVED,
                    "Both CPU and GPU work rose during a local "
                    "stutter; no unique cause can be selected.",
                    window_start,
                    window_end,
                    evidence=event_evidence
                    + [
                        f"CPUBusy increase "
                        f"{cpu_increase:.2f} ms; GPUBusy increase "
                        f"{gpu_increase:.2f} ms.",
                    ],
                    caveats=event_caveats,
                    metrics={
                        "cpu_increase_ms": cpu_increase,
                        "gpu_increase_ms": gpu_increase,
                        "margin_ms": margin_ms,
                    },
                )
            )

        elif cpu_association:

            findings.append(
                _finding(
                    "local_stutter_cpu_association",
                    CATEGORY_CPU,
                    SEVERITY_WARNING,
                    CONFIDENCE_LOW,
                    CLAIM_OBSERVED,
                    "CPU busy work rose more than GPU work during "
                    "this local stutter.",
                    window_start,
                    window_end,
                    evidence=event_evidence
                    + [
                        f"CPUBusy increase "
                        f"{cpu_increase:.2f} ms"
                        + (
                            f"; GPUBusy increase "
                            f"{gpu_increase:.2f} ms"
                            if gpu_increase is not None
                            else "; GPUBusy unavailable"
                        )
                        + ".",
                        "Event frame CPUWait/FrameTime "
                        f"{(event_frame.cpu_wait_ratio or 0.0):.4f}.",
                    ],
                    caveats=event_caveats,
                    metrics={
                        "cpu_increase_ms": cpu_increase,
                        "gpu_increase_ms": gpu_increase,
                        "cpu_wait_ratio": (
                            event_frame.cpu_wait_ratio
                        ),
                    },
                )
            )

        elif gpu_association:

            findings.append(
                _finding(
                    "local_stutter_gpu_association",
                    CATEGORY_GPU,
                    SEVERITY_WARNING,
                    CONFIDENCE_LOW,
                    CLAIM_OBSERVED,
                    "GPU busy work rose more than CPU work during "
                    "this local stutter.",
                    window_start,
                    window_end,
                    evidence=event_evidence
                    + [
                        f"GPUBusy increase "
                        f"{gpu_increase:.2f} ms"
                        + (
                            f"; CPUBusy increase "
                            f"{cpu_increase:.2f} ms"
                            if cpu_increase is not None
                            else "; CPUBusy unavailable"
                        )
                        + ".",
                        "Event frame GPUBusy/GPUTime "
                        f"{(event_frame.gpu_active_ratio or 0.0):.3f}.",
                    ],
                    caveats=event_caveats
                    + (
                        "NVML device utilization is not attributed "
                        "to the target process and was not used here.",
                    ),
                    metrics={
                        "gpu_increase_ms": gpu_increase,
                        "cpu_increase_ms": cpu_increase,
                        "gpu_active_ratio": (
                            event_frame.gpu_active_ratio
                        ),
                    },
                )
            )

        presentation_association = False

        if (
            display_available
            and not cpu_association
            and not gpu_association
        ):

            displayed_drop = (
                baseline_summary["displayed_fraction"]
                - window_summary["displayed_fraction"]
                >= 0.05
            )
            window_latency = window_summary[
                "display_latency_ratio_median"
            ]
            baseline_latency = baseline_summary[
                "display_latency_ratio_median"
            ]
            latency_jump = (
                window_latency is not None
                and baseline_latency is not None
                and (
                    window_latency >= baseline_latency + 0.5
                    or (
                        baseline_latency > 0
                        and window_latency
                        >= baseline_latency * 1.5
                    )
                )
            )

            if displayed_drop or latency_jump:

                presentation_association = True
                findings.append(
                    _finding(
                        "local_stutter_presentation_association",
                        CATEGORY_PRESENTATION,
                        SEVERITY_WARNING,
                        CONFIDENCE_LOW,
                        CLAIM_OBSERVED,
                        "Displayed-frame or display-latency behaviour "
                        "changed during this local stutter; no unique "
                        "presentation cause is claimed.",
                        window_start,
                        window_end,
                        evidence=event_evidence
                        + [
                            "Displayed fraction "
                            f"{baseline_summary['displayed_fraction']:.3f} "
                            "→ "
                            f"{window_summary['displayed_fraction']:.3f}.",
                        ],
                        caveats=event_caveats
                        + (
                            "DisplayedTime=NA means the frame was not "
                            "displayed; it does not identify the reason.",
                        ),
                        metrics={
                            "displayed_fraction_baseline": baseline_summary[
                                "displayed_fraction"
                            ],
                            "displayed_fraction_window": window_summary[
                                "displayed_fraction"
                            ],
                        },
                    )
                )

        memory_association = False

        if telemetry_aligned and telemetry is not None:

            window_telemetry = _telemetry_summary(
                telemetry.samples,
                window_start,
                window_end,
            )
            baseline_telemetry = _telemetry_summary(
                telemetry.samples,
                event.time_ms - config.local_baseline_ms,
                event.time_ms - config.local_baseline_gap_ms,
            )

            if (
                window_telemetry
                and window_telemetry["count"]
                >= config.min_telemetry_samples
                and window_telemetry["ram_median"]
                is not None
                and window_telemetry["ram_median"]
                >= config.ram_high_percent
            ):

                rss_growth = None

                if (
                    window_telemetry["target_rss_median"]
                    is not None
                    and baseline_telemetry
                    and baseline_telemetry["count"]
                    >= config.min_telemetry_samples
                    and baseline_telemetry["target_rss_median"]
                ):

                    baseline_rss = baseline_telemetry[
                        "target_rss_median"
                    ]
                    window_rss = window_telemetry[
                        "target_rss_median"
                    ]
                    rss_growth = window_rss - baseline_rss

                if (
                    rss_growth is not None
                    and (
                        rss_growth
                        >= config.rss_growth_bytes
                        or (
                            baseline_telemetry
                            and baseline_telemetry[
                                "target_rss_median"
                            ]
                            and rss_growth
                            >= baseline_telemetry[
                                "target_rss_median"
                            ]
                            * config.rss_window_growth_ratio
                        )
                    )
                ):

                    memory_association = True
                    findings.append(
                        _finding(
                            "local_stutter_memory_pressure_association",
                            CATEGORY_MEMORY,
                            SEVERITY_WARNING,
                            CONFIDENCE_LOW,
                            CLAIM_OBSERVED,
                            "High system RAM and a larger target "
                            "working set coincide with this local "
                            "stutter; this is an association only.",
                            window_start,
                            window_end,
                            evidence=event_evidence
                            + _telemetry_evidence(
                                window_telemetry,
                                "event window",
                            )
                            + [
                                "Target working-set change vs local "
                                f"baseline: {rss_growth / 1024**2:.0f} MiB.",
                            ],
                            caveats=event_caveats
                            + (
                                "System RAM pressure is not "
                                "per-process pressure; working-set "
                                "growth can be normal caching.",
                                "Device-wide VRAM/NVML data is not "
                                "attributed to the target process.",
                            ),
                            metrics={
                                "ram_median": window_telemetry[
                                    "ram_median"
                                ],
                                "rss_growth_bytes": rss_growth,
                            },
                        )
                    )

        if (
            not cpu_association
            and not gpu_association
            and not presentation_association
            and not memory_association
        ):

            findings.append(
                _finding(
                    "local_stutter_unclassified",
                    CATEGORY_UNKNOWN,
                    SEVERITY_INFO,
                    CONFIDENCE_LOW,
                    CLAIM_INSUFFICIENT,
                    "A local stutter was detected, but no CPU, GPU, "
                    "presentation or aligned memory rule met its "
                    "evidence threshold.",
                    window_start,
                    window_end,
                    evidence=event_evidence,
                    caveats=event_caveats
                    + (
                        "Do not assign a cause to this event.",
                    ),
                )
            )

    return findings


def _global_memory_finding(
    stats,
    summary,
    target_fps,
    config,
    telemetry,
    telemetry_aligned,
    event_count,
):

    if not telemetry_aligned or telemetry is None:

        return None

    telemetry_summary = _telemetry_summary(
        telemetry.samples
    )

    if not telemetry_summary:

        return None

    if telemetry_summary["count"] < config.min_telemetry_samples:

        return None

    ram_high = (
        telemetry_summary["ram_median"] is not None
        and telemetry_summary["ram_median"]
        >= config.ram_high_percent
    )
    rss_growth = telemetry_summary["target_rss_growth"]

    if not (
        ram_high
        and rss_growth is not None
        and rss_growth >= config.rss_growth_bytes
        and (
            event_count > 0
            or summary["median_frame_ms"]
            >= (1000.0 / target_fps) * config.frame_budget_ratio
            or stats.p95_frame_ms
            > (1000.0 / target_fps) * config.p95_budget_ratio
        )
    ):

        return None

    return _finding(
        "global_memory_pressure_association",
        CATEGORY_MEMORY,
        SEVERITY_WARNING,
        CONFIDENCE_LOW,
        CLAIM_OBSERVED,
        "System RAM is high and the target working set grew "
        "during the capture; this coincides with frame pressure.",
        None,
        None,
        evidence=(
            _budget_evidence(
                target_fps,
                stats,
                1000.0 / target_fps,
            ),
        )
        + tuple(_telemetry_evidence(telemetry_summary)),
        caveats=COMMON_CAVEATS
        + (
            "System RAM pressure is not per-process pressure; "
            "working-set growth can be normal caching.",
            "Device-wide VRAM/NVML data is not attributed to the "
            "target process.",
        ),
        metrics={
            "ram_median": telemetry_summary["ram_median"],
            "rss_growth_bytes": rss_growth,
            "telemetry_samples": telemetry_summary["count"],
        },
    )


def _display_missing_finding(summary, display_available):

    if not display_available:

        return None

    displayed_fraction = summary["displayed_fraction"]

    if displayed_fraction >= 0.98:

        return None

    return _finding(
        "displayed_frames_missing",
        CATEGORY_PRESENTATION,
        SEVERITY_INFO,
        CONFIDENCE_LOW,
        CLAIM_OBSERVED,
        f"{100.0 * (1.0 - displayed_fraction):.1f}% of captured "
        "frames have DisplayedTime=NA (not displayed).",
        None,
        None,
        evidence=(
            f"Displayed frames: {displayed_fraction:.3f}.",
        ),
        caveats=COMMON_CAVEATS
        + (
            "DisplayedTime=NA means the frame was not displayed; "
            "it does not identify why (queueing, dropping, capture "
            "loss or another cause).",
        ),
        metrics={
            "displayed_fraction": displayed_fraction,
        },
    )


def _upgrade_likely(
    findings,
    cpu_available,
    gpu_available,
    config,
):

    cpu_global = [
        finding for finding in findings
        if finding.code == "global_cpu_bottleneck_candidate"
    ]
    cpu_events = [
        finding for finding in findings
        if finding.code == "local_stutter_cpu_association"
    ]
    gpu_global = [
        finding for finding in findings
        if finding.code == "global_gpu_bottleneck_candidate"
    ]
    gpu_events = [
        finding for finding in findings
        if finding.code == "local_stutter_gpu_association"
    ]

    promote = set()

    if (
        cpu_global
        and gpu_available
        and len(cpu_events) >= config.min_events_for_likely
        and not gpu_global
        and not gpu_events
    ):

        promote.update(id(item) for item in cpu_global)
        promote.update(id(item) for item in cpu_events)

    if (
        gpu_global
        and cpu_available
        and len(gpu_events) >= config.min_events_for_likely
        and not cpu_global
        and not cpu_events
    ):

        promote.update(id(item) for item in gpu_global)
        promote.update(id(item) for item in gpu_events)

    if not promote:

        return findings

    upgraded = []

    for finding in findings:

        if id(finding) in promote:

            upgraded.append(
                replace(
                    finding,
                    claim_level=CLAIM_LIKELY,
                    confidence=CONFIDENCE_MEDIUM,
                    evidence=finding.evidence
                    + (
                        "The same side is supported by a global "
                        "pattern and at least "
                        f"{config.min_events_for_likely} local "
                        "stutter windows, with no contradictory "
                        "opposite-side association.",
                    ),
                    caveats=finding.caveats
                    + (
                        "Likely still requires a controlled A/B "
                        "experiment for confirmation.",
                    ),
                )
            )

        else:

            upgraded.append(finding)

    return upgraded


def _control_improvement(control, default_minimum):

    metric = CONTROL_METRICS.get(control.metric)

    if metric is None:

        return None

    try:

        baseline = float(control.baseline_value)
        treatment = float(control.treatment_value)

    except (TypeError, ValueError):

        return None

    if not (
        math.isfinite(baseline)
        and math.isfinite(treatment)
    ):

        return None

    if baseline == 0:

        return None

    if metric:

        improvement = (
            treatment - baseline
        ) / abs(baseline)

    else:

        improvement = (
            baseline - treatment
        ) / abs(baseline)

    try:

        minimum = (
            default_minimum
            if control.minimum_improvement is None
            else float(control.minimum_improvement)
        )

    except (TypeError, ValueError):

        return None

    if minimum < 0 or minimum > 1:

        return None

    return improvement, minimum


def _control_rejection(control, config):

    if not str(control.target or "").strip():

        return "target is empty"

    factor = str(control.factor or "").strip()

    if not factor:

        return "factor is empty"

    baseline_capture = str(
        control.baseline_capture or ""
    ).strip()
    treatment_capture = str(
        control.treatment_capture or ""
    ).strip()

    if not baseline_capture or not treatment_capture:

        return "capture identifiers are empty"

    if baseline_capture == treatment_capture:

        return "baseline and treatment captures are identical"

    baseline_scenario = str(
        control.baseline_scenario or ""
    ).strip()
    treatment_scenario = str(
        control.treatment_scenario or ""
    ).strip()

    if not baseline_scenario or not treatment_scenario:

        return "scenario identifiers are empty"

    if baseline_scenario != treatment_scenario:

        return "baseline and treatment scenarios differ"

    baseline_settings = control.baseline_settings
    treatment_settings = control.treatment_settings

    if (
        not isinstance(baseline_settings, dict)
        or not isinstance(treatment_settings, dict)
        or not baseline_settings
        or not treatment_settings
    ):

        return "settings metadata is missing"

    keys = set(baseline_settings) | set(treatment_settings)
    changed = [
        key for key in keys
        if baseline_settings.get(key)
        != treatment_settings.get(key)
    ]

    if len(changed) != 1:

        return (
            "exactly one changed setting is required "
            f"(found {len(changed)})"
        )

    if changed[0].strip().casefold() != factor.casefold():

        return (
            "factor does not match the single changed setting "
            f"'{changed[0]}'"
        )

    try:

        baseline_duration = float(
            control.baseline_duration_s
        )
        treatment_duration = float(
            control.treatment_duration_s
        )

    except (TypeError, ValueError):

        return "capture duration is missing"

    if (
        not math.isfinite(baseline_duration)
        or not math.isfinite(treatment_duration)
        or baseline_duration <= 0
        or treatment_duration <= 0
    ):

        return "capture duration is invalid"

    shortest = min(baseline_duration, treatment_duration)
    longest = max(baseline_duration, treatment_duration)

    if shortest < config.control_min_duration_s:

        return (
            f"capture duration {shortest:.1f}s is below "
            f"{config.control_min_duration_s:.1f}s"
        )

    if longest / shortest > config.control_max_duration_ratio:

        return (
            "capture durations are not comparable "
            f"({baseline_duration:.1f}s vs "
            f"{treatment_duration:.1f}s)"
        )

    try:

        baseline_frames = int(control.baseline_frames)
        treatment_frames = int(control.treatment_frames)

    except (TypeError, ValueError):

        return "frame counts are missing"

    if (
        baseline_frames < config.control_min_frames
        or treatment_frames < config.control_min_frames
    ):

        return (
            f"each capture needs at least "
            f"{config.control_min_frames} frames"
        )

    result = _control_improvement(
        control,
        config.control_min_improvement,
    )

    if result is None:

        return "invalid metric or numeric values"

    improvement, minimum = result

    if improvement < minimum:

        return (
            f"improvement {improvement:.1%} is below "
            f"{minimum:.1%}"
        )

    return ""


def _apply_controls(
    findings,
    control_experiments,
    config,
):

    if not control_experiments:

        return findings, ()

    if not config.allow_confirmed_by_control:

        return findings, tuple(
            f"{str(control.target or '<empty>')}: controlled "
            "confirmation is disabled until the A/B data itself is "
            "validated"
            for control in control_experiments
        )

    rejections = []
    upgraded = list(findings)

    for control in control_experiments:

        reason = _control_rejection(
            control,
            config,
        )

        if reason:

            rejections.append(
                f"{control.target or '<empty>'}: {reason}"
            )
            continue

        improvement, _minimum = _control_improvement(
            control,
            config.control_min_improvement,
        )

        for index, finding in enumerate(upgraded):

            if control.target not in (
                finding.code,
                finding.category,
            ):

                continue

            if (
                finding.claim_level == CLAIM_INSUFFICIENT
                or finding.claim_level == CLAIM_CONFIRMED
                or finding.category
                not in (
                    CATEGORY_CPU,
                    CATEGORY_GPU,
                    CATEGORY_MEMORY,
                )
            ):

                continue

            upgraded[index] = replace(
                finding,
                claim_level=CLAIM_CONFIRMED,
                confidence=CONFIDENCE_HIGH,
                evidence=finding.evidence
                + (
                    "Controlled A/B metadata: "
                    f"{control.factor}; {control.metric} improved "
                    f"{improvement:.1%} "
                    f"({control.baseline_value} → "
                    f"{control.treatment_value}) between "
                    f"{control.baseline_capture} and "
                    f"{control.treatment_capture}.",
                ),
                caveats=finding.caveats
                + (
                    "The A/B metadata was supplied by the caller; "
                    "C-2.1 does not re-analyse the two captures.",
                ),
            )

    return upgraded, tuple(rejections)


def _data_quality_findings(
    metrics,
    summary,
    frames,
    telemetry,
    telemetry_aligned,
    config,
):

    findings = []

    if summary["cpu_count"] == 0:

        findings.append(
            _finding(
                "cpu_fields_unavailable",
                CATEGORY_DATA_QUALITY,
                SEVERITY_INFO,
                CONFIDENCE_LOW,
                CLAIM_INSUFFICIENT,
                "CPUBusy/CPUWait are not available; CPU-side "
                "diagnosis is disabled.",
            )
        )

    if summary["gpu_count"] == 0:

        findings.append(
            _finding(
                "gpu_fields_unavailable",
                CATEGORY_DATA_QUALITY,
                SEVERITY_INFO,
                CONFIDENCE_LOW,
                CLAIM_INSUFFICIENT,
                "GPUBusy/GPUWait/GPUTime are not available; "
                "GPU-side diagnosis is disabled.",
                caveats=(
                    "This is expected with --no_track_gpu or a "
                    "PresentMon version/configuration that omits "
                    "GPU frame metrics.",
                ),
            )
        )

    if not any(
        "DisplayedTime" in (frame.get("row") or {})
        for frame in frames
    ):

        findings.append(
            _finding(
                "display_fields_unavailable",
                CATEGORY_DATA_QUALITY,
                SEVERITY_INFO,
                CONFIDENCE_LOW,
                CLAIM_INSUFFICIENT,
                "DisplayedTime/DisplayLatency are not available; "
                "presentation diagnosis is disabled.",
            )
        )

    if telemetry is None or not getattr(
        telemetry,
        "available",
        False,
    ):

        findings.append(
            _finding(
                "telemetry_unavailable",
                CATEGORY_DATA_QUALITY,
                SEVERITY_INFO,
                CONFIDENCE_LOW,
                CLAIM_INSUFFICIENT,
                "No C-1 telemetry sidecar is available; hardware "
                "context and memory-pressure association are "
                "disabled.",
            )
        )

    elif not telemetry_aligned:

        findings.append(
            _finding(
                "telemetry_timebase_untrusted",
                CATEGORY_DATA_QUALITY,
                SEVERITY_INFO,
                CONFIDENCE_LOW,
                CLAIM_INSUFFICIENT,
                "Telemetry exists, but the frame timebase is not a "
                "trusted QPC capture-start mapping; frame/hardware "
                "temporal correlation is disabled.",
                evidence=(
                    "Only a verified QPC mapping may be used for "
                    "frame-to-telemetry window association.",
                ),
                caveats=(
                    "Legacy or first-frame-only timebases remain "
                    "relative-only; 4 Hz samples are not attached "
                    "to frame windows.",
                ),
            )
        )

    elif (
        summary["count"] >= config.min_frames
        and len(getattr(telemetry, "samples", ()))
        < config.min_telemetry_samples
    ):

        findings.append(
            _finding(
                "telemetry_samples_insufficient",
                CATEGORY_DATA_QUALITY,
                SEVERITY_INFO,
                CONFIDENCE_LOW,
                CLAIM_INSUFFICIENT,
                "The telemetry sidecar has too few samples for "
                "window context.",
            )
        )

    if telemetry_aligned:

        telemetry_summary = _telemetry_summary(
            telemetry.samples
        )

        if (
            telemetry_summary
            and telemetry_summary["target_cpu_all_zero"]
        ):

            findings.append(
                _finding(
                    "target_cpu_unusable",
                    CATEGORY_DATA_QUALITY,
                    SEVERITY_INFO,
                    CONFIDENCE_LOW,
                    CLAIM_INSUFFICIENT,
                    "All target CPU samples are 0.0; target CPU was "
                    "not used as evidence.",
                    evidence=(
                        "Target CPU sampling appears to have no "
                        "usable deltas in this sidecar.",
                    ),
                    caveats=(
                        "Frame-level CPUBusy and CPUWait remain "
                        "available and are used instead.",
                    ),
                )
            )

    return findings


def _build_event_records(events, findings, config):

    records = []

    for event in events:

        window_start = (
            event.time_ms - config.event_window_before_ms
        )
        window_end = (
            event.time_ms + config.event_window_after_ms
        )
        codes = tuple(
            finding.code
            for finding in findings
            if (
                finding.code.startswith("local_stutter_")
                and finding.window_start_ms is not None
                and finding.window_end_ms is not None
                and abs(
                    finding.window_start_ms - window_start
                ) < 1e-6
                and abs(
                    finding.window_end_ms - window_end
                ) < 1e-6
            )
        )

        records.append(
            DiagnosticEvent(
                time_ms=event.time_ms,
                duration_ms=event.duration_ms,
                baseline_median_ms=event.baseline_median_ms,
                threshold_ms=event.threshold_ms,
                window_start_ms=window_start,
                window_end_ms=window_end,
                frame_index=event.index,
                finding_codes=codes,
            )
        )

    return tuple(records)


def _insufficient_finding(
    metrics,
    summary,
    telemetry_aligned,
    reason,
):

    return _finding(
        "insufficient_evidence",
        CATEGORY_DATA_QUALITY,
        SEVERITY_INFO,
        CONFIDENCE_LOW,
        CLAIM_INSUFFICIENT,
        reason,
        metrics[0].time_ms if metrics else None,
        metrics[-1].time_ms if metrics else None,
        evidence=(
            f"Valid frame metrics: {len(metrics)}.",
            f"CPU fields: {summary['cpu_count']}; "
            f"GPU fields: {summary['gpu_count']}.",
            "Telemetry aligned: "
            f"{'yes' if telemetry_aligned else 'no'}.",
        ),
        caveats=(
            "No CPU/GPU/presentation/memory cause is claimed.",
        ),
    )


def analyze(
    frames,
    stats=None,
    telemetry=None,
    target_fps=60,
    config=None,
    control_experiments=(),
    timebase=None,
):
    """Analyze selected frames and return a structured report.

    ``frames`` must be the selected frames from
    ``frame_viewer.load_frames`` (or equivalent dicts with ``time``,
    ``duration``, ``row`` and timebase metadata).  ``telemetry`` is a
    ``telemetry.TelemetryReadResult``.  The function never mutates the
    input frames and never imports Qt.
    """

    try:

        target_fps = int(target_fps)

    except (TypeError, ValueError):

        raise ValueError("target_fps must be an integer")

    if not 1 <= target_fps <= 1000:

        raise ValueError("target_fps must be between 1 and 1000")

    config = config or DiagnosticConfig()
    budget_ms = 1000.0 / target_fps
    frames = list(frames or [])
    timebase_info = (
        dict(timebase)
        if isinstance(timebase, dict)
        else _timebase_from_frames(frames)
    )
    metrics = _build_metrics(frames)
    telemetry_available = bool(
        telemetry is not None
        and getattr(telemetry, "available", False)
        and getattr(telemetry, "samples", None)
    )
    telemetry_complete = bool(
        telemetry_available
        and getattr(telemetry, "complete", False)
    )
    telemetry_sample_count = len(
        getattr(telemetry, "samples", ()) or ()
    )

    if not metrics:

        finding = _insufficient_finding(
            metrics,
            {
                "cpu_count": 0,
                "gpu_count": 0,
            },
            False,
            "No valid frame metrics are available.",
        )

        return DiagnosticReport(
            findings=(finding,),
            frame_count=0,
            duration_s=0.0,
            target_fps=target_fps,
            target_budget_ms=budget_ms,
            timebase=timebase_info,
            telemetry_aligned=False,
            event_count=0,
            telemetry_available=telemetry_available,
            telemetry_complete=telemetry_complete,
            telemetry_sample_count=telemetry_sample_count,
        )

    if stats is None:

        try:

            stats = compute_stats(frames)

        except (TypeError, ValueError):

            finding = _insufficient_finding(
                metrics,
                _summary(metrics),
                False,
                "Frame statistics could not be computed.",
            )

            return DiagnosticReport(
                findings=(finding,),
                frame_count=len(metrics),
                duration_s=0.0,
                target_fps=target_fps,
                target_budget_ms=budget_ms,
                timebase=timebase_info,
                telemetry_aligned=False,
                event_count=0,
                telemetry_available=telemetry_available,
                telemetry_complete=telemetry_complete,
                telemetry_sample_count=telemetry_sample_count,
            )

    summary = _summary(metrics)

    cpu_available = summary["cpu_count"] > 0
    gpu_available = summary["gpu_count"] > 0
    display_available = any(
        "DisplayedTime" in (frame.get("row") or {})
        for frame in frames
    )

    absolute_timebase = bool(
        timebase_info.get("absolute_mapping_trusted")
        and timebase_info.get("kind") == "qpc_ms"
        and timebase_info.get("sync_quality")
        in ("verified_qpc", "sidecar_qpc")
    )
    telemetry_aligned = bool(
        telemetry_available
        and absolute_timebase
        and getattr(telemetry, "complete", False)
    )

    if len(metrics) < config.min_frames:

        finding = _insufficient_finding(
            metrics,
            summary,
            telemetry_aligned,
            f"Only {len(metrics)} valid frames are available; "
            f"at least {config.min_frames} are required.",
        )

        return DiagnosticReport(
            findings=(finding,),
            frame_count=len(metrics),
            duration_s=stats.duration_s,
            target_fps=target_fps,
            target_budget_ms=budget_ms,
            timebase=timebase_info,
            telemetry_aligned=telemetry_aligned,
            event_count=0,
            telemetry_available=telemetry_available,
            telemetry_complete=telemetry_complete,
            telemetry_sample_count=telemetry_sample_count,
        )

    data_quality = _data_quality_findings(
        metrics,
        summary,
        frames,
        telemetry,
        telemetry_aligned,
        config,
    )

    telemetry_global = (
        _telemetry_summary(telemetry.samples)
        if telemetry_aligned
        else None
    )

    events = _detect_local_stutters(
        metrics,
        config,
    )
    findings = []

    findings.extend(
        _global_pressure_findings(
            metrics,
            stats,
            summary,
            target_fps,
            config,
            telemetry_aligned,
            telemetry_global,
        )
    )
    findings.extend(
        _event_findings(
            metrics,
            events,
            stats,
            target_fps,
            config,
            telemetry,
            telemetry_aligned,
            display_available,
        )
    )

    memory_finding = _global_memory_finding(
        stats,
        summary,
        target_fps,
        config,
        telemetry,
        telemetry_aligned,
        len(events),
    )

    if memory_finding is not None:

        findings.append(memory_finding)

    display_finding = _display_missing_finding(
        summary,
        display_available,
    )

    if display_finding is not None:

        findings.append(display_finding)

    findings = _upgrade_likely(
        findings,
        cpu_available,
        gpu_available,
        config,
    )
    findings, control_rejections = _apply_controls(
        findings,
        control_experiments,
        config,
    )

    cause_findings = [
        finding for finding in findings
        if finding.category in CAUSE_CATEGORIES
    ]

    if not cause_findings:

        findings.append(
            _insufficient_finding(
                metrics,
                summary,
                telemetry_aligned,
                "No CPU, GPU, presentation or memory rule met its "
                "evidence threshold.",
            )
        )

    event_records = _build_event_records(
        events,
        findings,
        config,
    )
    findings = data_quality + findings

    return DiagnosticReport(
        findings=tuple(findings),
        frame_count=len(metrics),
        duration_s=stats.duration_s,
        target_fps=target_fps,
        target_budget_ms=budget_ms,
        timebase=timebase_info,
        telemetry_aligned=telemetry_aligned,
        event_count=len(events),
        events=event_records,
        telemetry_available=telemetry_available,
        telemetry_complete=telemetry_complete,
        telemetry_sample_count=telemetry_sample_count,
        control_rejections=control_rejections,
    )


def analyze_capture(
    frames,
    stats=None,
    telemetry=None,
    target_fps=60,
    config=None,
    control_experiments=(),
    timebase=None,
):
    """Readable alias for :func:`analyze`."""

    return analyze(
        frames,
        stats=stats,
        telemetry=telemetry,
        target_fps=target_fps,
        config=config,
        control_experiments=control_experiments,
        timebase=timebase,
    )
