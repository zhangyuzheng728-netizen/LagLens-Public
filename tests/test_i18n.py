"""A-1: message catalog and language manager tests."""

import json
import os
import tempfile
import unittest

from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

import capture_core
import frame_stats
import i18n
import swap_chains


def make_rows():

    return [
        {
            "Application": "game.exe",
            "ProcessID": "100",
            "SwapChainAddress": "0x1",
            "CPUStartTime": str(index * 16),
            "FrameTime": "16.0",
            "DisplayedTime": "16.0",
        }
        for index in range(20)
    ]


class CatalogTests(unittest.TestCase):

    def test_catalogs_share_keys_and_placeholders(self):

        english = i18n.load_catalog(
            i18n.DEFAULT_LOCALE_DIR / "en.json"
        )
        chinese = i18n.load_catalog(
            i18n.DEFAULT_LOCALE_DIR / "zh_CN.json"
        )

        self.assertTrue(english)
        self.assertTrue(chinese)

        self.assertEqual(
            set(english),
            set(chinese),
            "en and zh_CN catalogs must expose the same keys",
        )

        for key in english:

            self.assertTrue(
                english[key].strip(),
                f"empty English value for {key}",
            )
            self.assertTrue(
                chinese[key].strip(),
                f"empty Chinese value for {key}",
            )
            self.assertEqual(
                i18n.placeholder_names(english[key]),
                i18n.placeholder_names(chinese[key]),
                f"placeholder mismatch for {key}",
            )

    def test_technical_identifiers_are_unchanged(self):

        self.assertEqual(
            i18n.load_catalog(
                i18n.DEFAULT_LOCALE_DIR / "en.json"
            )["app.brand"],
            "LagLens",
        )


class LanguageManagerTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):

        cls.app = (
            QApplication.instance()
            or QApplication([])
        )

    def test_default_is_english(self):

        manager = i18n.LanguageManager(env={})

        self.assertEqual(manager.language, "en")
        self.assertEqual(
            manager.translate("tab.settings"),
            "Settings",
        )

    def test_lookup_and_interpolation(self):

        manager = i18n.LanguageManager(env={})

        manager.set_language("zh_CN")

        self.assertEqual(
            manager.translate("tab.settings"),
            "设置",
        )

        self.assertEqual(
            manager.translate(
                "status.saved",
                frames=12,
                name="capture.csv",
            ),
            "已保存 12 帧到 capture.csv",
        )

    def test_missing_key_returns_the_key(self):

        manager = i18n.LanguageManager(env={})

        self.assertEqual(
            manager.translate("does.not.exist"),
            "does.not.exist",
        )

    def test_unknown_language_mode_is_rejected(self):

        manager = i18n.LanguageManager(env={})

        with self.assertRaises(ValueError):

            manager.set_mode("fr_FR")

        with self.assertRaises(ValueError):

            manager.set_language("ja_JP")

    def test_language_signal_fires_only_on_change(self):

        manager = i18n.LanguageManager(env={})

        seen = []
        manager.language_changed.connect(seen.append)

        manager.set_language("zh_CN")
        manager.set_language("zh_CN")
        manager.set_language("en")

        self.assertEqual(seen, ["zh_CN", "en"])

    def test_system_locale_resolution(self):

        manager = i18n.LanguageManager(env={})

        self.assertEqual(
            manager.set_mode(
                "system",
                system_locale="zh-Hans-CN",
            ),
            "zh_CN",
        )
        self.assertEqual(
            manager.set_mode(
                "system",
                system_locale="en-US",
            ),
            "en",
        )
        self.assertEqual(
            manager.set_mode(
                "system",
                system_locale="fr-FR",
            ),
            "en",
        )

        self.assertEqual(
            manager.set_mode(
                "zh_CN",
                system_locale="en-US",
            ),
            "zh_CN",
        )

        # Traditional Chinese and the ambiguous bare "zh" fall back
        # to English; the user can still choose Simplified manually.
        self.assertEqual(
            i18n.resolve_language(
                "system",
                "zh_TW",
            ),
            "en",
        )

    def test_simplified_and_traditional_locale_mapping(self):

        cases = {
            "zh_CN": "zh_CN",
            "zh_SG": "zh_CN",
            "zh-Hans-CN": "zh_CN",
            "zh-Hans": "zh_CN",
            "zh_TW": None,
            "zh_HK": None,
            "zh_MO": None,
            "zh-Hant-TW": None,
            "zh": None,
            "en_US": "en",
            "fr_FR": None,
        }

        for value, expected in cases.items():

            self.assertEqual(
                i18n.normalize_language(value),
                expected,
                value,
            )

    def test_windows_display_language_takes_priority(self):

        with mock.patch.object(
            i18n,
            "windows_display_language",
            return_value="zh-CN",
        ), mock.patch.object(
            i18n.QLocale,
            "system",
        ) as system:

            self.assertEqual(
                i18n.resolve_language("system"),
                "zh_CN",
            )

            system.assert_not_called()

    def test_qt_locale_is_the_fallback(self):

        with mock.patch.object(
            i18n,
            "windows_display_language",
            return_value=None,
        ), mock.patch.object(
            i18n,
            "QLocale",
        ) as locale:

            locale.system.return_value.name.return_value = "zh_CN"

            self.assertEqual(
                i18n.detect_system_language(),
                "zh_CN",
            )

    def test_env_override_is_used_for_tests(self):

        self.assertEqual(
            i18n.LanguageManager(
                env={"LAGLENS_LANGUAGE": "zh_cn"}
            ).language,
            "zh_CN",
        )

        self.assertEqual(
            i18n.LanguageManager(
                env={"LAGLENS_LANGUAGE": "de_DE"}
            ).language,
            "en",
        )

    def test_missing_translation_falls_back_to_english(self):

        with tempfile.TemporaryDirectory() as folder:

            root = Path(folder)

            (root / "en.json").write_text(
                json.dumps(
                    {
                        "only.en": "English text",
                        "with.arg": "Value {value}",
                    }
                ),
                encoding="utf-8",
            )

            (root / "zh_CN.json").write_text(
                json.dumps({"with.arg": "值 {value}"}),
                encoding="utf-8",
            )

            manager = i18n.LanguageManager(
                env={},
                catalog_dir=root,
            )
            manager.set_language("zh_CN")

            self.assertEqual(
                manager.translate("only.en"),
                "English text",
            )
            self.assertEqual(
                manager.translate("with.arg", value=7),
                "值 7",
            )

    def test_corrupt_catalog_does_not_break_startup(self):

        with tempfile.TemporaryDirectory() as folder:

            root = Path(folder)

            (root / "en.json").write_text(
                json.dumps({"safe.key": "Safe"}),
                encoding="utf-8",
            )
            (root / "zh_CN.json").write_text(
                "{ not valid json",
                encoding="utf-8",
            )

            manager = i18n.LanguageManager(
                env={},
                catalog_dir=root,
            )
            manager.set_language("zh_CN")

            self.assertEqual(
                manager.translate("safe.key"),
                "Safe",
            )

    def test_bad_placeholders_do_not_raise(self):

        with tempfile.TemporaryDirectory() as folder:

            root = Path(folder)

            payload = json.dumps(
                {"needs.name": "Hello {name}"}
            )

            (root / "en.json").write_text(
                payload,
                encoding="utf-8",
            )
            (root / "zh_CN.json").write_text(
                payload,
                encoding="utf-8",
            )

            manager = i18n.LanguageManager(
                env={},
                catalog_dir=root,
            )

            self.assertEqual(
                manager.translate("needs.name"),
                "Hello {name}",
            )

    def test_switching_language_does_not_touch_core_logic(self):
        """i18n must not alter capture, statistics or chain selection."""

        rows = make_rows()

        def snapshot():

            command = capture_core.build_capture_command(
                "PresentMon.exe",
                "LagLensTest",
                "Palworld-Win64-Shipping.exe",
            )

            index = swap_chains.build_index(rows)
            selection = swap_chains.recommend(index)
            stats = frame_stats.compute_stats(
                selection.legacy_frames()
            )

            return (
                tuple(command),
                selection.frame_count,
                tuple(
                    chain.key
                    for chain in selection.selected.chains
                ),
                selection.reason,
                round(stats.average_fps, 6),
                round(stats.p99_frame_ms, 6),
                stats.stutter_count,
            )

        manager = i18n.LanguageManager(env={})

        before = snapshot()

        manager.set_language("zh_CN")
        during = snapshot()

        manager.set_language("en")
        after = snapshot()

        self.assertEqual(before, during)
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
