"""B-2: independent process-selection dialog.

The dialog only selects an executable name for the existing target
combo.  It never starts a capture, never auto-selects a row and never
switches the target silently.

PresentMon 2.6 targets processes by executable name.  PID and full path
are shown to distinguish same-name processes, but the UI states
explicitly that a PID cannot be used to capture one specific instance.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

import process_catalog
import ui_theme

from i18n import get_manager, tr


logger = logging.getLogger("laglens.process_dialog")
logger.addHandler(logging.NullHandler())


MODE_RECOMMENDED = "recommended"
MODE_ALL = "all"


class MiddleElideDelegate(QStyledItemDelegate):
    """Keep both ends of a long executable path visible."""

    def initStyleOption(self, option, index):

        super().initStyleOption(option, index)
        option.textElideMode = Qt.TextElideMode.ElideMiddle


class ProcessDialog(QDialog):
    """Recommended/all process picker with live search."""

    def __init__(
        self,
        parent=None,
        entries_provider=None,
        remembered_targets=(),
    ):

        super().__init__(parent)

        ui_theme.ensure_application_theme()

        self._entries_provider = (
            entries_provider
            or process_catalog.collect_processes
        )
        self._remembered_targets = tuple(
            remembered_targets or ()
        )

        self._entries = []
        self._recommendations = []
        self._selected_entry = None
        self._refresh_failed = False

        self.setObjectName("processDialog")
        self.resize(1180, 820)
        self.setMinimumSize(980, 640)

        self.build_ui()
        self.retranslate()

        self.mode_combo.currentIndexChanged.connect(
            self.apply_filter
        )
        self.search_input.textChanged.connect(
            self.apply_filter
        )
        self.refresh_button.clicked.connect(
            self.refresh
        )
        self.table.itemSelectionChanged.connect(
            self.update_selection_state
        )
        self.select_button.clicked.connect(
            self.accept
        )
        self.cancel_button.clicked.connect(
            self.reject
        )

        get_manager().language_changed.connect(
            self.retranslate
        )

        self.refresh()

    # --------------------------------------
    # UI construction
    # --------------------------------------

    def build_ui(self):

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            ui_theme.SPACE["lg"],
            ui_theme.SPACE["lg"],
            ui_theme.SPACE["lg"],
            ui_theme.SPACE["lg"],
        )
        layout.setSpacing(ui_theme.SPACE["md"])

        self.heading = QLabel()
        ui_theme.apply_font(self.heading, "heading")
        self.heading.setObjectName("dialogHeading")
        layout.addWidget(self.heading)

        self.subtitle = QLabel()
        self.subtitle.setObjectName("muted")
        self.subtitle.setWordWrap(True)
        ui_theme.apply_font(self.subtitle, "caption")
        self.subtitle.setText(tr("process_dialog.subtitle"))
        layout.addWidget(self.subtitle)

        top = QHBoxLayout()
        top.setSpacing(ui_theme.SPACE["sm"])

        self.mode_label = QLabel()
        ui_theme.apply_font(self.mode_label, "label")
        top.addWidget(self.mode_label)

        self.mode_combo = QComboBox()
        ui_theme.apply_font(self.mode_combo, "body")
        self.mode_combo.addItem("", MODE_RECOMMENDED)
        self.mode_combo.addItem("", MODE_ALL)
        top.addWidget(self.mode_combo)

        self.search_input = QLineEdit()
        ui_theme.apply_font(self.search_input, "body")
        top.addWidget(self.search_input, 1)

        self.refresh_button = QPushButton()
        ui_theme.apply_font(self.refresh_button, "body")
        ui_theme.set_button_variant(
            self.refresh_button,
            "ghost",
        )
        top.addWidget(self.refresh_button)

        layout.addLayout(top)

        self.table = QTableWidget(0, 5)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.table.setSortingEnabled(False)
        self.table.setWordWrap(False)
        self.table.setShowGrid(False)
        self.table.setTextElideMode(
            Qt.TextElideMode.ElideRight
        )
        self.table.verticalHeader().setVisible(False)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(
            0,
            QHeaderView.ResizeMode.ResizeToContents,
        )
        header.setSectionResizeMode(
            1,
            QHeaderView.ResizeMode.ResizeToContents,
        )
        header.setSectionResizeMode(
            2,
            QHeaderView.ResizeMode.Interactive,
        )
        header.setSectionResizeMode(
            3,
            QHeaderView.ResizeMode.Stretch,
        )
        header.setSectionResizeMode(
            4,
            QHeaderView.ResizeMode.Interactive,
        )
        self.table.setColumnWidth(2, 220)
        self.table.setColumnWidth(4, 320)
        self.table.setItemDelegateForColumn(
            3,
            MiddleElideDelegate(self.table),
        )

        ui_theme.apply_table_typography(self.table)

        layout.addWidget(self.table, 1)

        self.note_label = QLabel()
        self.note_label.setWordWrap(True)
        ui_theme.apply_font(self.note_label, "caption")
        self.note_label.setObjectName("muted")
        layout.addWidget(self.note_label)

        self.heuristic_label = QLabel()
        self.heuristic_label.setWordWrap(True)
        ui_theme.apply_font(
            self.heuristic_label,
            "caption",
        )
        self.heuristic_label.setObjectName("muted")
        layout.addWidget(self.heuristic_label)

        self.collision_label = QLabel()
        self.collision_label.setWordWrap(True)
        ui_theme.apply_font(
            self.collision_label,
            "label",
            weight=QFont.Weight.Medium,
        )
        self.collision_label.setObjectName("warningLabel")
        self.collision_label.hide()
        layout.addWidget(self.collision_label)

        self.reason_detail = QLabel()
        self.reason_detail.setWordWrap(True)
        ui_theme.apply_font(
            self.reason_detail,
            "body",
        )
        self.reason_detail.setObjectName("reasonPanel")
        layout.addWidget(self.reason_detail)

        footer = QHBoxLayout()
        footer.setSpacing(ui_theme.SPACE["sm"])

        self.count_label = QLabel()
        ui_theme.apply_font(self.count_label, "caption")
        self.count_label.setObjectName("muted")
        footer.addWidget(self.count_label, 1)

        self.cancel_button = QPushButton()
        self.cancel_button.setAutoDefault(False)
        ui_theme.apply_font(
            self.cancel_button,
            "body",
            weight=QFont.Weight.Medium,
        )
        self.cancel_button.setMinimumHeight(40)
        self.cancel_button.setMinimumWidth(96)
        footer.addWidget(self.cancel_button)

        self.select_button = QPushButton()
        self.select_button.setObjectName("selectButton")
        self.select_button.setDefault(True)
        self.select_button.setEnabled(False)
        ui_theme.apply_font(
            self.select_button,
            "body",
            weight=QFont.Weight.DemiBold,
        )
        ui_theme.set_button_variant(
            self.select_button,
            "primary",
        )
        self.select_button.setMinimumHeight(40)
        self.select_button.setMinimumWidth(96)
        footer.addWidget(self.select_button)

        layout.addLayout(footer)

    # --------------------------------------
    # Data and filtering
    # --------------------------------------

    def refresh(self, _checked=False):

        preserve = self.selection_key()

        try:

            entries = list(self._entries_provider())
            self._refresh_failed = False

        except Exception as error:  # pragma: no cover - defensive UI

            logger.debug(
                "process enumeration failed: %s",
                error,
                exc_info=True,
            )

            entries = []
            self._refresh_failed = True

        self._entries = entries

        try:

            self._recommendations = (
                process_catalog.rank_processes(
                    entries,
                    self._remembered_targets,
                )
            )

        except Exception as error:  # pragma: no cover - defensive UI

            logger.debug(
                "process ranking failed: %s",
                error,
                exc_info=True,
            )

            self._recommendations = []
            self._refresh_failed = True

        self.populate(preserve)

    def apply_filter(self, _value=None):

        self.populate(self.selection_key())

    def current_mode(self):

        mode = self.mode_combo.currentData()

        if mode == MODE_ALL:

            return MODE_ALL

        return MODE_RECOMMENDED

    def matching_recommendations(self):

        if self.current_mode() == MODE_ALL:

            candidates = sorted(
                self._recommendations,
                key=lambda item: (
                    item.entry.name.casefold(),
                    item.entry.pid,
                ),
            )

        else:

            candidates = [
                item
                for item in self._recommendations
                if item.recommended
            ]

        query = (
            self.search_input.text()
            .strip()
            .casefold()
        )

        if not query:

            return candidates

        return [
            item
            for item in candidates
            if self.matches(item.entry, query)
        ]

    @staticmethod
    def matches(entry, query):

        haystacks = (
            entry.name,
            entry.exe,
            entry.window_title,
        )

        return any(
            query in (value or "").casefold()
            for value in haystacks
        )

    def populate(self, preserve_key=None):

        matches = self.matching_recommendations()

        self.table.setUpdatesEnabled(False)
        self.table.blockSignals(True)
        self.table.setRowCount(0)

        selected_row = -1

        for row, recommendation in enumerate(matches):

            entry = recommendation.entry

            self.table.insertRow(row)

            name_item = QTableWidgetItem(entry.name)
            name_item.setData(
                Qt.ItemDataRole.UserRole,
                entry,
            )
            name_item.setToolTip(entry.name)
            self.table.setItem(row, 0, name_item)

            pid_item = QTableWidgetItem(str(entry.pid))
            pid_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight
                | Qt.AlignmentFlag.AlignVCenter
            )
            pid_item.setFont(ui_theme.font("mono"))
            self.table.setItem(row, 1, pid_item)

            window = entry.window_title.strip()

            window_item = QTableWidgetItem(
                window or tr("process_dialog.window.none")
            )
            window_item.setToolTip(window)
            self.table.setItem(row, 2, window_item)

            path = entry.exe.strip()

            path_item = QTableWidgetItem(
                path or tr("process_dialog.path.unavailable")
            )
            path_item.setToolTip(path)
            self.table.setItem(row, 3, path_item)

            reason = self.format_reasons(recommendation)

            reason_item = QTableWidgetItem(
                reason or tr("process_dialog.none")
            )
            reason_item.setToolTip(reason)
            self.table.setItem(row, 4, reason_item)

            if (
                preserve_key is not None
                and (
                    entry.pid,
                    entry.normalized_path,
                )
                == preserve_key
            ):

                selected_row = row

        self.table.blockSignals(False)
        self.table.setUpdatesEnabled(True)

        if selected_row >= 0:

            self.table.selectRow(selected_row)

        else:

            self.table.clearSelection()
            self.table.setCurrentItem(None)

        self.update_count(len(matches))
        self.update_selection_state()

    def update_count(self, visible):

        if self._refresh_failed:

            text = tr("process_dialog.refresh_failed")

        elif not visible and self._entries:

            text = tr("process_dialog.empty")

        else:

            text = tr(
                "process_dialog.count",
                visible=visible,
                total=len(self._entries),
            )

        self.count_label.setText(text)

    # --------------------------------------
    # Selection state
    # --------------------------------------

    def entry_for_row(self, row):

        item = self.table.item(row, 0)

        if item is None:

            return None

        entry = item.data(Qt.ItemDataRole.UserRole)

        if isinstance(entry, process_catalog.ProcessEntry):

            return entry

        return None

    def selection_key(self):

        row = self.table.currentRow()
        entry = (
            self.entry_for_row(row)
            if row >= 0
            else None
        )

        if entry is None:

            return None

        return (
            entry.pid,
            entry.normalized_path,
        )

    def recommendation_for_entry(self, entry):

        for recommendation in self._recommendations:

            if (
                recommendation.entry.pid == entry.pid
                and recommendation.entry.normalized_path
                == entry.normalized_path
            ):

                return recommendation

        return None

    def update_reason_detail(self, entry):

        if entry is None:

            self.reason_detail.setText(
                tr("process_dialog.reason.hint")
            )

            return

        recommendation = self.recommendation_for_entry(
            entry
        )

        reason = (
            self.format_reasons(recommendation)
            if recommendation is not None
            else ""
        )

        if reason:

            self.reason_detail.setText(
                tr(
                    "process_dialog.reason.selected",
                    reason=reason,
                )
            )

        else:

            self.reason_detail.setText(
                tr("process_dialog.reason.none")
            )

    def update_selection_state(self):

        row = self.table.currentRow()
        entry = (
            self.entry_for_row(row)
            if row >= 0
            else None
        )

        self._selected_entry = entry
        self.select_button.setEnabled(entry is not None)
        self.update_reason_detail(entry)

        if entry is None:

            self.collision_label.hide()

            return

        same_name = [
            item
            for item in self._entries
            if (
                item.name.casefold()
                == entry.name.casefold()
            )
        ]

        if len(same_name) > 1:

            self.collision_label.setText(
                tr(
                    "process_dialog.collision",
                    count=len(same_name) - 1,
                )
            )
            self.collision_label.show()

        else:

            self.collision_label.hide()

    def selected_entry(self):

        return self._selected_entry

    def accept(self):

        if self._selected_entry is None:

            return

        super().accept()

    # --------------------------------------
    # Translation
    # --------------------------------------

    def format_reasons(self, recommendation):

        parts = []

        for key, args in recommendation.reasons:

            if (
                key == process_catalog.REMEMBERED_REASON
                and not args.get("last_success")
            ):

                parts.append(
                    tr("process.reason.remembered_short")
                )

            else:

                parts.append(tr(key, **args))

        if recommendation.entry.system_executable:

            parts.append(
                tr("process.reason.system")
            )

        return tr(
            "process_dialog.reason.separator"
        ).join(parts)

    def retranslate(self, _language=None):

        preserve = self.selection_key()

        self.setWindowTitle(tr("process_dialog.title"))
        self.heading.setText(tr("process_dialog.heading"))
        self.subtitle.setText(tr("process_dialog.subtitle"))
        self.mode_label.setText(tr("process_dialog.mode"))

        self.mode_combo.setItemText(
            0,
            tr("process_dialog.mode.recommended"),
        )
        self.mode_combo.setItemText(
            1,
            tr("process_dialog.mode.all"),
        )

        self.search_input.setPlaceholderText(
            tr("process_dialog.search")
        )

        self.refresh_button.setText(
            tr("process_dialog.refresh")
        )

        self.table.setHorizontalHeaderLabels(
            [
                tr("process_dialog.column.name"),
                tr("process_dialog.column.pid"),
                tr("process_dialog.column.window"),
                tr("process_dialog.column.path"),
                tr("process_dialog.column.reason"),
            ]
        )

        self.note_label.setText(tr("process_dialog.note"))
        self.heuristic_label.setText(
            tr("process_dialog.heuristic")
        )
        self.select_button.setText(
            tr("process_dialog.select")
        )
        self.cancel_button.setText(
            tr("process_dialog.cancel")
        )

        self.populate(preserve)
