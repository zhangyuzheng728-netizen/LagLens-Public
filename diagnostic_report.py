"""Local JSON/Markdown export for C-3 diagnostic reports.

The exporter never writes a full capture path, username or environment
path into the report.  Callers pass only the capture basename and target
name.  JSON is a structured technical artifact; Markdown is localized
for players through the existing i18n catalogs.
"""

from __future__ import annotations

import json

from pathlib import Path

import diagnostic_text
from i18n import tr


def _capture_payload(
    capture_name,
    target_name="",
    profile="",
):

    return {
        "file": Path(capture_name).name,
        "target": (
            Path(target_name).name
            if target_name
            else ""
        ),
        "profile": profile,
    }


def build_json(
    report,
    capture_name,
    target_name="",
    profile="",
):

    return json.dumps(
        {
            "schema_version": 1,
            "capture": _capture_payload(
                capture_name,
                target_name,
                profile,
            ),
            "report": report.to_dict(),
        },
        indent=2,
        ensure_ascii=False,
    )


def _timebase_label(report):

    timebase = report.timebase or {}
    kind = timebase.get("kind", "unknown")
    quality = timebase.get("sync_quality", "untrusted")

    if kind == "qpc_ms" and timebase.get(
        "absolute_mapping_trusted"
    ):

        quality = tr(
            "analysis.diagnostics.sync.quality.verified"
        )

    elif kind == "qpc_ms":

        quality = tr(
            "analysis.diagnostics.sync.quality.unverified"
        )

    elif kind == "relative":

        quality = tr(
            "analysis.diagnostics.sync.quality.relative"
        )

    else:

        quality = tr(
            "analysis.diagnostics.sync.quality.unknown"
        )

    return kind, quality


def _table_cell(value):

    return str(value).replace("|", "\\|").replace(
        "\n",
        " ",
    )


def build_markdown(
    report,
    capture_name,
    target_name="",
    profile="",
):

    capture = _capture_payload(
        capture_name,
        target_name,
        profile,
    )
    kind, quality = _timebase_label(report)
    separator = tr(
        "analysis.diagnostics.label_separator"
    )
    lines = [
        f"# {tr('analysis.report.title')}",
        "",
        f"## {tr('analysis.report.capture')}",
        "",
        tr("analysis.report.file", name=capture["file"]),
        tr(
            "analysis.report.target",
            target=capture["target"] or "n/a",
        ),
        tr(
            "analysis.report.frames",
            frames=report.frame_count,
            duration=report.duration_s,
        ),
        tr(
            "analysis.report.target_fps",
            fps=report.target_fps,
            budget=report.target_budget_ms,
        ),
        tr(
            "analysis.report.timebase",
            kind=kind,
            quality=quality,
        ),
        tr(
            "analysis.report.telemetry",
            count=report.telemetry_sample_count,
            complete=(
                tr("analysis.diagnostics.sync.complete")
                if report.telemetry_complete
                else tr("analysis.diagnostics.sync.incomplete")
            ),
        )
        if report.telemetry_available
        else tr("analysis.diagnostics.sync.telemetry_missing"),
    ]

    warning = diagnostic_text.evidence_warning(report)

    if warning:

        lines.extend(
            [
                "",
                f"> {tr('analysis.report.data_limit')}"
                f"{separator}{warning}",
            ]
        )

    lines.extend(
        [
            "",
            f"## {tr('analysis.diagnostics.overview.title')}",
            "",
        ]
    )

    for line in diagnostic_text.anomaly_summary(report):

        lines.append(f"- {line}")

    lines.extend(
        [
            "",
            f"## {tr('analysis.report.findings')}",
            "",
        ]
    )

    groups = diagnostic_text.group_findings(
        report.findings
    )

    if not groups:

        lines.append(
            tr("analysis.diagnostics.code.insufficient_evidence")
        )

    category_advice_seen = {}

    for group in groups:

        finding = group["finding"]
        count = group["count"]
        summary = diagnostic_text.finding_summary(finding)
        why = diagnostic_text.why_text(finding)
        limitation = diagnostic_text.limit_text(finding)
        advice = diagnostic_text.advice_text(finding)
        heading = (
            f"### {diagnostic_text.category_label(finding.category)}"
            f" — {summary}"
        )

        if count > 1:

            heading += (
                f" ({tr('analysis.report.group_count', count=count)})"
            )

        lines.extend(
            [
                heading,
                "",
                f"**{tr('analysis.report.what_found')}**"
                f"{separator}{summary}",
                "",
                f"**{tr('analysis.report.why')}**"
                f"{separator}"
                f"{why or tr('analysis.diagnostics.why.unknown')}",
                "",
                f"**{tr('analysis.report.certainty')}**"
                f"{separator}"
                f"{diagnostic_text.certainty_text(finding)}",
                "",
                f"**{tr('analysis.report.does_not_tell')}**"
                f"{separator}"
                f"{limitation or tr('analysis.diagnostics.limit.unknown')}",
            ]
        )

        if finding.category not in category_advice_seen:

            lines.extend(
                [
                    "",
                    f"**{tr('analysis.report.next')}**"
                    f"{separator}"
                    f"{advice or tr('analysis.diagnostics.advice.unknown')}",
                ]
            )
            category_advice_seen[finding.category] = True

        lines.extend(
            [
                "",
                f"#### {tr('analysis.report.technical')}",
                "",
                f"- {tr('analysis.report.claim')}"
                f"{separator}"
                f"{diagnostic_text.claim_label(finding.claim_level)}"
                f" (`{finding.claim_level}`)",
                f"- {tr('analysis.report.confidence')}"
                f"{separator}"
                f"{diagnostic_text.confidence_label(finding.confidence)}"
                f" (`{finding.confidence}`)",
                f"- {tr('analysis.report.severity')}"
                f"{separator}"
                f"{diagnostic_text.severity_label(finding.severity)}"
                f" (`{finding.severity}`)",
            ]
        )

        if count > 1:

            lines.append(
                f"- {tr('analysis.report.group_count', count=count)}"
            )

        else:

            window = diagnostic_text.finding_window_text(
                finding
            )

            if window:

                lines.append(
                    f"- {tr('analysis.report.window')}"
                    f"{separator}{window}"
                )

            metric_lines = diagnostic_text.metric_lines(
                finding
            )

            if metric_lines:

                lines.extend(
                    f"- {line}" for line in metric_lines
                )

        lines.append("")

    lines.extend(
        [
            f"## {tr('analysis.diagnostics.events.table.title')}",
            "",
        ]
    )

    rows, _periodicity = diagnostic_text.event_table_rows(
        report
    )

    if rows:

        headers = [
            tr("analysis.diagnostics.events.table.time"),
            tr("analysis.diagnostics.events.table.duration"),
            tr("analysis.diagnostics.events.table.type"),
            tr("analysis.diagnostics.events.table.pattern"),
            tr("analysis.diagnostics.events.table.evidence"),
        ]
        lines.append(
            "| "
            + " | ".join(headers)
            + " |"
        )
        lines.append(
            "|"
            + "|".join("---" for _ in headers)
            + "|"
        )

        for row in rows:

            cells = [
                f"{row['time']:.2f} s",
                f"{row['duration']:.2f} ms",
                _table_cell(row["type"]),
                _table_cell(row["pattern"]),
                _table_cell(row["evidence"]),
            ]
            lines.append(
                "| " + " | ".join(cells) + " |"
            )

    else:

        lines.append(
            tr("analysis.diagnostics.events.empty")
        )

    lines.extend(
        [
            "",
            f"## {tr('analysis.report.limitations')}",
            "",
            tr("analysis.report.note"),
            "",
            tr("analysis.diagnostics.advice.note"),
            "",
            tr("analysis.report.generated_by"),
            "",
        ]
    )

    return "\n".join(lines)


def write_report(
    report,
    path,
    capture_name,
    target_name="",
    profile="",
):

    path = Path(path)
    suffix = path.suffix.lower()

    if suffix == ".json":

        text = build_json(
            report,
            capture_name,
            target_name,
            profile,
        )

    else:

        text = build_markdown(
            report,
            capture_name,
            target_name,
            profile,
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")

    return path
