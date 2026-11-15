"""Lightweight, privacy-bounded diagnostics for AI requests.

The log is intentionally narrow: it records enough to tell a model/format
error apart from a fact-reference, numeric or API error, but never stores
credentials, chat text, raw responses or full capture paths.

Each line is one JSON object.  The file is capped at about 10 MiB total
(5 MiB active + one 5 MiB backup) and backups older than 7 days are
removed.  Logging failures never propagate to the caller.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time

from datetime import datetime, timezone
from pathlib import Path


MAX_BYTES = 5 * 1024 * 1024
RETENTION_DAYS = 7
MAX_STRING = 240

_DENIED_KEYS = {
    "api_key",
    "authorization",
    "headers",
    "header",
    "env",
    "environment",
    "content",
    "messages",
    "question",
    "answer",
    "response",
    "raw",
    "detail",
    "report_path",
    "file_path",
    "path",
}

_NUMERIC_ERROR = re.compile(
    r"does not match its fact (?P<fact>\S+): "
    r"(?P<number>\d+(?:\.\d+)?)\s*(?P<unit>ms|%|秒|s|FPS)",
    re.IGNORECASE,
)

_FACT_ERROR = re.compile(
    r"(?:unknown fact_id|unknown hypothesis fact_id|"
    r"observation cites invalid fact|"
    r"hypothesis cites invalid fact): (?P<fact>\S+)"
)


def report_identity(report):
    """Return a short hash and a basename; never the full report path."""

    report = report or {}
    key = str(
        report.get("report_key")
        or report.get("file")
        or report.get("application")
        or ""
    )
    name = str(report.get("file") or key)
    file_name = Path(name).name if name else ""
    digest = (
        hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
        if key
        else ""
    )
    return digest, file_name


def classify_validation_errors(errors):
    """Turn internal validation strings into safe structured entries."""

    classified = []

    for error in errors or ():

        text = str(error)
        entry = {"type": "other", "reason": text[:MAX_STRING]}
        match = _NUMERIC_ERROR.search(text)

        if match:

            entry = {
                "type": "numeric",
                "fact_id": match.group("fact"),
                "number": match.group("number"),
                "unit": match.group("unit"),
            }

        else:

            match = _FACT_ERROR.search(text)

            if match:

                entry = {
                    "type": "fact_reference",
                    "fact_id": match.group("fact"),
                }

            elif "response is not a JSON object" in text:

                entry = {"type": "json", "reason": text[:MAX_STRING]}

            elif (
                "conclusion" in text
                or "evidence_strength" in text
            ):

                entry = {"type": "conclusion"}

            elif (
                "network" in text
                or "alignment" in text
            ):

                entry = {
                    "type": "network",
                    "reason": text[:MAX_STRING],
                }

            elif "hardware" in text:

                entry = {"type": "hardware"}

            elif (
                "performance problem" in text
                or "scenario" in text
            ):

                entry = {"type": "scenario"}

            elif "unsafe" in text:

                entry = {"type": "safety"}

            elif (
                "must be" in text
                or "no supporting" in text
                or "at most one" in text
                or "empty" in text
            ):

                entry = {
                    "type": "format",
                    "reason": text[:MAX_STRING],
                }

        if entry not in classified:

            classified.append(entry)

    return classified


def _sanitize(value, depth=0):
    """Drop denied keys and cap strings/lists without touching numbers."""

    if depth > 3:

        return "..."

    if isinstance(value, dict):

        return {
            str(key): _sanitize(item, depth + 1)
            for key, item in value.items()
            if str(key).lower() not in _DENIED_KEYS
        }

    if isinstance(value, (list, tuple)):

        return [
            _sanitize(item, depth + 1)
            for item in list(value)[:20]
        ]

    if isinstance(value, str):

        text = value.replace("\r", " ").replace("\n", " ")

        return text[:MAX_STRING]

    if isinstance(value, (bool, int, float)) or value is None:

        return value

    return str(value)[:MAX_STRING]


class AIDiagnosticLog:
    """Append-only JSONL log with a strict local size/retention cap."""

    def __init__(
        self,
        path=None,
        max_bytes=MAX_BYTES,
        retention_days=RETENTION_DAYS,
    ):

        self._path = Path(path) if path is not None else None
        self.max_bytes = max(128, int(max_bytes))
        self.retention_days = max(1, int(retention_days))
        self._lock = threading.Lock()
        self._last_prune = 0.0

    @property
    def path(self):

        if self._path is None:

            from settings import user_data_dir

            self._path = (
                user_data_dir()
                / "logs"
                / "ai_diagnostics.jsonl"
            )

        return self._path

    def record(self, event, **fields):
        """Append one line; return False instead of raising on any error."""

        try:

            payload = {
                "ts": datetime.now(timezone.utc).isoformat(
                    timespec="seconds"
                ),
                "event": str(event),
            }
            payload.update(_sanitize(fields))
            line = (
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                + "\n"
            )
            data = line.encode("utf-8")

            with self._lock:

                self._prune_locked()
                path = self.path
                path.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                if (
                    path.exists()
                    and path.stat().st_size + len(data)
                    > self.max_bytes
                ):

                    backup = self._backup_path()

                    try:

                        if backup.exists():

                            backup.unlink()

                        path.replace(backup)

                    except OSError:

                        pass

                with path.open(
                    "a",
                    encoding="utf-8",
                    newline="",
                ) as handle:

                    handle.write(line)

            return True

        except Exception:

            return False

    def _backup_path(self):

        return self.path.with_name(
            self.path.name + ".1"
        )

    def _prune_locked(self):

        now = time.time()

        if now - self._last_prune < 3600:

            return

        self._last_prune = now
        cutoff = now - self.retention_days * 86400
        path = self.path
        candidates = [self._backup_path()]

        try:

            candidates += sorted(
                path.parent.glob(path.name + ".*")
            )

        except OSError:

            pass

        for candidate in candidates:

            try:

                if (
                    candidate.is_file()
                    and candidate.stat().st_mtime < cutoff
                ):

                    candidate.unlink()

            except OSError:

                pass


_LOG = None
_LOG_LOCK = threading.Lock()


def get_log():
    """Return the process-wide diagnostic log (lazy, thread-safe)."""

    global _LOG

    if _LOG is None:

        with _LOG_LOCK:

            if _LOG is None:

                _LOG = AIDiagnosticLog()

    return _LOG


def usage_summary(usage):
    """Keep only token counts from a provider usage object."""

    if not isinstance(usage, dict):

        return None

    summary = {}

    for key in (
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
    ):

        value = usage.get(key)

        if isinstance(value, int) and value >= 0:

            summary[key] = value

    return summary or None
