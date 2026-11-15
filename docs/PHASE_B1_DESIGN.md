# Phase B-1 Design: Process Catalog, Ranking and Path Memory

Date: 2026-11-12
Status: implementation complete, awaiting manual review.

## Scope

B-1 is the headless data layer for Phase B:

- enumerate running executables with best-effort metadata;
- rank them with explainable signals;
- remember successful targets by executable path.

It does not add the process-selection dialog (B-2), main-window
integration or localized text (B-3). It does not change the PresentMon
capture pipeline, frame statistics or swap-chain selection.

## Module API

New module: `process_catalog.py`.

| API | Responsibility |
|---|---|
| `ProcessEntry` | One running executable: PID, name, path, user, memory, create time, visible-window title. |
| `Recommendation` | Entry plus score, reason parts and `recommended` flag. |
| `collect_processes()` | Enumerate executables; per-process failures are skipped. |
| `visible_window_titles()` | Best-effort Win32 visible top-level window map. |
| `is_system_executable()` | Path-based Windows shell/system filter. |
| `rank_processes()` | Score, explain and sort all entries deterministically. |
| `remembered_by_path()` | Index settings memory by normalized path; latest timestamp wins. |
| `remember_successful_target()` | Add/update one path memory record. |
| `update_successful_targets()` | Read/update/persist through `AppSettings`, safely. |
| `read_process_ids()` | Read every unique positive ProcessID from a capture CSV. |
| `read_process_id()` | Convenience wrapper returning the first positive ProcessID. |
| `resolve_target_paths()` | Verify the captured PIDs against running processes; no name fallback. |
| `remember_capture_target()` | Record only paths verified by captured PIDs. |

## Enumeration and graceful degradation

- Fields: `pid`, `name`, `exe`, `username`, `memory_info`, `create_time`.
- Only `.exe` processes are included; the current LagLens PID is excluded.
- A process with an inaccessible path is kept with `exe=""` and
  `path_accessible == False`, so it still appears in the all-processes
  list without breaking path matching.
- `psutil.AccessDenied`, `NoSuchProcess`, `ZombieProcess` and other
  process errors are handled per process; one protected process cannot
  abort a refresh.
- Window lookup failure returns an empty map; enumeration continues
  without window hints.
- Settings read/write failures leave memory unchanged and never raise.

## Scoring (explainable)

| Signal | Score | Reason key |
|---|---:|---|
| Exact executable path in successful memory | +100 | `process.reason.remembered` |
| Visible top-level window | +40 | `process.reason.window` or `process.reason.visible` |
| Non-empty window title | +5 | included in `process.reason.window` |
| Process uses at least 512 MiB RAM | +10 | `process.reason.memory` |

`RECOMMENDED_MIN_SCORE` is 40, so a visible window or a remembered path
is enough; memory alone is not. A process running from a Windows system
path (`System32`, `SysWOW64`, `SystemApps`, `ImmersiveControlPanel`, or
`explorer.exe`) is never marked recommended, but it still appears in
the complete ranked list for the all-processes view.

Sorting is deterministic: score descending, visible window first, then
case-insensitive executable name, then PID.

The executable name is not a positive game signal. Path memory, visible
windows and memory use are the signals; the path-based system filter is
the only name-independent exclusion.

## Successful-target memory

Stored schema, one record per normalized path:

```json
{
  "path": "D:\\Games\\Game.exe",
  "executable": "Game.exe",
  "last_success": "2026-11-12T01:00:00"
}
```

Rules:

- The key is the normalized executable path, never a PID.
- Every unique positive `ProcessID` in the capture CSV is collected and
  used transiently to resolve the executable path of the process that
  actually produced frames; PIDs are never persisted.
- A PID is accepted only if it still belongs to a running process with
  the expected executable name and an accessible path. A missing
  process (exited early), a stale/reused PID, a name mismatch or an
  inaccessible path is skipped.
- There is no name-only fallback. Two processes with the same name at
  different paths are not treated as the same success; only paths
  verified by captured PIDs are written.
- Multiple captured PIDs store each verified path; duplicate paths are
  deduplicated.
- Updating the same path refreshes `last_success` instead of adding a
  duplicate.
- At most `MAX_REMEMBERED_TARGETS` (50) records are kept.
- Existing records are cleaned to the three-field schema; an accidental
  `pid` field is stripped.

## Verification

New tests: `tests/test_process_catalog.py`, 63 tests covering path
normalization, enumeration degradation, ranking, system filtering,
memory round-trips, CSV PID reading, same-name/different-path targets,
multiple PIDs, early process exit, stale PIDs, path resolution and
failure handling.

Full suite: **269 tests passing** (206 existing + 63 new).

Real-machine probe on 2026-11-12:

- 300 executables enumerated; all 300 paths accessible in this run.
- 10 processes had visible top-level windows.
- 6 were recommended after the system-path filter.
- Remembering `<game-path>\game.exe` moved it to the top with score
  145 and `recommended == True`.

This probe validated real `psutil`/Win32 enumeration; it is not a
replacement for the automated tests.

## Known limits

- Recommendation is a heuristic, not a game database. A user
  application with a visible window (for example Chrome) can appear in
  the recommended list.
- Only visible top-level windows are detected; a hidden or minimized
  game may rely on path memory instead.
- Memory verification needs the captured process to still be running
  when the success is recorded. If it exits immediately after capture,
  no path is written; this is intentional rather than guessing from the
  name.
- Window titles are raw system text; some legacy windows return
  mojibake. B-2 should display them as-is, not use them for guessing.

## Next steps

- **B-2:** selection dialog with Recommended/All, live search, refresh,
  and columns for name, PID, path and localized recommendation reason.
- **B-3:** wire the dialog into the main window, add the four reason
  keys to both catalogs, call `remember_capture_target()` after a
  successful capture, and add launcher/renderer guidance without
  auto-selecting a process.
