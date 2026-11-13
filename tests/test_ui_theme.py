"""UI-1 typography/high-DPI foundation tests."""

import os
import sys
import unittest

from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtGui import (  # noqa: E402
    QColor,
    QFont,
    QImage,
    QPalette,
)
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QFrame,
    QPushButton,
    QTableWidget,
    QWidget,
)

import main as laglens  # noqa: E402
import ui_theme  # noqa: E402
from frame_viewer import FrameChart  # noqa: E402


class UiThemeTests(unittest.TestCase):

    app = None

    @classmethod
    def setUpClass(cls):

        cls.app = QApplication.instance() or QApplication([])

    def test_base_point_size_has_a_readable_floor(self):

        self.assertEqual(
            ui_theme.system_base_point_size(
                QFont("Segoe UI", 8)
            ),
            10.0,
        )
        self.assertEqual(
            ui_theme.system_base_point_size(
                QFont("Segoe UI", 12)
            ),
            12.0,
        )

    def test_role_scale_is_ordered(self):

        base = 10.0

        body = ui_theme.build_font("body", base)
        heading = ui_theme.build_font("heading", base)
        caption = ui_theme.build_font("caption", base)
        metric = ui_theme.build_font("metric", base)
        label = ui_theme.build_font("label", base)

        self.assertEqual(body.pointSizeF(), 10.0)
        self.assertGreater(
            heading.pointSizeF(),
            body.pointSizeF(),
        )
        self.assertLess(
            caption.pointSizeF(),
            body.pointSizeF(),
        )
        self.assertGreater(
            metric.pointSizeF(),
            body.pointSizeF(),
        )
        self.assertLess(
            label.pointSizeF(),
            body.pointSizeF(),
        )

    def test_family_stack_keeps_cjk_fallback(self):

        families = ui_theme.build_font(
            "body",
            10.0,
        ).families()

        self.assertIn("Segoe UI Variable Text", families)
        self.assertIn("Microsoft YaHei UI", families)

    def test_metric_and_mono_fonts_use_tabular_figures(self):

        for role in ("metric", "mono"):

            font = ui_theme.build_font(role, 10.0)

            self.assertTrue(
                font.featureTags(),
                f"{role} must request tabular figures",
            )

    def test_table_typography_is_font_aware(self):

        table = QTableWidget(0, 2)

        try:

            ui_theme.apply_table_typography(table)

            body_height = ui_theme.font("body").pointSizeF()
            row_height = (
                table.verticalHeader()
                .defaultSectionSize()
            )

            self.assertGreater(body_height, 0)
            self.assertGreaterEqual(row_height, 32)
            self.assertIsNotNone(table.font())
            self.assertIsNotNone(
                table.horizontalHeader().font()
            )

        finally:

            table.deleteLater()
            self.app.processEvents()

    def test_chart_typography_uses_the_caption_role(self):

        chart = QWidget()

        try:

            ui_theme.apply_chart_typography(chart)

            self.assertGreater(
                chart.font().pointSizeF(),
                0,
            )

        finally:

            chart.deleteLater()
            self.app.processEvents()

    def test_live_chart_renders_without_pixmap_scaling(self):

        chart = laglens.LiveChart("%")

        try:

            chart.resize(800, 300)

            for value in (10, 25, 40, 55, 70):
                chart.add(value)

            image = QImage(
                800,
                300,
                QImage.Format.Format_ARGB32,
            )
            image.fill(QColor("#0B0F10"))

            chart.render(image)

            self.assertFalse(image.isNull())
            self.assertEqual(image.width(), 800)

        finally:

            chart.deleteLater()
            self.app.processEvents()

    def test_frame_chart_renders_with_font_metrics(self):

        frames = [
            {
                "time": index * 16.0,
                "duration": 16.0 + index * 5.0,
            }
            for index in range(20)
        ]

        chart = FrameChart(frames, 50.0)

        try:

            chart.resize(900, 320)

            image = QImage(
                900,
                320,
                QImage.Format.Format_ARGB32,
            )
            image.fill(QColor("#0B0F10"))

            chart.render(image)

            self.assertFalse(image.isNull())
            self.assertEqual(len(chart.points), 20)

        finally:

            chart.deleteLater()
            self.app.processEvents()

    def test_design_tokens_are_complete(self):

        self.assertEqual(ui_theme.SPACE["md"], 12)
        self.assertEqual(ui_theme.RADIUS["lg"], 14)
        self.assertIn("accent", ui_theme.COLORS)
        self.assertIn("surface", ui_theme.COLORS)
        self.assertTrue(
            (ROOT / "assets" / "check.svg").is_file()
        )
        self.assertTrue(
            (ROOT / "assets" / "chevron-down.svg").is_file()
        )

    def test_card_grid_reflows_with_width(self):

        grid = laglens.CardGrid(210)

        try:

            grid.show()

            for _ in range(5):
                grid.add_card(QFrame())

            grid.resize(1180, 200)
            self.app.processEvents()

            self.assertEqual(grid.column_count(), 5)

            grid.resize(900, 200)
            self.app.processEvents()

            self.assertEqual(grid.column_count(), 4)

            grid.resize(500, 200)
            self.app.processEvents()

            self.assertEqual(grid.column_count(), 2)

        finally:

            grid.close()
            grid.deleteLater()
            self.app.processEvents()

    def test_theme_applies_fusion_and_palette(self):

        ui_theme.ensure_application_theme(self.app)

        self.assertTrue(
            self.app.property(ui_theme.THEME_PROPERTY)
        )
        self.assertEqual(
            self.app.palette()
            .color(QPalette.ColorRole.Window)
            .name()
            .lower(),
            ui_theme.COLORS["canvas"].lower(),
        )
        self.assertIn(
            'QPushButton[variant="primary"]',
            self.app.styleSheet(),
        )
        stylesheet = self.app.styleSheet()

        for selector in (
            "QPushButton:hover",
            "QPushButton:pressed",
            "QPushButton:focus",
            "QPushButton:disabled",
            "QLineEdit:focus",
            "QCheckBox::indicator:checked",
            "QTableWidget::item:selected",
            "QHeaderView::section",
            "QScrollBar:vertical",
            "QToolTip",
        ):

            self.assertIn(selector, stylesheet)

    def test_button_variant_property_is_set(self):

        button = QPushButton()

        try:

            ui_theme.set_button_variant(
                button,
                "primary",
            )

            self.assertEqual(
                button.property("variant"),
                "primary",
            )

        finally:

            button.deleteLater()
            self.app.processEvents()

    def test_global_stylesheet_no_longer_hardcodes_pixel_fonts(self):

        stylesheet = ui_theme.build_stylesheet()

        self.assertNotIn("13px", stylesheet)
        self.assertNotIn("font-size", stylesheet)
        self.assertNotIn("font-family", stylesheet)

        for name in (
            "main.py",
            "frame_viewer.py",
            "process_dialog.py",
        ):

            source = (ROOT / name).read_text(
                encoding="utf-8"
            )

            self.assertNotIn("font-size:", source, name)
            self.assertNotIn("font-family:", source, name)
            self.assertNotIn("13px 'Segoe UI'", source, name)


if __name__ == "__main__":

    unittest.main()
