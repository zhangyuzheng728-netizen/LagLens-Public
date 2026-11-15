"""Evidence-driven diagnosis pipeline.

This module owns scenario detection, data-quality checks, fact extraction
and validation of structured AI answers.  It does not talk to any AI
provider and does not recalculate raw frame/network data.
"""

from __future__ import annotations

import json
import math
import re

from pathlib import Path


SCENARIOS = (
    "game",
    "video",
    "browser",
    "desktop",
    "unknown",
)

CONCLUSIONS = (
    "local_performance",
    "network",
    "both",
    "no_clear_issue",
    "insufficient_evidence",
)

STRENGTH_ORDER = {
    "insufficient_evidence": 0,
    "limited_evidence": 1,
    "moderate_evidence": 2,
    "strong_evidence": 3,
}

HARDWARE_FACT_IDS = frozenset(
    {
        "cpu_process_median",
        "system_cpu_median",
        "gpu_util_median",
        "ram_percent_median",
        "frame_cpu_busy_median",
        "frame_gpu_busy_median",
    }
)

_VIDEO_NAMES = (
    "douyin",
    "tiktok",
    "potplayer",
    "vlc",
    "mpv",
    "bilibili",
    "youtube",
    "kmplayer",
    "mpc-hc",
)

_BROWSER_NAMES = (
    "chrome",
    "msedge",
    "firefox",
    "brave",
    "opera",
    "vivaldi",
)

_GAME_NAMES = (
    "palworld",
    "steam",
    "game",
    "unity",
    "unreal",
    "-win64-shipping",
)

_DESKTOP_NAMES = (
    "explorer",
    "dwm",
    "notepad",
    "code",
    "winword",
    "excel",
    "powerpnt",
    "acrobat",
)


def detect_scenario(application, override=None):
    """Classify the application context without claiming the activity."""

    name = Path(str(application or "")).name.lower()

    if override in SCENARIOS:

        return {
            "id": override,
            "source": "user",
            "confidence": "high",
            "reason": "user selected",
        }

    if any(token in name for token in _VIDEO_NAMES):

        return {
            "id": "video",
            "source": "process_name",
            "confidence": "medium",
            "reason": "process name suggests video playback",
        }

    if any(token in name for token in _BROWSER_NAMES):

        return {
            "id": "browser",
            "source": "process_name",
            "confidence": "low",
            "reason": "browser process; current activity is unknown",
        }

    if any(token in name for token in _GAME_NAMES):

        return {
            "id": "game",
            "source": "process_name",
            "confidence": "medium",
            "reason": "process name suggests a game",
        }

    if any(token in name for token in _DESKTOP_NAMES):

        return {
            "id": "desktop",
            "source": "process_name",
            "confidence": "low",
            "reason": "desktop application; activity is unknown",
        }

    return {
        "id": "unknown",
        "source": "none",
        "confidence": "insufficient",
        "reason": "application activity is unknown",
    }


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _fact(
    fact_id,
    metric,
    value,
    unit,
    source,
    samples=None,
    start_s=None,
    end_s=None,
    time_s=None,
    window_s=None,
    valid=True,
    limit="",
):
    return {
        "id": fact_id,
        "metric": metric,
        "value": value,
        "unit": unit,
        "source": source,
        "samples": samples,
        "range_s": (
            [start_s, end_s]
            if start_s is not None or end_s is not None
            else None
        ),
        "time_s": time_s,
        "window_s": list(window_s) if window_s else None,
        "valid": bool(valid),
        "limit": limit,
    }


def _network_probe(report, name):
    network = report.get("network") or {}
    probes = network.get("probes") or {}
    return probes.get(name) or {}


def build_facts(report, scenario):
    display = report.get("display") or {}
    hardware = report.get("hardware") or {}
    network = report.get("network") or {}
    game = report.get("game_output") or {}
    classification = report.get("classification") or {}
    facts = []

    if display.get("available"):

        facts.append(
            _fact(
                "display_fps",
                "displayed_fps",
                display.get("average_fps"),
                "FPS",
                "DisplayedTime",
                display.get("frames"),
                0.0,
                display.get("seconds"),
                window_s=[
                    0.0,
                    display.get("seconds"),
                ],
                limit=(
                    "PresentMon display timing is not the source "
                    "video frame rate"
                    if scenario["id"] == "video"
                    else ""
                ),
            )
        )
        facts.append(
            _fact(
                "displayed_frames",
                "displayed_frames",
                display.get("frames"),
                "frames",
                "DisplayedTime",
                samples=display.get("frames"),
            )
        )
        facts.append(
            _fact(
                "display_p95_interval",
                "displayed_interval_p95",
                display.get("p95_interval_ms"),
                "ms",
                "DisplayedTime",
                samples=display.get("frames"),
            )
        )
        facts.append(
            _fact(
                "display_p99_interval",
                "displayed_interval_p99",
                display.get("p99_interval_ms"),
                "ms",
                "DisplayedTime",
                samples=display.get("frames"),
            )
        )
        facts.append(
            _fact(
                "longest_display_stall",
                "longest_display_stall",
                display.get("longest_stall_s"),
                "s",
                "DisplayedTime",
                None,
                display.get("longest_stall_at_s"),
                display.get("longest_stall_at_s"),
                time_s=display.get("longest_stall_at_s"),
                limit="display interval, not necessarily a playback hiccup",
            )
        )
        events = report.get("events") or {}

        if events.get("count"):

            facts.append(
                _fact(
                    "abnormal_frame_events",
                    "abnormal_frame_events",
                    events.get("count"),
                    "",
                    "diagnostics",
                    samples=events.get("count"),
                    limit=(
                        "merged recorded display intervals; "
                        "not necessarily visible freezes"
                    ),
                )
            )

        if events.get("over_1s"):

            facts.append(
                _fact(
                    "stalls_over_1s",
                    "stalls_over_1s",
                    events.get("over_1s"),
                    "",
                    "diagnostics",
                    samples=events.get("over_1s"),
                    limit=(
                        "recorded display intervals of at least 1 s; "
                        "not necessarily visible freezes"
                    ),
                )
            )
        facts.append(
            _fact(
                "display_interval_median",
                "displayed_interval_median",
                display.get("median_interval_ms"),
                "ms",
                "DisplayedTime",
                display.get("frames"),
            )
        )
    else:

        facts.append(
            _fact(
                "display_fps",
                "displayed_fps",
                None,
                "FPS",
                "DisplayedTime",
                valid=False,
                limit="no valid DisplayedTime",
            )
        )

    quality = report.get("quality") or {}
    aligned = quality.get("telemetry_aligned")

    if aligned is True:

        alignment_value = "aligned"

    elif aligned is False:

        alignment_value = "unverified"

    else:

        alignment_value = "unknown"

    facts.append(
        _fact(
            "telemetry_alignment",
            "telemetry_alignment",
            alignment_value,
            "",
            "diagnostics",
            limit=(
                "hardware samples exist but the frame timebase "
                "is untrusted; do not align events or blame CPU/GPU"
                if alignment_value == "unverified"
                else ""
            ),
        )
    )

    target = report.get("target_fps")
    source = report.get("target_source", "unknown")

    facts.append(
        _fact(
            "target_fps",
            "target_fps",
            target,
            "FPS",
            source,
            valid=target is not None,
            limit=(
                ""
                if target is not None
                else "target FPS is unknown"
            ),
        )
    )

    if game.get("average_fps") is not None:

        facts.append(
            _fact(
                "game_output_fps",
                "game_output_fps",
                game.get("average_fps"),
                "FPS",
                "FrameTime",
                limit="CPU frame interval estimate, not display FPS",
            )
        )

    if scenario["id"] == "video":

        facts.append(
            _fact(
                "video_source_fps",
                "video_source_fps",
                None,
                "FPS",
                "not measured",
                valid=False,
                limit=(
                    "video source FPS is unknown; do not infer "
                    "video dropped frames from PresentMon"
                ),
            )
        )

    for fact_id, metric, key, unit, source_name, limit in (
        (
            "cpu_process_median",
            "target_process_cpu_median",
            "target_cpu_median",
            "%",
            "hardware_telemetry",
            "process-level CPU, not per-core load",
        ),
        (
            "system_cpu_median",
            "system_cpu_median",
            "system_cpu_median",
            "%",
            "hardware_telemetry",
            "system-level CPU",
        ),
        (
            "gpu_util_median",
            "gpu_utilization_median",
            "gpu_util_median",
            "%",
            "hardware_telemetry",
            "device/system utilization, not proof of bottleneck",
        ),
        (
            "ram_percent_median",
            "ram_percent_median",
            "ram_percent_median",
            "%",
            "hardware_telemetry",
            "system-level memory",
        ),
        (
            "frame_cpu_busy_median",
            "frame_cpu_busy_median",
            "frame_cpu_busy_median_ms",
            "ms",
            "presentmon_frame",
            "per-frame CPU work, not system CPU utilization",
        ),
        (
            "frame_gpu_busy_median",
            "frame_gpu_busy_median",
            "frame_gpu_busy_median_ms",
            "ms",
            "presentmon_frame",
            "per-frame GPU work, not GPU utilization",
        ),
    ):

        value = hardware.get(key)

        facts.append(
            _fact(
                fact_id,
                metric,
                value,
                unit,
                source_name,
                hardware.get("samples"),
                valid=value is not None,
                limit=(
                    limit
                    if value is not None
                    else "not captured in this session"
                ),
            )
        )

    if not hardware.get("aligned", False):

        facts.append(
            _fact(
                "hardware_alignment",
                "hardware_alignment",
                None,
                "",
                "hardware_telemetry",
                valid=False,
                limit="telemetry and frame time alignment unverified",
            )
        )

    for name, label in (
        ("gateway", "gateway"),
        ("public", "public"),
    ):

        probe = _network_probe(report, name)
        samples = int(probe.get("samples", 0) or 0)
        responses = int(probe.get("responses", 0) or 0)
        timeouts = int(probe.get("timeouts", 0) or 0)
        probe_window = probe.get("range_s")

        facts.append(
            _fact(
                f"network_{label}_samples",
                f"{label}_probe_samples",
                samples if samples else None,
                "samples",
                "network_sidecar",
                samples if samples else None,
                window_s=probe_window,
                valid=bool(samples),
                limit="" if samples else "no network samples",
            )
        )
        facts.append(
            _fact(
                f"network_{label}_timeouts",
                f"{label}_probe_timeouts",
                timeouts if samples else None,
                "timeouts",
                "network_sidecar",
                samples if samples else None,
                window_s=probe_window,
                valid=bool(samples),
                limit=(
                    ""
                    if samples
                    else "total probe count unknown"
                ),
            )
        )
        facts.append(
            _fact(
                f"network_{label}_responses",
                f"{label}_valid_responses",
                responses if samples else None,
                "responses",
                "network_sidecar",
                samples if samples else None,
                window_s=probe_window,
                valid=bool(samples),
                limit="" if samples else "no valid probe reply",
            )
        )
        facts.append(
            _fact(
                f"network_{label}_timeout_rate",
                f"{label}_probe_timeout_rate",
                (
                    round(timeouts / samples, 4)
                    if samples
                    else None
                ),
                "ratio",
                "network_sidecar",
                samples if samples else None,
                window_s=probe_window,
                valid=bool(samples),
                limit=(
                    ""
                    if samples
                    else "total probe count unknown; do not judge rate"
                ),
            )
        )

    alignment_value = (
        (report.get("network") or {}).get("alignment_quality")
        or report.get("alignment_quality")
        or "unknown"
    )
    network_available = bool(
        (report.get("network") or {}).get("available")
    )
    alignment_limit = (
        "millisecond causal claims are not supported; "
        "verified_qpc does not mean the network is normal"
    )

    if not network_available:

        alignment_limit += "; no network samples were collected"

    facts.append(
        _fact(
            "network_available",
            "network_measurement_available",
            "available" if network_available else "unavailable",
            "",
            "network_sidecar",
            limit=(
                ""
                if network_available
                else "no network probes; do not judge the network"
            ),
        )
    )
    facts.append(
        _fact(
            "network_alignment",
            "network_frame_alignment",
            alignment_value,
            "",
            "session_timebase",
            valid=alignment_value in (
                "verified_qpc",
                "capture_relative",
            ),
            limit=alignment_limit,
        )
    )
    facts.append(
        _fact(
            "timebase_quality",
            "frame_timebase_quality",
            (report.get("quality") or {}).get(
                "sync_quality",
                "unknown",
            ),
            "",
            "session_metadata",
        )
    )
    session_status = str(
        report.get("session_status", "unknown") or "unknown"
    )
    facts.append(
        _fact(
            "session_status",
            "session_status",
            session_status,
            "",
            "session_metadata",
            limit=(
                "session metadata missing or status unknown; "
                "unknown is not success"
                if session_status == "unknown"
                else ""
            ),
        )
    )
    facts.append(
        _fact(
            "evidence_window_count",
            "evidence_window_count",
            len((report.get("joint") or {}).get("evidence") or []),
            "windows",
            "local_pipeline",
        )
    )

    return facts


def _quality_checks(report, facts):
    display = report.get("display") or {}
    hardware = report.get("hardware") or {}
    checks = []
    missing = []

    duration = _number(display.get("seconds"))
    frames = int(display.get("frames", 0) or 0)
    telemetry_samples = int(hardware.get("samples", 0) or 0)
    network_samples = sum(
        int(_network_probe(report, p).get("samples", 0) or 0)
        for p in ("gateway", "public")
    )
    network_responses = sum(
        int(_network_probe(report, p).get("responses", 0) or 0)
        for p in ("gateway", "public")
    )
    network_status = (report.get("joint") or {}).get(
        "network_status",
        "unknown",
    )

    def check(name, ok, detail, required=True):
        checks.append(
            {
                "name": name,
                "status": "ok" if ok else "missing",
                "detail": detail,
                "required": required,
            }
        )
        if not ok and required:
            missing.append(name)

    check(
        "duration",
        duration is not None and duration >= 5.0,
        f"{duration or 0:.1f}s",
    )
    check(
        "display_samples",
        frames >= 30,
        f"{frames} frames",
    )
    check(
        "telemetry_samples",
        telemetry_samples >= 3,
        f"{telemetry_samples} samples",
        required=False,
    )
    check(
        "network_samples",
        network_samples > 0,
        f"{network_samples} target samples",
        required=False,
    )
    check(
        "network_replies",
        network_responses > 0,
        f"{network_responses} valid replies",
        required=False,
    )
    check(
        "network_status",
        network_status not in ("unmeasured", "start_failed"),
        str(network_status),
        required=False,
    )
    check(
        "timebase",
        (report.get("quality") or {}).get("sync_quality")
        in ("verified_qpc", "exact_relative"),
        str(
            (report.get("quality") or {}).get(
                "sync_quality",
                "unknown",
            )
        ),
        required=False,
    )

    if network_samples:

        for name in ("gateway", "public"):

            probe = _network_probe(report, name)
            samples = int(probe.get("samples", 0) or 0)
            timeouts = int(probe.get("timeouts", 0) or 0)
            checks.append(
                {
                    "name": f"{name}_timeout_rate",
                    "status": "ok" if samples else "unknown",
                    "detail": (
                        f"{timeouts}/{samples} "
                        f"({timeouts / samples:.1%})"
                        if samples
                        else "total unknown"
                    ),
                    "required": False,
                }
            )

    if missing:
        status = "limited"
    else:
        status = "ok"

    if (
        (duration is not None and duration < 3.0)
        or frames < 10
        or not display.get("available")
    ):
        status = "insufficient"

    return {
        "status": status,
        "checks": checks,
        "missing": missing,
    }


def _strength(report, quality, scenario):
    if quality["status"] == "insufficient":
        return "insufficient_evidence"

    network_status = (report.get("joint") or {}).get(
        "network_status",
        "unknown",
    )
    timebase = (report.get("quality") or {}).get(
        "sync_quality",
        "unknown",
    )
    hardware = report.get("hardware") or {}

    if timebase == "untrusted":
        return "insufficient_evidence"

    if (
        quality["status"] == "limited"
        or scenario["id"] == "unknown"
        or network_status in ("unmeasured", "start_failed")
        or not hardware.get("available")
    ):
        return "limited_evidence"

    if (
        timebase in ("verified_qpc", "exact_relative")
        and hardware.get("aligned")
        and network_status in ("stable", "fluctuating")
    ):
        return "moderate_evidence"

    return "limited_evidence"


def build_diagnosis(report, scenario_override=None):
    scenario = detect_scenario(
        report.get("application", ""),
        scenario_override,
    )
    facts = build_facts(report, scenario)
    quality = _quality_checks(report, facts)
    strength = _strength(report, quality, scenario)
    allowed = list(CONCLUSIONS)

    if scenario["id"] in ("video", "browser", "unknown"):

        allowed = [
            value for value in allowed
            if value != "local_performance"
        ]

    if not (report.get("network") or {}).get("available"):

        allowed = [
            value for value in allowed
            if value not in ("network", "both")
        ]

    return {
        "scenario": scenario,
        "quality": quality,
        "evidence_strength": strength,
        "allowed_conclusions": allowed,
        "facts": facts,
    }


_STRUCTURED_SCHEMA = (
    '{"conclusion":"...",'
    '"evidence_strength":"...",'
    '"observations":[{"fact_id":"...","text":"..."}],'
    '"hypotheses":[{"text":"...","fact_ids":["..."],'
    '"alternative":"...","confidence":"likely|possible|unclear"}],'
    '"missing_evidence":["..."],'
    '"recommended_actions":[{"text":"...","risk":"low",'
    '"verification":"..."}]}'
)


def structured_prompt():
    return (
        "只输出 JSON，不要 Markdown。"
        "先判断有无异常，再判断原因；无异常用 no_clear_issue，"
        "数据不足用 insufficient_evidence，不预设有问题。"
        "只使用报告事实 ID，不编造事实或数值。"
        "fact_id 只写冒号前的 ID（如 display_fps），不带数字或等号；"
        "数字必须与引用事实同一行一致，不要互换相邻事实的值。"
        "conclusion：local_performance|network|both|no_clear_issue|"
        "insufficient_evidence。"
        "evidence_strength：strong_evidence|moderate_evidence|"
        "limited_evidence|insufficient_evidence，不得高于本地上限。"
        "observations 只写事实；原因只放 hypotheses 并标注 "
        "likely/possible/unclear；异常≠已证实原因。"
        "不要因用户二选一就强行二选一。"
        "视频/浏览器不得仅凭 FPS 或一次长间隔认定卡顿/性能不足；"
        "只有长间隔时用 no_clear_issue 或 insufficient_evidence，"
        "observation 只写停顿。"
        "无网络数据时不得说网络正常或不是主因；"
        "verified_qpc 仅代表帧时间可信，不代表网络正常。"
        "只有帧时间异常且无 CPU/GPU 遥测时不得判硬件瓶颈。"
        "网络探测是秒级采样，不得写成毫秒级因果。"
        "建议最多一个，基于事实且可验证；"
        "无明确问题就说无需优化，不要编造问题。\n"
        + _STRUCTURED_SCHEMA
    )


def repair_prompt():
    """Compact prompt for one bounded repair request."""

    return (
        "只返回修正后的 JSON，不要 Markdown 或解释。"
        "只使用报告事实 ID，不编造数值。"
        "fact_id 只写事实列表冒号前的 ID（如 display_fps），"
        "不要带数字或等号；数字必须与所引用事实同一行一致，"
        "不要把相邻事实的值互换。"
        "无异常用 no_clear_issue，数据不足用 insufficient_evidence。"
        "conclusion/evidence_strength 必须使用给定枚举，"
        "证据强度不得高于本地上限。"
        "observations 只写事实；原因只放 hypotheses，标注 "
        "likely/possible/unclear。"
        "浏览器只有一次长显示间隔时用 no_clear_issue 或 "
        "insufficient_evidence，不要写卡顿/性能不足；"
        "observation 只写显示停顿。"
        "无网络数据不得说网络正常；无 CPU/GPU 遥测不得认定硬件瓶颈。"
        "建议最多一个，无明确问题就说无需优化。\n"
        + _STRUCTURED_SCHEMA
    )


def parse_structured(text):
    if not isinstance(text, str):
        return None
    cleaned = text.strip()
    cleaned = re.sub(
        r"^```(?:json)?\s*|\s*```$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        value = json.loads(cleaned[start : end + 1])
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def normalize_structured_ids(value, diagnosis):
    """Repair fact-ID syntax without touching numbers or claims.

    Models sometimes copy ``display_fps=67.76FPS`` as the whole fact ID.  The
    value is still checked against the fact after the ID is reduced to
    ``display_fps``; this is a format repair, not a validation relaxation.
    """

    if not isinstance(value, dict):
        return value, []

    fact_ids = {
        str(fact.get("id"))
        for fact in diagnosis.get("facts", ())
    }
    repairs = []

    def clean(raw):
        text = str(raw or "").strip()

        if text in fact_ids:
            return text

        for separator in (
            "=",
            "：",
            ":",
            "（",
            "(",
            " ",
            "\t",
        ):

            if separator in text:

                prefix = text.split(separator, 1)[0].strip()

                if prefix in fact_ids:
                    return prefix

        return text

    normalized = json.loads(
        json.dumps(value, ensure_ascii=False)
    )
    observations = normalized.get("observations")

    if isinstance(observations, list):

        for observation in observations:

            if not isinstance(observation, dict):
                continue

            if "fact_id" not in observation:
                continue

            old = observation.get("fact_id")
            new = clean(old)

            if new != old:

                observation["fact_id"] = new
                repairs.append(
                    {
                        "field": "observation.fact_id",
                        "from": str(old)[:80],
                        "to": new,
                    }
                )

    hypotheses = normalized.get("hypotheses")

    if isinstance(hypotheses, list):

        for hypothesis in hypotheses:

            if not isinstance(hypothesis, dict):
                continue

            ids = hypothesis.get("fact_ids")

            if not isinstance(ids, list):
                continue

            cleaned_ids = []

            for old in ids:

                new = clean(old)
                cleaned_ids.append(new)

                if new != old:

                    repairs.append(
                        {
                            "field": "hypothesis.fact_ids",
                            "from": str(old)[:80],
                            "to": new,
                        }
                    )

            hypothesis["fact_ids"] = cleaned_ids

    return normalized, repairs


def validate_structured(value, diagnosis, report):
    errors = []
    if not isinstance(value, dict):
        return ["response is not a JSON object"]

    conclusion = value.get("conclusion")
    strength = value.get("evidence_strength")
    if conclusion not in CONCLUSIONS:
        errors.append("invalid conclusion")
    elif conclusion not in diagnosis.get(
        "allowed_conclusions",
        (),
    ):
        errors.append("conclusion not supported by available scenario/data")
    if strength not in STRENGTH_ORDER:
        errors.append("invalid evidence_strength")
    elif (
        STRENGTH_ORDER[strength]
        > STRENGTH_ORDER[diagnosis["evidence_strength"]]
    ):
        errors.append("evidence_strength exceeds local limit")

    facts = {
        fact["id"]: fact
        for fact in diagnosis.get("facts", ())
    }
    observations = value.get("observations")
    hypotheses = value.get("hypotheses")
    missing = value.get("missing_evidence")
    actions = value.get("recommended_actions")

    if not isinstance(observations, list):
        errors.append("observations must be a list")
        observations = []
    if not isinstance(hypotheses, list):
        errors.append("hypotheses must be a list")
        hypotheses = []
    if not isinstance(missing, list):
        errors.append("missing_evidence must be a list")
        missing = []
    if not isinstance(actions, list):
        errors.append("recommended_actions must be a list")
        actions = []
    if len(actions) > 1:
        errors.append("at most one recommended action is allowed")

    for action in actions:
        if not isinstance(action, dict):
            errors.append("recommended_action must be an object")
        elif not str(action.get("text") or "").strip():
            errors.append("recommended_action text is empty")

    for observation in observations:
        if not isinstance(observation, dict):
            errors.append("observation must be an object")
            continue
        fact_id = observation.get("fact_id")
        if fact_id not in facts:
            errors.append(f"unknown fact_id: {fact_id}")
            continue
        if facts[fact_id].get("valid") is False:
            errors.append(
                f"observation cites invalid fact: {fact_id}"
            )
        observation_text = str(
            observation.get("text", "")
        )
        observation_claims = any(
            token in observation_text
            for token in (
                "掉帧",
                "卡顿",
                "性能不足",
                "性能问题",
                "瓶颈",
            )
        )
        if (
            diagnosis["scenario"]["id"] in ("video", "browser", "unknown")
            and observation_claims
        ):
            errors.append(
                "video/browser/unknown observation claims a performance "
                "problem without source evidence"
            )

    for hypothesis in hypotheses:
        if not isinstance(hypothesis, dict):
            errors.append("hypothesis must be an object")
            continue
        ids = hypothesis.get("fact_ids") or []
        if not isinstance(ids, list):
            errors.append("hypothesis fact_ids must be a list")
            continue
        if not ids:
            errors.append("hypothesis has no supporting fact IDs")
        if hypothesis.get("confidence") not in (
            "likely",
            "possible",
            "unclear",
        ):
            errors.append("invalid hypothesis confidence")
        for fact_id in ids:
            if fact_id not in facts:
                errors.append(f"unknown hypothesis fact_id: {fact_id}")
            elif facts[fact_id].get("valid") is False:
                errors.append(
                    f"hypothesis cites invalid fact: {fact_id}"
                )
        text = str(hypothesis.get("text", "")).lower()
        claims_problem = any(
            token in text
            for token in (
                "掉帧",
                "卡顿",
                "性能不足",
                "性能问题",
                "瓶颈",
                "带不动",
            )
        )
        if (
            diagnosis["scenario"]["id"] in ("video", "browser", "unknown")
            and claims_problem
            and "video_source_fps" not in ids
        ):
            errors.append(
                "video/browser/unknown scenario claims a performance "
                "problem without source evidence"
            )
        alignment = facts.get("network_alignment", {}).get(
            "value"
        )
        network_measured = (
            facts.get("network_available", {}).get("value")
            == "available"
        )
        if (
            any(
                token in text
                for token in ("同时", "重合", "一起")
            )
            and any(
                str(fid).startswith("network_")
                for fid in ids
            )
            and (
                alignment not in (
                    "verified_qpc",
                    "capture_relative",
                )
                or not network_measured
            )
        ):
            errors.append(
                "network/frame correlation claimed without verified "
                "alignment and network data"
            )

        mentions_hardware = any(
            token in text
            for token in (
                "cpu",
                "gpu",
                "显卡",
                "处理器",
                "显存",
                "内存",
            )
        )
        claims_hardware_cause = any(
            token in text
            for token in (
                "瓶颈",
                "不足",
                "过高",
                "过热",
                "降频",
                "满载",
                "占满",
            )
        )
        if mentions_hardware and claims_hardware_cause:
            has_hardware_evidence = any(
                fact_id in HARDWARE_FACT_IDS
                and fact_id in facts
                and facts[fact_id].get("valid") is not False
                for fact_id in ids
            )
            if not has_hardware_evidence:
                errors.append(
                    "hardware bottleneck claim without valid "
                    "hardware evidence"
                )

    cited_fact_ids = set()

    for observation in observations:
        if (
            isinstance(observation, dict)
            and observation.get("fact_id") in facts
        ):
            cited_fact_ids.add(observation["fact_id"])

    for hypothesis in hypotheses:
        if isinstance(hypothesis, dict):
            for fact_id in hypothesis.get("fact_ids") or []:
                if fact_id in facts:
                    cited_fact_ids.add(fact_id)

    if actions and not cited_fact_ids and not missing:
        errors.append(
            "recommended action has no supporting evidence"
        )

    # Numeric observations must be traceable to the cited fact.
    #
    # A fact can expose several labelled numbers: its main value, an event
    # time (``time_s``) and a capture/sample window (``window_s``).  This
    # matters for a stall fact: "at 11 s there was a 5.695 s stall" cites the
    # stall fact but mentions its timestamp, not its duration.  Only the
    # cited fact's own numbers are accepted, so this does not relax the check
    # for arbitrary numbers.
    unit_pattern = re.compile(
        r"(\d+(?:\.\d+)?)\s*(ms|%|秒|s|FPS)"
    )

    def converted(number, text_unit, fact_unit):
        """Convert to the target unit, or return None when incompatible."""

        text_unit = (text_unit or "").lower()
        fact_unit = str(fact_unit or "").lower()

        if text_unit == "%" and fact_unit == "ratio":
            return number / 100.0

        if text_unit == "ms" and fact_unit == "s":
            return number / 1000.0

        if text_unit in ("s", "秒") and fact_unit == "ms":
            return number * 1000.0

        if text_unit in ("s", "秒") and fact_unit == "s":
            return number

        if text_unit == "ms" and fact_unit == "ms":
            return number

        if text_unit == "%" and fact_unit == "%":
            return number

        if text_unit == "fps" and fact_unit == "fps":
            return number

        return None

    def fact_numbers(fact):
        """Yield (label, value, unit) for the cited fact's own numbers."""

        value = _number(fact.get("value"))

        if value is not None:
            yield "value", value, fact.get("unit") or ""

        event_time = _number(fact.get("time_s"))

        if event_time is not None:
            yield "time_s", event_time, "s"

        window = fact.get("window_s")

        if isinstance(window, (list, tuple)) and len(window) == 2:

            for index, endpoint in enumerate(window):

                endpoint_value = _number(endpoint)

                if endpoint_value is not None:
                    yield f"window_{index}", endpoint_value, "s"

    for observation in observations:
        if not isinstance(observation, dict):
            continue
        text = str(observation.get("text", ""))
        fact_id = observation.get("fact_id")
        fact = facts.get(fact_id) or {}
        candidates = list(fact_numbers(fact))

        if not candidates:
            continue

        for match in unit_pattern.finditer(text):
            number = _number(match.group(1))

            if number is None:
                continue

            matched = False

            for _label, candidate, unit in candidates:

                converted_number = converted(
                    number,
                    match.group(2),
                    unit,
                )

                if converted_number is None:
                    continue

                if abs(converted_number - candidate) <= max(
                    0.2,
                    abs(candidate) * 0.05,
                ):
                    matched = True
                    break

            if not matched:
                errors.append(
                    "observation number does not match its fact "
                    f"{fact_id}: {match.group(0)}"
                )

    text_all = json.dumps(value, ensure_ascii=False)
    for forbidden in (
        "注册表",
        "超频",
        "关闭系统安全",
        "禁用服务",
    ):
        if forbidden in text_all:
            errors.append(f"unsafe recommendation: {forbidden}")

    network_available = bool(
        (report.get("network") or {}).get("available")
    )

    if not network_available and any(
        token in text_all
        for token in (
            "网络正常",
            "网络没问题",
            "网络良好",
            "网络稳定",
            "网络未见异常",
            "网络没有异常",
            "排除网络",
            "不是网络",
            "网络不是主要原因",
            "网络不是主因",
        )
    ):
        errors.append("network claim without network data")

    return errors


_SUMMARY_LABELS = {
    "zh_CN": {
        "conclusion": "结论",
        "strength": "证据强度",
        "observations": "观察",
        "hypotheses": "可能原因",
        "missing": "无法确定",
        "actions": "建议",
        "basis": "依据",
        "fallback": (
            "AI 回答未通过本地事实校验，以下只展示采集到的事实；"
            "未通过校验的内容不会作为结论。"
        ),
        "scenario": "场景",
        "quality": "数据质量",
        "facts": "事实",
        "reason": "提示",
        "conclusions": {
            "local_performance": "本机性能",
            "network": "网络",
            "both": "本机与网络",
            "no_clear_issue": "没有明显问题",
            "insufficient_evidence": "证据不足",
        },
        "strengths": {
            "strong_evidence": "强证据",
            "moderate_evidence": "中等证据",
            "limited_evidence": "有限证据",
            "insufficient_evidence": "证据不足",
        },
    },
    "en": {
        "conclusion": "Conclusion",
        "strength": "Evidence strength",
        "observations": "Observations",
        "hypotheses": "Possible causes",
        "missing": "Not determined",
        "actions": "Next step",
        "basis": "basis",
        "fallback": (
            "The AI answer failed local fact validation. Only measured "
            "facts are shown; unchecked content is not presented as a "
            "conclusion."
        ),
        "scenario": "Scenario",
        "quality": "Data quality",
        "facts": "Facts",
        "reason": "Note",
        "conclusions": {
            "local_performance": "Local performance",
            "network": "Network",
            "both": "Local and network",
            "no_clear_issue": "No clear issue",
            "insufficient_evidence": "Insufficient evidence",
        },
        "strengths": {
            "strong_evidence": "Strong evidence",
            "moderate_evidence": "Moderate evidence",
            "limited_evidence": "Limited evidence",
            "insufficient_evidence": "Insufficient evidence",
        },
    },
}


def _labels(language):
    return _SUMMARY_LABELS.get(language, _SUMMARY_LABELS["zh_CN"])


def _enum_label(value, table, language):
    text = table.get(str(value), "")

    if not text:
        return str(value)

    if language == "zh_CN":
        return f"{value}（{text}）"

    return f"{value} ({text})"


def structured_summary(value, language="zh_CN"):
    """Convert a validated structure to readable chat text."""

    if not value:
        return ""

    labels = _labels(language)
    sep = "：" if language == "zh_CN" else ": "
    conclusion = _enum_label(
        value.get("conclusion", ""),
        labels["conclusions"],
        language,
    )
    strength = _enum_label(
        value.get("evidence_strength", ""),
        labels["strengths"],
        language,
    )
    lines = [
        f"{labels['conclusion']}{sep}{conclusion}",
        f"{labels['strength']}{sep}{strength}",
    ]
    observations = value.get("observations") or []
    if observations:
        lines.append(f"{labels['observations']}{sep}")
        for item in observations:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"- [{item.get('fact_id')}] {item.get('text', '')}"
            )
    hypotheses = value.get("hypotheses") or []
    if hypotheses:
        lines.append(f"{labels['hypotheses']}{sep}")
        for item in hypotheses:
            if not isinstance(item, dict):
                continue
            basis = ", ".join(item.get("fact_ids") or [])
            lines.append(
                f"- {item.get('text', '')} "
                f"({labels['basis']}: {basis})"
            )
    missing = value.get("missing_evidence") or []
    if missing:
        lines.append(f"{labels['missing']}{sep}")
        for item in missing:
            lines.append(f"- {item}")
    actions = value.get("recommended_actions") or []
    if actions:
        lines.append(f"{labels['actions']}{sep}")
        for item in actions:
            if not isinstance(item, dict):
                continue
            lines.append(f"- {item.get('text', '')}")
    return "\n".join(lines)


def _friendly_error(error, language):
    """Map an internal validation error to a user-facing note."""

    text = str(error)
    zh = language == "zh_CN"

    if "does not match its fact" in text:
        return (
            "AI 引用的数字与本地事实不一致，已忽略该表述。"
            if zh
            else "The AI quoted a number that does not match the "
            "measured fact; that statement was ignored."
        )

    if "unknown fact_id" in text or "unknown hypothesis fact_id" in text:
        return (
            "AI 引用了不存在的事实 ID。"
            if zh
            else "The AI cited a fact ID that does not exist."
        )

    if "conclusion not supported" in text:
        return (
            "AI 的结论超出当前场景和数据允许的范围。"
            if zh
            else "The AI conclusion is outside what this scenario and "
            "data allow."
        )

    if "evidence_strength exceeds" in text:
        return (
            "AI 给出的证据强度高于本地数据支持的上限。"
            if zh
            else "The AI claimed stronger evidence than the local data "
            "supports."
        )

    if "hardware bottleneck claim" in text:
        return (
            "缺少有效硬件遥测，不能认定 CPU/GPU 瓶颈。"
            if zh
            else "A CPU/GPU bottleneck cannot be claimed without valid "
            "hardware telemetry."
        )

    if "network claim without network data" in text:
        return (
            "本次没有网络数据，不能评价网络正常或异常。"
            if zh
            else "No network data was captured, so the network cannot be "
            "called normal or abnormal."
        )

    if "network/frame correlation" in text:
        return (
            "网络与帧时间的对齐未验证，不能声称两者同时发生。"
            if zh
            else "Network/frame alignment is unverified, so simultaneous "
            "occurrence cannot be claimed."
        )

    if "recommended action has no supporting evidence" in text:
        return (
            "优化建议缺少事实依据，已忽略。"
            if zh
            else "The advice had no supporting evidence and was ignored."
        )

    if "performance problem without source evidence" in text:
        return (
            "当前场景的证据不足以判断为卡顿或性能不足。"
            if zh
            else "The current scenario does not support a stutter or "
            "performance conclusion."
        )

    if "invalid hypothesis confidence" in text:
        return (
            "AI 把未证实的原因标成了确定结论。"
            if zh
            else "The AI labelled an unproven cause as certain."
        )

    if "unsafe recommendation" in text:
        return (
            "AI 给出了不安全或高风险的建议，已忽略。"
            if zh
            else "The AI gave an unsafe or high-risk recommendation; it "
            "was ignored."
        )

    return (
        "AI 回答不符合结构化事实要求。"
        if zh
        else "The AI answer did not meet the structured fact requirements."
    )


def fallback_text(diagnosis, reason="", language="zh_CN"):
    labels = _labels(language)
    sep = "：" if language == "zh_CN" else ": "
    facts = diagnosis.get("facts", ())
    lines = [
        labels["fallback"],
        f"{labels['scenario']}{sep}"
        f"{diagnosis.get('scenario', {}).get('id', 'unknown')}",
        f"{labels['quality']}{sep}"
        f"{diagnosis.get('quality', {}).get('status', 'unknown')}",
        f"{labels['facts']}{sep}",
    ]
    for fact in facts:
        if fact.get("value") is None:
            continue
        lines.append(
            f"- {fact['id']}: {fact['value']}{fact.get('unit', '')}"
        )
    friendly = []

    for error in str(reason or "").split("；"):

        if not error.strip():
            continue

        text = _friendly_error(error, language)

        if text not in friendly:
            friendly.append(text)

    if friendly:
        lines.append(
            f"{labels['reason']}{sep}" + "；".join(friendly[:3])
        )

    return "\n".join(lines)
