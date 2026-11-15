"""Capture-session identity and metadata shared by frames, telemetry and network."""

from __future__ import annotations

import json
import os
import time
import uuid

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


SCHEMA_VERSION = 1


def session_path(csv_path) -> Path:
    return Path(str(csv_path) + ".session.json")


def new_session_id():
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    return f"{stamp}-{uuid.uuid4().hex[:8]}"


@dataclass
class CaptureSession:
    session_id: str
    csv_path: Path
    target_name: str
    started_monotonic_ns: int
    started_wall_ns: int
    ended_monotonic_ns: int | None = None
    ended_wall_ns: int | None = None
    frame_status: str = "running"
    frame_reason: str = ""
    telemetry_status: str = "unknown"
    telemetry_reason: str = ""
    network_status: str = "unknown"
    network_reason: str = ""
    frame_timebase: dict | None = None
    metadata: dict = field(default_factory=dict)

    @classmethod
    def create(cls, csv_path, target_name=""):
        now_ns = time.perf_counter_ns()
        return cls(
            session_id=new_session_id(),
            csv_path=Path(csv_path),
            target_name=str(target_name or ""),
            started_monotonic_ns=now_ns,
            started_wall_ns=time.time_ns(),
        )

    def to_dict(self):
        return {
            "schema_version": SCHEMA_VERSION,
            "session_id": self.session_id,
            "capture": {
                "csv_name": self.csv_path.name,
                "target_name": self.target_name,
                "started_monotonic_ns": (
                    self.started_monotonic_ns
                ),
                "started_wall_ns": self.started_wall_ns,
                "ended_monotonic_ns": (
                    self.ended_monotonic_ns
                ),
                "ended_wall_ns": self.ended_wall_ns,
                "status": self.frame_status,
                "reason": self.frame_reason,
            },
            "timebase": {
                "monotonic_clock": "perf_counter_ns",
                "wall_clock": "time_ns",
                "origin_monotonic_ns": (
                    self.started_monotonic_ns
                ),
                "note": (
                    "network and telemetry t_ms use this origin; "
                    "QPC frames use the same perf_counter origin"
                ),
                "frame": self.frame_timebase,
            },
            "data": {
                "frames": {
                    "csv_name": self.csv_path.name,
                    "status": self.frame_status,
                    "reason": self.frame_reason,
                },
                "telemetry": {
                    "sidecar": (
                        self.csv_path.name
                        + ".telemetry.jsonl"
                    ),
                    "status": self.telemetry_status,
                    "reason": self.telemetry_reason,
                },
                "network": {
                    "sidecar": (
                        self.csv_path.name
                        + ".network.jsonl"
                    ),
                    "status": self.network_status,
                    "reason": self.network_reason,
                },
            },
        }

    def write(self):
        path = session_path(self.csv_path)

        try:
            path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )
            temp = path.with_suffix(
                path.suffix + ".tmp"
            )
            temp.write_text(
                json.dumps(
                    self.to_dict(),
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            os.replace(temp, path)
            return True
        except OSError:
            return False

    def finish(
        self,
        frame_status=None,
        frame_reason=None,
        telemetry_status=None,
        telemetry_reason=None,
        network_status=None,
        network_reason=None,
        frame_timebase=None,
    ):
        if frame_status is not None:
            self.frame_status = frame_status
        if frame_reason is not None:
            self.frame_reason = frame_reason
        if telemetry_status is not None:
            self.telemetry_status = telemetry_status
        if telemetry_reason is not None:
            self.telemetry_reason = telemetry_reason
        if network_status is not None:
            self.network_status = network_status
        if network_reason is not None:
            self.network_reason = network_reason
        if frame_timebase is not None:
            self.frame_timebase = dict(frame_timebase)

        self.ended_monotonic_ns = time.perf_counter_ns()
        self.ended_wall_ns = time.time_ns()
        return self.write()


def read_session(csv_path):
    path = session_path(csv_path)

    try:
        data = json.loads(
            path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return None

    return data if isinstance(data, dict) else None


def session_id_of(data):
    if not isinstance(data, dict):
        return ""
    return str(data.get("session_id") or "")
