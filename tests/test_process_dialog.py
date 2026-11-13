"""B-2: independent process-selection dialog tests."""

import os
import sys
import unittest

from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import i18n  # noqa: E402
import process_catalog  # noqa: E402
from process_dialog import ProcessDialog  # noqa: E402


def make_entry(
    pid=1,
    name="Game.exe",
    exe=r"D:\Games\Game.exe",
    **kwargs,
):

    return process_catalog.ProcessEntry(
        pid=pid,
        name=name,
        exe=exe,
        **kwargs,
    )


class ProcessDialogTests(unittest.TestCase):

    app = None

    @classmethod
    def setUpClass(cls):

        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):

        i18n.get_manager().set_language("en")

        self.entries = [
            make_entry(
                pid=101,
                name="Game.exe",
                exe=r"D:\Games\Game.exe",
                has_window=True,
                window_title="Game",
                memory_bytes=1024**3,
            ),
            make_entry(
                pid=102,
                name="Game.exe",
                exe=r"E:\Copy\Game.exe",
                has_window=True,
                window_title="Game Copy",
                memory_bytes=2 * 1024**3,
            ),
            make_entry(
                pid=103,
                name="Tool.exe",
                exe=r"D:\Tools\Tool.exe",
            ),
            make_entry(
                pid=104,
                name="SystemSettings.exe",
                exe=(
                    r"C:\Windows\ImmersiveControlPanel"
                    r"\SystemSettings.exe"
                ),
                has_window=True,
                window_title="Settings",
            ),
            make_entry(
                pid=105,
                name="Hidden.exe",
                exe=r"D:\Games\Hidden.exe",
                memory_bytes=2 * 1024**3,
            ),
        ]

        self.dialog = ProcessDialog(
            entries_provider=lambda: list(self.entries),
        )
        self.dialog.show()
        self.app.processEvents()

    def tearDown(self):

        self.dialog.close()
        self.dialog.deleteLater()

        QApplication.sendPostedEvents(
            None,
            QEvent.Type.DeferredDelete,
        )
        QApplication.processEvents()

        self.dialog = None

        i18n.get_manager().set_language("en")

    def visible_names(self):

        return [
            self.dialog.table.item(row, 0).text()
            for row in range(self.dialog.table.rowCount())
        ]

    def row_for_pid(self, pid):

        for row in range(self.dialog.table.rowCount()):

            if self.dialog.table.item(row, 1).text() == str(pid):

                return row

        return -1

    def test_no_selection_shows_the_reason_hint(self):

        self.assertIn(
            "Select a process to see the full",
            self.dialog.reason_detail.text(),
        )

    def test_reason_column_has_a_full_text_tooltip(self):

        dialog = ProcessDialog(
            entries_provider=lambda: [self.entries[0]],
            remembered_targets=[
                {
                    "path": r"D:\Games\Game.exe",
                    "executable": "Game.exe",
                    "last_success": "2026-11-12T01:00:00",
                }
            ],
        )

        try:

            item = dialog.table.item(0, 4)

            self.assertIn(
                "previously captured successfully",
                item.toolTip(),
            )
            self.assertIn("visible window: Game", item.toolTip())
            self.assertIn("MiB of RAM", item.toolTip())

        finally:

            dialog.close()
            dialog.deleteLater()
            self.app.processEvents()

    def test_selected_full_reason_is_shown_and_translated(self):

        dialog = ProcessDialog(
            entries_provider=lambda: [self.entries[0]],
            remembered_targets=[
                {
                    "path": r"D:\Games\Game.exe",
                    "executable": "Game.exe",
                    "last_success": "2026-11-12T01:00:00",
                }
            ],
        )
        dialog.show()
        self.app.processEvents()

        try:

            dialog.table.selectRow(0)
            self.app.processEvents()

            detail = dialog.reason_detail.text()

            self.assertIn("Selected reason:", detail)
            self.assertIn(
                "previously captured successfully",
                detail,
            )
            self.assertIn("visible window: Game", detail)
            self.assertIn("MiB of RAM", detail)

            i18n.get_manager().set_language("zh_CN")
            self.app.processEvents()

            detail = dialog.reason_detail.text()

            self.assertIn("已选原因：", detail)
            self.assertIn("之前成功抓取过", detail)
            self.assertIn("可见窗口", detail)

        finally:

            i18n.get_manager().set_language("en")
            dialog.close()
            dialog.deleteLater()
            self.app.processEvents()

    def test_columns_and_no_default_selection(self):

        headers = [
            self.dialog.table.horizontalHeaderItem(index).text()
            for index in range(self.dialog.table.columnCount())
        ]

        self.assertEqual(
            headers,
            [
                "Process",
                "PID",
                "Window title",
                "Executable path",
                "Recommendation signals",
            ],
        )
        self.assertEqual(self.dialog.table.rowCount(), 2)
        self.assertEqual(self.dialog.table.currentRow(), -1)
        self.assertFalse(self.dialog.select_button.isEnabled())
        self.assertIsNone(self.dialog.selected_entry())

    def test_recommended_and_all_modes(self):

        self.assertEqual(
            self.visible_names(),
            ["Game.exe", "Game.exe"],
        )

        self.dialog.mode_combo.setCurrentIndex(1)
        self.app.processEvents()

        self.assertEqual(
            sorted(self.visible_names()),
            [
                "Game.exe",
                "Game.exe",
                "Hidden.exe",
                "SystemSettings.exe",
                "Tool.exe",
            ],
        )

    def test_search_filters_name_path_and_window_title(self):

        self.dialog.search_input.setText("copy")
        self.app.processEvents()

        self.assertEqual(self.visible_names(), ["Game.exe"])

        self.dialog.search_input.setText(r"E:\Copy")
        self.app.processEvents()

        self.assertEqual(self.visible_names(), ["Game.exe"])

        self.dialog.mode_combo.setCurrentIndex(1)
        self.dialog.search_input.setText("Tool")
        self.app.processEvents()

        self.assertEqual(self.visible_names(), ["Tool.exe"])

    def test_no_match_shows_empty_state(self):

        self.dialog.search_input.setText("does-not-exist")
        self.app.processEvents()

        self.assertEqual(self.dialog.table.rowCount(), 0)
        self.assertIn(
            "No running processes match",
            self.dialog.count_label.text(),
        )

    def test_selecting_a_row_enables_select_and_returns_entry(self):

        self.dialog.table.selectRow(0)
        self.app.processEvents()

        self.assertTrue(self.dialog.select_button.isEnabled())
        self.assertIsNotNone(self.dialog.selected_entry())
        self.assertEqual(
            self.dialog.selected_entry().pid,
            101,
        )

    def test_refresh_clears_selection_when_entry_disappears(self):

        self.dialog.table.selectRow(0)
        self.app.processEvents()

        self.entries = [
            entry
            for entry in self.entries
            if entry.pid != 101
        ]

        self.dialog.refresh()
        self.app.processEvents()

        self.assertEqual(self.dialog.table.currentRow(), -1)
        self.assertFalse(self.dialog.select_button.isEnabled())
        self.assertIsNone(self.dialog.selected_entry())

    def test_refresh_preserves_the_same_pid_and_path(self):

        self.dialog.table.selectRow(0)
        self.app.processEvents()

        self.entries.append(
            make_entry(
                pid=106,
                name="New.exe",
                exe=r"D:\Games\New.exe",
                has_window=True,
                window_title="New",
            )
        )

        self.dialog.refresh()
        self.app.processEvents()

        self.assertIsNotNone(self.dialog.selected_entry())
        self.assertEqual(
            self.dialog.selected_entry().pid,
            101,
        )
        self.assertTrue(self.dialog.select_button.isEnabled())

    def test_name_collision_warning_is_shown_and_cleared(self):

        self.dialog.table.selectRow(0)
        self.app.processEvents()

        self.assertTrue(
            self.dialog.collision_label.isVisible()
        )
        self.assertIn(
            "share this name: 1",
            self.dialog.collision_label.text(),
        )

        self.dialog.mode_combo.setCurrentIndex(1)
        self.app.processEvents()

        tool_row = self.row_for_pid(103)
        self.dialog.table.selectRow(tool_row)
        self.app.processEvents()

        self.assertFalse(
            self.dialog.collision_label.isVisible()
        )

    def test_all_mode_distinguishes_same_name_paths_and_pids(self):

        self.dialog.mode_combo.setCurrentIndex(1)
        self.app.processEvents()

        rows = []

        for pid in (101, 102):

            row = self.row_for_pid(pid)

            rows.append(
                (
                    self.dialog.table.item(row, 1).text(),
                    self.dialog.table.item(row, 3).text(),
                )
            )

        self.assertEqual(
            rows,
            [
                ("101", r"D:\Games\Game.exe"),
                ("102", r"E:\Copy\Game.exe"),
            ],
        )

    def test_unavailable_path_and_missing_window_are_localized(self):

        self.entries.append(
            make_entry(
                pid=107,
                name="NoPath.exe",
                exe="",
            )
        )

        self.dialog.refresh()
        self.dialog.mode_combo.setCurrentIndex(1)
        self.app.processEvents()

        row = self.row_for_pid(107)

        self.assertEqual(
            self.dialog.table.item(row, 2).text(),
            "—",
        )
        self.assertEqual(
            self.dialog.table.item(row, 3).text(),
            "Path unavailable",
        )

    def test_reasons_explain_memory_window_and_previous_success(self):

        dialog = ProcessDialog(
            entries_provider=lambda: [self.entries[0]],
            remembered_targets=[
                {
                    "path": r"D:\Games\Game.exe",
                    "executable": "Game.exe",
                    "last_success": "2026-11-12T01:00:00",
                }
            ],
        )

        try:

            reason = dialog.table.item(0, 4).text()

            self.assertIn(
                "previously captured successfully",
                reason,
            )
            self.assertIn("visible window: Game", reason)
            self.assertIn("MiB of RAM", reason)

            i18n.get_manager().set_language("zh_CN")
            self.app.processEvents()

            reason = dialog.table.item(0, 4).text()

            self.assertIn("之前成功抓取过", reason)
            self.assertIn("可见窗口", reason)
            self.assertIn("MiB", reason)

        finally:

            dialog.close()
            dialog.deleteLater()
            self.app.processEvents()

    def test_system_process_is_not_recommended_but_appears_in_all(self):

        self.assertNotIn(
            "SystemSettings.exe",
            self.visible_names(),
        )

        self.dialog.mode_combo.setCurrentIndex(1)
        self.app.processEvents()

        row = self.row_for_pid(104)

        self.assertGreaterEqual(row, 0)
        self.assertIn(
            "system process (not recommended)",
            self.dialog.table.item(row, 4).text(),
        )

    def test_language_switch_updates_text_and_keeps_selection(self):

        self.dialog.table.selectRow(0)
        self.app.processEvents()

        selected = self.dialog.selected_entry()

        i18n.get_manager().set_language("zh_CN")
        self.app.processEvents()

        self.assertEqual(
            self.dialog.windowTitle(),
            "选择目标进程",
        )
        self.assertEqual(
            self.dialog.table.horizontalHeaderItem(0).text(),
            "进程",
        )
        self.assertEqual(
            self.dialog.mode_combo.itemText(0),
            "推荐候选",
        )
        self.assertEqual(
            self.dialog.select_button.text(),
            "选择",
        )
        self.assertEqual(
            self.dialog.search_input.placeholderText(),
            "搜索名称、路径或窗口标题",
        )
        self.assertIsNotNone(self.dialog.selected_entry())
        self.assertEqual(
            self.dialog.selected_entry().pid,
            selected.pid,
        )
        self.assertTrue(self.dialog.select_button.isEnabled())

    def test_empty_provider_does_not_crash(self):

        dialog = ProcessDialog(
            entries_provider=lambda: [],
        )

        try:

            self.assertEqual(dialog.table.rowCount(), 0)
            self.assertFalse(dialog.select_button.isEnabled())
            self.assertIn(
                "0 of 0",
                dialog.count_label.text(),
            )

        finally:

            dialog.close()
            dialog.deleteLater()
            self.app.processEvents()

    def test_provider_failure_does_not_crash(self):

        def broken_provider():

            raise OSError("enumeration failed")

        dialog = ProcessDialog(
            entries_provider=broken_provider,
        )

        try:

            self.assertEqual(dialog.table.rowCount(), 0)
            self.assertIn(
                "Could not enumerate processes",
                dialog.count_label.text(),
            )
            self.assertFalse(dialog.select_button.isEnabled())

        finally:

            dialog.close()
            dialog.deleteLater()
            self.app.processEvents()

    def test_subtitle_is_localized(self):

        self.assertIn(
            "Recommendations are hints",
            self.dialog.subtitle.text(),
        )

        i18n.get_manager().set_language("zh_CN")
        self.app.processEvents()

        self.assertIn(
            "推荐只是提示",
            self.dialog.subtitle.text(),
        )

    def test_heuristic_note_is_visible(self):

        self.assertIn(
            "not confirmation that the process is a game",
            self.dialog.heuristic_label.text(),
        )
        self.assertIn(
            "PresentMon targets the executable name",
            self.dialog.note_label.text(),
        )


if __name__ == "__main__":

    unittest.main()
