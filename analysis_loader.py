"""Pure-Python analysis preparation for background loading.

The heavy CSV parsing, statistics, diagnostic rules and AI report summary
run here (in a worker thread).  The Qt viewer is constructed afterwards from
the returned data; widgets are still created on the main thread.
"""

from __future__ import annotations

import math

from dataclasses import dataclass, field
from pathlib import Path

import ai_insight
import capture_session
import diagnostics
import frame_stats
import frame_timebase
import network_sampler
import swap_chains

from frame_viewer import read_telemetry


@dataclass
class PreparedAnalysis:
    filename: str
    frames: list = field(default_factory=list)
    index: object = None
    selection: object = None
    target_name: str = ""
    stats: object = None
    diagnostic_report: object = None
    ai_report: dict = field(default_factory=dict)
    telemetry: object = None
    network: object = None
    network_summary: dict = field(default_factory=dict)
    session_metadata: object = None
    session_id: str = ""
    network_capture_state: str = "unknown"
    network_failure_reason: str = ""
    telemetry_session_mismatch: bool = False
    network_session_mismatch: bool = False
    network_time_aligned: bool = True
    frame_timebase_kind: str = "unknown"
    frame_alignment_quality: str = "unknown"
    network_alignment_quality: str = "unknown"


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _network_error_marker(prepared):
    if prepared.network_session_mismatch:
        return "mismatch"
    if prepared.network_capture_state in (
        "start_failed",
        "not_started",
        "time_mismatch",
    ):
        return prepared.network_capture_state
    if (
        prepared.network_capture_state == "captured"
        and not prepared.network.available
    ):
        return "missing"
    return None


def load_analysis_bundle(
    filename,
    target_fps=60,
    target_fps_explicit=False,
    language="zh_CN",
    scenario_override=None,
):
    """Load and compute everything the viewer needs except Qt widgets."""

    path = Path(filename)
    rows = swap_chains.load_csv_rows(path)
    timebase = frame_timebase.resolve_timebase(
        rows[0].keys() if rows else (),
        csv_path=path,
    )
    index = swap_chains.build_index(
        rows,
        session=str(path),
        timebase=timebase,
    )
    selection = swap_chains.recommend(index)
    frames = selection.legacy_frames()
    target_name = ""

    if frames:
        target_name = (
            (frames[0].get("row") or {}).get(
                "Application",
                "",
            )
        )

    try:
        telemetry = read_telemetry(path)
    except Exception:
        telemetry = None

    try:
        session_metadata = capture_session.read_session(path)
    except Exception:
        session_metadata = None

    try:
        network = network_sampler.read_network(path)
    except Exception:
        network = network_sampler.NetworkReadResult()

    prepared = PreparedAnalysis(
        filename=path.name,
        frames=frames,
        index=index,
        selection=selection,
        target_name=target_name,
        telemetry=telemetry,
        network=network,
        session_metadata=session_metadata,
    )
    prepared.session_id = capture_session.session_id_of(
        session_metadata
    )
    telemetry_metadata = (
        getattr(telemetry, "metadata", None) or {}
    )
    telemetry_session_id = str(
        (telemetry_metadata.get("capture") or {}).get(
            "session_id"
        )
        or ""
    )
    network_session_id = str(
        (network.metadata or {}).get("session_id") or ""
    )

    if (
        prepared.session_id
        and telemetry_session_id
        and telemetry_session_id != prepared.session_id
    ):
        prepared.telemetry_session_mismatch = True
        prepared.telemetry = None
        telemetry = None

    if (
        prepared.session_id
        and network_session_id
        and network_session_id != prepared.session_id
    ):
        prepared.network_session_mismatch = True
        prepared.network = network_sampler.NetworkReadResult(
            error="session mismatch"
        )
        network = prepared.network

    session_network = (
        (session_metadata or {}).get("data") or {}
    ).get("network") or {}

    if prepared.network_session_mismatch:
        prepared.network_capture_state = "mismatch"
    elif session_network.get("status"):
        prepared.network_capture_state = str(
            session_network.get("status")
        )
        prepared.network_failure_reason = str(
            session_network.get("reason") or ""
        )
    elif prepared.network.available:
        prepared.network_capture_state = "captured"

    prepared.network_summary = network_sampler.summarize_result(
        prepared.network
    )

    session_timebase = (
        (session_metadata or {}).get("timebase") or {}
    ).get("frame") or {}
    first_frame = frames[0] if frames else {}
    prepared.frame_timebase_kind = str(
        session_timebase.get("kind")
        or first_frame.get("timebase_kind")
        or "unknown"
    )
    frame_trusted = bool(
        session_timebase.get("absolute_mapping_trusted")
        or first_frame.get("absolute_mapping_trusted")
    )

    if prepared.frame_timebase_kind == "qpc_ms":
        prepared.frame_alignment_quality = (
            "verified_qpc"
            if frame_trusted
            else "qpc_unverified"
        )
    elif prepared.frame_timebase_kind == "relative":
        prepared.frame_alignment_quality = "capture_relative"
    else:
        prepared.frame_alignment_quality = "unknown"

    prepared.network_alignment_quality = (
        prepared.frame_alignment_quality
    )

    if prepared.network.available and frames:
        frame_times = [
            value
            for value in (
                _number(frame.get("time"))
                for frame in frames
            )
            if value is not None
        ]
        network_times = [
            value
            for value in (
                _number(sample.get("t_ms"))
                for sample in prepared.network.samples
            )
            if value is not None
        ]

        if frame_times and network_times:
            prepared.network_time_aligned = bool(
                max(network_times) >= min(frame_times)
                and min(network_times) <= max(frame_times)
            )

            if not prepared.network_time_aligned:
                prepared.network = network_sampler.NetworkReadResult(
                    error="time mismatch"
                )
                prepared.network_capture_state = "time_mismatch"
                prepared.network_alignment_quality = "time_mismatch"

        prepared.network_summary = network_sampler.summarize_result(
            prepared.network
        )

    prepared.stats = frame_stats.compute_stats(frames)

    try:
        prepared.diagnostic_report = diagnostics.analyze(
            frames,
            stats=prepared.stats,
            telemetry=prepared.telemetry,
            target_fps=target_fps,
        )
    except Exception:
        prepared.diagnostic_report = None

    prepared.ai_report = ai_insight.build_report_summary(
        frames,
        application=prepared.target_name,
        target_fps=target_fps,
        target_fps_explicit=target_fps_explicit,
        diagnostic_report=prepared.diagnostic_report,
        stats=prepared.stats,
        telemetry=prepared.telemetry,
        network=prepared.network_summary,
        network_samples=prepared.network.samples,
        network_error=_network_error_marker(prepared),
        network_alignment_quality=(
            prepared.network_alignment_quality
        ),
        scenario_override=scenario_override,
        session_status=(
            ((session_metadata or {}).get("capture") or {}).get(
                "status"
            )
            or "unknown"
        ),
        session_id=prepared.session_id,
        language=language,
        file_name=path.name,
        report_key=str(path.resolve()),
    )

    return prepared
