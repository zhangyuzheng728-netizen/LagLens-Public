"""Swap-chain discovery and selection for LagLens.

The CSV produced by PresentMon can contain frames from several swap
chains, either because an application recreated its chain (sequential
activity) or because several windows presented at the same time
(concurrent activity).  Mixing concurrent chains would corrupt frame
statistics, while ignoring recreated chains silently drops data.

This module keeps the original rows, groups them by process and swap
chain, detects sequential vs concurrent activity, and produces a
deterministic recommendation with a human-readable explanation.  It
never modifies or discards the original CSV records; a caller can
select any chain or valid sequential group explicitly.

Heuristics (all documented and deterministic)
---------------------------------------------

* A chain is identified by ``(Application, ProcessID,
  SwapChainAddress)``.  A missing or zero-like identifier is scored
  lower but is never hidden.
* A chain is split into segments when consecutive frames are more than
  ``SEGMENT_SPLIT_GAP_MS`` apart.  This keeps a reused address
  distinguishable for manual selection.  Long gaps do **not** split
  the analysis groups: a paused game is still the same chain.
* Coverage means activity coverage, not first-to-last span: the
  capture is divided into one-second buckets and coverage is the
  fraction of buckets in which the chain actually produced frames.
  Two frames sixty seconds apart therefore have very low coverage.
* Chains are merged only when their active intervals never overlap by
  more than ``OVERLAP_TOLERANCE_MS``.  When overlaps exist, the
  algorithm also builds one maximal non-overlapping set (interval
  scheduling), so an auxiliary overlay that overlaps two sequential
  main chains does not prevent those main chains from being merged.
* Automatic selection scores candidate groups with:

      score = 0.45 * activity coverage
            + 0.30 * active at the end of the capture
            + 0.15 * share of captured frames
            + 0.10 * reliable identifier

  Frame count alone is never the deciding factor.
* Confidence is based on the score margin only.  An unreliable
  identifier lowers the score by at most 0.10 and can never produce a
  high-confidence result on its own; when the best candidate is
  unreliable the confidence is always ``low``.
* If the best two candidates are within ``AMBIGUITY_MARGIN`` the result
  is explicitly marked ``uncertain``.
* Manual overrides can target a whole address or a specific
  ``(address, segment)`` pair, so a reused address is unambiguous.
"""

from __future__ import annotations

import csv
import math

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import frame_timebase


REQUIRED_COLUMNS = frozenset(
    {
        "Application",
        "ProcessID",
        "SwapChainAddress",
        "FrameTime",
    }
)

# Split a reused address into separate segments after this gap.
SEGMENT_SPLIT_GAP_MS = 5000.0

# Activity is measured in one-second buckets.
ACTIVITY_BUCKET_MS = 1000.0

# Small overlaps are normal when a chain is recreated.
OVERLAP_TOLERANCE_MS = 250.0

# "Active at the end" means the last frame is within this window of
# the end of the capture.
TAIL_WINDOW_MS = 2000.0

AMBIGUITY_MARGIN = 0.10
HIGH_CONFIDENCE_MARGIN = 0.25

SCORE_WEIGHTS = {
    "coverage": 0.45,
    "tail": 0.30,
    "share": 0.15,
    "reliable": 0.10,
}


def identifier_is_reliable(value):
    """True when a SwapChainAddress looks like a real address."""

    text = (value or "").strip().lower()

    if text in {"", "na", "none", "0"}:

        return False

    if text.startswith("0x"):

        digits = text[2:]

        if digits and set(digits) <= set("0"):

            return False

    return True


def process_is_reliable(process_id):

    return (process_id or "").strip() not in {
        "",
        "?",
        "0",
    }


@dataclass(frozen=True)
class FrameRecord:
    """One original PresentMon row plus its parsed frame values."""

    index: int
    application: str
    process_id: str
    swap_chain: str
    time_ms: float
    frame_time_ms: float
    displayed: bool
    row: dict
    raw_time_ms: float | None = None
    timebase: frame_timebase.FrameTimebase | None = None

    def as_legacy(self):
        """Shape used by frame_viewer / frame_stats.

        ``time`` stays capture-relative for existing statistics and
        charts.  ``raw_time`` and the timebase fields are additive and
        preserve the original CSV timestamp for later diagnostics.
        """

        base = self.timebase or frame_timebase.unknown_timebase()

        return {
            "time": self.time_ms,
            "raw_time": self.raw_time_ms,
            "time_column": base.raw_column,
            "timebase_kind": base.kind,
            "sync_quality": base.sync_quality,
            "absolute_mapping_trusted": (
                base.absolute_mapping_trusted
            ),
            "duration": self.frame_time_ms,
            "displayed": self.displayed,
            "row": self.row,
        }


@dataclass(frozen=True)
class ChainSegment:
    """A continuous run of frames on one swap chain."""

    application: str
    process_id: str
    swap_chain: str
    segment: int
    frames: tuple[FrameRecord, ...]
    identifier_ok: bool

    @property
    def frame_count(self):

        return len(self.frames)

    @property
    def first_ms(self):

        return self.frames[0].time_ms

    @property
    def last_ms(self):

        return self.frames[-1].time_ms

    @property
    def span_ms(self):

        return self.last_ms - self.first_ms

    @property
    def key(self):

        return (
            self.application,
            self.process_id,
            self.swap_chain,
            self.segment,
        )

    @property
    def label(self):

        address = self.swap_chain or "<missing>"

        if self.segment:

            return f"{address} (segment {self.segment + 1})"

        return address


@dataclass(frozen=True)
class CaptureIndex:
    """All frames and chains found in one CSV capture."""

    frames: tuple[FrameRecord, ...]
    chains: tuple[ChainSegment, ...]
    start_ms: float
    end_ms: float
    session: str = ""
    timebase: frame_timebase.FrameTimebase | None = None

    @property
    def total_frames(self):

        return len(self.frames)

    @property
    def span_ms(self):

        return max(0.0, self.end_ms - self.start_ms)

    @property
    def bucket_count(self):

        first = int(
            math.floor(
                self.start_ms / ACTIVITY_BUCKET_MS
            )
        )

        last = int(
            math.floor(
                self.end_ms / ACTIVITY_BUCKET_MS
            )
        )

        return max(1, last - first + 1)


@dataclass(frozen=True)
class ChainGroup:
    """Chains that may be analysed together."""

    application: str
    process_id: str
    chains: tuple[ChainSegment, ...]
    frames: tuple[FrameRecord, ...]
    sequential: bool
    concurrent_activity: bool
    reliable: bool

    @property
    def frame_count(self):

        return len(self.frames)

    @property
    def first_ms(self):

        return self.frames[0].time_ms

    @property
    def last_ms(self):

        return self.frames[-1].time_ms

    @property
    def span_ms(self):

        return self.last_ms - self.first_ms

    @property
    def merged(self):

        return self.sequential and len(self.chains) > 1

    @property
    def chain_ids(self):

        return tuple(
            chain.swap_chain
            for chain in self.chains
        )

    @property
    def process_label(self):

        return (
            f"{self.application} "
            f"(pid {self.process_id})"
        )


@dataclass(frozen=True)
class SelectionOverride:
    """Explicit user selection.

    ``swap_chains`` accepts an address (selects every segment with that
    address) or an ``(address, segment)`` pair (selects one segment).
    """

    swap_chains: tuple
    application: str | None = None
    process_id: str | None = None


@dataclass(frozen=True)
class SelectionChoice:
    """One entry for a selection UI."""

    label: str
    group: ChainGroup


@dataclass(frozen=True)
class SelectionResult:
    """Recommendation plus the frames to analyse."""

    selected: ChainGroup
    frames: tuple[FrameRecord, ...]
    confidence: str
    uncertain: bool
    reason: str
    candidates: tuple[ChainGroup, ...]
    reason_parts: tuple[tuple[str, dict], ...] = ()
    activity_coverage: float = 0.0
    overridden: bool = False

    @property
    def frame_count(self):

        return len(self.frames)

    def legacy_frames(self):

        return [
            frame.as_legacy()
            for frame in self.frames
        ]


def build_index(
    rows,
    session="",
    timebase=None,
) -> CaptureIndex:
    """Parse rows into frames and chain segments.

    ``rows`` are the original ``csv.DictReader`` mappings.  They are
    never modified; ``FrameRecord.row`` references the original dict.
    ``timebase`` may be supplied by a caller that has already read the
    C-1 sidecar.  Without it, a QPC CSV is normalized using the first
    frame as a clearly labelled fallback origin.
    """

    rows = list(rows)

    if not rows:

        raise ValueError(
            "CSV has no valid frame-time data"
        )

    missing = REQUIRED_COLUMNS - set(rows[0].keys())

    if missing:

        raise ValueError(
            "CSV is missing required PresentMon columns: "
            + ", ".join(sorted(missing))
        )

    if timebase is None:

        timebase = frame_timebase.resolve_timebase(
            rows[0].keys()
        )

    if not timebase.raw_column:

        raise ValueError(
            "CSV is missing required PresentMon time column: "
            "CPUStartTime or CPUStartQPCTime"
        )

    parsed = []

    for index, row in enumerate(rows):

        try:

            raw_time_ms = float(
                row[timebase.raw_column]
            )
            frame_time_ms = float(row["FrameTime"])

        except (KeyError, TypeError, ValueError):

            continue

        if (
            not math.isfinite(raw_time_ms)
            or not math.isfinite(frame_time_ms)
            or frame_time_ms <= 0
        ):

            continue

        parsed.append(
            (index, row, raw_time_ms, frame_time_ms)
        )

    if not parsed:

        raise ValueError(
            "CSV has no valid frame-time data"
        )

    if (
        timebase.kind == "qpc_ms"
        and timebase.origin_qpc_ms is None
    ):

        timebase = timebase.with_origin(
            min(item[2] for item in parsed),
            "first_frame",
            "inferred_qpc",
            note=frame_timebase.QPC_FIRST_FRAME_NOTE,
        )

    frames = []

    for index, row, raw_time_ms, frame_time_ms in parsed:

        try:

            time_ms = timebase.normalize(raw_time_ms)

        except (TypeError, ValueError):

            continue

        application = (
            (row.get("Application") or "").strip()
            or "<unknown>"
        )

        process_id = (
            (row.get("ProcessID") or "").strip()
            or "?"
        )

        swap_chain = (
            (row.get("SwapChainAddress") or "").strip()
        )

        frames.append(
            FrameRecord(
                index=index,
                application=application,
                process_id=process_id,
                swap_chain=swap_chain,
                time_ms=time_ms,
                frame_time_ms=frame_time_ms,
                displayed=(
                    row.get("DisplayedTime", "NA")
                    not in ("", "NA", None)
                ),
                row=row,
                raw_time_ms=raw_time_ms,
                timebase=timebase,
            )
        )

    if not frames:

        raise ValueError(
            "CSV has no valid frame-time data"
        )

    frames.sort(
        key=lambda frame: (
            frame.time_ms,
            frame.index,
        )
    )

    timebase = timebase.with_range(
        frames[0].raw_time_ms,
        frames[-1].raw_time_ms,
    )

    buckets = defaultdict(list)

    for frame in frames:

        buckets[
            (
                frame.application,
                frame.process_id,
                frame.swap_chain,
            )
        ].append(frame)

    chains = []

    for key, items in buckets.items():

        application, process_id, swap_chain = key

        items.sort(
            key=lambda frame: (
                frame.time_ms,
                frame.index,
            )
        )

        segment = []
        segment_index = 0

        for frame in items:

            if (
                segment
                and frame.time_ms
                - segment[-1].time_ms
                > SEGMENT_SPLIT_GAP_MS
            ):

                chains.append(
                    ChainSegment(
                        application=application,
                        process_id=process_id,
                        swap_chain=swap_chain,
                        segment=segment_index,
                        frames=tuple(segment),
                        identifier_ok=(
                            identifier_is_reliable(
                                swap_chain
                            )
                        ),
                    )
                )

                segment = []
                segment_index += 1

            segment.append(frame)

        if segment:

            chains.append(
                ChainSegment(
                    application=application,
                    process_id=process_id,
                    swap_chain=swap_chain,
                    segment=segment_index,
                    frames=tuple(segment),
                    identifier_ok=(
                        identifier_is_reliable(swap_chain)
                    ),
                )
            )

    chains.sort(
        key=lambda chain: (
            chain.application,
            chain.process_id,
            chain.swap_chain,
            chain.segment,
        )
    )

    return CaptureIndex(
        frames=tuple(frames),
        chains=tuple(chains),
        start_ms=frames[0].time_ms,
        end_ms=frames[-1].time_ms,
        session=str(session),
        timebase=timebase,
    )


def _overlaps(first, second):

    overlap = (
        min(first.last_ms, second.last_ms)
        - max(first.first_ms, second.first_ms)
    )

    return overlap > OVERLAP_TOLERANCE_MS


def _process_has_overlap(chains):

    ordered = sorted(
        chains,
        key=lambda chain: (
            chain.first_ms,
            chain.swap_chain,
            chain.segment,
        ),
    )

    for index, chain in enumerate(ordered):

        for other in ordered[index + 1:]:

            if _overlaps(chain, other):

                return True

    return False


def _greedy_sequential(chains):
    """Maximal non-overlapping set (interval scheduling)."""

    ordered = sorted(
        chains,
        key=lambda chain: (
            chain.last_ms,
            chain.first_ms,
            chain.swap_chain,
            chain.segment,
        ),
    )

    selected = []
    end = None

    for chain in ordered:

        if (
            end is None
            or chain.first_ms
            >= end - OVERLAP_TOLERANCE_MS
        ):

            selected.append(chain)
            end = chain.last_ms

    return selected


def _merge_frames(chains):

    frames = [
        frame
        for chain in chains
        for frame in chain.frames
    ]

    frames.sort(
        key=lambda frame: (
            frame.time_ms,
            frame.index,
        )
    )

    return tuple(frames)


def _make_group(
    application,
    process_id,
    chains,
    sequential,
    concurrent_activity,
):

    chains = tuple(chains)

    return ChainGroup(
        application=application,
        process_id=process_id,
        chains=chains,
        frames=_merge_frames(chains),
        sequential=sequential,
        concurrent_activity=concurrent_activity,
        reliable=(
            all(
                chain.identifier_ok
                for chain in chains
            )
            and process_is_reliable(process_id)
        ),
    )


def build_groups(index):

    by_process = defaultdict(list)

    for chain in index.chains:

        by_process[
            (chain.application, chain.process_id)
        ].append(chain)

    groups = []

    for (application, process_id), chains in sorted(
        by_process.items()
    ):

        chains.sort(
            key=lambda chain: (
                chain.first_ms,
                chain.swap_chain,
                chain.segment,
            )
        )

        if not _process_has_overlap(chains):

            # A paused game is still one chain: keep every segment in
            # the group.  Coverage measures real activity, so a long
            # pause does not inflate the score.
            groups.append(
                _make_group(
                    application,
                    process_id,
                    chains,
                    sequential=len(chains) > 1,
                    concurrent_activity=False,
                )
            )

            continue

        # Concurrent activity.  Build one maximal non-overlapping set
        # so an auxiliary overlay does not prevent two sequential main
        # chains from being merged.
        greedy = _greedy_sequential(chains)

        if len(greedy) > 1:

            groups.append(
                _make_group(
                    application,
                    process_id,
                    greedy,
                    sequential=True,
                    concurrent_activity=True,
                )
            )

        for chain in chains:

            groups.append(
                _make_group(
                    application,
                    process_id,
                    (chain,),
                    sequential=False,
                    concurrent_activity=True,
                )
            )

    unique = {}

    for group in groups:

        key = tuple(
            chain.key
            for chain in group.chains
        )

        unique.setdefault(key, group)

    return sorted(
        unique.values(),
        key=lambda group: (
            group.first_ms,
            tuple(
                chain.key
                for chain in group.chains
            ),
        ),
    )


def _activity_coverage(group, index):

    if index.bucket_count <= 0:

        return 0.0

    buckets = {
        int(
            math.floor(
                frame.time_ms / ACTIVITY_BUCKET_MS
            )
        )
        for frame in group.frames
    }

    return len(buckets) / index.bucket_count


def _max_gap_ms(group):

    frames = group.frames

    return max(
        (
            second.time_ms - first.time_ms
            for first, second in zip(
                frames,
                frames[1:],
            )
        ),
        default=0.0,
    )


def _score(group, index):

    coverage = _activity_coverage(group, index)

    tail = (
        1.0
        if index.end_ms - group.last_ms
        <= TAIL_WINDOW_MS
        else 0.0
    )

    share = (
        group.frame_count / index.total_frames
        if index.total_frames
        else 0.0
    )

    reliable = 1.0 if group.reliable else 0.0

    return (
        SCORE_WEIGHTS["coverage"] * coverage
        + SCORE_WEIGHTS["tail"] * tail
        + SCORE_WEIGHTS["share"] * share
        + SCORE_WEIGHTS["reliable"] * reliable
    )


# English fallback templates for reason_parts.  The GUI translates
# the same keys through the JSON catalogs.
_EN_REASON = {
    "chain.reason.frames_one": (
        "{frames} frames from one swap chain"
    ),
    "chain.reason.frames_many": (
        "{frames} frames from {chains} swap chains"
    ),
    "chain.reason.sequential": (
        "used sequentially with no overlap"
    ),
    "chain.reason.concurrent": (
        "concurrent swap chains detected; other chains "
        "are excluded from this analysis"
    ),
    "chain.reason.coverage": (
        "activity coverage {percent:.0f}% of the capture"
    ),
    "chain.reason.active_end": "active at the end",
    "chain.reason.not_active_end": (
        "not active at the end"
    ),
    "chain.reason.unreliable": (
        "swap-chain identifier is missing or zero"
    ),
    "chain.reason.unreliable_lower": (
        "{count} chain(s) with a missing or zero identifier "
        "were scored lower"
    ),
    "chain.reason.inactive": (
        "contains a long inactive interval (>5 s)"
    ),
    "chain.reason.uncertain": (
        "alternatives are too close (score margin "
        "{margin:.2f}); selection is uncertain"
    ),
    "chain.reason.margin": (
        "best alternative is {margin:.2f} behind"
    ),
    "chain.reason.process": (
        "process {application} (pid {pid})"
    ),
    "chain.reason.user": (
        "User selection: {frames} frames from {chains} "
        "swap chain(s) ({labels}); other chains remain in "
        "the CSV but are excluded from this analysis"
    ),
}


def _render_reason_parts(parts):
    """Render the English fallback string for logs and tests."""

    return "; ".join(
        _EN_REASON[key].format(**args)
        for key, args in parts
    )


def _reason(
    best,
    index,
    margin,
    uncertain,
    unreliable_count,
    all_groups,
    candidate_count,
):

    parts = []

    if len(best.chains) == 1:

        parts.append(
            (
                "chain.reason.frames_one",
                {"frames": best.frame_count},
            )
        )

    else:

        parts.append(
            (
                "chain.reason.frames_many",
                {
                    "frames": best.frame_count,
                    "chains": len(best.chains),
                },
            )
        )

    if best.merged:

        parts.append(
            ("chain.reason.sequential", {})
        )

    if best.concurrent_activity:

        parts.append(
            ("chain.reason.concurrent", {})
        )

    parts.append(
        (
            "chain.reason.coverage",
            {
                "percent": (
                    _activity_coverage(best, index)
                    * 100.0
                ),
            },
        )
    )

    active_at_end = (
        index.end_ms - best.last_ms
        <= TAIL_WINDOW_MS
    )

    parts.append(
        (
            (
                "chain.reason.active_end"
                if active_at_end
                else "chain.reason.not_active_end"
            ),
            {},
        )
    )

    if not best.reliable:

        parts.append(
            ("chain.reason.unreliable", {})
        )

    if unreliable_count and best.reliable:

        parts.append(
            (
                "chain.reason.unreliable_lower",
                {"count": unreliable_count},
            )
        )

    if _max_gap_ms(best) > SEGMENT_SPLIT_GAP_MS:

        parts.append(
            ("chain.reason.inactive", {})
        )

    if uncertain:

        parts.append(
            (
                "chain.reason.uncertain",
                {"margin": margin},
            )
        )

    elif candidate_count > 1:

        parts.append(
            (
                "chain.reason.margin",
                {"margin": margin},
            )
        )

    parts.append(
        (
            "chain.reason.process",
            {
                "application": best.application,
                "pid": best.process_id,
            },
        )
    )

    return (
        _render_reason_parts(parts),
        tuple(parts),
    )


def _spec_matches(chain, spec):

    if isinstance(spec, tuple):

        address, segment = spec

        return (
            chain.swap_chain == address
            and chain.segment == int(segment)
        )

    return chain.swap_chain == spec


def _apply_override(index, groups, override):

    wanted = tuple(override.swap_chains)

    if not wanted:

        raise ValueError(
            "Override must name at least one swap chain"
        )

    candidates = []
    seen = set()

    for spec in wanted:

        matches = [
            chain
            for chain in index.chains
            if _spec_matches(chain, spec)
        ]

        if override.application is not None:

            matches = [
                chain
                for chain in matches
                if chain.application == override.application
            ]

        if override.process_id is not None:

            matches = [
                chain
                for chain in matches
                if chain.process_id == str(override.process_id)
            ]

        if not matches:

            raise ValueError(
                "Override does not match any swap chain: "
                f"{spec!r}"
            )

        for chain in matches:

            if chain.key in seen:

                continue

            seen.add(chain.key)
            candidates.append(chain)

    processes = {
        (chain.application, chain.process_id)
        for chain in candidates
    }

    if len(processes) > 1:

        raise ValueError(
            "Override matches chains from multiple "
            "processes; specify application and process_id"
        )

    ordered = sorted(
        candidates,
        key=lambda chain: (
            chain.first_ms,
            chain.swap_chain,
            chain.segment,
        ),
    )

    for first, second in zip(
        ordered,
        ordered[1:],
    ):

        if (
            second.first_ms
            < first.last_ms - OVERLAP_TOLERANCE_MS
        ):

            raise ValueError(
                "Selected swap chains overlap in time; "
                "they cannot be merged"
            )

    application = ordered[0].application
    process_id = ordered[0].process_id

    group = _make_group(
        application,
        process_id,
        ordered,
        sequential=len(ordered) > 1,
        concurrent_activity=False,
    )

    labels = ", ".join(
        chain.label
        for chain in ordered
    )

    reason_parts = (
        (
            "chain.reason.user",
            {
                "frames": group.frame_count,
                "chains": len(ordered),
                "labels": labels,
            },
        ),
    )

    return SelectionResult(
        selected=group,
        frames=group.frames,
        confidence="user",
        uncertain=False,
        reason=_render_reason_parts(reason_parts),
        reason_parts=reason_parts,
        candidates=tuple(groups),
        activity_coverage=_activity_coverage(
            group,
            index,
        ),
        overridden=True,
    )


def recommend(index, override=None) -> SelectionResult:
    """Return the frames to analyse plus an explanation."""

    groups = build_groups(index)

    if not groups:

        raise ValueError(
            "CSV has no valid frame-time data"
        )

    if override is not None:

        return _apply_override(index, groups, override)

    scored = sorted(
        (
            (_score(group, index), group)
            for group in groups
        ),
        key=lambda item: (
            -item[0],
            item[1].first_ms,
            item[1].chain_ids,
            item[1].process_id,
        ),
    )

    best_score, best = scored[0]

    unreliable_count = sum(
        1
        for group in groups
        if not group.reliable
    )

    if len(scored) == 1:

        margin = 1.0

        confidence = (
            "high" if best.reliable else "low"
        )

        uncertain = False

    else:

        margin = best_score - scored[1][0]

        # Reliability is part of the score, never a reason to hide a
        # candidate and never a reason for high confidence by itself.
        if not best.reliable:

            confidence = "low"
            uncertain = False

        elif margin >= HIGH_CONFIDENCE_MARGIN - 1e-9:

            confidence = "high"
            uncertain = False

        elif margin >= AMBIGUITY_MARGIN - 1e-9:

            confidence = "medium"
            uncertain = False

        else:

            confidence = "uncertain"
            uncertain = True

    reason, reason_parts = _reason(
        best,
        index,
        margin,
        uncertain,
        unreliable_count,
        groups,
        len(scored),
    )

    return SelectionResult(
        selected=best,
        frames=best.frames,
        confidence=confidence,
        uncertain=uncertain,
        reason=reason,
        reason_parts=reason_parts,
        candidates=tuple(
            group for _, group in scored
        ),
        activity_coverage=_activity_coverage(
            best,
            index,
        ),
        overridden=False,
    )


def _choice_label(group):

    if len(group.chains) == 1:

        name = group.chains[0].label

    else:

        name = f"{len(group.chains)} chains"

    return (
        f"{name} - {group.frame_count} frames, "
        f"{group.span_ms / 1000.0:.1f} s"
    )


def list_choices(index):
    """Candidate groups plus every individual segment for a UI."""

    choices = {}

    for group in build_groups(index):

        key = tuple(
            chain.key
            for chain in group.chains
        )

        choices.setdefault(
            key,
            SelectionChoice(
                label=_choice_label(group),
                group=group,
            ),
        )

    for chain in index.chains:

        key = (chain.key,)

        if key in choices:

            continue

        group = _make_group(
            chain.application,
            chain.process_id,
            (chain,),
            sequential=False,
            concurrent_activity=False,
        )

        choices[key] = SelectionChoice(
            label=_choice_label(group),
            group=group,
        )

    return tuple(
        sorted(
            choices.values(),
            key=lambda choice: (
                choice.group.first_ms,
                choice.group.chain_ids,
                choice.group.process_id,
                choice.group.chains[0].segment,
            ),
        )
    )


def load_csv_rows(path):
    """Read the raw PresentMon rows without modifying them."""

    with Path(path).open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:

        return list(csv.DictReader(file))
