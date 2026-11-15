"""Source-mode checks for packaged resource locations."""

import sys
import unittest

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import main  # noqa: E402
import runtime_paths  # noqa: E402


class RuntimePathTests(unittest.TestCase):

    def test_source_mode_resource_paths_exist(self):

        self.assertFalse(runtime_paths.is_frozen())
        self.assertEqual(runtime_paths.app_dir(), ROOT)
        self.assertTrue(
            runtime_paths.resource_path(
                "locales",
                "en.json",
            ).is_file()
        )
        self.assertTrue(
            runtime_paths.resource_path(
                "assets",
                "check.svg",
            ).is_file()
        )

    def test_source_mode_uses_bundled_presentmon(self):

        self.assertEqual(
            main.DEFAULT_PRESENTMON.name,
            "PresentMon-2.6.0-x64.exe",
        )
        self.assertTrue(
            main.DEFAULT_PRESENTMON.is_file()
        )
        self.assertEqual(
            main.DEFAULT_PRESENTMON.parent.name,
            "presentmon",
        )


if __name__ == "__main__":

    unittest.main()
