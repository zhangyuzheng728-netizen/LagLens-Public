"""B-1: process discovery, explainable recommendation and path memory.

This module keeps the process-selection logic headless so it can be
tested without a QApplication.  The GUI will consume it in B-2/B-3.

Design rules:

* a process is never judged solely by its executable name;
* the strongest signal is an exact executable-path match with a
  previously successful capture;
* a visible top-level window is the next signal;
* memory use is only a weak additional hint;
* inaccessible executable paths degrade to "unknown" and never raise;
* successful-target memory stores paths, never PIDs.
"""

from __future__ import annotations

import csv
import logging
import ntpath
import os

from dataclasses import dataclass
from datetime import datetime

import psutil

from settings import MAX_REMEMBERED_TARGETS


logger = logging.getLogger("laglens.process_catalog")
logger.addHandler(logging.NullHandler())


SCORE_REMEMBERED_PATH = 100
SCORE_VISIBLE_WINDOW = 40
SCORE_WINDOW_TITLE = 5
SCORE_LARGE_MEMORY = 10

RECOMMENDED_MIN_SCORE = SCORE_VISIBLE_WINDOW
LARGE_MEMORY_BYTES = 512 * 1024 * 1024
PID_REUSE_TOLERANCE_SECONDS = 5.0

PROCESS_FIELDS = [
    "pid",
    "name",
    "exe",
    "username",
    "memory_info",
    "create_time",
]

REMEMBERED_REASON = "process.reason.remembered"
WINDOW_REASON = "process.reason.window"
VISIBLE_REASON = "process.reason.visible"
MEMORY_REASON = "process.reason.memory"


@dataclass(frozen=True)
class ProcessEntry:
    """One running executable as seen by the process picker."""

    pid: int
    name: str
    exe: str = ""
    username: str = ""
    memory_bytes: int = 0
    create_time: float = 0.0
    window_title: str = ""
    has_window: bool = False

    @property
    def path_accessible(self) -> bool:
        """True when Windows allowed us to read the executable path."""

        return bool((self.exe or "").strip())

    @property
    def normalized_path(self) -> str:
        """Case/separator-insensitive key used for path memory."""

        return normalize_path(self.exe)

    @property
    def system_executable(self) -> bool:
        """True for processes that belong to the Windows shell/system."""

        return is_system_executable(self.exe)


@dataclass(frozen=True)
class Recommendation:
    """A process plus an explainable score and reason parts."""

    entry: ProcessEntry
    score: int
    reasons: tuple[tuple[str, dict], ...] = ()

    @property
    def recommended(self) -> bool:
        return (
            self.score >= RECOMMENDED_MIN_SCORE
            and not self.entry.system_executable
        )


@dataclass(frozen=True)
class RendererHint:
    """Hint for a selected process that looks like a launcher."""

    target: str
    similar: tuple[str, ...] = ()
    suggested: str = ""
    target_visible: bool = False
    suspected: bool = False


def normalize_path(path) -> str:
    """Return a Windows path key for comparisons, or "" if unusable.

    ``ntpath`` is used deliberately: process paths are Windows paths even
    when the test runner is not Windows.
    """

    text = str(path or "").strip().strip('"')

    if not text:

        return ""

    try:

        return ntpath.normcase(
            ntpath.normpath(text)
        )

    except (OSError, ValueError):

        return ""


def is_system_executable(
    path,
    system_root=None,
) -> bool:
    """True for Windows shell/system binaries, not for user games.

    The check is path-based, not name-based, so a game is never
    excluded merely because its executable has a common name.
    """

    key = normalize_path(path)

    if not key:

        return False

    root = normalize_path(
        system_root
        or os.environ.get("SystemRoot")
        or r"C:\Windows"
    )

    if not root:

        return False

    if key == root + "\\explorer.exe":

        return True

    return any(
        key.startswith(
            root + "\\" + folder + "\\"
        )
        for folder in (
            "system32",
            "syswow64",
            "systemapps",
            "immersivecontrolpanel",
        )
    )


def _target_name(target) -> str:
    """Extract the executable name PresentMon targets."""

    text = str(target or "").strip().strip('"')

    if not text:

        return ""

    try:

        name = ntpath.basename(
            ntpath.normpath(text)
        )

    except (OSError, ValueError):

        return ""

    if name and not name.lower().endswith(".exe"):

        name += ".exe"

    return name


def visible_window_titles() -> dict:
    """Map PID -> visible top-level window title.

    Windows-only and intentionally best-effort.  Any failure (missing
    user32, permissions, ctypes mismatch) yields an empty mapping so
    process enumeration can continue without window hints.
    """

    if os.name != "nt":

        return {}

    try:

        import ctypes

        from ctypes import wintypes

        user32 = ctypes.WinDLL(
            "user32",
            use_last_error=True,
        )

        callback_type = ctypes.WINFUNCTYPE(
            wintypes.BOOL,
            wintypes.HWND,
            wintypes.LPARAM,
        )

        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL

        user32.GetWindowTextLengthW.argtypes = [
            wintypes.HWND
        ]
        user32.GetWindowTextLengthW.restype = ctypes.c_int

        user32.GetWindowTextW.argtypes = [
            wintypes.HWND,
            wintypes.LPWSTR,
            ctypes.c_int,
        ]
        user32.GetWindowTextW.restype = ctypes.c_int

        user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        ]
        user32.GetWindowThreadProcessId.restype = (
            wintypes.DWORD
        )

        user32.EnumWindows.argtypes = [
            callback_type,
            wintypes.LPARAM,
        ]
        user32.EnumWindows.restype = wintypes.BOOL

        titles = {}

        @callback_type
        def callback(hwnd, _lparam):

            if not user32.IsWindowVisible(hwnd):

                return True

            length = user32.GetWindowTextLengthW(hwnd)

            if length <= 0:

                return True

            buffer = ctypes.create_unicode_buffer(
                length + 1
            )

            user32.GetWindowTextW(
                hwnd,
                buffer,
                length + 1,
            )

            title = buffer.value.strip()

            if not title:

                return True

            pid = wintypes.DWORD()

            user32.GetWindowThreadProcessId(
                hwnd,
                ctypes.byref(pid),
            )

            if pid.value:

                titles.setdefault(pid.value, title)

            return True

        user32.EnumWindows(callback, 0)

        return titles

    except Exception as error:  # pragma: no cover - OS/ctypes edge

        logger.debug(
            "window enumeration unavailable: %s",
            error,
            exc_info=True,
        )

        return {}


def collect_processes(
    process_iter_factory=None,
    window_lookup=None,
    current_pid=None,
) -> list:
    """Enumerate running executables with best-effort metadata.

    Every process is handled independently: an access-denied process is
    skipped without aborting the whole refresh.
    """

    factory = (
        process_iter_factory
        or psutil.process_iter
    )

    if current_pid is None:

        current_pid = os.getpid()

    try:

        raw_windows = (
            window_lookup()
            if window_lookup is not None
            else visible_window_titles()
        )

    except (
        OSError,
        TypeError,
        ValueError,
        psutil.Error,
    ) as error:

        logger.debug(
            "window lookup failed: %s",
            error,
        )

        raw_windows = {}

    windows = {}

    if isinstance(raw_windows, dict):

        for key, value in raw_windows.items():

            try:

                windows[int(key)] = str(value or "")

            except (TypeError, ValueError):

                continue

    try:

        iterator = factory(PROCESS_FIELDS)

    except (
        OSError,
        TypeError,
        ValueError,
        psutil.Error,
    ) as error:

        logger.debug(
            "process enumeration failed: %s",
            error,
        )

        return []

    entries = []

    try:

        for process in iterator:

            entry = _entry_from_process(
                process,
                windows,
                current_pid,
            )

            if entry is not None:

                entries.append(entry)

    except (
        OSError,
        TypeError,
        ValueError,
        psutil.Error,
    ) as error:

        logger.debug(
            "process iteration stopped early: %s",
            error,
        )

    return sorted(
        entries,
        key=lambda entry: (
            entry.name.casefold(),
            entry.pid,
        ),
    )


def _entry_from_process(
    process,
    windows,
    current_pid,
):
    """Build one entry; return None when the process is unusable."""

    try:

        info = process.info

    except (
        OSError,
        TypeError,
        ValueError,
        psutil.Error,
    ):

        return None

    if not isinstance(info, dict):

        try:

            info = dict(info)

        except (TypeError, ValueError):

            return None

    try:

        pid = int(info.get("pid"))

    except (TypeError, ValueError):

        return None

    if pid <= 0 or pid == current_pid:

        return None

    name = str(info.get("name") or "").strip()
    exe = str(info.get("exe") or "").strip()

    if not name.lower().endswith(".exe"):

        if exe.lower().endswith(".exe"):

            name = ntpath.basename(exe)

        else:

            return None

    if not name:

        return None

    memory = info.get("memory_info")

    if isinstance(memory, int):

        memory_bytes = max(0, memory)

    else:

        try:

            memory_bytes = max(
                0,
                int(getattr(memory, "rss", 0) or 0),
            )

        except (TypeError, ValueError):

            memory_bytes = 0

    try:

        create_time = float(
            info.get("create_time") or 0.0
        )

    except (TypeError, ValueError):

        create_time = 0.0

    has_window = pid in windows
    window_title = (
        str(windows.get(pid) or "")
        if has_window
        else ""
    )

    return ProcessEntry(
        pid=pid,
        name=name,
        exe=exe,
        username=str(info.get("username") or ""),
        memory_bytes=memory_bytes,
        create_time=create_time,
        window_title=window_title,
        has_window=has_window,
    )


def remembered_by_path(targets) -> dict:
    """Index successful targets by normalized executable path.

    Duplicate paths keep the record with the latest ISO timestamp.
    """

    records = {}

    if not isinstance(targets, (list, tuple)):

        return records

    for item in targets:

        if not isinstance(item, dict):

            continue

        path = item.get("path")
        executable = item.get("executable")

        if (
            not isinstance(path, str)
            or not path.strip()
        ):

            continue

        key = normalize_path(path)

        if not key:

            continue

        name = (
            executable.strip()
            if isinstance(executable, str)
            else ""
        )

        if not name:

            name = ntpath.basename(path.strip())

        if not name:

            continue

        record = {
            "path": path.strip(),
            "executable": name,
            "last_success": str(
                item.get("last_success") or ""
            ),
        }

        previous = records.get(key)

        if (
            previous is None
            or record["last_success"]
            >= previous["last_success"]
        ):

            records[key] = record

    return records


def rank_processes(
    entries,
    remembered_targets=(),
) -> list:
    """Score and sort every process; callers may filter ``recommended``.

    Scoring is deliberately simple and explainable:

    * +100 exact path remembered from a successful capture
    * +40 visible top-level window
    * +5 non-empty window title
    * +10 process uses at least 512 MiB of RAM (weak hint)
    """

    remembered = remembered_by_path(
        remembered_targets
    )

    ranked = []

    for entry in entries:

        score = 0
        reasons = []

        record = remembered.get(entry.normalized_path)

        if record is not None:

            score += SCORE_REMEMBERED_PATH

            reasons.append(
                (
                    REMEMBERED_REASON,
                    {
                        "last_success": record[
                            "last_success"
                        ]
                    },
                )
            )

        if entry.has_window:

            score += SCORE_VISIBLE_WINDOW

            if entry.window_title:

                score += SCORE_WINDOW_TITLE

                reasons.append(
                    (
                        WINDOW_REASON,
                        {
                            "title": entry.window_title
                        },
                    )
                )

            else:

                reasons.append(
                    (VISIBLE_REASON, {})
                )

        if entry.memory_bytes >= LARGE_MEMORY_BYTES:

            score += SCORE_LARGE_MEMORY

            reasons.append(
                (
                    MEMORY_REASON,
                    {
                        "mib": (
                            entry.memory_bytes
                            // 1024**2
                        )
                    },
                )
            )

        ranked.append(
            Recommendation(
                entry=entry,
                score=score,
                reasons=tuple(reasons),
            )
        )

    ranked.sort(
        key=lambda item: (
            -item.score,
            -int(item.entry.has_window),
            item.entry.name.casefold(),
            item.entry.pid,
        )
    )

    return ranked


def renderer_hint(
    target,
    similar_names,
    entries,
) -> RendererHint:
    """Suggest a likely renderer among similarly named processes.

    A process is treated as a suspected launcher only when it has no
    visible top-level window.  If the selected process already has a
    window, no warning is needed.  The suggestion is always a hint;
    callers must not switch the target silently.
    """

    wanted = _target_name(target)

    similar = []
    seen = set()

    for name in similar_names or ():

        text = str(name or "").strip()
        key = text.casefold()

        if not text or key in seen:

            continue

        seen.add(key)
        similar.append(text)

    if not similar:

        return RendererHint(
            target=wanted,
            similar=(),
            suspected=False,
        )

    try:

        entries = list(entries)

    except TypeError:

        entries = []

    target_entries = [
        entry
        for entry in entries
        if (
            (entry.name or "").casefold()
            == wanted.casefold()
        )
    ]

    similar_keys = {
        name.casefold()
        for name in similar
    }

    similar_entries = [
        entry
        for entry in entries
        if (
            (entry.name or "").casefold()
            in similar_keys
        )
    ]

    target_visible = any(
        entry.has_window
        for entry in target_entries
    )

    if target_visible:

        return RendererHint(
            target=wanted,
            similar=tuple(similar),
            suggested="",
            target_visible=True,
            suspected=False,
        )

    candidates = sorted(
        similar_entries,
        key=lambda entry: (
            -int(entry.has_window),
            -entry.memory_bytes,
            entry.name.casefold(),
            entry.pid,
        ),
    )

    suggested = (
        candidates[0].name
        if candidates
        else ""
    )

    return RendererHint(
        target=wanted,
        similar=tuple(similar),
        suggested=suggested,
        target_visible=False,
        suspected=True,
    )


def _clean_targets(targets) -> list:
    """Normalize the settings schema without ever keeping a PID."""

    cleaned = []
    seen = set()

    if not isinstance(targets, (list, tuple)):

        return cleaned

    for item in targets:

        if not isinstance(item, dict):

            continue

        path = item.get("path")
        executable = item.get("executable")

        if (
            not isinstance(path, str)
            or not path.strip()
        ):

            continue

        if (
            not isinstance(executable, str)
            or not executable.strip()
        ):

            continue

        key = normalize_path(path)

        if not key or key in seen:

            continue

        seen.add(key)

        cleaned.append(
            {
                "path": path.strip(),
                "executable": executable.strip(),
                "last_success": str(
                    item.get("last_success") or ""
                ),
            }
        )

    return cleaned[:MAX_REMEMBERED_TARGETS]


def remember_successful_target(
    existing,
    executable,
    path,
    last_success=None,
) -> list:
    """Add or update one path; an inaccessible path changes nothing."""

    cleaned = _clean_targets(existing)

    clean_path = str(path or "").strip().strip('"')
    key = normalize_path(clean_path)

    if not key:

        return cleaned

    name = str(executable or "").strip()

    if not name:

        name = ntpath.basename(clean_path)

    if not name:

        return cleaned

    stamp = str(last_success or "").strip()

    if not stamp:

        stamp = datetime.now().isoformat(
            timespec="seconds"
        )

    record = {
        "path": clean_path,
        "executable": name,
        "last_success": stamp,
    }

    updated = [record]
    updated.extend(
        item
        for item in cleaned
        if normalize_path(item["path"]) != key
    )

    return updated[:MAX_REMEMBERED_TARGETS]


def update_successful_targets(
    settings,
    executable,
    path,
    last_success=None,
) -> list:
    """Read, update and persist path memory; failures are non-fatal."""

    try:

        existing = settings.successful_targets

    except (
        AttributeError,
        OSError,
        TypeError,
        ValueError,
    ) as error:

        logger.debug(
            "cannot read successful targets: %s",
            error,
        )

        return []

    updated = remember_successful_target(
        existing,
        executable,
        path,
        last_success,
    )

    if updated == existing:

        return updated

    try:

        settings.set_successful_targets(updated)

    except (
        AttributeError,
        OSError,
        TypeError,
        ValueError,
    ) as error:

        logger.debug(
            "cannot write successful targets: %s",
            error,
        )

        return []

    return updated


def read_process_ids(csv_path) -> list:
    """Read every unique positive ProcessID from a PresentMon CSV.

    The PIDs are used only to verify the executable paths of the process
    instances that actually produced frames; they are never persisted.
    """

    pids = []
    seen = set()

    try:

        file = open(
            csv_path,
            "r",
            encoding="utf-8-sig",
            newline="",
            errors="replace",
        )

    except (
        OSError,
        TypeError,
        UnicodeError,
        ValueError,
    ) as error:

        logger.debug(
            "cannot open capture CSV: %s",
            error,
        )

        return []

    try:

        with file:

            reader = csv.reader(file)

            header = next(reader, None)

            if not header:

                return []

            columns = {
                name.strip().lower(): index
                for index, name in enumerate(header)
            }

            index = columns.get("processid")

            if index is None:

                return []

            try:

                for row in reader:

                    if index >= len(row):

                        continue

                    try:

                        pid = int(row[index].strip())

                    except (TypeError, ValueError):

                        continue

                    if pid > 0 and pid not in seen:

                        seen.add(pid)
                        pids.append(pid)

            except csv.Error as error:

                logger.debug(
                    "capture CSV ended with a parse error: %s",
                    error,
                )

    except (
        OSError,
        csv.Error,
        TypeError,
        UnicodeError,
        ValueError,
    ) as error:

        logger.debug(
            "cannot read capture process ids: %s",
            error,
        )

        return []

    return pids


def read_process_id(csv_path):
    """Return the first positive ProcessID, or None."""

    pids = read_process_ids(csv_path)

    return pids[0] if pids else None


def resolve_target_paths(
    target,
    entries,
    pids=(),
    created_before=None,
) -> list:
    """Return paths verified by the PIDs that produced captured frames.

    A PID is accepted only when it still belongs to a running process
    with the expected executable name and an accessible path.  When
    ``created_before`` is supplied, the process must also have existed
    by that wall-clock time, which guards against a reused PID mapping
    to a newly started process after the capture.  There is
    deliberately no name-only fallback.
    """

    wanted = _target_name(target)

    if not wanted:

        return []

    try:

        entries = list(entries)

    except TypeError:

        return []

    if isinstance(pids, (int, str)):

        pids = [pids]

    collected = []
    seen_pids = set()

    for pid in pids or ():

        try:

            value = int(pid)

        except (TypeError, ValueError):

            continue

        if value > 0 and value not in seen_pids:

            seen_pids.add(value)
            collected.append(value)

    if not collected:

        return []

    by_pid = {
        entry.pid: entry
        for entry in entries
    }

    cutoff = None

    if created_before is not None:

        try:

            cutoff = float(created_before)

        except (TypeError, ValueError):

            cutoff = None

    paths = []
    seen_paths = set()

    for pid in collected:

        entry = by_pid.get(pid)

        if entry is None:

            continue

        if (
            (entry.name or "").casefold()
            != wanted.casefold()
        ):

            continue

        if cutoff is not None:

            if (
                not entry.create_time
                or entry.create_time
                > cutoff + PID_REUSE_TOLERANCE_SECONDS
            ):

                # The PID now belongs to a process that did not exist
                # when the capture finished; treat it as PID reuse.
                continue

        if not entry.path_accessible:

            continue

        key = entry.normalized_path

        if not key or key in seen_paths:

            continue

        seen_paths.add(key)
        paths.append(entry.exe.strip())

    return paths


def remember_capture_target(
    settings,
    target,
    csv_path,
    entries=None,
    last_success=None,
    created_before=None,
) -> list:
    """Record the path(s) of a just-captured executable.

    If the process already exited, its path is inaccessible, settings
    are unavailable, or a PID was reused after the capture, the memory
    is left unchanged.
    """

    try:

        if entries is None:

            entries = collect_processes(
                window_lookup=lambda: {}
            )

        else:

            entries = list(entries)

    except (
        OSError,
        TypeError,
        ValueError,
        psutil.Error,
    ) as error:

        logger.debug(
            "cannot enumerate the captured target: %s",
            error,
        )

        return []

    pids = read_process_ids(csv_path)
    paths = resolve_target_paths(
        target,
        entries,
        pids,
        created_before=created_before,
    )

    if not paths:

        return []

    try:

        existing = settings.successful_targets

    except (
        AttributeError,
        OSError,
        TypeError,
        ValueError,
    ) as error:

        logger.debug(
            "cannot read successful targets: %s",
            error,
        )

        return []

    updated = existing

    for path in paths:

        updated = remember_successful_target(
            updated,
            ntpath.basename(path),
            path,
            last_success,
        )

    if updated == existing:

        return updated

    try:

        settings.set_successful_targets(updated)

    except (
        AttributeError,
        OSError,
        TypeError,
        ValueError,
    ) as error:

        logger.debug(
            "cannot write successful targets: %s",
            error,
        )

        return []

    return updated
