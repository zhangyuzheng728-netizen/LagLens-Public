"""B-1: process catalog, explainable ranking and path memory tests."""

import tempfile
import unittest

from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import process_catalog as catalog


def make_entry(pid=1, name="Game.exe", exe=r"D:\Games\Game.exe", **kwargs):

    return catalog.ProcessEntry(
        pid=pid,
        name=name,
        exe=exe,
        **kwargs,
    )


class FakeProcess:

    def __init__(self, **info):

        self.info = info


class DeniedProcess:

    @property
    def info(self):

        import psutil

        raise psutil.AccessDenied(pid=1)


class FakeSettings:

    def __init__(
        self,
        targets=None,
        fail_get=False,
        fail_set=False,
    ):

        self._targets = list(targets or [])
        self.fail_get = fail_get
        self.fail_set = fail_set
        self.writes = []

    @property
    def successful_targets(self):

        if self.fail_get:

            raise OSError("settings unavailable")

        return [dict(item) for item in self._targets]

    def set_successful_targets(self, targets):

        if self.fail_set:

            raise OSError("settings unavailable")

        self._targets = [dict(item) for item in targets]
        self.writes.append(
            [dict(item) for item in targets]
        )


class NormalizePathTests(unittest.TestCase):

    def test_windows_paths_compare_case_and_separator_insensitively(self):

        first = catalog.normalize_path(
            r"D:\Games\Game.exe"
        )
        second = catalog.normalize_path(
            "d:/games/GAME.exe"
        )

        self.assertEqual(first, second)

    def test_empty_and_missing_paths_normalise_to_empty(self):

        self.assertEqual(catalog.normalize_path(""), "")
        self.assertEqual(catalog.normalize_path(None), "")
        self.assertEqual(catalog.normalize_path("   "), "")

    def test_quoted_path_is_accepted(self):

        self.assertEqual(
            catalog.normalize_path(
                r'"D:\Games\Game.exe"'
            ),
            catalog.normalize_path(
                r"D:\Games\Game.exe"
            ),
        )

    def test_entry_reports_whether_the_path_is_accessible(self):

        accessible = make_entry()
        inaccessible = make_entry(exe="")
        missing = make_entry(exe=None)

        self.assertTrue(accessible.path_accessible)
        self.assertFalse(inaccessible.path_accessible)
        self.assertFalse(missing.path_accessible)
        self.assertEqual(
            accessible.normalized_path,
            catalog.normalize_path(accessible.exe),
        )

    def test_system_executable_detection_is_path_based(self):

        system_paths = [
            r"C:\Windows\System32\ApplicationFrameHost.exe",
            r"C:\Windows\SysWOW64\rundll32.exe",
            r"C:\Windows\SystemApps\ShellExperienceHost.exe",
            r"C:\Windows\ImmersiveControlPanel\SystemSettings.exe",
            r"C:\Windows\explorer.exe",
        ]

        for path in system_paths:

            self.assertTrue(
                catalog.is_system_executable(
                    path,
                    system_root=r"C:\Windows",
                ),
                path,
            )

        self.assertFalse(
            catalog.is_system_executable(
                r"D:\Games\Game.exe",
                system_root=r"C:\Windows",
            )
        )
        self.assertFalse(
            catalog.is_system_executable(
                "",
                system_root=r"C:\Windows",
            )
        )

    def test_system_root_override_is_supported(self):

        self.assertTrue(
            catalog.is_system_executable(
                r"E:\Windows\System32\game.exe",
                system_root=r"E:\Windows",
            )
        )
        self.assertFalse(
            catalog.is_system_executable(
                r"E:\Windows\System32\game.exe",
                system_root=r"D:\Windows",
            )
        )


class CollectProcessesTests(unittest.TestCase):

    def collect(self, processes, windows=None, current_pid=999):

        return catalog.collect_processes(
            process_iter_factory=lambda fields: iter(processes),
            window_lookup=lambda: (windows or {}),
            current_pid=current_pid,
        )

    def test_keeps_exe_processes_and_marks_the_visible_window(self):

        processes = [
            FakeProcess(
                pid=10,
                name="Game.exe",
                exe=r"D:\Games\Game.exe",
                username="player",
                memory_info=SimpleNamespace(rss=2048),
                create_time=123.0,
            ),
        ]

        entries = self.collect(
            processes,
            windows={10: "Game Window"},
        )

        self.assertEqual(len(entries), 1)

        entry = entries[0]

        self.assertEqual(entry.pid, 10)
        self.assertEqual(entry.name, "Game.exe")
        self.assertEqual(entry.exe, r"D:\Games\Game.exe")
        self.assertEqual(entry.username, "player")
        self.assertEqual(entry.memory_bytes, 2048)
        self.assertEqual(entry.create_time, 123.0)
        self.assertTrue(entry.has_window)
        self.assertEqual(entry.window_title, "Game Window")

    def test_skips_self_non_exe_and_invalid_pids(self):

        processes = [
            FakeProcess(pid=999, name="LagLens.exe", exe=r"D:\LagLens.exe"),
            FakeProcess(pid=11, name="notepad", exe=""),
            FakeProcess(pid=0, name="System Idle Process", exe=""),
            FakeProcess(pid=12, name="Game.exe", exe=r"D:\Games\Game.exe"),
        ]

        entries = self.collect(processes)

        self.assertEqual(
            [entry.pid for entry in entries],
            [12],
        )

    def test_inaccessible_path_is_kept_and_degrades_gracefully(self):

        processes = [
            FakeProcess(
                pid=20,
                name="Protected.exe",
                exe=None,
                username=None,
                memory_info=None,
                create_time=None,
            ),
        ]

        entries = self.collect(processes)

        self.assertEqual(len(entries), 1)
        self.assertFalse(entries[0].path_accessible)
        self.assertEqual(entries[0].memory_bytes, 0)
        self.assertEqual(entries[0].create_time, 0.0)

    def test_access_denied_process_is_skipped_without_failing(self):

        processes = [
            DeniedProcess(),
            FakeProcess(pid=12, name="Game.exe", exe=r"D:\Games\Game.exe"),
        ]

        entries = self.collect(processes)

        self.assertEqual(
            [entry.pid for entry in entries],
            [12],
        )

    def test_iterator_failure_returns_an_empty_list(self):

        def broken_factory(fields):

            raise OSError("process enumeration failed")

        entries = catalog.collect_processes(
            process_iter_factory=broken_factory,
            window_lookup=lambda: {},
            current_pid=999,
        )

        self.assertEqual(entries, [])

    def test_window_lookup_failure_does_not_break_enumeration(self):

        def broken_windows():

            raise OSError("user32 unavailable")

        entries = catalog.collect_processes(
            process_iter_factory=lambda fields: iter(
                [
                    FakeProcess(
                        pid=12,
                        name="Game.exe",
                        exe=r"D:\Games\Game.exe",
                    )
                ]
            ),
            window_lookup=broken_windows,
            current_pid=999,
        )

        self.assertEqual(len(entries), 1)
        self.assertFalse(entries[0].has_window)

    def test_name_without_extension_uses_the_executable_basename(self):

        entries = self.collect(
            [
                FakeProcess(
                    pid=13,
                    name="Game",
                    exe=r"D:\Games\Game.exe",
                )
            ]
        )

        self.assertEqual(entries[0].name, "Game.exe")

    def test_results_are_sorted_by_name_then_pid(self):

        entries = self.collect(
            [
                FakeProcess(pid=3, name="Beta.exe", exe=r"D:\Beta.exe"),
                FakeProcess(pid=2, name="alpha.exe", exe=r"D:\alpha.exe"),
                FakeProcess(pid=1, name="Alpha.exe", exe=r"E:\Alpha.exe"),
            ]
        )

        self.assertEqual(
            [(entry.name, entry.pid) for entry in entries],
            [("Alpha.exe", 1), ("alpha.exe", 2), ("Beta.exe", 3)],
        )


class RankingTests(unittest.TestCase):

    def test_remembered_path_is_the_strongest_signal(self):

        ranked = catalog.rank_processes(
            [
                make_entry(
                    pid=1,
                    exe=r"D:\Games\New.exe",
                    has_window=True,
                    window_title="New Game",
                    memory_bytes=4 * 1024**3,
                ),
                make_entry(
                    pid=2,
                    exe=r"D:\Games\Old.exe",
                    has_window=False,
                ),
            ],
            remembered_targets=[
                {
                    "path": r"d:/games/OLD.exe",
                    "executable": "Old.exe",
                    "last_success": "2026-11-12T01:00:00",
                }
            ],
        )

        self.assertEqual(ranked[0].entry.pid, 2)
        self.assertGreaterEqual(
            ranked[0].score,
            catalog.RECOMMENDED_MIN_SCORE,
        )
        self.assertEqual(
            ranked[0].reasons[0][0],
            "process.reason.remembered",
        )

    def test_visible_window_and_memory_are_explained(self):

        ranked = catalog.rank_processes(
            [
                make_entry(
                    pid=1,
                    memory_bytes=(
                        catalog.LARGE_MEMORY_BYTES
                        + 1024**2
                    ),
                    has_window=True,
                    window_title="Big Game",
                )
            ]
        )

        reasons = dict(ranked[0].reasons)

        self.assertIn("process.reason.window", reasons)
        self.assertIn("process.reason.memory", reasons)
        self.assertEqual(
            reasons["process.reason.window"]["title"],
            "Big Game",
        )
        self.assertEqual(
            reasons["process.reason.memory"]["mib"],
            catalog.LARGE_MEMORY_BYTES // 1024**2 + 1,
        )
        self.assertTrue(ranked[0].recommended)

    def test_same_executable_name_at_another_path_is_not_remembered(self):

        ranked = catalog.rank_processes(
            [
                make_entry(
                    pid=1,
                    exe=r"D:\Games\Game.exe",
                )
            ],
            remembered_targets=[
                {
                    "path": r"E:\Other\Game.exe",
                    "executable": "Game.exe",
                    "last_success": "2026-11-12T01:00:00",
                }
            ],
        )

        self.assertEqual(ranked[0].score, 0)
        self.assertFalse(ranked[0].recommended)
        self.assertEqual(ranked[0].reasons, ())

    def test_recommendation_threshold_requires_a_real_signal(self):

        ranked = catalog.rank_processes(
            [
                make_entry(pid=1, has_window=False),
                make_entry(
                    pid=2,
                    has_window=True,
                    window_title="Window",
                ),
            ]
        )

        by_pid = {
            item.entry.pid: item
            for item in ranked
        }

        self.assertFalse(by_pid[1].recommended)
        self.assertTrue(by_pid[2].recommended)

    def test_system_visible_process_is_not_recommended(self):

        ranked = catalog.rank_processes(
            [
                make_entry(
                    pid=1,
                    exe=(
                        r"C:\Windows\System32"
                        r"\ApplicationFrameHost.exe"
                    ),
                    name="ApplicationFrameHost.exe",
                    has_window=True,
                    window_title="Settings",
                )
            ]
        )

        self.assertGreaterEqual(
            ranked[0].score,
            catalog.RECOMMENDED_MIN_SCORE,
        )
        self.assertFalse(ranked[0].recommended)

    def test_user_visible_process_is_recommended(self):

        ranked = catalog.rank_processes(
            [
                make_entry(
                    pid=1,
                    exe=r"D:\Games\Game.exe",
                    has_window=True,
                    window_title="Game",
                )
            ]
        )

        self.assertTrue(ranked[0].recommended)

    def test_sorting_is_deterministic_for_equal_scores(self):

        ranked = catalog.rank_processes(
            [
                make_entry(pid=5, name="Beta.exe"),
                make_entry(pid=4, name="alpha.exe"),
                make_entry(pid=3, name="Alpha.exe"),
            ]
        )

        self.assertEqual(
            [item.entry.pid for item in ranked],
            [3, 4, 5],
        )

    def test_empty_last_success_is_still_a_memory_reason(self):

        ranked = catalog.rank_processes(
            [make_entry(pid=1)],
            remembered_targets=[
                {
                    "path": r"D:\Games\Game.exe",
                    "executable": "Game.exe",
                    "last_success": "",
                }
            ],
        )

        self.assertEqual(
            ranked[0].reasons[0][0],
            "process.reason.remembered",
        )
        self.assertEqual(
            ranked[0].reasons[0][1]["last_success"],
            "",
        )

    def test_invalid_remembered_records_are_ignored(self):

        ranked = catalog.rank_processes(
            [make_entry(pid=1)],
            remembered_targets=[
                "not a dict",
                {"path": "", "executable": "Game.exe"},
                {"path": None, "executable": "Game.exe"},
            ],
        )

        self.assertEqual(ranked[0].score, 0)

    def test_missing_executable_is_derived_from_the_path(self):

        ranked = catalog.rank_processes(
            [make_entry(pid=1)],
            remembered_targets=[
                {
                    "path": r"D:\Games\Game.exe",
                    "last_success": "2026-11-12T01:00:00",
                }
            ],
        )

        self.assertEqual(ranked[0].score, 100)
        self.assertEqual(
            ranked[0].reasons[0][0],
            "process.reason.remembered",
        )

    def test_duplicate_remembered_paths_use_the_latest_timestamp(self):

        ranked = catalog.rank_processes(
            [make_entry(pid=1)],
            remembered_targets=[
                {
                    "path": r"D:\Games\Game.exe",
                    "executable": "Game.exe",
                    "last_success": "2026-01-01T00:00:00",
                },
                {
                    "path": r"d:/games/game.exe",
                    "executable": "Game.exe",
                    "last_success": "2026-11-12T00:00:00",
                },
            ],
        )

        self.assertEqual(
            ranked[0].reasons[0][1]["last_success"],
            "2026-11-12T00:00:00",
        )


class RendererHintTests(unittest.TestCase):

    def test_no_similar_names_is_not_suspected(self):

        hint = catalog.renderer_hint(
            "Game.exe",
            [],
            [make_entry(pid=1)],
        )

        self.assertFalse(hint.suspected)
        self.assertEqual(hint.suggested, "")

    def test_target_without_a_window_and_visible_similar_is_suspected(self):

        hint = catalog.renderer_hint(
            "Palworld.exe",
            ["Palworld-Win64-Shipping.exe"],
            [
                make_entry(
                    pid=1,
                    name="Palworld.exe",
                    exe=r"D:\Games\Palworld.exe",
                ),
                make_entry(
                    pid=2,
                    name="Palworld-Win64-Shipping.exe",
                    exe=(
                        r"D:\Games"
                        r"\Palworld-Win64-Shipping.exe"
                    ),
                    has_window=True,
                    window_title="Palworld",
                ),
            ],
        )

        self.assertTrue(hint.suspected)
        self.assertEqual(
            hint.suggested,
            "Palworld-Win64-Shipping.exe",
        )
        self.assertTrue(hint.target_visible is False)

    def test_target_with_a_window_is_not_suspected(self):

        hint = catalog.renderer_hint(
            "Palworld-Win64-Shipping.exe",
            ["Palworld.exe"],
            [
                make_entry(
                    pid=2,
                    name="Palworld-Win64-Shipping.exe",
                    exe=(
                        r"D:\Games"
                        r"\Palworld-Win64-Shipping.exe"
                    ),
                    has_window=True,
                    window_title="Palworld",
                ),
                make_entry(
                    pid=1,
                    name="Palworld.exe",
                    exe=r"D:\Games\Palworld.exe",
                ),
            ],
        )

        self.assertFalse(hint.suspected)
        self.assertEqual(hint.suggested, "")

    def test_visible_similar_is_preferred_over_hidden_similar(self):

        hint = catalog.renderer_hint(
            "Launcher.exe",
            ["BigHidden.exe", "SmallVisible.exe"],
            [
                make_entry(
                    pid=1,
                    name="Launcher.exe",
                    exe=r"D:\Games\Launcher.exe",
                ),
                make_entry(
                    pid=2,
                    name="BigHidden.exe",
                    exe=r"D:\Games\BigHidden.exe",
                    memory_bytes=8 * 1024**3,
                ),
                make_entry(
                    pid=3,
                    name="SmallVisible.exe",
                    exe=r"D:\Games\SmallVisible.exe",
                    has_window=True,
                    window_title="Game",
                    memory_bytes=1024**2,
                ),
            ],
        )

        self.assertEqual(hint.suggested, "SmallVisible.exe")

    def test_visible_similar_with_more_memory_is_preferred(self):

        hint = catalog.renderer_hint(
            "Launcher.exe",
            ["First.exe", "Second.exe"],
            [
                make_entry(
                    pid=1,
                    name="Launcher.exe",
                    exe=r"D:\Games\Launcher.exe",
                ),
                make_entry(
                    pid=2,
                    name="First.exe",
                    exe=r"D:\Games\First.exe",
                    has_window=True,
                    window_title="First",
                    memory_bytes=1024**3,
                ),
                make_entry(
                    pid=3,
                    name="Second.exe",
                    exe=r"D:\Games\Second.exe",
                    has_window=True,
                    window_title="Second",
                    memory_bytes=4 * 1024**3,
                ),
            ],
        )

        self.assertEqual(hint.suggested, "Second.exe")

    def test_similar_names_are_deduplicated_case_insensitively(self):

        hint = catalog.renderer_hint(
            "Launcher.exe",
            ["Renderer.exe", "renderer.EXE"],
            [
                make_entry(
                    pid=1,
                    name="Launcher.exe",
                    exe=r"D:\Games\Launcher.exe",
                ),
            ],
        )

        self.assertEqual(
            hint.similar,
            ("Renderer.exe",),
        )

    def test_missing_target_is_suspected_when_similar_is_running(self):

        hint = catalog.renderer_hint(
            "Launcher.exe",
            ["Renderer.exe"],
            [
                make_entry(
                    pid=2,
                    name="Renderer.exe",
                    exe=r"D:\Games\Renderer.exe",
                    has_window=True,
                    window_title="Game",
                ),
            ],
        )

        self.assertTrue(hint.suspected)
        self.assertEqual(hint.suggested, "Renderer.exe")


class MemoryTests(unittest.TestCase):

    def test_new_success_stores_only_path_executable_and_timestamp(self):

        updated = catalog.remember_successful_target(
            [],
            "Game.exe",
            r"D:\Games\Game.exe",
            "2026-11-12T01:00:00",
        )

        self.assertEqual(
            updated,
            [
                {
                    "path": r"D:\Games\Game.exe",
                    "executable": "Game.exe",
                    "last_success": "2026-11-12T01:00:00",
                }
            ],
        )
        self.assertNotIn("pid", updated[0])

    def test_same_path_is_updated_not_duplicated(self):

        updated = catalog.remember_successful_target(
            [
                {
                    "path": r"D:\Games\Game.exe",
                    "executable": "Game.exe",
                    "last_success": "2026-01-01T00:00:00",
                }
            ],
            "Game.exe",
            r"d:/games/GAME.exe",
            "2026-11-12T01:00:00",
        )

        self.assertEqual(len(updated), 1)
        self.assertEqual(
            updated[0]["last_success"],
            "2026-11-12T01:00:00",
        )

    def test_inaccessible_path_does_not_change_the_memory(self):

        existing = [
            {
                "path": r"D:\Games\Game.exe",
                "executable": "Game.exe",
                "last_success": "2026-01-01T00:00:00",
            }
        ]

        self.assertEqual(
            catalog.remember_successful_target(
                existing,
                "Game.exe",
                "",
                "2026-11-12T01:00:00",
            ),
            existing,
        )
        self.assertEqual(
            catalog.remember_successful_target(
                existing,
                "Game.exe",
                None,
                "2026-11-12T01:00:00",
            ),
            existing,
        )

    def test_memory_is_capped_and_keeps_the_newest_entry(self):

        existing = [
            {
                "path": rf"D:\Games\Game{index}.exe",
                "executable": f"Game{index}.exe",
                "last_success": f"2026-01-{index + 1:02d}T00:00:00",
            }
            for index in range(
                catalog.MAX_REMEMBERED_TARGETS
            )
        ]

        updated = catalog.remember_successful_target(
            existing,
            "New.exe",
            r"D:\Games\New.exe",
            "2026-11-12T01:00:00",
        )

        self.assertEqual(
            len(updated),
            catalog.MAX_REMEMBERED_TARGETS,
        )
        self.assertEqual(
            updated[0]["executable"],
            "New.exe",
        )

    def test_invalid_existing_records_are_cleaned(self):

        updated = catalog.remember_successful_target(
            [
                "not a dict",
                {"path": "", "executable": "Bad.exe"},
                {
                    "path": r"D:\Games\Game.exe",
                    "executable": "Game.exe",
                    "last_success": "2026-01-01T00:00:00",
                    "pid": 1234,
                },
            ],
            "New.exe",
            r"D:\Games\New.exe",
            "2026-11-12T01:00:00",
        )

        self.assertEqual(len(updated), 2)
        self.assertEqual(
            set(updated[1]),
            {"path", "executable", "last_success"},
        )
        self.assertNotIn("pid", updated[1])

    def test_update_settings_persists_the_new_record(self):

        settings = FakeSettings()

        updated = catalog.update_successful_targets(
            settings,
            "Game.exe",
            r"D:\Games\Game.exe",
            "2026-11-12T01:00:00",
        )

        self.assertEqual(len(updated), 1)
        self.assertEqual(len(settings.writes), 1)
        self.assertEqual(
            settings.successful_targets[0]["path"],
            r"D:\Games\Game.exe",
        )

    def test_update_settings_is_safe_when_reading_fails(self):

        settings = FakeSettings(fail_get=True)

        updated = catalog.update_successful_targets(
            settings,
            "Game.exe",
            r"D:\Games\Game.exe",
            "2026-11-12T01:00:00",
        )

        self.assertEqual(updated, [])
        self.assertEqual(settings.writes, [])

    def test_update_settings_is_safe_when_writing_fails(self):

        settings = FakeSettings(fail_set=True)

        updated = catalog.update_successful_targets(
            settings,
            "Game.exe",
            r"D:\Games\Game.exe",
            "2026-11-12T01:00:00",
        )

        self.assertEqual(updated, [])
        self.assertEqual(settings.writes, [])


class ReadProcessIdTests(unittest.TestCase):

    def write_csv(self, folder, text, name="capture.csv"):

        path = Path(folder) / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_reads_the_first_valid_process_id(self):

        with tempfile.TemporaryDirectory() as folder:

            path = self.write_csv(
                folder,
                "\ufeffApplication,ProcessID,FrameTime\n"
                "game.exe,not-a-pid,16.7\n"
                "game.exe,4321,16.7\n"
                "game.exe,9999,16.7\n",
            )

            self.assertEqual(
                catalog.read_process_id(path),
                4321,
            )

    def test_missing_process_id_column_returns_none(self):

        with tempfile.TemporaryDirectory() as folder:

            path = self.write_csv(
                folder,
                "Application,FrameTime\ngame.exe,16.7\n",
            )

            self.assertIsNone(
                catalog.read_process_id(path)
            )

    def test_empty_and_missing_files_return_none(self):

        with tempfile.TemporaryDirectory() as folder:

            empty = self.write_csv(folder, "")

            self.assertIsNone(
                catalog.read_process_id(empty)
            )
            self.assertIsNone(
                catalog.read_process_id(
                    Path(folder) / "missing.csv"
                )
            )

    def test_directory_path_returns_none(self):

        with tempfile.TemporaryDirectory() as folder:

            self.assertIsNone(
                catalog.read_process_id(folder)
            )

    def test_non_positive_pids_are_skipped(self):

        with tempfile.TemporaryDirectory() as folder:

            path = self.write_csv(
                folder,
                "Application,ProcessID,FrameTime\n"
                "game.exe,0,16.7\n"
                "game.exe,-1,16.7\n"
                "game.exe,7,16.7\n",
            )

            self.assertEqual(
                catalog.read_process_id(path),
                7,
            )


class ReadProcessIdsTests(unittest.TestCase):

    def write_csv(self, folder, text, name="capture.csv"):

        path = Path(folder) / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_collects_unique_positive_ids_in_first_seen_order(self):

        with tempfile.TemporaryDirectory() as folder:

            path = self.write_csv(
                folder,
                "\ufeffApplication,ProcessID,FrameTime\n"
                "game.exe,4321,16.7\n"
                "game.exe,9999,16.7\n"
                "game.exe,4321,16.7\n"
                "game.exe,not-a-pid,16.7\n"
                "game.exe,0,16.7\n"
                "game.exe,-1,16.7\n",
            )

            self.assertEqual(
                catalog.read_process_ids(path),
                [4321, 9999],
            )

    def test_missing_process_id_column_returns_empty(self):

        with tempfile.TemporaryDirectory() as folder:

            path = self.write_csv(
                folder,
                "Application,FrameTime\ngame.exe,16.7\n",
            )

            self.assertEqual(
                catalog.read_process_ids(path),
                [],
            )

    def test_empty_and_missing_files_return_empty(self):

        with tempfile.TemporaryDirectory() as folder:

            empty = self.write_csv(folder, "")

            self.assertEqual(
                catalog.read_process_ids(empty),
                [],
            )
            self.assertEqual(
                catalog.read_process_ids(
                    Path(folder) / "missing.csv"
                ),
                [],
            )

    def test_directory_path_returns_empty(self):

        with tempfile.TemporaryDirectory() as folder:

            self.assertEqual(
                catalog.read_process_ids(folder),
                [],
            )


class ResolveTargetPathsTests(unittest.TestCase):

    def test_only_the_captured_pid_path_is_returned(self):

        entries = [
            make_entry(pid=1, exe=r"D:\Games\Game.exe"),
            make_entry(pid=2, exe=r"E:\Copy\Game.exe"),
        ]

        self.assertEqual(
            catalog.resolve_target_paths(
                "Game.exe",
                entries,
                pids=[2],
            ),
            [r"E:\Copy\Game.exe"],
        )

    def test_multiple_captured_pids_return_each_path(self):

        entries = [
            make_entry(pid=1, exe=r"D:\Games\Game.exe"),
            make_entry(pid=2, exe=r"E:\Copy\Game.exe"),
            make_entry(pid=3, exe=r"F:\Backup\Game.exe"),
        ]

        self.assertEqual(
            catalog.resolve_target_paths(
                "Game.exe",
                entries,
                pids=[2, 3],
            ),
            [r"E:\Copy\Game.exe", r"F:\Backup\Game.exe"],
        )

    def test_duplicate_pids_are_deduplicated(self):

        entries = [
            make_entry(pid=2, exe=r"E:\Copy\Game.exe"),
        ]

        self.assertEqual(
            catalog.resolve_target_paths(
                "Game.exe",
                entries,
                pids=[2, 2, "2"],
            ),
            [r"E:\Copy\Game.exe"],
        )

    def test_there_is_no_name_only_fallback(self):

        entries = [
            make_entry(pid=1, name="Game.exe", exe=r"D:\Games\Game.exe"),
        ]

        self.assertEqual(
            catalog.resolve_target_paths(
                "Game.exe",
                entries,
                pids=[],
            ),
            [],
        )

    def test_pid_with_a_different_process_name_is_skipped(self):

        entries = [
            make_entry(pid=2, name="Other.exe", exe=r"D:\Other\Other.exe"),
        ]

        self.assertEqual(
            catalog.resolve_target_paths(
                "Game.exe",
                entries,
                pids=[2],
            ),
            [],
        )

    def test_full_target_path_is_normalized_to_the_executable_name(self):

        entries = [
            make_entry(pid=1, name="Game.exe", exe=r"D:\Games\Game.exe"),
        ]

        self.assertEqual(
            catalog.resolve_target_paths(
                r"C:\Somewhere\game.EXE",
                entries,
                pids=[1],
            ),
            [r"D:\Games\Game.exe"],
        )

    def test_inaccessible_paths_are_skipped(self):

        entries = [
            make_entry(pid=1, exe=""),
        ]

        self.assertEqual(
            catalog.resolve_target_paths(
                "Game.exe",
                entries,
                pids=[1],
            ),
            [],
        )

    def test_unknown_pid_returns_empty(self):

        self.assertEqual(
            catalog.resolve_target_paths(
                "Game.exe",
                [make_entry(pid=1)],
                pids=[99],
            ),
            [],
        )

    def test_invalid_pid_values_are_ignored(self):

        entries = [
            make_entry(pid=2, exe=r"E:\Copy\Game.exe"),
        ]

        self.assertEqual(
            catalog.resolve_target_paths(
                "Game.exe",
                entries,
                pids=["bad", None, 2],
            ),
            [r"E:\Copy\Game.exe"],
        )

    def test_process_created_after_the_capture_is_rejected_as_pid_reuse(self):

        entries = [
            make_entry(
                pid=2,
                exe=r"E:\Copy\Game.exe",
                create_time=1000.0,
            ),
        ]

        self.assertEqual(
            catalog.resolve_target_paths(
                "Game.exe",
                entries,
                pids=[2],
                created_before=100.0,
            ),
            [],
        )

    def test_process_created_before_the_capture_is_accepted(self):

        entries = [
            make_entry(
                pid=2,
                exe=r"E:\Copy\Game.exe",
                create_time=50.0,
            ),
        ]

        self.assertEqual(
            catalog.resolve_target_paths(
                "Game.exe",
                entries,
                pids=[2],
                created_before=100.0,
            ),
            [r"E:\Copy\Game.exe"],
        )

    def test_unknown_create_time_is_rejected_when_the_cutoff_is_set(self):

        entries = [
            make_entry(
                pid=2,
                exe=r"E:\Copy\Game.exe",
                create_time=0.0,
            ),
        ]

        self.assertEqual(
            catalog.resolve_target_paths(
                "Game.exe",
                entries,
                pids=[2],
                created_before=100.0,
            ),
            [],
        )

    def test_no_cutoff_keeps_the_legacy_path_resolution(self):

        entries = [
            make_entry(
                pid=2,
                exe=r"E:\Copy\Game.exe",
                create_time=0.0,
            ),
        ]

        self.assertEqual(
            catalog.resolve_target_paths(
                "Game.exe",
                entries,
                pids=[2],
            ),
            [r"E:\Copy\Game.exe"],
        )


class RememberCaptureTargetTests(unittest.TestCase):

    def write_capture(self, folder, process_ids=(1,)):

        if isinstance(process_ids, int):

            process_ids = [process_ids]

        path = Path(folder) / "capture.csv"
        path.write_text(
            "Application,ProcessID,FrameTime\n"
            + "".join(
                f"Game.exe,{pid},16.7\n"
                for pid in process_ids
            ),
            encoding="utf-8",
        )
        return path

    def test_successful_capture_stores_the_executable_path(self):

        with tempfile.TemporaryDirectory() as folder:

            csv_path = self.write_capture(folder, 2)
            settings = FakeSettings()
            entries = [
                make_entry(pid=2, exe=r"D:\Games\Game.exe"),
            ]

            updated = catalog.remember_capture_target(
                settings,
                "Game.exe",
                csv_path,
                entries=entries,
                last_success="2026-11-12T01:00:00",
            )

            self.assertEqual(
                updated[0]["path"],
                r"D:\Games\Game.exe",
            )
            self.assertNotIn("pid", updated[0])
            self.assertEqual(
                settings.successful_targets[0]["path"],
                r"D:\Games\Game.exe",
            )

    def test_same_name_other_path_is_not_stored(self):

        with tempfile.TemporaryDirectory() as folder:

            csv_path = self.write_capture(folder, 2)
            settings = FakeSettings()
            entries = [
                make_entry(pid=2, exe=r"D:\Games\Game.exe"),
                make_entry(pid=3, exe=r"E:\Copy\Game.exe"),
            ]

            updated = catalog.remember_capture_target(
                settings,
                "Game.exe",
                csv_path,
                entries=entries,
                last_success="2026-11-12T01:00:00",
            )

            self.assertEqual(
                [item["path"] for item in updated],
                [r"D:\Games\Game.exe"],
            )

    def test_multiple_captured_pids_store_each_verified_path(self):

        with tempfile.TemporaryDirectory() as folder:

            csv_path = self.write_capture(folder, [2, 3])
            settings = FakeSettings()
            entries = [
                make_entry(pid=2, exe=r"D:\Games\Game.exe"),
                make_entry(pid=3, exe=r"E:\Copy\Game.exe"),
                make_entry(pid=4, exe=r"F:\Other\Game.exe"),
            ]

            updated = catalog.remember_capture_target(
                settings,
                "Game.exe",
                csv_path,
                entries=entries,
                last_success="2026-11-12T01:00:00",
            )

            self.assertEqual(
                {item["path"] for item in updated},
                {
                    r"D:\Games\Game.exe",
                    r"E:\Copy\Game.exe",
                },
            )
            self.assertEqual(len(settings.writes), 1)

    def test_partial_pid_resolution_stores_only_verified_paths(self):

        with tempfile.TemporaryDirectory() as folder:

            csv_path = self.write_capture(folder, [2, 3])
            settings = FakeSettings()
            entries = [
                make_entry(pid=2, exe=r"D:\Games\Game.exe"),
            ]

            updated = catalog.remember_capture_target(
                settings,
                "Game.exe",
                csv_path,
                entries=entries,
                last_success="2026-11-12T01:00:00",
            )

            self.assertEqual(
                [item["path"] for item in updated],
                [r"D:\Games\Game.exe"],
            )

    def test_stale_pid_with_a_different_name_is_not_stored(self):

        with tempfile.TemporaryDirectory() as folder:

            csv_path = self.write_capture(folder, 2)
            settings = FakeSettings()
            entries = [
                make_entry(
                    pid=2,
                    name="Other.exe",
                    exe=r"D:\Other\Other.exe",
                ),
            ]

            updated = catalog.remember_capture_target(
                settings,
                "Game.exe",
                csv_path,
                entries=entries,
            )

            self.assertEqual(updated, [])
            self.assertEqual(settings.writes, [])

    def test_reused_pid_is_not_recorded_as_a_success(self):

        with tempfile.TemporaryDirectory() as folder:

            csv_path = self.write_capture(folder, 2)
            settings = FakeSettings()
            entries = [
                make_entry(
                    pid=2,
                    exe=r"D:\Games\Game.exe",
                    create_time=1000.0,
                ),
            ]

            updated = catalog.remember_capture_target(
                settings,
                "Game.exe",
                csv_path,
                entries=entries,
                created_before=100.0,
            )

            self.assertEqual(updated, [])
            self.assertEqual(settings.writes, [])

    def test_old_process_is_recorded_with_a_cutoff(self):

        with tempfile.TemporaryDirectory() as folder:

            csv_path = self.write_capture(folder, 2)
            settings = FakeSettings()
            entries = [
                make_entry(
                    pid=2,
                    exe=r"D:\Games\Game.exe",
                    create_time=50.0,
                ),
            ]

            updated = catalog.remember_capture_target(
                settings,
                "Game.exe",
                csv_path,
                entries=entries,
                created_before=100.0,
            )

            self.assertEqual(
                updated[0]["path"],
                r"D:\Games\Game.exe",
            )

    def test_missing_process_id_column_does_not_write(self):

        with tempfile.TemporaryDirectory() as folder:

            csv_path = Path(folder) / "capture.csv"
            csv_path.write_text(
                "Application,FrameTime\n"
                "Game.exe,16.7\n",
                encoding="utf-8",
            )
            settings = FakeSettings()
            entries = [
                make_entry(pid=2, exe=r"D:\Games\Game.exe"),
            ]

            updated = catalog.remember_capture_target(
                settings,
                "Game.exe",
                csv_path,
                entries=entries,
            )

            self.assertEqual(updated, [])
            self.assertEqual(settings.writes, [])

    def test_repeated_success_updates_the_same_path(self):

        with tempfile.TemporaryDirectory() as folder:

            csv_path = self.write_capture(folder, 2)
            settings = FakeSettings()
            entries = [
                make_entry(pid=2, exe=r"D:\Games\Game.exe"),
            ]

            catalog.remember_capture_target(
                settings,
                "Game.exe",
                csv_path,
                entries=entries,
                last_success="2026-01-01T00:00:00",
            )
            updated = catalog.remember_capture_target(
                settings,
                "Game.exe",
                csv_path,
                entries=entries,
                last_success="2026-11-12T01:00:00",
            )

            self.assertEqual(len(updated), 1)
            self.assertEqual(
                updated[0]["last_success"],
                "2026-11-12T01:00:00",
            )

    def test_inaccessible_process_path_does_not_write(self):

        with tempfile.TemporaryDirectory() as folder:

            csv_path = self.write_capture(folder, 2)
            settings = FakeSettings()
            entries = [
                make_entry(pid=2, exe=""),
            ]

            updated = catalog.remember_capture_target(
                settings,
                "Game.exe",
                csv_path,
                entries=entries,
            )

            self.assertEqual(updated, [])
            self.assertEqual(settings.writes, [])

    def test_exited_process_does_not_write(self):

        with tempfile.TemporaryDirectory() as folder:

            csv_path = self.write_capture(folder, 2)
            settings = FakeSettings()

            updated = catalog.remember_capture_target(
                settings,
                "Game.exe",
                csv_path,
                entries=[],
            )

            self.assertEqual(updated, [])
            self.assertEqual(settings.writes, [])

    def test_enumeration_failure_does_not_raise(self):

        with tempfile.TemporaryDirectory() as folder:

            csv_path = self.write_capture(folder, 2)
            settings = FakeSettings()

            with mock.patch.object(
                catalog,
                "collect_processes",
                side_effect=OSError("enumeration failed"),
            ):

                updated = catalog.remember_capture_target(
                    settings,
                    "Game.exe",
                    csv_path,
                )

            self.assertEqual(updated, [])
            self.assertEqual(settings.writes, [])

    def test_settings_read_failure_does_not_raise(self):

        with tempfile.TemporaryDirectory() as folder:

            csv_path = self.write_capture(folder, 2)
            settings = FakeSettings(fail_get=True)

            updated = catalog.remember_capture_target(
                settings,
                "Game.exe",
                csv_path,
                entries=[
                    make_entry(pid=2, exe=r"D:\Games\Game.exe"),
                ],
            )

            self.assertEqual(updated, [])
            self.assertEqual(settings.writes, [])

    def test_settings_write_failure_does_not_raise(self):

        with tempfile.TemporaryDirectory() as folder:

            csv_path = self.write_capture(folder, 2)
            settings = FakeSettings(fail_set=True)

            updated = catalog.remember_capture_target(
                settings,
                "Game.exe",
                csv_path,
                entries=[
                    make_entry(pid=2, exe=r"D:\Games\Game.exe"),
                ],
            )

            self.assertEqual(updated, [])
            self.assertEqual(settings.writes, [])


if __name__ == "__main__":

    unittest.main()
