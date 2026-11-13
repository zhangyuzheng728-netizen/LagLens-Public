
import html
import math
import sys

from pathlib import Path

from PySide6.QtCore import (
    QPointF,
    QRectF,
    Qt,
    Signal,
)

from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPen,
    QPolygonF,
)

from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListView,
    QListWidget,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from frame_stats import compute_stats
from i18n import get_manager, tr
import diagnostic_report
import diagnostic_text
import diagnostics
import frame_timebase
import swap_chains
import ui_theme
from telemetry import read_telemetry


# ==========================================
# 读取 PresentMon CSV 数据
# ==========================================
def load_frames(csv_path, override=None):
    """Load the frames selected by swap_chains.recommend().

    ``override`` is an optional swap_chains.SelectionOverride; the
    GUI uses it later for manual chain selection.
    """

    rows = swap_chains.load_csv_rows(csv_path)

    timebase = frame_timebase.resolve_timebase(
        rows[0].keys() if rows else (),
        csv_path=csv_path,
    )

    index = swap_chains.build_index(
        rows,
        session=str(csv_path),
        timebase=timebase,
    )

    selection = swap_chains.recommend(
        index,
        override,
    )

    return selection.legacy_frames()


# ==========================================
# 帧时间曲线
# ==========================================
class FrameChart(QWidget):
    selected = Signal(int)

    def __init__(self, frames, threshold):
        super().__init__()

        self.frames = frames
        self.threshold = threshold
        self.points = []
        self.selected_index = None

        ui_theme.apply_chart_typography(self)

        self.setMinimumHeight(320)

    def paintEvent(self, event):
        painter = QPainter(self)

        painter.setRenderHint(
            QPainter.RenderHint.Antialiasing,
            True,
        )
        painter.setRenderHint(
            QPainter.RenderHint.TextAntialiasing,
            True,
        )

        painter.fillRect(
            self.rect(),
            QColor(ui_theme.CHART["surface"]),
        )

        metrics = QFontMetrics(self.font())
        line_height = metrics.height()

        # 自动计算 Y 轴范围
        maximum = max(
            frame["duration"]
            for frame in self.frames
        )

        scale = max(
            50.0,
            math.ceil(maximum * 1.1 / 25) * 25.0
        )

        labels = [
            f"{fraction * scale:.0f} ms"
            for fraction in (0, 0.25, 0.5, 0.75, 1)
        ]

        left = max(
            metrics.horizontalAdvance(text)
            for text in labels
        ) + 14

        top = line_height + 8

        right = max(
            left + 1,
            self.width() - 16
        )

        bottom = max(
            top + 1,
            self.height() - line_height - 12
        )

        width = right - left
        height = bottom - top

        # 1px 网格线保持像素清晰
        painter.save()
        painter.setRenderHint(
            QPainter.RenderHint.Antialiasing,
            False,
        )

        grid_pen = QPen(
            QColor(ui_theme.CHART["grid"]),
            1,
        )
        grid_pen.setCosmetic(True)
        painter.setPen(grid_pen)

        for fraction in (
            0, 0.25, 0.5, 0.75, 1
        ):
            y = round(
                bottom - fraction * height
            )

            painter.drawLine(
                QPointF(left, y),
                QPointF(right, y),
            )

        painter.restore()

        painter.setPen(QColor(ui_theme.CHART["axis"]))

        for fraction, text in zip(
            (0, 0.25, 0.5, 0.75, 1),
            labels,
        ):
            y = bottom - fraction * height
            rect = QRectF(
                0,
                y - line_height / 2,
                max(1, left - 10),
                line_height,
            )

            painter.drawText(
                rect,
                Qt.AlignmentFlag.AlignRight
                | Qt.AlignmentFlag.AlignVCenter,
                text,
            )

        # 异常阈值虚线
        if self.threshold <= scale:
            y = round(
                bottom
                - self.threshold / scale * height
            )

            painter.save()
            painter.setRenderHint(
                QPainter.RenderHint.Antialiasing,
                False,
            )
            threshold_pen = QPen(
                QColor(ui_theme.CHART["alert"]),
                1,
                Qt.PenStyle.DashLine,
            )
            threshold_pen.setCosmetic(True)
            painter.setPen(threshold_pen)
            painter.drawLine(
                QPointF(left, y),
                QPointF(right, y),
            )
            painter.restore()

        # 帧时间坐标
        start = self.frames[0]["time"]

        duration_range = max(
            0.001,
            self.frames[-1]["time"] - start
        )

        self.points = []

        for frame in self.frames:
            x = (
                left
                + (frame["time"] - start)
                / duration_range * width
            )

            y = (
                bottom
                - frame["duration"] / scale * height
            )

            self.points.append(
                QPointF(x, y)
            )

        # 青绿色曲线
        line_pen = QPen(
            QColor(ui_theme.CHART["line"]),
            2,
        )
        line_pen.setCosmetic(True)
        painter.setPen(line_pen)

        if len(self.points) >= 2:
            painter.drawPolyline(
                QPolygonF(self.points)
            )

        # 异常帧红点
        painter.setPen(
            Qt.PenStyle.NoPen
        )

        painter.setBrush(
            QColor(ui_theme.CHART["alert"])
        )

        for point, frame in zip(
            self.points,
            self.frames
        ):
            if frame["duration"] > self.threshold:
                painter.drawEllipse(
                    point, 5, 5
                )

        # 选中帧标记
        if (
            self.selected_index is not None
            and 0 <= self.selected_index < len(self.points)
        ):

            selected = self.points[
                self.selected_index
            ]

            marker_pen = QPen(
                QColor(ui_theme.COLORS["accent"]),
                2,
            )
            marker_pen.setCosmetic(True)
            painter.setPen(marker_pen)
            painter.drawLine(
                QPointF(selected.x(), top),
                QPointF(selected.x(), bottom),
            )
            painter.setBrush(
                QColor(ui_theme.COLORS["accent"])
            )
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(selected, 7, 7)

        # X 轴标签
        painter.setPen(
            QColor(ui_theme.CHART["axis"])
        )

        x_rect = QRectF(
            left,
            bottom + 4,
            width,
            line_height,
        )

        painter.drawText(
            x_rect,
            Qt.AlignmentFlag.AlignLeft
            | Qt.AlignmentFlag.AlignVCenter,
            tr("analysis.chart.start"),
        )
        painter.drawText(
            x_rect,
            Qt.AlignmentFlag.AlignRight
            | Qt.AlignmentFlag.AlignVCenter,
            tr("analysis.chart.end"),
        )

        painter.end()

    # 点击曲线上的数据点
    def mousePressEvent(self, event):
        if not self.points:
            return

        click = event.position()

        index = min(
            range(len(self.points)),
            key=lambda i: (
                (self.points[i].x() - click.x()) ** 2
                + (self.points[i].y() - click.y()) ** 2
            )
        )

        point = self.points[index]

        distance_squared = (
            (point.x() - click.x()) ** 2
            + (point.y() - click.y()) ** 2
        )

        if distance_squared <= 20**2:
            self.selected.emit(index)


# ==========================================
# 帧数据分析窗口
# ==========================================
class FrameViewer(QWidget):
    recheck_requested = Signal(str)

    def __init__(
        self,
        frames,
        filename="PresentMon CSV",
        index=None,
        selection=None,
        csv_path=None,
        telemetry=None,
        target_fps=60,
        embedded=False,
    ):
        super().__init__()

        ui_theme.ensure_application_theme()

        self.embedded = bool(embedded)
        self.index = index
        self.selection = selection
        self.csv_path = (
            Path(csv_path) if csv_path is not None else None
        )
        self.target_fps = int(target_fps)

        if telemetry is None and self.csv_path is not None:

            try:

                telemetry = read_telemetry(self.csv_path)

            except Exception:

                telemetry = None

        self.telemetry = telemetry

        if selection is not None:

            frames = selection.legacy_frames()

        self.frames = frames
        self.filename = filename
        self.target_name = self._find_target_name()

        self.stats = compute_stats(frames)

        self.threshold = self.stats.stutter_threshold_ms

        self.chain_panel = None
        self.chain_choices = ()

        self._bindings = []
        self._selected_index = None
        self._selected_choice_key = None
        self.diagnostic_report = None
        self._display_groups = []
        self._display_events = []
        self._guide_states = {}
        self._guide_category = None
        self.guide_checks = []
        self.guide_step_labels = []
        self.finding_blocks = []
        self.overview_values = {}
        self.export_status = None

        # 设置窗口
        if not self.embedded:

            self.setWindowTitle(tr("analysis.title"))

            self.resize(1120, 900)
            self.setMinimumSize(980, 720)

        else:

            self.setMinimumSize(0, 0)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        content.setObjectName("analysisContent")

        layout = QVBoxLayout(content)
        layout.setContentsMargins(
            ui_theme.SPACE["lg"],
            ui_theme.SPACE["lg"],
            ui_theme.SPACE["lg"],
            ui_theme.SPACE["lg"],
        )
        layout.setSpacing(ui_theme.SPACE["xl"])

        scroll.setWidget(content)
        outer.addWidget(scroll)

        # 标题
        title = QLabel()

        self._bind(title, "analysis.heading")

        ui_theme.apply_font(title, "display")

        title.setObjectName("analysisHeading")
        title.setVisible(not self.embedded)
        self.title_label = title

        # 统计摘要
        self.summary = QLabel()

        self.summary.setWordWrap(True)

        ui_theme.apply_font(
            self.summary,
            "body",
            tabular=True,
        )

        self.metrics_help = QLabel()

        self._bind(
            self.metrics_help,
            "analysis.metrics_help",
        )

        self.metrics_help.setWordWrap(True)

        ui_theme.apply_font(
            self.metrics_help,
            "caption",
        )

        self.metrics_help.setObjectName("muted")

        summary_card, summary_layout = self.make_card(
            "analysis.summary.title"
        )
        summary_layout.addWidget(self.summary)
        summary_layout.addWidget(self.metrics_help)

        self.glossary_toggle = QPushButton()
        self.glossary_toggle.setCheckable(True)
        self.glossary_toggle.setChecked(False)
        ui_theme.apply_font(
            self.glossary_toggle,
            "label",
        )
        ui_theme.set_button_variant(
            self.glossary_toggle,
            "ghost",
        )
        self.glossary_toggle.toggled.connect(
            self._toggle_glossary
        )
        summary_layout.addWidget(self.glossary_toggle)

        self.glossary_panel = QLabel()
        self.glossary_panel.setWordWrap(True)
        self.glossary_panel.setObjectName("muted")
        self.glossary_panel.setTextFormat(
            Qt.TextFormat.PlainText
        )
        ui_theme.apply_font(
            self.glossary_panel,
            "caption",
        )
        self.glossary_panel.setVisible(False)
        summary_layout.addWidget(self.glossary_panel)
        self._update_glossary_toggle_text()
        self._update_glossary_text()

        # 交换链选择（仅在提供 CaptureIndex 时显示）
        if (
            self.index is not None
            and self.selection is not None
        ):

            self.chain_panel = self.build_chain_panel()

        # 卡顿阈值控制
        controls = QHBoxLayout()
        controls.setSpacing(ui_theme.SPACE["sm"])

        self.auto_threshold = QCheckBox()

        self._bind(
            self.auto_threshold,
            "analysis.threshold.auto_label",
        )

        ui_theme.apply_font(
            self.auto_threshold,
            "body",
        )

        self._bind(
            self.auto_threshold,
            "analysis.threshold.tip",
            method="setToolTip",
        )

        self.auto_threshold.setChecked(True)

        self.threshold_input = QDoubleSpinBox()

        ui_theme.apply_font(
            self.threshold_input,
            "body",
        )

        self.threshold_input.setRange(0.1, 10000.0)
        self.threshold_input.setDecimals(1)
        self.threshold_input.setSingleStep(1.0)
        self.threshold_input.setSuffix(" ms")
        self.threshold_input.setValue(self.threshold)
        self.threshold_input.setEnabled(False)

        self.auto_threshold.toggled.connect(
            self.set_auto_threshold
        )

        self.threshold_input.valueChanged.connect(
            self.set_manual_threshold
        )

        controls.addWidget(self.auto_threshold)
        controls.addWidget(self.threshold_input)
        controls.addStretch()

        # 曲线
        self.chart = FrameChart(
            frames,
            self.threshold
        )

        # 点击帧后的详细信息
        self.details = QLabel()

        self._bind(
            self.details,
            "analysis.details.hint",
        )

        ui_theme.apply_font(
            self.details,
            "body",
        )

        self.details.setWordWrap(True)
        self.details.setMinimumHeight(
            max(
                115,
                QFontMetrics(
                    self.details.font()
                ).height() * 3,
            )
        )

        self.details.setObjectName("detailsPanel")

        details_title = QLabel()
        self._bind(details_title, "analysis.details.title")
        ui_theme.apply_font(details_title, "subheading")

        note = QLabel()

        self._bind(note, "analysis.note")

        note.setWordWrap(True)

        ui_theme.apply_font(note, "caption")

        note.setObjectName("muted")

        layout.addWidget(title)
        self.overview_card = self.build_overview_card()
        layout.addWidget(self.overview_card)
        layout.addWidget(summary_card)

        if self.chain_panel is not None:

            layout.addWidget(self.chain_panel)

        self.diagnostic_card = self.build_diagnostics_card()
        layout.addWidget(self.diagnostic_card)

        chart_card = QFrame()
        chart_card.setObjectName("card")

        chart_layout = QVBoxLayout(chart_card)
        chart_layout.setContentsMargins(
            ui_theme.SPACE["lg"],
            ui_theme.SPACE["lg"],
            ui_theme.SPACE["lg"],
            ui_theme.SPACE["lg"],
        )
        chart_layout.setSpacing(ui_theme.SPACE["md"])

        chart_header = QHBoxLayout()
        chart_header.setSpacing(ui_theme.SPACE["sm"])

        chart_title = QLabel()
        self._bind(chart_title, "analysis.chart.title")
        ui_theme.apply_font(chart_title, "subheading")
        chart_header.addWidget(chart_title)
        chart_header.addStretch()

        controls.addStretch()
        chart_header.addLayout(controls)
        chart_layout.addLayout(chart_header)
        chart_layout.addWidget(self.chart, 1)

        layout.addWidget(chart_card, 1)
        layout.addWidget(details_title)
        layout.addWidget(self.details)
        layout.addWidget(note)

        self.chart.selected.connect(
            self.show_details
        )

        self.update_summary()

        if self.chain_panel is not None:

            self.update_chain_panel()

        self._refresh_diagnostics()

        get_manager().language_changed.connect(
            self.retranslate
        )

    def build_overview_card(self):

        card, layout = self.make_card(
            "analysis.overview.title"
        )

        grid = QGridLayout()
        grid.setHorizontalSpacing(
            ui_theme.SPACE["lg"]
        )
        grid.setVerticalSpacing(
            ui_theme.SPACE["md"]
        )

        def add_tile(key, label_key, row, column, column_span=1):

            tile = QWidget()
            box = QVBoxLayout(tile)
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(ui_theme.SPACE["xs"])

            label = QLabel()
            self._bind(label, label_key)
            label.setObjectName("muted")
            ui_theme.apply_font(label, "caption")

            value = QLabel("--")
            value.setObjectName("value")
            value.setWordWrap(True)
            ui_theme.apply_font(value, "metric")

            box.addWidget(label)
            box.addWidget(value)
            self.overview_values[key] = value
            grid.addWidget(
                tile,
                row,
                column,
                1,
                column_span,
            )

        add_tile(
            "game",
            "analysis.overview.game",
            0,
            0,
            2,
        )
        add_tile(
            "duration",
            "analysis.overview.duration",
            0,
            2,
        )
        add_tile(
            "frames",
            "analysis.overview.frames",
            0,
            3,
        )
        add_tile(
            "average_fps",
            "analysis.overview.avg_fps",
            1,
            0,
        )
        add_tile(
            "p95",
            "analysis.overview.p95",
            1,
            1,
        )
        add_tile(
            "one_percent_low",
            "analysis.overview.one_percent_low",
            1,
            2,
        )
        add_tile(
            "anomalies",
            "analysis.overview.anomalies",
            1,
            3,
        )

        layout.addLayout(grid)

        return card

    def _update_overview(self):

        if not self.overview_values:

            return

        stats = self.stats
        game = (
            self.target_name
            or Path(self.filename).stem
            or tr("analysis.overview.na")
        )
        anomalies = (
            str(len(self.diagnostic_report.events))
            if self.diagnostic_report is not None
            else tr("analysis.overview.na")
        )

        values = {
            "game": game,
            "duration": f"{stats.duration_s:.2f} s",
            "frames": f"{stats.frame_count:,}",
            "average_fps": f"{stats.average_fps:.1f}",
            "p95": f"{stats.p95_frame_ms:.2f} ms",
            "one_percent_low": (
                f"{stats.one_percent_low_fps:.1f} FPS"
            ),
            "anomalies": anomalies,
        }

        for key, value in values.items():

            label = self.overview_values.get(key)

            if label is not None:

                label.setText(value)

    def make_card(self, title_key=None):

        frame = QFrame()
        frame.setObjectName("card")

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(
            ui_theme.SPACE["lg"],
            ui_theme.SPACE["lg"],
            ui_theme.SPACE["lg"],
            ui_theme.SPACE["lg"],
        )
        layout.setSpacing(ui_theme.SPACE["md"])

        if title_key is not None:

            title = QLabel()
            self._bind(title, title_key)
            ui_theme.apply_font(title, "subheading")
            layout.addWidget(title)

        return frame, layout

    def build_diagnostics_card(self):

        card, layout = self.make_card(
            "analysis.diagnostics.title"
        )

        header = QHBoxLayout()
        header.setSpacing(ui_theme.SPACE["sm"])

        intro = QLabel()
        self._bind(
            intro,
            "analysis.diagnostics.intro",
        )
        intro.setWordWrap(True)
        ui_theme.apply_font(intro, "caption")
        intro.setObjectName("muted")
        header.addWidget(intro, 1)

        self.export_btn = QPushButton()
        self._bind(
            self.export_btn,
            "analysis.diagnostics.export",
        )
        ui_theme.apply_font(self.export_btn, "label")
        ui_theme.set_button_variant(
            self.export_btn,
            "secondary",
        )
        self.export_btn.clicked.connect(
            self.export_report
        )
        header.addWidget(self.export_btn)
        layout.addLayout(header)

        overview_title = QLabel()
        self._bind(
            overview_title,
            "analysis.diagnostics.overview.title",
        )
        ui_theme.apply_font(
            overview_title,
            "label",
            weight=QFont.Weight.DemiBold,
        )
        layout.addWidget(overview_title)

        self.overview_label = QLabel()
        self.overview_label.setWordWrap(True)
        self.overview_label.setObjectName("detailsPanel")
        ui_theme.apply_font(
            self.overview_label,
            "body",
        )
        layout.addWidget(self.overview_label)

        report_intro = QLabel()
        self._bind(
            report_intro,
            "analysis.diagnostics.report.intro",
        )
        report_intro.setWordWrap(True)
        report_intro.setObjectName("muted")
        ui_theme.apply_font(
            report_intro,
            "caption",
        )
        layout.addWidget(report_intro)

        self.report_warning = QLabel()
        self.report_warning.setWordWrap(True)
        self.report_warning.setObjectName("muted")
        ui_theme.apply_font(
            self.report_warning,
            "caption",
        )
        self.report_warning.setVisible(False)
        layout.addWidget(self.report_warning)

        self.findings_report_container = QWidget()
        self.findings_report_layout = QVBoxLayout(
            self.findings_report_container
        )
        self.findings_report_layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )
        self.findings_report_layout.setSpacing(
            ui_theme.SPACE["md"]
        )
        layout.addWidget(
            self.findings_report_container
        )

        findings_title = QLabel()
        self._bind(
            findings_title,
            "analysis.diagnostics.report.guide_focus",
        )
        ui_theme.apply_font(
            findings_title,
            "label",
            weight=QFont.Weight.DemiBold,
        )
        layout.addWidget(findings_title)

        self.guide_focus_note = QLabel()
        self._bind(
            self.guide_focus_note,
            "analysis.diagnostics.report.guide_focus_note",
        )
        self.guide_focus_note.setWordWrap(True)
        self.guide_focus_note.setObjectName("muted")
        ui_theme.apply_font(
            self.guide_focus_note,
            "caption",
        )
        layout.addWidget(self.guide_focus_note)

        self.finding_list = QListWidget()
        self.finding_list.setWordWrap(True)
        self.finding_list.setSpacing(2)
        self.finding_list.setMinimumHeight(0)
        self.finding_list.setMaximumHeight(230)
        self.finding_list.setResizeMode(
            QListView.ResizeMode.Adjust
        )
        self.finding_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        ui_theme.apply_font(self.finding_list, "body")
        self.finding_list.currentRowChanged.connect(
            self._on_finding_selected
        )
        layout.addWidget(self.finding_list)

        self.finding_detail = QLabel()
        self.finding_detail.setWordWrap(True)
        self.finding_detail.setObjectName("detailsPanel")
        self.finding_detail.setMinimumHeight(76)
        ui_theme.apply_font(
            self.finding_detail,
            "body",
        )
        layout.addWidget(self.finding_detail)
        self.finding_detail.setVisible(False)

        guide_title = QLabel()
        self._bind(
            guide_title,
            "analysis.diagnostics.guide.title",
        )
        ui_theme.apply_font(
            guide_title,
            "label",
            weight=QFont.Weight.DemiBold,
        )
        layout.addWidget(guide_title)

        self.guide_note = QLabel()
        self._bind(
            self.guide_note,
            "analysis.diagnostics.guide.note",
        )
        self.guide_note.setWordWrap(True)
        ui_theme.apply_font(
            self.guide_note,
            "caption",
        )
        self.guide_note.setObjectName("muted")
        layout.addWidget(self.guide_note)

        self.guide_empty = QLabel()
        self._bind(
            self.guide_empty,
            "analysis.diagnostics.guide.empty",
        )
        self.guide_empty.setWordWrap(True)
        ui_theme.apply_font(
            self.guide_empty,
            "caption",
        )
        self.guide_empty.setObjectName("muted")
        layout.addWidget(self.guide_empty)

        self.guide_steps_layout = QVBoxLayout()
        self.guide_steps_layout.setSpacing(
            ui_theme.SPACE["sm"]
        )
        layout.addLayout(self.guide_steps_layout)

        guide_actions = QHBoxLayout()
        guide_actions.setSpacing(
            ui_theme.SPACE["sm"]
        )

        self.guide_progress = QLabel()
        self.guide_progress.setWordWrap(True)
        self.guide_progress.setObjectName("muted")
        ui_theme.apply_font(
            self.guide_progress,
            "caption",
        )
        guide_actions.addWidget(self.guide_progress, 1)

        self.guide_reset_btn = QPushButton()
        self._bind(
            self.guide_reset_btn,
            "analysis.diagnostics.guide.reset",
        )
        ui_theme.apply_font(
            self.guide_reset_btn,
            "label",
        )
        ui_theme.set_button_variant(
            self.guide_reset_btn,
            "ghost",
        )
        self.guide_reset_btn.clicked.connect(
            self.reset_guide_steps
        )
        self.guide_reset_btn.setEnabled(False)
        guide_actions.addWidget(self.guide_reset_btn)

        self.recheck_btn = QPushButton()
        self._bind(
            self.recheck_btn,
            "analysis.diagnostics.guide.recheck",
        )
        ui_theme.apply_font(
            self.recheck_btn,
            "label",
        )
        ui_theme.set_button_variant(
            self.recheck_btn,
            "secondary",
        )
        self.recheck_btn.clicked.connect(
            self.request_recheck
        )
        self.recheck_btn.setEnabled(
            bool(self.target_name)
        )
        guide_actions.addWidget(self.recheck_btn)
        layout.addLayout(guide_actions)

        self.technical_toggle = QPushButton()
        self.technical_toggle.setCheckable(True)
        self.technical_toggle.setChecked(False)
        ui_theme.apply_font(
            self.technical_toggle,
            "label",
        )
        ui_theme.set_button_variant(
            self.technical_toggle,
            "ghost",
        )
        layout.addWidget(self.technical_toggle)

        self.technical_panel = QWidget()
        technical_layout = QVBoxLayout(
            self.technical_panel
        )
        technical_layout.setContentsMargins(0, 0, 0, 0)
        technical_layout.setSpacing(
            ui_theme.SPACE["sm"]
        )

        self.technical_detail = QLabel()
        self.technical_detail.setWordWrap(True)
        self.technical_detail.setObjectName("muted")
        self.technical_detail.setTextFormat(
            Qt.TextFormat.PlainText
        )
        ui_theme.apply_font(
            self.technical_detail,
            "caption",
        )
        technical_layout.addWidget(
            self.technical_detail
        )

        sync_title = QLabel()
        self._bind(
            sync_title,
            "analysis.diagnostics.sync.title",
        )
        ui_theme.apply_font(
            sync_title,
            "label",
            weight=QFont.Weight.DemiBold,
        )
        technical_layout.addWidget(sync_title)

        self.sync_detail = QLabel()
        self.sync_detail.setWordWrap(True)
        self.sync_detail.setObjectName("muted")
        ui_theme.apply_font(
            self.sync_detail,
            "caption",
        )
        technical_layout.addWidget(self.sync_detail)

        self.technical_panel.setVisible(False)
        layout.addWidget(self.technical_panel)

        self.technical_toggle.toggled.connect(
            self._toggle_technical_details
        )
        self.technical_toggle.setText(
            tr("analysis.diagnostics.technical.show")
        )

        events_title = QLabel()
        self._bind(
            events_title,
            "analysis.diagnostics.events.title",
        )
        ui_theme.apply_font(
            events_title,
            "label",
            weight=QFont.Weight.DemiBold,
        )
        layout.addWidget(events_title)

        self.events_note = QLabel()
        self._bind(
            self.events_note,
            "analysis.diagnostics.events.note",
        )
        self.events_note.setWordWrap(True)
        ui_theme.apply_font(
            self.events_note,
            "caption",
        )
        self.events_note.setObjectName("muted")
        layout.addWidget(self.events_note)

        self.event_hint = QLabel()
        self._bind(
            self.event_hint,
            "analysis.diagnostics.events.table.hint",
        )
        self.event_hint.setWordWrap(True)
        ui_theme.apply_font(
            self.event_hint,
            "caption",
        )
        self.event_hint.setObjectName("muted")
        self.event_hint.setVisible(False)
        layout.addWidget(self.event_hint)

        self.event_table = QTableWidget(0, 5)
        self.event_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.event_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.event_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.event_table.setAlternatingRowColors(True)
        self.event_table.setShowGrid(False)
        self.event_table.setWordWrap(True)
        self.event_table.verticalHeader().setVisible(False)
        self.event_table.setMinimumHeight(0)
        self.event_table.setMaximumHeight(320)
        self.event_table.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        ui_theme.apply_table_typography(
            self.event_table
        )
        header = self.event_table.horizontalHeader()
        header.setStretchLastSection(True)

        for column in range(4):

            header.setSectionResizeMode(
                column,
                QHeaderView.ResizeMode.ResizeToContents,
            )

        header.setSectionResizeMode(
            4,
            QHeaderView.ResizeMode.Stretch,
        )
        self.event_table.itemSelectionChanged.connect(
            self._on_event_table_selection
        )
        self.event_table.setVisible(False)
        layout.addWidget(self.event_table)

        self.events_empty = QLabel()
        self._bind(
            self.events_empty,
            "analysis.diagnostics.events.empty",
        )
        self.events_empty.setWordWrap(True)
        ui_theme.apply_font(
            self.events_empty,
            "caption",
        )
        self.events_empty.setObjectName("muted")
        self.events_empty.setVisible(False)
        layout.addWidget(self.events_empty)

        self.event_detail_title = QLabel()
        self._bind(
            self.event_detail_title,
            "analysis.diagnostics.event.details_title",
        )
        ui_theme.apply_font(
            self.event_detail_title,
            "label",
            weight=QFont.Weight.DemiBold,
        )
        self.event_detail_title.setVisible(False)
        layout.addWidget(self.event_detail_title)

        self.event_detail = QLabel()
        self.event_detail.setWordWrap(True)
        self.event_detail.setObjectName("detailsPanel")
        self.event_detail.setMinimumHeight(60)
        ui_theme.apply_font(self.event_detail, "body")
        self.event_detail.setVisible(False)
        layout.addWidget(self.event_detail)

        self._update_event_table_headers()

        self.export_status = QLabel()
        self.export_status.setWordWrap(True)
        self.export_status.setObjectName("muted")
        ui_theme.apply_font(
            self.export_status,
            "caption",
        )
        layout.addWidget(self.export_status)

        return card

    def _clear_findings_report(self):

        while self.findings_report_layout.count():

            item = self.findings_report_layout.takeAt(0)
            widget = item.widget()

            if widget is not None:

                widget.setParent(None)
                widget.deleteLater()

        self.finding_blocks = []

    def _finding_evidence_text(self, finding):

        lines = []
        metrics = diagnostic_text.metric_lines(finding)

        if metrics:

            lines.append(
                tr("analysis.diagnostics.technical.metrics")
                + tr("analysis.diagnostics.label_separator")
            )
            lines.extend(f"- {line}" for line in metrics)

        if finding.evidence:

            if lines:

                lines.append("")

            lines.append(
                tr(
                    "analysis.diagnostics.technical.engine_evidence"
                )
                + tr("analysis.diagnostics.label_separator")
            )
            lines.extend(
                f"- {line}" for line in finding.evidence
            )

        if finding.caveats:

            if lines:

                lines.append("")

            lines.append(
                tr("analysis.diagnostics.technical.caveats")
                + tr("analysis.diagnostics.label_separator")
            )
            lines.extend(
                f"- {line}" for line in finding.caveats
            )

        if not lines:

            return tr(
                "analysis.diagnostics.report.evidence_none"
            )

        return "\n".join(lines)

    def _build_finding_report_block(self, group):

        finding = group["finding"]
        count = group["count"]
        guide_row = next(
            (
                row
                for row, guide_group in enumerate(
                    self._display_groups
                )
                if (
                    guide_group["category"]
                    == group["category"]
                    and guide_group["code"]
                    == group["code"]
                )
            ),
            None,
        )
        separator = tr(
            "analysis.diagnostics.label_separator"
        )
        muted = ui_theme.COLORS["text_muted"]

        frame = QFrame()
        frame.setObjectName("reportBlock")
        box = QVBoxLayout(frame)
        box.setContentsMargins(
            ui_theme.SPACE["lg"],
            ui_theme.SPACE["lg"],
            ui_theme.SPACE["lg"],
            ui_theme.SPACE["lg"],
        )
        box.setSpacing(ui_theme.SPACE["sm"])

        heading = QLabel(
            f"{diagnostic_text.category_label(finding.category)}"
            f" — {diagnostic_text.finding_summary(finding)}"
            f"{diagnostic_text.group_count_label(count)}"
        )
        heading.setWordWrap(True)
        heading.setObjectName("value")
        ui_theme.apply_font(heading, "subheading")
        box.addWidget(heading)

        badges = QLabel(
            f"{tr('analysis.diagnostics.technical.severity')}"
            f"{separator}"
            f"{diagnostic_text.severity_label(finding.severity)}"
            f"  ·  "
            f"{tr('analysis.diagnostics.technical.confidence')}"
            f"{separator}"
            f"{diagnostic_text.confidence_label(finding.confidence)}"
            f"  ·  "
            f"{tr('analysis.diagnostics.technical.claim')}"
            f"{separator}"
            f"{diagnostic_text.claim_label(finding.claim_level)}"
        )
        badges.setWordWrap(True)
        badges.setObjectName("muted")
        ui_theme.apply_font(badges, "caption")
        box.addWidget(badges)

        summary = diagnostic_text.finding_summary(finding)
        why = (
            diagnostic_text.why_text(finding)
            or tr("analysis.diagnostics.why.unknown")
        )
        limitation = (
            diagnostic_text.limit_text(finding)
            or tr("analysis.diagnostics.limit.unknown")
        )
        advice = (
            diagnostic_text.advice_text(finding)
            or tr("analysis.diagnostics.advice.unknown")
        )
        details = QLabel(
            f"<div><b>{html.escape(tr('analysis.diagnostics.plain.what_found'))}</b>"
            f"{html.escape(separator)}"
            f"{html.escape(summary)}</div>"
            f"<div style='margin-top:6px'>"
            f"<b>{html.escape(tr('analysis.diagnostics.plain.why'))}</b>"
            f"{html.escape(separator)}"
            f"{html.escape(why)}</div>"
            f"<div style='margin-top:6px'>"
            f"<b>{html.escape(tr('analysis.diagnostics.plain.certainty'))}</b>"
            f"{html.escape(separator)}"
            f"{html.escape(diagnostic_text.certainty_text(finding))}</div>"
            f"<div style='margin-top:6px; color:{muted}'>"
            f"<b>{html.escape(tr('analysis.diagnostics.plain.does_not_tell'))}</b>"
            f"{html.escape(separator)}"
            f"{html.escape(limitation)}</div>"
            f"<div style='margin-top:6px'>"
            f"<b>{html.escape(tr('analysis.diagnostics.advice.title'))}</b>"
            f"{html.escape(separator)}"
            f"{html.escape(advice)}</div>"
        )
        details.setWordWrap(True)
        details.setObjectName("detailsPanel")
        details.setTextFormat(Qt.TextFormat.RichText)
        ui_theme.apply_font(details, "body")
        box.addWidget(details)

        if count > 1:

            group_note = QLabel(
                tr(
                    "analysis.diagnostics.group.note",
                    count=count,
                )
            )
            group_note.setWordWrap(True)
            group_note.setObjectName("muted")
            ui_theme.apply_font(group_note, "caption")
            box.addWidget(group_note)

        evidence_label = QLabel(
            self._finding_evidence_text(finding)
        )
        evidence_label.setWordWrap(True)
        evidence_label.setObjectName("muted")
        evidence_label.setTextFormat(
            Qt.TextFormat.PlainText
        )
        ui_theme.apply_font(evidence_label, "caption")
        evidence_label.setVisible(False)

        evidence_toggle = QPushButton()
        evidence_toggle.setCheckable(True)
        evidence_toggle.setChecked(False)
        ui_theme.apply_font(evidence_toggle, "label")
        ui_theme.set_button_variant(
            evidence_toggle,
            "ghost",
        )
        evidence_toggle.setText(
            tr("analysis.diagnostics.report.evidence_show")
        )

        def toggle_evidence(checked):

            evidence_label.setVisible(bool(checked))
            evidence_toggle.setText(
                tr(
                    "analysis.diagnostics.report.evidence_hide"
                    if checked
                    else "analysis.diagnostics.report.evidence_show"
                )
            )

        evidence_toggle.toggled.connect(
            toggle_evidence
        )
        box.addWidget(evidence_toggle)
        box.addWidget(evidence_label)

        guide_btn = QPushButton()
        guide_btn.setText(
            tr("analysis.diagnostics.report.use_guide")
        )
        ui_theme.apply_font(guide_btn, "label")
        ui_theme.set_button_variant(
            guide_btn,
            "secondary",
        )
        guide_btn.setEnabled(guide_row is not None)
        guide_btn.clicked.connect(
            lambda _checked=False, row=guide_row: (
                self._focus_guide(row)
            )
        )
        box.addWidget(guide_btn)

        return {
            "frame": frame,
            "group": group,
            "heading": heading,
            "badges": badges,
            "details": details,
            "evidence": evidence_label,
            "evidence_toggle": evidence_toggle,
            "guide_button": guide_btn,
        }

    def _render_findings_report(self, groups):

        self._clear_findings_report()

        for group in groups:

            block = self._build_finding_report_block(
                group
            )
            self.findings_report_layout.addWidget(
                block["frame"]
            )
            self.finding_blocks.append(block)

    def _glossary_text(self):

        terms = (
            "fps",
            "one_percent_low",
            "p99",
            "frame_time",
            "qpc",
            "telemetry",
        )

        return "\n".join(
            f"{tr(f'analysis.glossary.{term}.term')}"
            f"{tr('analysis.diagnostics.label_separator')}"
            f"{tr(f'analysis.glossary.{term}.description')}"
            for term in terms
        )

    def _update_glossary_text(self):

        self.glossary_panel.setText(
            self._glossary_text()
        )

    def _update_glossary_toggle_text(self):

        key = (
            "analysis.glossary.hide"
            if self.glossary_toggle.isChecked()
            else "analysis.glossary.show"
        )
        self.glossary_toggle.setText(tr(key))

    def _toggle_glossary(self, checked):

        self.glossary_panel.setVisible(bool(checked))
        self._update_glossary_toggle_text()

    def _update_technical_toggle_text(self):

        key = (
            "analysis.diagnostics.technical.hide"
            if self.technical_toggle.isChecked()
            else "analysis.diagnostics.technical.show"
        )
        self.technical_toggle.setText(tr(key))

    def _toggle_technical_details(self, checked):

        self.technical_panel.setVisible(bool(checked))
        self._update_technical_toggle_text()

    def _update_event_table_headers(self):

        self.event_table.setHorizontalHeaderLabels(
            [
                tr("analysis.diagnostics.events.table.time"),
                tr("analysis.diagnostics.events.table.duration"),
                tr("analysis.diagnostics.events.table.type"),
                tr("analysis.diagnostics.events.table.pattern"),
                tr("analysis.diagnostics.events.table.evidence"),
            ]
        )

    def _fit_event_table_height(self):

        count = self.event_table.rowCount()

        if count <= 0:

            height = 36

        else:

            self.event_table.resizeRowsToContents()
            height = (
                self.event_table.horizontalHeader().height()
                + sum(
                    self.event_table.rowHeight(index)
                    for index in range(count)
                )
                + 2 * self.event_table.frameWidth()
                + 8
            )

        self.event_table.setFixedHeight(
            max(36, min(height, 320))
        )
        self._relayout_event_area()

    def _relayout_event_area(self):

        parent = self.event_table.parentWidget()

        if (
            parent is not None
            and parent.layout() is not None
        ):

            parent.layout().invalidate()
            parent.layout().activate()

    def _on_event_table_selection(self):

        if not self.event_table.selectedItems():

            self.event_detail.clear()
            self.event_detail.setVisible(False)
            self.event_detail_title.setVisible(False)
            self._relayout_event_area()
            return

        row = self.event_table.currentRow()

        if not 0 <= row < len(self._display_events):

            return

        self.event_detail_title.setVisible(True)
        self.event_detail.setVisible(True)
        self._show_event(
            self._display_events[row]
        )
        self._relayout_event_area()

    def _update_technical_detail(self, finding, count=1):

        if (
            self.diagnostic_report is None
            or finding is None
        ):

            self.technical_detail.setText(
                tr("analysis.diagnostics.technical.none")
            )
            return

        report = self.diagnostic_report
        budget = getattr(
            report,
            "target_budget_ms",
            0.0,
        )
        lines = [
            f"{tr('analysis.diagnostics.technical.category')}"
            f"{tr('analysis.diagnostics.label_separator')}"
            f"{diagnostic_text.category_label(finding.category)}"
            f" ({finding.category})",
            f"{tr('analysis.diagnostics.technical.claim')}"
            f"{tr('analysis.diagnostics.label_separator')}"
            f"{finding.claim_level} · "
            f"{diagnostic_text.claim_label(finding.claim_level)}",
            f"{tr('analysis.diagnostics.technical.confidence')}"
            f"{tr('analysis.diagnostics.label_separator')}"
            f"{finding.confidence} · "
            f"{diagnostic_text.confidence_label(finding.confidence)}",
            f"{tr('analysis.diagnostics.technical.severity')}"
            f"{tr('analysis.diagnostics.label_separator')}"
            f"{finding.severity} · "
            f"{diagnostic_text.severity_label(finding.severity)}",
            f"{tr('analysis.diagnostics.technical.target_fps')}"
            f"{tr('analysis.diagnostics.label_separator')}"
            f"{self.target_fps} ({budget:.2f} ms)",
            f"{tr('analysis.diagnostics.technical.threshold')}"
            f"{tr('analysis.diagnostics.label_separator')}"
            f"{self.threshold:.2f} ms",
        ]

        if count > 1:

            lines.append(
                f"{tr('analysis.diagnostics.technical.group_count')}"
                f"{tr('analysis.diagnostics.label_separator')}"
                f"{count}"
            )
            lines.append("")
            lines.append(
                tr("analysis.diagnostics.technical.select_event")
            )
            self.technical_detail.setText(
                "\n".join(lines)
            )
            return

        window = diagnostic_text.finding_window_text(finding)

        if window:

            lines.append(
                f"{tr('analysis.diagnostics.technical.window')}"
                f"{tr('analysis.diagnostics.label_separator')}"
                f"{window}"
            )

        lines.append("")
        lines.append(
            f"{tr('analysis.diagnostics.technical.metrics')}"
            f"{tr('analysis.diagnostics.label_separator')}"
        )
        metric_lines = diagnostic_text.metric_lines(finding)

        if metric_lines:

            lines.extend(
                f"- {line}" for line in metric_lines
            )

        else:

            lines.append(
                f"- {tr('analysis.diagnostics.technical.no_metrics')}"
            )

        lines.append("")
        lines.append(
            f"{tr('analysis.diagnostics.technical.engine_evidence')}"
            f"{tr('analysis.diagnostics.label_separator')}"
        )

        if finding.evidence:

            lines.extend(
                f"- {line}" for line in finding.evidence
            )

        else:

            lines.append(
                f"- {tr('analysis.diagnostics.technical.no_evidence')}"
            )

        lines.append("")
        lines.append(
            f"{tr('analysis.diagnostics.technical.caveats')}"
            f"{tr('analysis.diagnostics.label_separator')}"
        )

        if finding.caveats:

            lines.extend(
                f"- {line}" for line in finding.caveats
            )

        else:

            lines.append(
                f"- {tr('analysis.diagnostics.technical.no_caveats')}"
            )

        self.technical_detail.setText(
            "\n".join(lines)
        )

    def _refresh_diagnostics(self, preserve_event_time=None):

        if preserve_event_time is None:

            preserve_event_time = self._selected_event_time()

        try:

            self.diagnostic_report = diagnostics.analyze(
                self.frames,
                stats=self.stats,
                telemetry=self.telemetry,
                target_fps=self.target_fps,
            )

        except Exception:

            self.diagnostic_report = None

        self._display_groups = []
        self._display_events = []

        self.finding_list.blockSignals(True)
        self.event_table.blockSignals(True)
        self.finding_list.clear()
        self.event_table.clearContents()
        self.event_table.setRowCount(0)
        self.event_table.setVisible(False)
        self.events_empty.setVisible(False)
        self.event_hint.setVisible(False)
        self.event_detail.clear()
        self.event_detail.setVisible(False)
        self.event_detail_title.setVisible(False)

        if self.diagnostic_report is None:

            self._clear_findings_report()
            self.report_warning.clear()
            self.report_warning.setVisible(False)
            self.overview_label.setText(
                "\n".join(
                    f"• {line}"
                    for line in diagnostic_text.anomaly_summary(
                        None
                    )
                )
            )
            self.finding_list.addItem(
                tr("analysis.diagnostics.code.insufficient_evidence")
            )
            self.finding_detail.setText(
                tr("analysis.diagnostics.code.insufficient_evidence")
            )
            self.events_empty.setVisible(True)
            self._fit_list_height(
                self.finding_list,
                230,
            )
            self.sync_detail.setText(
                tr(
                    "analysis.diagnostics.sync.quality.unknown"
                )
            )
            self.export_btn.setEnabled(False)
            self._show_guide(None)
            self._update_technical_detail(None)
            self._update_overview()
            self.finding_list.blockSignals(False)
            self.event_table.blockSignals(False)
            return

        report = self.diagnostic_report
        data_quality = [
            finding for finding in report.findings
            if finding.category == "data_quality"
        ]
        report_groups = diagnostic_text.group_findings(
            report.findings
        )
        ordered_report_groups = [
            group for group in report_groups
            if group["category"] != "data_quality"
        ] + [
            group for group in report_groups
            if group["category"] == "data_quality"
        ]

        groups = ordered_report_groups
        self._display_groups = groups
        self._render_findings_report(
            ordered_report_groups
        )

        warning = diagnostic_text.evidence_warning(report)
        self.report_warning.setText(warning)
        self.report_warning.setVisible(bool(warning))

        for group in groups:

            finding = group["finding"]
            item_text = (
                f"{diagnostic_text.category_label(finding.category)}"
                f" · {diagnostic_text.finding_summary(finding)}"
                f"{diagnostic_text.group_count_label(group['count'])}\n"
                f"{diagnostic_text.plain_claim_label(finding.claim_level)}"
                f" · {diagnostic_text.plain_strength_label(finding.confidence)}"
            )
            self.finding_list.addItem(item_text)

        self._display_events = list(report.events)
        rows, _periodicity = (
            diagnostic_text.event_table_rows(report)
        )
        selected_index = None

        if rows:

            self.event_table.setRowCount(len(rows))

            for index, row in enumerate(rows):

                values = (
                    f"{row['time']:.2f} s",
                    f"{row['duration']:.2f} ms",
                    row["type"],
                    row["pattern"],
                    row["evidence"],
                )

                for column, value in enumerate(values):

                    item = QTableWidgetItem(value)
                    item.setFlags(
                        item.flags()
                        & ~Qt.ItemFlag.ItemIsEditable
                    )
                    self.event_table.setItem(
                        index,
                        column,
                        item,
                    )

            self.event_table.setVisible(True)
            self.events_empty.setVisible(False)
            self.event_hint.setVisible(True)
            self._fit_event_table_height()

            if preserve_event_time is not None:

                for index, event in enumerate(
                    self._display_events
                ):

                    if abs(
                        event.time_ms - preserve_event_time
                    ) < 1e-6:

                        selected_index = index
                        break

        else:

            self.event_table.setVisible(False)
            self.events_empty.setVisible(True)

        self.overview_label.setText(
            "\n".join(
                f"• {line}"
                for line in diagnostic_text.anomaly_summary(
                    report
                )
            )
        )
        self._fit_list_height(
            self.finding_list,
            230,
        )

        self.finding_list.blockSignals(False)
        self.event_table.blockSignals(False)

        if self.finding_list.count():

            self.finding_list.setCurrentRow(0)

        else:

            self._show_guide(None)
            self._update_technical_detail(None)

        self.sync_detail.setText(
            diagnostic_text.sync_lines(
                report,
                data_quality,
            )
        )
        self.export_btn.setEnabled(True)
        self.export_status.clear()
        self._update_overview()

        if selected_index is not None:

            self.event_table.setCurrentCell(
                selected_index,
                0,
            )
            self._on_event_table_selection()

        else:

            self.event_table.setCurrentCell(-1, -1)
            self.event_table.clearSelection()
            self._on_event_table_selection()

    def _find_target_name(self):

        for frame in self.frames:

            row = frame.get("row") or {}
            name = row.get("Application")

            if name:

                return str(name)

        return ""

    def _guide_key(self, category):

        if (
            category in diagnostic_text.GUIDE_KEYS
            and category != "unknown"
        ):

            return category

        return "data_quality"

    def _clear_guide_steps(self):

        while self.guide_steps_layout.count():

            item = self.guide_steps_layout.takeAt(0)
            widget = item.widget()

            if widget is not None:

                widget.setParent(None)
                widget.deleteLater()

        self.guide_checks = []
        self.guide_step_labels = []

    def _show_guide(self, category):

        self._clear_guide_steps()
        self._guide_category = (
            None
            if category is None
            else self._guide_key(category)
        )

        if category is None:

            self.guide_empty.show()
            self.guide_progress.clear()
            self.guide_reset_btn.setEnabled(False)
            return

        self.guide_empty.hide()
        steps = diagnostic_text.guide_steps(category)
        state = self._guide_states.setdefault(
            self._guide_category,
            [False] * len(steps),
        )

        if len(state) != len(steps):

            state[:] = (
                list(state) + [False] * len(steps)
            )[:len(steps)]

        for index, text in enumerate(steps):

            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(ui_theme.SPACE["sm"])

            check = QCheckBox()
            check.setAccessibleName(text)
            check.setSizePolicy(
                QSizePolicy.Policy.Fixed,
                QSizePolicy.Policy.Fixed,
            )
            check.setChecked(bool(state[index]))
            check.toggled.connect(
                lambda checked, position=index: (
                    self._on_guide_step_toggled(
                        position,
                        checked,
                    )
                )
            )
            row_layout.addWidget(
                check,
                0,
                Qt.AlignmentFlag.AlignTop,
            )

            label = QLabel(text)
            label.setWordWrap(True)
            label.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Preferred,
            )
            ui_theme.apply_font(label, "body")
            row_layout.addWidget(label, 1)

            self.guide_steps_layout.addWidget(row)
            self.guide_checks.append(check)
            self.guide_step_labels.append(label)

        self.guide_reset_btn.setEnabled(True)
        self._update_guide_progress()

    def _on_guide_step_toggled(self, index, checked):

        if self._guide_category is None:

            return

        state = self._guide_states.setdefault(
            self._guide_category,
            [],
        )

        if 0 <= index < len(state):

            state[index] = bool(checked)

        self._update_guide_progress()

    def _update_guide_progress(self):

        total = len(self.guide_checks)
        done = sum(
            1
            for check in self.guide_checks
            if check.isChecked()
        )

        self.guide_progress.setText(
            tr(
                "analysis.diagnostics.guide.progress",
                done=done,
                total=total,
            )
            if total
            else ""
        )

    def reset_guide_steps(self):

        if self._guide_category is None:

            return

        state = self._guide_states.get(
            self._guide_category
        )

        if not state:

            return

        for index, check in enumerate(self.guide_checks):

            check.blockSignals(True)
            check.setChecked(False)
            check.blockSignals(False)

            if index < len(state):

                state[index] = False

        self._update_guide_progress()

    def request_recheck(self):

        if self.target_name:

            self.recheck_requested.emit(
                self.target_name
            )

    def _fit_list_height(self, widget, max_height):

        widget.setMinimumHeight(0)
        widget.setMaximumHeight(max_height)
        count = widget.count()

        if count <= 0:

            height = 36

        else:

            widget.doItemsLayout()
            row_height = max(
                max(
                    widget.sizeHintForRow(index),
                    widget.visualItemRect(
                        widget.item(index)
                    ).height(),
                )
                for index in range(count)
            )

            if row_height <= 0:

                row_height = (
                    widget.fontMetrics().height() + 8
                )

            height = (
                row_height * count
                + 2 * widget.frameWidth()
                + 8
            )

        widget.setFixedHeight(
            max(36, min(height, max_height))
        )

    def _selected_event_time(self):

        if not self.event_table.selectedItems():

            return None

        row = self.event_table.currentRow()

        if 0 <= row < len(self._display_events):

            return self._display_events[row].time_ms

        return None

    def _focus_guide(self, row):

        if row is None:

            return

        self.finding_list.setCurrentRow(row)
        scroll = self.findChild(QScrollArea)

        if scroll is not None:

            scroll.ensureWidgetVisible(
                self.guide_note,
                0,
                24,
            )

    def _on_finding_selected(self, row):

        if not 0 <= row < len(self._display_groups):

            return

        group = self._display_groups[row]
        finding = group["finding"]
        count = group["count"]
        muted = ui_theme.COLORS["text_muted"]
        separator = tr(
            "analysis.diagnostics.label_separator"
        )
        summary = diagnostic_text.finding_summary(finding)
        why = diagnostic_text.why_text(finding)
        limitation = diagnostic_text.limit_text(finding)
        warning = diagnostic_text.evidence_warning(
            self.diagnostic_report
        )
        parts = [
            f"<div><b>{html.escape(tr('analysis.diagnostics.plain.what_found'))}</b>"
            f"{html.escape(separator)}"
            f"{html.escape(summary)}</div>",
            f"<div style='margin-top:6px'>"
            f"<b>{html.escape(tr('analysis.diagnostics.plain.why'))}</b>"
            f"{html.escape(separator)}"
            f"{html.escape(why or tr('analysis.diagnostics.why.unknown'))}</div>",
            f"<div style='margin-top:6px'>"
            f"<b>{html.escape(tr('analysis.diagnostics.plain.certainty'))}</b>"
            f"{html.escape(separator)}"
            f"{html.escape(diagnostic_text.certainty_text(finding))}</div>",
            f"<div style='color:{muted}; margin-top:4px'>"
            f"<b>{html.escape(tr('analysis.diagnostics.plain.does_not_tell'))}</b>"
            f"{html.escape(separator)}"
            f"{html.escape(limitation or tr('analysis.diagnostics.limit.unknown'))}</div>",
        ]

        if count > 1:

            parts.append(
                f"<div style='color:{muted}; margin-top:4px'>"
                f"{html.escape(tr('analysis.diagnostics.group.note', count=count))}</div>"
            )

        if warning:

            parts.append(
                f"<div style='color:{muted}; margin-top:4px'>"
                f"{html.escape(warning)}</div>"
            )

        parts.append(
            f"<div style='margin-top:6px'>"
            f"<b>{html.escape(tr('analysis.diagnostics.plain.next'))}</b>"
            f"{html.escape(separator)}"
            f"{html.escape(tr('analysis.diagnostics.plain.next_text'))}</div>"
        )

        self.finding_detail.setTextFormat(
            Qt.TextFormat.RichText
        )
        self.finding_detail.setText("".join(parts))
        self._update_technical_detail(finding, count)
        self._show_guide(finding.category)

    def _show_event(self, event):

        frame_index = event.frame_index

        if not (
            0 <= frame_index < len(self.frames)
        ):

            frame_index = min(
                range(len(self.frames)),
                key=lambda index: abs(
                    self.frames[index]["time"]
                    - event.time_ms
                ),
            )

        self.show_details(frame_index)
        related_finding = diagnostic_text.event_finding(
            event,
            self.diagnostic_report.findings,
        )
        related = (
            [related_finding]
            if related_finding is not None
            else []
        )
        detail_lines = diagnostic_text.event_details(
            event,
            self.frames[frame_index],
        ).splitlines()
        muted = ui_theme.COLORS["text_muted"]
        parts = []

        if detail_lines:

            parts.append(
                f"<div><b>{html.escape(detail_lines[0])}</b></div>"
            )
            parts.extend(
                f"<div style='color:{muted}'>"
                f"{html.escape(line)}</div>"
                for line in detail_lines[1:]
                if line
            )

        parts.extend(
            f"<div>• {html.escape(diagnostic_text.finding_summary(finding))}</div>"
            for finding in related
        )
        self.event_detail.setTextFormat(
            Qt.TextFormat.RichText
        )
        self.event_detail.setText("".join(parts))

    def export_report(self):

        if self.diagnostic_report is None:

            QMessageBox.information(
                self,
                tr("analysis.diagnostics.export.title"),
                tr("analysis.diagnostics.export.none"),
            )
            return

        default_name = Path(self.filename).name

        if self.csv_path is not None:

            default = self.csv_path.with_suffix(
                ".diagnostics.md"
            )

        else:

            default = Path(
                default_name
            ).with_suffix(".diagnostics.md")

        filename, selected_filter = (
            QFileDialog.getSaveFileName(
                self,
                tr("analysis.diagnostics.export.title"),
                str(default),
                tr("analysis.diagnostics.export.filter"),
            )
        )

        if not filename:

            return

        path = Path(filename)

        if path.suffix.lower() not in (".md", ".json"):

            path = path.with_suffix(
                ".json"
                if "JSON" in selected_filter
                else ".md"
            )

        target = ""

        if self.frames:

            target = (
                (self.frames[0].get("row") or {}).get(
                    "Application",
                    "",
                )
            )

        profile = ""

        if self.telemetry is not None:

            metadata = (
                getattr(self.telemetry, "metadata", {}) or {}
            )
            profile = (
                (metadata.get("capture") or {}).get(
                    "profile",
                    "",
                )
            )

        try:

            diagnostic_report.write_report(
                self.diagnostic_report,
                path,
                capture_name=Path(self.filename).name,
                target_name=target,
                profile=profile,
            )

        except (OSError, ValueError) as error:

            QMessageBox.warning(
                self,
                tr("analysis.diagnostics.export.failed.title"),
                tr(
                    "analysis.diagnostics.export.failed.message",
                    detail=str(error),
                ),
            )
            return

        self.export_status.setText(
            tr(
                "analysis.diagnostics.export.done",
                name=path.name,
            )
        )

    def _bind(
        self,
        widget,
        key,
        method="setText",
        **kwargs,
    ):

        self._bindings.append(
            (widget, key, method, kwargs)
        )

        getattr(widget, method)(
            tr(key, **kwargs)
        )

        return widget

    def _choice_key(self, choice):

        return tuple(
            chain.key
            for chain in choice.group.chains
        )

    def _choice_label(self, choice):

        if len(choice.group.chains) > 1:

            name = tr(
                "analysis.chain.merged",
                count=len(choice.group.chains),
            )

        else:

            name = choice.group.chains[0].label

        return tr(
            "analysis.chain.choice",
            name=name,
            frames=choice.group.frame_count,
            duration=(
                choice.group.span_ms / 1000.0
            ),
        )

    # --------------------------------------
    # 交换链选择面板
    # --------------------------------------

    def build_chain_panel(self):

        panel = QFrame()
        panel.setObjectName("chainPanel")

        box = QVBoxLayout(panel)
        box.setContentsMargins(
            ui_theme.SPACE["lg"],
            ui_theme.SPACE["md"],
            ui_theme.SPACE["lg"],
            ui_theme.SPACE["md"],
        )

        row = QHBoxLayout()
        row.setSpacing(ui_theme.SPACE["sm"])

        chain_label = QLabel()

        self._bind(chain_label, "analysis.chain.label")

        ui_theme.apply_font(chain_label, "label")

        row.addWidget(chain_label)

        self.chain_combo = QComboBox()

        ui_theme.apply_font(
            self.chain_combo,
            "body",
        )

        self.chain_combo.setMinimumWidth(420)

        self._bind(
            self.chain_combo,
            "analysis.chain.tip",
            method="setToolTip",
        )

        self.chain_choices = swap_chains.list_choices(
            self.index
        )

        self.chain_combo.addItem(
            tr("analysis.chain.auto")
        )

        for choice in self.chain_choices:

            self.chain_combo.addItem(
                self._choice_label(choice)
            )

        row.addWidget(self.chain_combo, 1)

        self.confidence_label = QLabel()

        ui_theme.apply_font(
            self.confidence_label,
            "label",
            weight=QFont.Weight.DemiBold,
        )

        row.addWidget(self.confidence_label)

        box.addLayout(row)

        self.chain_reason = QLabel()

        self.chain_reason.setWordWrap(True)

        ui_theme.apply_font(
            self.chain_reason,
            "caption",
        )

        self.chain_reason.setObjectName("muted")

        box.addWidget(self.chain_reason)

        self.chain_note = QLabel()

        self.chain_note.setWordWrap(True)

        ui_theme.apply_font(
            self.chain_note,
            "caption",
        )

        self.chain_note.setObjectName("muted")

        box.addWidget(self.chain_note)

        self.chain_combo.currentIndexChanged.connect(
            self.on_chain_changed
        )

        return panel

    def on_chain_changed(self, combo_index):

        if self.index is None:

            return

        try:

            if combo_index <= 0:

                self._selected_choice_key = None

                selection = swap_chains.recommend(
                    self.index
                )

            else:

                choice = self.chain_choices[
                    combo_index - 1
                ]

                self._selected_choice_key = (
                    self._choice_key(choice)
                )

                specs = tuple(
                    (
                        chain.swap_chain,
                        chain.segment,
                    )
                    for chain in choice.group.chains
                )

                selection = swap_chains.recommend(
                    self.index,
                    swap_chains.SelectionOverride(
                        swap_chains=specs
                    ),
                )

        except ValueError as error:

            QMessageBox.warning(
                self,
                tr("analysis.chain.error_title"),
                str(error),
            )

            self.chain_combo.blockSignals(True)
            self.chain_combo.setCurrentIndex(0)
            self.chain_combo.blockSignals(False)

            return

        self.apply_selection(selection)

    def apply_selection(self, selection):

        self.selection = selection
        self.frames = selection.legacy_frames()

        self.chart.frames = self.frames
        self.chart.points = []
        self.chart.selected_index = None
        self._selected_index = None

        self.details.setText(
            tr("analysis.details.hint")
        )

        self.recompute_stats()
        self.update_chain_panel()
        self._refresh_diagnostics()

    def _render_reason(self, selection):

        if not selection.reason_parts:

            return selection.reason

        separator = tr("analysis.reason.separator")

        return separator.join(
            tr(key, **args)
            for key, args in selection.reason_parts
        )

    def update_chain_panel(self):

        if (
            self.chain_panel is None
            or self.selection is None
        ):

            return

        selection = self.selection

        styles = {
            "high": ui_theme.COLORS["accent"],
            "medium": ui_theme.COLORS["warning"],
            "uncertain": ui_theme.COLORS["danger"],
            "low": ui_theme.COLORS["danger"],
            "user": ui_theme.COLORS["info"],
        }

        color = styles.get(
            selection.confidence,
            ui_theme.COLORS["text_muted"],
        )

        text = tr(
            "analysis.confidence."
            + selection.confidence
        )

        self.confidence_label.setText(text)

        self.confidence_label.setStyleSheet(
            f"color: {color};"
        )

        self.chain_reason.setText(
            tr("analysis.reason.prefix")
            + " "
            + self._render_reason(selection)
        )

        selected_keys = {
            chain.key
            for chain in selection.selected.chains
        }

        excluded = [
            chain
            for chain in self.index.chains
            if chain.key not in selected_keys
        ]

        if excluded:

            self.chain_note.setText(
                tr(
                    "analysis.chain.excluded",
                    selected=len(
                        selection.selected.chains
                    ),
                    total=len(self.index.chains),
                    excluded=len(excluded),
                )
            )

        else:

            self.chain_note.setText(
                tr("analysis.chain.all")
            )

    # 统计摘要
    def update_summary(self):

        stats = self.stats

        mode = tr(
            "analysis.threshold.auto"
            if self.auto_threshold.isChecked()
            else "analysis.threshold.manual"
        )

        lines = [
            tr(
                "analysis.summary.file",
                name=self.filename,
            ),
            tr(
                "analysis.summary.frames",
                frames=stats.frame_count,
                duration=stats.duration_s,
            ),
            tr(
                "analysis.summary.fps",
                fps=stats.average_fps,
                low=stats.one_percent_low_fps,
                mean=stats.mean_frame_ms,
            ),
            tr(
                "analysis.summary.percentiles",
                p50=stats.median_frame_ms,
                p95=stats.p95_frame_ms,
                p99=stats.p99_frame_ms,
                maximum=stats.max_frame_ms,
            ),
            tr(
                "analysis.summary.stutters",
                count=stats.stutter_count,
                percent=stats.stutter_percent,
                mode=mode,
                threshold=stats.stutter_threshold_ms,
            ),
        ]

        if stats.skipped_frames:

            lines.append(
                tr(
                    "analysis.summary.skipped",
                    count=stats.skipped_frames,
                )
            )

        if stats.long_frame_count:

            lines.append(
                tr(
                    "analysis.summary.long_frames",
                    count=stats.long_frame_count,
                )
            )

        self.summary.setText("\n".join(lines))
        self._update_overview()

        # Keep the manual control in sync without re-entering
        # recompute_stats() through valueChanged.
        self.threshold_input.blockSignals(True)
        self.threshold_input.setValue(
            stats.stutter_threshold_ms
        )
        self.threshold_input.blockSignals(False)

    def set_auto_threshold(self, enabled):

        self.threshold_input.setEnabled(not enabled)

        self.recompute_stats()

    def set_manual_threshold(self, _value):

        if self.auto_threshold.isChecked():

            return

        self.recompute_stats()

    def recompute_stats(self):

        threshold = (
            None
            if self.auto_threshold.isChecked()
            else self.threshold_input.value()
        )

        self.stats = compute_stats(
            self.frames,
            threshold_ms=threshold,
        )

        self.threshold = (
            self.stats.stutter_threshold_ms
        )

        self.chart.threshold = self.threshold
        self.chart.update()

        self.update_summary()

    def _sync_chain_combo(self):

        if self.chain_panel is None:

            return

        self.chain_combo.blockSignals(True)

        self.chain_combo.setItemText(
            0,
            tr("analysis.chain.auto"),
        )

        for position, choice in enumerate(
            self.chain_choices
        ):

            self.chain_combo.setItemText(
                position + 1,
                self._choice_label(choice),
            )

        current = 0

        if self._selected_choice_key is not None:

            for position, choice in enumerate(
                self.chain_choices
            ):

                if (
                    self._choice_key(choice)
                    == self._selected_choice_key
                ):

                    current = position + 1
                    break

        self.chain_combo.setCurrentIndex(current)
        self.chain_combo.blockSignals(False)

    def retranslate(self):
        """Refresh text only; statistics and selection are untouched."""

        if not self.embedded:

            self.setWindowTitle(tr("analysis.title"))

        for widget, key, method, kwargs in self._bindings:

            getattr(widget, method)(
                tr(key, **kwargs)
            )

        self._sync_chain_combo()
        self.update_summary()
        self._update_glossary_toggle_text()
        self._update_glossary_text()
        self._update_technical_toggle_text()
        self._update_event_table_headers()

        if self.chain_panel is not None:

            self.update_chain_panel()

        if self.diagnostic_report is not None:

            self._refresh_diagnostics()

        else:

            self.overview_label.setText(
                "\n".join(
                    f"• {line}"
                    for line in diagnostic_text.anomaly_summary(
                        None
                    )
                )
            )
            self._update_technical_detail(None)

        if self._selected_index is not None:

            self.show_details(
                self._selected_index
            )

        else:

            self.details.setText(
                tr("analysis.details.hint")
            )

        self.chart.update()

    # 显示某一帧的数据
    def show_details(self, index):

        self._selected_index = index
        self.chart.selected_index = index
        self.chart.update()

        frame = self.frames[index]
        row = frame["row"]

        display = tr(
            (
                "analysis.details.display_yes"
                if frame["displayed"]
                else "analysis.details.display_no"
            )
        )

        self.details.setText(
            tr(
                "analysis.details.frame",
                index=index + 1,
                duration=frame["duration"],
            )
            + "\n"
            + tr(
                "analysis.details.cpu_gpu",
                cpu=row.get("CPUBusy", "NA"),
                gpu=row.get("GPUBusy", "NA"),
                wait=row.get("GPUWait", "NA"),
            )
            + "\n"
            + display
        )


# ==========================================
# 单独运行分析器（可选）
# ==========================================
def main():
    if len(sys.argv) > 1:
        csv_path = Path(sys.argv[1])
    else:
        csv_path = Path(__file__).with_name(
            "sample_capture.csv"
        )

    ui_theme.configure_high_dpi()

    app = QApplication(sys.argv)

    ui_theme.ensure_application_theme(app)

    try:
        frames = load_frames(csv_path)

    except (OSError, ValueError, KeyError) as error:
        print(f"Failed to load CSV: {error}")
        return 1

    window = FrameViewer(
        frames,
        csv_path.name,
        csv_path=csv_path,
    )

    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
