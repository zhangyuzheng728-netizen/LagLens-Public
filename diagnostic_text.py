"""Localized, player-facing text for diagnostic findings.

The diagnostic engine is intentionally language-neutral in structure:
it returns codes, categories, metrics and evidence.  This module maps
those structures to UI/report text through the existing i18n catalogs.
Raw engine evidence strings are not shown in the localized UI; numeric
metrics and event context are rendered instead.
"""

from __future__ import annotations

import math

from i18n import tr


CLAIM_KEYS = {
    "observed_association": "analysis.diagnostics.claim.observed_association",
    "likely": "analysis.diagnostics.claim.likely",
    "confirmed_by_control": "analysis.diagnostics.claim.confirmed_by_control",
    "insufficient_evidence": "analysis.diagnostics.claim.insufficient_evidence",
}

CONFIDENCE_KEYS = {
    "low": "analysis.diagnostics.confidence.low",
    "medium": "analysis.diagnostics.confidence.medium",
    "high": "analysis.diagnostics.confidence.high",
}

SEVERITY_KEYS = {
    "info": "analysis.diagnostics.severity.info",
    "warning": "analysis.diagnostics.severity.warning",
    "critical": "analysis.diagnostics.severity.critical",
}

CATEGORY_KEYS = {
    "cpu": "analysis.diagnostics.category.cpu",
    "gpu": "analysis.diagnostics.category.gpu",
    "mixed": "analysis.diagnostics.category.mixed",
    "memory": "analysis.diagnostics.category.memory",
    "presentation": "analysis.diagnostics.category.presentation",
    "data_quality": "analysis.diagnostics.category.data_quality",
    "unknown": "analysis.diagnostics.category.unknown",
}

ADVICE_KEYS = {
    "cpu": "analysis.diagnostics.advice.cpu",
    "gpu": "analysis.diagnostics.advice.gpu",
    "mixed": "analysis.diagnostics.advice.mixed",
    "memory": "analysis.diagnostics.advice.memory",
    "presentation": "analysis.diagnostics.advice.presentation",
    "data_quality": "analysis.diagnostics.advice.data_quality",
    "unknown": "analysis.diagnostics.advice.unknown",
}

WHY_KEYS = {
    "cpu": "analysis.diagnostics.why.cpu",
    "gpu": "analysis.diagnostics.why.gpu",
    "mixed": "analysis.diagnostics.why.mixed",
    "memory": "analysis.diagnostics.why.memory",
    "presentation": "analysis.diagnostics.why.presentation",
    "data_quality": "analysis.diagnostics.why.data_quality",
    "unknown": "analysis.diagnostics.why.unknown",
}

LIMIT_KEYS = {
    "cpu": "analysis.diagnostics.limit.cpu",
    "gpu": "analysis.diagnostics.limit.gpu",
    "mixed": "analysis.diagnostics.limit.mixed",
    "memory": "analysis.diagnostics.limit.memory",
    "presentation": "analysis.diagnostics.limit.presentation",
    "data_quality": "analysis.diagnostics.limit.data_quality",
    "unknown": "analysis.diagnostics.limit.unknown",
}

PLAIN_CLAIM_KEYS = {
    "observed_association": (
        "analysis.diagnostics.plain.claim."
        "observed_association"
    ),
    "likely": "analysis.diagnostics.plain.claim.likely",
    "confirmed_by_control": (
        "analysis.diagnostics.plain.claim."
        "confirmed_by_control"
    ),
    "insufficient_evidence": (
        "analysis.diagnostics.plain.claim."
        "insufficient_evidence"
    ),
}

PLAIN_STRENGTH_KEYS = {
    "low": "analysis.diagnostics.plain.strength.low",
    "medium": "analysis.diagnostics.plain.strength.medium",
    "high": "analysis.diagnostics.plain.strength.high",
}

CERTAINTY_KEYS = {
    "observed_association": (
        "analysis.diagnostics.plain.certainty."
        "observed_association"
    ),
    "likely": "analysis.diagnostics.plain.certainty.likely",
    "confirmed_by_control": (
        "analysis.diagnostics.plain.certainty."
        "confirmed_by_control"
    ),
    "insufficient_evidence": (
        "analysis.diagnostics.plain.certainty."
        "insufficient_evidence"
    ),
}

GUIDE_KEYS = {
    "cpu": (
        "analysis.diagnostics.guide.cpu.step1",
        "analysis.diagnostics.guide.cpu.step2",
        "analysis.diagnostics.guide.cpu.step3",
        "analysis.diagnostics.guide.cpu.step4",
    ),
    "gpu": (
        "analysis.diagnostics.guide.gpu.step1",
        "analysis.diagnostics.guide.gpu.step2",
        "analysis.diagnostics.guide.gpu.step3",
        "analysis.diagnostics.guide.gpu.step4",
    ),
    "mixed": (
        "analysis.diagnostics.guide.mixed.step1",
        "analysis.diagnostics.guide.mixed.step2",
        "analysis.diagnostics.guide.mixed.step3",
        "analysis.diagnostics.guide.mixed.step4",
    ),
    "memory": (
        "analysis.diagnostics.guide.memory.step1",
        "analysis.diagnostics.guide.memory.step2",
        "analysis.diagnostics.guide.memory.step3",
        "analysis.diagnostics.guide.memory.step4",
    ),
    "presentation": (
        "analysis.diagnostics.guide.presentation.step1",
        "analysis.diagnostics.guide.presentation.step2",
        "analysis.diagnostics.guide.presentation.step3",
        "analysis.diagnostics.guide.presentation.step4",
    ),
    "data_quality": (
        "analysis.diagnostics.guide.data_quality.step1",
        "analysis.diagnostics.guide.data_quality.step2",
        "analysis.diagnostics.guide.data_quality.step3",
        "analysis.diagnostics.guide.data_quality.step4",
    ),
    "unknown": (
        "analysis.diagnostics.guide.data_quality.step1",
        "analysis.diagnostics.guide.data_quality.step2",
        "analysis.diagnostics.guide.data_quality.step3",
        "analysis.diagnostics.guide.data_quality.step4",
    ),
}


def _translated_or(key, fallback):

    value = tr(key)

    if value == key:

        return fallback

    return value


def category_label(category):

    return _translated_or(
        CATEGORY_KEYS.get(
            category,
            "analysis.diagnostics.category.unknown",
        ),
        category.replace("_", " ").title(),
    )


def claim_label(claim):

    return _translated_or(
        CLAIM_KEYS.get(
            claim,
            "analysis.diagnostics.claim.insufficient_evidence",
        ),
        claim.replace("_", " ").title(),
    )


def confidence_label(confidence):

    return _translated_or(
        CONFIDENCE_KEYS.get(
            confidence,
            "analysis.diagnostics.confidence.low",
        ),
        confidence.title(),
    )


def plain_claim_label(claim):

    return _translated_or(
        PLAIN_CLAIM_KEYS.get(
            claim,
            "analysis.diagnostics.plain.claim.insufficient_evidence",
        ),
        claim.replace("_", " ").title(),
    )


def plain_strength_label(confidence):

    return _translated_or(
        PLAIN_STRENGTH_KEYS.get(
            confidence,
            "analysis.diagnostics.plain.strength.low",
        ),
        confidence.title(),
    )


def certainty_text(finding):

    claim = finding.claim_level
    key = CERTAINTY_KEYS.get(
        claim,
        CERTAINTY_KEYS["insufficient_evidence"],
    )

    return tr(
        key,
        strength=plain_strength_label(
            finding.confidence
        ),
    )


def evidence_warning(report):

    if report is None:

        return ""

    if not report.telemetry_available:

        return tr(
            "analysis.diagnostics.plain.telemetry_missing"
        )

    if not report.telemetry_aligned:

        return tr(
            "analysis.diagnostics.plain.timebase_untrusted"
        )

    if not report.telemetry_complete:

        return tr(
            "analysis.diagnostics.plain.telemetry_incomplete"
        )

    return ""


def severity_label(severity):

    return _translated_or(
        SEVERITY_KEYS.get(
            severity,
            "analysis.diagnostics.severity.info",
        ),
        severity.title(),
    )


def finding_summary(finding):

    return _translated_or(
        f"analysis.diagnostics.code.{finding.code}",
        finding.summary,
    )


def why_text(finding):

    return _translated_or(
        WHY_KEYS.get(
            finding.category,
            "analysis.diagnostics.why.unknown",
        ),
        "",
    )


def limit_text(finding):

    return _translated_or(
        LIMIT_KEYS.get(
            finding.category,
            "analysis.diagnostics.limit.unknown",
        ),
        "",
    )


def advice_text(finding):

    return _translated_or(
        ADVICE_KEYS.get(
            finding.category,
            "analysis.diagnostics.advice.unknown",
        ),
        "",
    )


def _number_text(key, value):

    if isinstance(value, bool):

        return "yes" if value else "no"

    if not isinstance(value, (int, float)):

        return str(value)

    if not math.isfinite(value):

        return "n/a"

    if key.endswith("_bytes"):

        return f"{value / 1024**2:.0f} MiB"

    if key.endswith("_ms"):

        return f"{value:.2f} ms"

    if "fraction" in key or key.endswith("_ratio"):

        return f"{value:.3f}"

    if "percent" in key:

        return f"{value:.1f}%"

    if key == "telemetry_samples":

        return str(int(value))

    return f"{value:.3f}"


def metric_lines(finding):

    lines = []

    for key, value in finding.metrics.items():

        if value is None:

            continue

        label = _translated_or(
            f"analysis.diagnostics.metric.{key}",
            key.replace("_", " "),
        )
        lines.append(
            tr(
                "analysis.diagnostics.metric.line",
                label=label,
                value=_number_text(key, value),
            )
        )

    return tuple(lines)


def finding_window_text(finding):

    if (
        finding.window_start_ms is None
        or finding.window_end_ms is None
    ):

        return ""

    return tr(
        "analysis.diagnostics.window",
        start=finding.window_start_ms / 1000.0,
        end=finding.window_end_ms / 1000.0,
    )


def event_label(event):

    return tr(
        "analysis.diagnostics.event.item",
        seconds=event.time_ms / 1000.0,
        duration=event.duration_ms,
    )


def event_details(event, frame):

    row = (frame or {}).get("row") or {}
    displayed = (
        (frame or {}).get("displayed", False)
    )

    return "\n".join(
        [
            tr(
                "analysis.diagnostics.event.details",
                seconds=event.time_ms / 1000.0,
                duration=event.duration_ms,
                baseline=event.baseline_median_ms,
                threshold=event.threshold_ms,
            ),
            tr(
                "analysis.diagnostics.event.frame",
                cpu=row.get("CPUBusy", "NA"),
                cpu_wait=row.get("CPUWait", "NA"),
                gpu=row.get("GPUBusy", "NA"),
                gpu_wait=row.get("GPUWait", "NA"),
                gpu_latency=row.get("GPULatency", "NA"),
                gpu_time=row.get("GPUTime", "NA"),
                display_latency=row.get(
                    "DisplayLatency",
                    "NA",
                ),
                displayed=(
                    tr("analysis.details.display_yes")
                    if displayed
                    else tr("analysis.details.display_no")
                ),
            ),
        ]
    )


def sync_lines(report, data_quality_findings=()):

    timebase = report.timebase or {}
    kind = timebase.get("kind", "unknown")
    quality = timebase.get("sync_quality", "untrusted")
    absolute = bool(
        timebase.get("absolute_mapping_trusted")
    )

    if kind == "qpc_ms" and absolute:

        quality_text = tr(
            "analysis.diagnostics.sync.quality.verified"
        )

    elif kind == "qpc_ms":

        quality_text = tr(
            "analysis.diagnostics.sync.quality.unverified"
        )

    elif kind == "relative":

        quality_text = tr(
            "analysis.diagnostics.sync.quality.relative"
        )

    else:

        quality_text = tr(
            "analysis.diagnostics.sync.quality.unknown"
        )

    lines = [
        tr(
            "analysis.diagnostics.sync.qpc",
            quality=quality_text,
        )
    ]

    if report.telemetry_available:

        lines.append(
            tr(
                "analysis.diagnostics.sync.telemetry",
                count=report.telemetry_sample_count,
                complete=(
                    tr("analysis.diagnostics.sync.complete")
                    if report.telemetry_complete
                    else tr("analysis.diagnostics.sync.incomplete")
                ),
            )
        )

    else:

        lines.append(
            tr("analysis.diagnostics.sync.telemetry_missing")
        )

    lines.append(
        tr(
            "analysis.diagnostics.sync.aligned",
            aligned=(
                tr("analysis.diagnostics.sync.aligned.yes")
                if report.telemetry_aligned
                else tr(
                    "analysis.diagnostics.sync.aligned.no"
                )
            ),
        )
    )

    for finding in data_quality_findings:

        lines.append(finding_summary(finding))

    return "\n".join(lines)


def guide_steps(category):

    keys = GUIDE_KEYS.get(
        category,
        GUIDE_KEYS["unknown"],
    )

    return tuple(tr(key) for key in keys)


def group_findings(findings):
    """Group repeated findings by category and code, preserving order."""

    groups = []
    indices = {}

    for finding in findings:

        key = (finding.category, finding.code)

        if key not in indices:

            indices[key] = len(groups)
            groups.append(
                {
                    "category": finding.category,
                    "code": finding.code,
                    "finding": finding,
                    "findings": [],
                }
            )

        groups[indices[key]]["findings"].append(finding)

    for group in groups:

        group["count"] = len(group["findings"])

    return groups


def group_count_label(count):

    if count <= 1:

        return ""

    return tr(
        "analysis.diagnostics.group.count",
        count=count,
    )


def _median(values):

    ordered = sorted(values)

    if not ordered:

        return 0.0

    middle = len(ordered) // 2

    if len(ordered) % 2:

        return ordered[middle]

    return (
        ordered[middle - 1] + ordered[middle]
    ) / 2.0


def event_periodicity(events):
    """Find a conservative common interval between event timestamps.

    This is presentation-only analysis of the event times.  It does not
    inspect causes and never claims that every event belongs to the
    interval.
    """

    times = sorted(
        float(event.time_ms)
        for event in events
    )
    total = len(times)
    result = {
        "total": total,
        "period_ms": None,
        "tolerance_ms": 0.0,
        "regular_indices": tuple(),
        "extra_indices": tuple(range(total)),
    }

    if total < 3:

        return result

    intervals = [
        right - left
        for left, right in zip(times, times[1:])
        if right > left
    ]

    if len(intervals) < 2:

        return result

    clusters = []

    for interval in sorted(intervals):

        if not clusters:

            clusters.append([interval])
            continue

        reference = clusters[-1][-1]
        tolerance = max(250.0, reference * 0.02)

        if abs(interval - reference) <= tolerance:

            clusters[-1].append(interval)

        else:

            clusters.append([interval])

    candidates = [
        _median(cluster)
        for cluster in clusters
        if len(cluster) >= 2
    ]

    best = None

    for period in candidates:

        if period <= 0:

            continue

        tolerance = max(250.0, period * 0.02)

        for anchor in times:

            regular = []
            residual_sum = 0.0

            for index, time in enumerate(times):

                offset = time - anchor

                if offset < -tolerance:

                    continue

                multiple = round(offset / period)
                residual = abs(
                    offset - multiple * period
                )

                if residual <= tolerance:

                    regular.append(index)
                    residual_sum += residual

            required = max(3, math.ceil(total * 0.5))

            if len(regular) < required:

                continue

            score = (
                len(regular),
                -residual_sum,
                -period,
            )

            if best is None or score > best["score"]:

                best = {
                    "score": score,
                    "period_ms": period,
                    "tolerance_ms": tolerance,
                    "regular_indices": tuple(regular),
                }

    if best is None:

        return result

    regular = set(best["regular_indices"])

    result.update(
        {
            "period_ms": best["period_ms"],
            "tolerance_ms": best["tolerance_ms"],
            "regular_indices": tuple(
                index
                for index in range(total)
                if index in regular
            ),
            "extra_indices": tuple(
                index
                for index in range(total)
                if index not in regular
            ),
        }
    )

    return result


def _event_finding(event, findings):
    """Find the finding that belongs to an event, preferring exact window."""

    matching_code = []

    for finding in findings:

        if finding.code not in event.finding_codes:

            continue

        matching_code.append(finding)

        if (
            finding.window_start_ms is not None
            and finding.window_end_ms is not None
            and abs(
                finding.window_start_ms
                - event.window_start_ms
            ) < 1e-6
            and abs(
                finding.window_end_ms
                - event.window_end_ms
            ) < 1e-6
        ):

            return finding

    if matching_code:

        return matching_code[0]

    return None


def event_finding(event, findings):

    return _event_finding(event, findings)


def event_type_label(event, findings):

    finding = _event_finding(event, findings)

    if finding is None:

        return tr(
            "analysis.diagnostics.events.unclassified"
        )

    return category_label(finding.category)


def event_key_evidence(event, findings):

    finding = _event_finding(event, findings)

    if finding is not None:

        metrics = finding.metrics

        if (
            "cpu_increase_ms" in metrics
            and "gpu_increase_ms" in metrics
        ):

            return tr(
                "analysis.diagnostics.events.evidence.cpu_gpu",
                cpu=metrics["cpu_increase_ms"],
                gpu=metrics["gpu_increase_ms"],
            )

        lines_for_finding = metric_lines(finding)

        if lines_for_finding:

            return " · ".join(lines_for_finding[:2])

    return tr(
        "analysis.diagnostics.events.evidence.fallback",
        duration=event.duration_ms,
        baseline=event.baseline_median_ms,
    )


def event_table_rows(report):

    periodicity = event_periodicity(report.events)
    rows = []

    for index, event in enumerate(report.events):

        if periodicity["period_ms"] is None:

            pattern = tr(
                "analysis.diagnostics.events.table.no_pattern"
            )

        elif index in periodicity["regular_indices"]:

            pattern = tr(
                "analysis.diagnostics.events.table.regular"
            )

        else:

            pattern = tr(
                "analysis.diagnostics.events.table.extra"
            )

        rows.append(
            {
                "event": event,
                "time": event.time_ms / 1000.0,
                "duration": event.duration_ms,
                "type": event_type_label(
                    event,
                    report.findings,
                ),
                "pattern": pattern,
                "evidence": event_key_evidence(
                    event,
                    report.findings,
                ),
            }
        )

    return rows, periodicity


def anomaly_summary(report):

    if report is None or not report.events:

        return (
            tr("analysis.diagnostics.overview.none"),
        )

    events = report.events
    total = len(events)
    lines = [
        tr(
            "analysis.diagnostics.overview.detected.one"
            if total == 1
            else "analysis.diagnostics.overview.detected",
            count=total,
        )
    ]
    periodicity = event_periodicity(events)

    if total < 3:

        lines.append(
            tr(
                "analysis.diagnostics.overview.period.insufficient"
            )
        )

    elif periodicity["period_ms"] is None:

        lines.append(
            tr(
                "analysis.diagnostics.overview.period.none",
                count=total,
            )
        )

    else:

        regular = len(
            periodicity["regular_indices"]
        )
        extra = len(periodicity["extra_indices"])
        period_s = periodicity["period_ms"] / 1000.0

        if extra == 0:

            lines.append(
                tr(
                    "analysis.diagnostics.overview.period.all",
                    count=total,
                    period=period_s,
                )
            )

        elif extra == 1:

            lines.append(
                tr(
                    "analysis.diagnostics.overview.period.some.one",
                    regular=regular,
                    total=total,
                    extra=extra,
                    period=period_s,
                )
            )

        else:

            lines.append(
                tr(
                    "analysis.diagnostics.overview.period.some.many",
                    regular=regular,
                    total=total,
                    extra=extra,
                    period=period_s,
                )
            )

        lines.append(
            tr("analysis.diagnostics.overview.period.note")
        )

    category_counts = {}

    for event in events:

        finding = _event_finding(
            event,
            report.findings,
        )

        if finding is None:

            continue

        category_counts[finding.category] = (
            category_counts.get(finding.category, 0)
            + 1
        )

    if category_counts:

        dominant = max(
            category_counts,
            key=category_counts.get,
        )
        dominant_count = category_counts[dominant]
        pattern_key = (
            "analysis.diagnostics.overview.evidence."
            f"{dominant}"
        )
        pattern = tr(pattern_key)

        if total == 1:

            lines.append(
                tr(
                    "analysis.diagnostics.overview.evidence.one",
                    pattern=pattern,
                )
            )

        elif dominant_count == total:

            lines.append(
                tr(
                    "analysis.diagnostics.overview.evidence.all",
                    count=total,
                    pattern=pattern,
                )
            )

        elif dominant_count > total / 2:

            lines.append(
                tr(
                    "analysis.diagnostics.overview.evidence.some",
                    count=dominant_count,
                    total=total,
                    pattern=pattern,
                )
            )

        else:

            lines.append(
                tr(
                    "analysis.diagnostics.overview.evidence.multiple"
                )
            )

    else:

        lines.append(
            tr(
                "analysis.diagnostics.overview.evidence.multiple"
            )
        )

    lines.append(
        tr("analysis.diagnostics.overview.observation")
    )
    lines.append(
        tr("analysis.diagnostics.overview.caveat")
    )

    return tuple(lines)


def advice_for_findings(findings):

    seen = set()
    lines = []

    for finding in findings:

        category = finding.category

        if category in seen:

            continue

        seen.add(category)
        advice = advice_text(finding)

        if advice:

            lines.append(advice)

    if not lines:

        lines.append(
            tr("analysis.diagnostics.advice.unknown")
        )

    return "\n".join(
        f"• {line}"
        for line in lines
    )
