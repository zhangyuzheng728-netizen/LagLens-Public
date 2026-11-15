"""A-1: persistent settings tests."""

import os
import tempfile
import unittest

from pathlib import Path
from unittest import mock

from PySide6.QtCore import QSettings

import settings


class SettingsTests(unittest.TestCase):

    def _path(self, folder):

        return Path(folder) / "LagLens.ini"

    def _raw(self, path):

        return QSettings(
            str(path),
            QSettings.Format.IniFormat,
        )

    def test_defaults(self):

        with tempfile.TemporaryDirectory() as folder:

            config = settings.AppSettings(
                self._path(folder)
            )

            self.assertEqual(
                config.language_mode,
                "system",
            )
            self.assertEqual(
                config.target_fps,
                settings.DEFAULT_TARGET_FPS,
            )
            self.assertEqual(
                config.successful_targets,
                [],
            )
            self.assertEqual(
                config.recent_captures,
                [],
            )
            self.assertFalse(
                config.onboarding_seen
            )

    def test_language_round_trip_and_restart(self):

        with tempfile.TemporaryDirectory() as folder:

            path = self._path(folder)

            first = settings.AppSettings(path)
            first.set_language_mode("zh_CN")

            second = settings.AppSettings(path)

            self.assertEqual(
                second.language_mode,
                "zh_CN",
            )

    def test_unknown_language_falls_back_safely(self):

        with tempfile.TemporaryDirectory() as folder:

            path = self._path(folder)
            raw = self._raw(path)
            raw.setValue(settings.LANGUAGE_KEY, "fr_FR")
            raw.sync()

            self.assertEqual(
                settings.AppSettings(path).language_mode,
                "system",
            )

    def test_invalid_language_is_rejected_on_write(self):

        with tempfile.TemporaryDirectory() as folder:

            config = settings.AppSettings(
                self._path(folder)
            )

            with self.assertRaises(ValueError):

                config.set_language_mode("fr_FR")

    def test_target_fps_round_trip(self):

        with tempfile.TemporaryDirectory() as folder:

            path = self._path(folder)

            config = settings.AppSettings(path)
            self.assertFalse(config.target_fps_explicit)
            config.set_target_fps(144)

            reloaded = settings.AppSettings(path)

            self.assertEqual(
                reloaded.target_fps,
                144,
            )
            self.assertTrue(
                reloaded.target_fps_explicit
            )

    def test_network_public_target_round_trip(self):

        with tempfile.TemporaryDirectory() as folder:

            path = self._path(folder)
            config = settings.AppSettings(path)

            self.assertEqual(
                config.network_public_target,
                settings.DEFAULT_NETWORK_PUBLIC_TARGET,
            )

            config.set_network_public_target("8.8.8.8")

            self.assertEqual(
                settings.AppSettings(
                    path
                ).network_public_target,
                "8.8.8.8",
            )

    def test_invalid_target_fps_falls_back(self):

        with tempfile.TemporaryDirectory() as folder:

            path = self._path(folder)

            for value in ("abc", 0, 5000, -1):

                raw = self._raw(path)
                raw.setValue(
                    settings.TARGET_FPS_KEY,
                    value,
                )
                raw.sync()

                self.assertEqual(
                    settings.AppSettings(path).target_fps,
                    settings.DEFAULT_TARGET_FPS,
                )

    def test_telemetry_interval_round_trip_and_defaults(self):

        with tempfile.TemporaryDirectory() as folder:

            path = self._path(folder)
            config = settings.AppSettings(path)

            self.assertEqual(
                config.telemetry_interval_ms,
                settings.DEFAULT_TELEMETRY_INTERVAL_MS,
            )

            config.set_telemetry_interval_ms(500)

            self.assertEqual(
                settings.AppSettings(
                    path
                ).telemetry_interval_ms,
                500,
            )

    def test_invalid_telemetry_interval_falls_back_or_raises(self):

        with tempfile.TemporaryDirectory() as folder:

            path = self._path(folder)
            raw = self._raw(path)

            for value in ("abc", 0, 99, 5001):
                raw.setValue(
                    settings.TELEMETRY_INTERVAL_KEY,
                    value,
                )
                raw.sync()

                self.assertEqual(
                    settings.AppSettings(
                        path
                    ).telemetry_interval_ms,
                    settings.DEFAULT_TELEMETRY_INTERVAL_MS,
                )

            with self.assertRaises(ValueError):

                settings.AppSettings(
                    path
                ).set_telemetry_interval_ms(99)

            with self.assertRaises(ValueError):

                settings.AppSettings(
                    path
                ).set_telemetry_interval_ms(5001)

    def test_successful_targets_round_trip_and_sanitising(self):

        with tempfile.TemporaryDirectory() as folder:

            path = self._path(folder)

            config = settings.AppSettings(path)

            config.set_successful_targets(
                [
                    {
                        "path": r"C:\Games\Palworld.exe",
                        "executable": "Palworld-Win64-Shipping.exe",
                        "last_success": "2026-11-12T01:00:00",
                    },
                    {
                        "path": r"C:\Games\Palworld.exe",
                        "executable": "duplicate.exe",
                    },
                    {"path": "", "executable": "bad.exe"},
                    "not a dict",
                ]
            )

            stored = settings.AppSettings(
                path
            ).successful_targets

            self.assertEqual(len(stored), 1)
            self.assertEqual(
                stored[0]["path"],
                r"C:\Games\Palworld.exe",
            )
            self.assertEqual(
                stored[0]["executable"],
                "Palworld-Win64-Shipping.exe",
            )

    def test_corrupt_targets_json_returns_empty(self):

        with tempfile.TemporaryDirectory() as folder:

            path = self._path(folder)
            raw = self._raw(path)
            raw.setValue(
                settings.SUCCESSFUL_TARGETS_KEY,
                "{ broken",
            )
            raw.sync()

            self.assertEqual(
                settings.AppSettings(
                    path
                ).successful_targets,
                [],
            )

    def test_recent_captures_round_trip_and_sanitising(self):

        with tempfile.TemporaryDirectory() as folder:

            path = self._path(folder)
            config = settings.AppSettings(path)

            config.set_recent_captures(
                [
                    {
                        "path": r"C:\Captures\one.csv",
                        "name": "one.csv",
                        "target": "game.exe",
                        "captured_at": "2026-11-12T10:00:00",
                        "frames": 120,
                        "telemetry": True,
                    },
                    {
                        "path": r"C:\Captures\one.csv",
                        "name": "duplicate.csv",
                    },
                    {"path": "", "name": "bad.csv"},
                    "not a dict",
                ]
            )

            stored = settings.AppSettings(
                path
            ).recent_captures

            self.assertEqual(len(stored), 1)
            self.assertEqual(
                stored[0]["path"],
                r"C:\Captures\one.csv",
            )
            self.assertEqual(stored[0]["name"], "one.csv")
            self.assertEqual(stored[0]["frames"], 120)
            self.assertTrue(stored[0]["telemetry"])

    def test_recent_captures_are_limited(self):

        with tempfile.TemporaryDirectory() as folder:

            config = settings.AppSettings(
                self._path(folder)
            )
            config.set_recent_captures(
                [
                    {
                        "path": f"D:\\Captures\\{index}.csv",
                        "frames": index,
                    }
                    for index in range(
                        settings.MAX_RECENT_CAPTURES + 4
                    )
                ]
            )

            stored = config.recent_captures

            self.assertEqual(
                len(stored),
                settings.MAX_RECENT_CAPTURES,
            )
            self.assertEqual(stored[0]["frames"], 0)
            self.assertEqual(
                stored[-1]["frames"],
                settings.MAX_RECENT_CAPTURES - 1,
            )

    def test_corrupt_recent_json_returns_empty(self):

        with tempfile.TemporaryDirectory() as folder:

            path = self._path(folder)
            raw = self._raw(path)
            raw.setValue(
                settings.RECENT_CAPTURES_KEY,
                "{ broken",
            )
            raw.sync()

            self.assertEqual(
                settings.AppSettings(
                    path
                ).recent_captures,
                [],
            )

    def test_onboarding_seen_round_trip(self):

        with tempfile.TemporaryDirectory() as folder:

            path = self._path(folder)
            first = settings.AppSettings(path)

            self.assertFalse(first.onboarding_seen)
            first.set_onboarding_seen(True)

            self.assertTrue(
                settings.AppSettings(
                    path
                ).onboarding_seen
            )

    def test_corrupt_ini_does_not_raise(self):

        with tempfile.TemporaryDirectory() as folder:

            path = self._path(folder)
            path.write_text(
                "this is not an ini file\n[[[",
                encoding="utf-8",
            )

            config = settings.AppSettings(path)

            self.assertEqual(config.language_mode, "system")
            self.assertEqual(
                config.target_fps,
                settings.DEFAULT_TARGET_FPS,
            )
            self.assertEqual(
                config.successful_targets,
                [],
            )

    def test_unknown_settings_are_preserved(self):

        with tempfile.TemporaryDirectory() as folder:

            path = self._path(folder)

            raw = self._raw(path)
            raw.setValue("custom/keep", "value")
            raw.sync()

            settings.AppSettings(
                path
            ).set_language_mode("zh_CN")

            raw = self._raw(path)

            self.assertEqual(
                raw.value("custom/keep"),
                "value",
            )

    def test_default_path_respects_data_dir_override(self):

        with tempfile.TemporaryDirectory() as folder, mock.patch.dict(
            os.environ,
            {settings.ENV_DATA_DIR: folder},
        ):

            path = settings.default_settings_path()

            self.assertEqual(
                path,
                Path(folder) / "LagLens.ini",
            )

            config = settings.AppSettings()

            self.assertEqual(
                config.path,
                Path(folder) / "LagLens.ini",
            )

    def test_default_path_is_outside_the_project(self):

        path = settings.default_settings_path()

        self.assertTrue(path.is_absolute())
        self.assertNotIn(
            str(settings.PROJECT_ROOT).lower(),
            str(path).lower(),
        )

    def test_default_path_uses_local_app_data(self):

        with mock.patch.dict(
            os.environ,
            {
                "LOCALAPPDATA": r"C:\Users\Test\AppData\Local",
            },
        ):

            path = settings.default_settings_path()

        self.assertEqual(
            path,
            Path(
                r"C:\Users\Test\AppData\Local"
            )
            / settings.CONFIG_DIR_NAME
            / settings.CONFIG_FILE_NAME,
        )

    def test_candidate_dirs_do_not_depend_on_a_fixed_drive(self):

        with mock.patch.dict(
            os.environ,
            {
                "LOCALAPPDATA": r"C:\Users\Test\AppData\Local",
            },
        ):

            candidates = settings.candidate_data_dirs()

        self.assertEqual(
            candidates[0],
            Path(
                r"C:\Users\Test\AppData\Local"
            )
            / settings.CONFIG_DIR_NAME,
        )
        self.assertNotIn(
            "D:\\LagLensData",
            [str(path) for path in candidates],
        )

    def test_user_data_dir_creates_local_app_data(self):

        with tempfile.TemporaryDirectory() as folder, mock.patch.dict(
            os.environ,
            {
                "LOCALAPPDATA": folder,
            },
        ):

            path = settings.user_data_dir()

            self.assertEqual(
                path,
                Path(folder) / settings.CONFIG_DIR_NAME,
            )
            self.assertTrue(path.is_dir())


if __name__ == "__main__":
    unittest.main()
