"""UI-1 typography and high-DPI foundation.

The Windows text-size preference is reflected in QApplication's default
font.  Qt style sheets with pixel font sizes override that preference,
so this module anchors all text roles to the system point size instead.

Qt 6 already scales widgets and QPainter coordinates for the display
DPR.  We only make the rounding policy explicit before QApplication is
created; we do not enable or re-apply scaling elsewhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from string import Template

from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontInfo,
    QFontMetrics,
    QGuiApplication,
    QPalette,
)
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QStyleFactory,
)

import runtime_paths


MIN_BASE_POINT_SIZE = 10.0

TEXT_FAMILIES = (
    "Segoe UI Variable Text",
    "Segoe UI",
    "Microsoft YaHei UI",
    "Microsoft YaHei",
)

DISPLAY_FAMILIES = (
    "Segoe UI Variable Display",
    "Segoe UI",
    "Microsoft YaHei UI",
    "Microsoft YaHei",
)

MONO_FAMILIES = (
    "Cascadia Mono",
    "Consolas",
    "Courier New",
)

BASE_POINT_PROPERTY = "laglens.basePointSize"
THEME_PROPERTY = "laglens.themeApplied"
CHECK_ICON = runtime_paths.resource_path(
    "assets",
    "check.svg",
).as_posix()
CHEVRON_ICON = runtime_paths.resource_path(
    "assets",
    "chevron-down.svg",
).as_posix()


COLORS = {
    "canvas": "#0B0D10",
    "surface": "#14181F",
    "surface_raised": "#1A202B",
    "overlay": "#222A36",
    "border": "#29323E",
    "border_strong": "#3A4656",
    "text_primary": "#F2F5F8",
    "text_secondary": "#B6C0CD",
    "text_muted": "#8894A3",
    "accent": "#2DD4BF",
    "accent_hover": "#5EEAD4",
    "accent_pressed": "#14B8A6",
    "primary": "#0D9488",
    "primary_hover": "#0F9F94",
    "primary_pressed": "#0B7C73",
    "button_text": "#FFFFFF",
    "success": "#34D399",
    "warning": "#FBBF24",
    "danger": "#F87171",
    "info": "#60A5FA",
    "selection": "#173C39",
    "focus": "#5EEAD4",
    "chart_grid": "#2A3441",
    "chart_axis": "#8A97A8",
    "chart_line": "#2DD4BF",
    "chart_alert": "#F87171",
    "chart_surface": "#14181F",
}

SPACE = {
    "xs": 4,
    "sm": 8,
    "md": 12,
    "lg": 16,
    "xl": 24,
    "xxl": 32,
}

RADIUS = {
    "sm": 6,
    "md": 10,
    "lg": 14,
    "xl": 18,
    "pill": 999,
}

CHART = {
    "grid": COLORS["chart_grid"],
    "axis": COLORS["chart_axis"],
    "line": COLORS["chart_line"],
    "alert": COLORS["chart_alert"],
    "surface": COLORS["chart_surface"],
}


_STYLE_TEMPLATE = Template(
    """
QWidget {
    color: $text_primary;
}

QWidget#root,
QWidget#pageContent,
QWidget#analysisContent,
QDialog,
QDialog#processDialog {
    background-color: $canvas;
}

QLabel {
    background: transparent;
}

QLabel#brand {
    color: $accent;
}

QLabel#value {
    color: $text_primary;
}

QLabel#muted,
QLabel[tone="muted"] {
    color: $text_secondary;
}

QLabel#settingsHeading,
QLabel#analysisHeading,
QLabel#dialogHeading {
    color: $text_primary;
}

QLabel#warningLabel {
    color: $warning;
}

QLabel#detailsPanel,
QLabel#reasonPanel {
    background-color: $surface_raised;
    border: 1px solid $border;
    border-radius: ${radius_lg}px;
    padding: ${space_lg}px;
}

QFrame#card,
QFrame#chainPanel {
    background-color: $surface;
    border: 1px solid $border;
    border-radius: ${radius_lg}px;
}

QFrame#reportBlock {
    background-color: $surface_raised;
    border: 1px solid $border;
    border-radius: ${radius_lg}px;
}

QPushButton {
    background-color: $surface_raised;
    border: 1px solid $border;
    border-radius: ${radius_md}px;
    padding: ${space_sm}px ${space_lg}px;
    color: $text_primary;
}

QPushButton:hover {
    background-color: $overlay;
    border-color: $border_strong;
}

QPushButton:pressed {
    background-color: $canvas;
}

QPushButton:disabled {
    background-color: $surface;
    border-color: $border;
    color: $text_muted;
}

QPushButton[variant="primary"] {
    background-color: $primary;
    border-color: $accent_pressed;
    color: $button_text;
    font-weight: 600;
}

QPushButton[variant="primary"]:hover {
    background-color: $primary_hover;
    border-color: $accent;
}

QPushButton[variant="primary"]:pressed {
    background-color: $primary_pressed;
}

QPushButton[variant="primary"]:disabled {
    background-color: $surface;
    border-color: $border;
    color: $text_muted;
}

QPushButton[variant="ghost"] {
    background: transparent;
    border-color: transparent;
    color: $text_secondary;
}

QPushButton[variant="ghost"]:hover {
    background-color: $surface_raised;
    border-color: $border;
    color: $text_primary;
}

QPushButton[variant="ghost"]:pressed {
    background-color: $canvas;
}

QPushButton:focus {
    border-color: $focus;
}

QPushButton[variant="primary"]:focus {
    border-color: $accent_hover;
}

QLineEdit,
QComboBox,
QSpinBox,
QDoubleSpinBox {
    background-color: $surface;
    border: 1px solid $border;
    border-radius: ${radius_md}px;
    padding: ${space_sm}px ${space_md}px;
    color: $text_primary;
    selection-background-color: $accent;
    selection-color: $canvas;
}

QLineEdit:hover,
QComboBox:hover,
QSpinBox:hover,
QDoubleSpinBox:hover {
    border-color: $border_strong;
}

QLineEdit:focus,
QComboBox:focus,
QSpinBox:focus,
QDoubleSpinBox:focus {
    border-color: $accent;
}

QListWidget {
    background-color: $surface;
    border: 1px solid $border;
    border-radius: ${radius_md}px;
    padding: ${space_xs}px;
    color: $text_primary;
    outline: none;
}

QListWidget::item {
    padding: ${space_sm}px ${space_md}px;
    border-bottom: 1px solid $border;
}

QListWidget::item:hover {
    background-color: $overlay;
}

QListWidget::item:selected {
    background-color: $selection;
    color: $text_primary;
}

QLineEdit:disabled,
QComboBox:disabled,
QSpinBox:disabled,
QDoubleSpinBox:disabled {
    background-color: $surface;
    color: $text_muted;
    border-color: $border;
}

QComboBox::drop-down {
    border: none;
    width: 28px;
}

QComboBox::down-arrow {
    image: url("$chevron_icon");
    width: 12px;
    height: 12px;
}

QComboBox QAbstractItemView {
    background-color: $overlay;
    border: 1px solid $border_strong;
    border-radius: ${radius_md}px;
    padding: ${space_xs}px;
    selection-background-color: $selection;
    selection-color: $text_primary;
    outline: 0;
}

QTabWidget::pane {
    border: 0;
}

QTabBar::tab {
    background: transparent;
    color: $text_secondary;
    padding: ${space_sm}px ${space_lg}px;
    margin-right: ${space_xs}px;
    border-radius: ${radius_md}px;
}

QTabBar::tab:hover {
    background: $surface_raised;
    color: $text_primary;
}

QTabBar::tab:selected {
    background: $surface_raised;
    color: $accent;
}

QTableWidget {
    background-color: $surface;
    alternate-background-color: $surface_raised;
    border: 1px solid $border;
    border-radius: ${radius_lg}px;
    gridline-color: $border;
    selection-background-color: $selection;
    selection-color: $text_primary;
    outline: 0;
}

QTableWidget::item {
    padding: ${space_sm}px;
    border: none;
}

QTableWidget::item:hover {
    background-color: $surface_raised;
}

QTableWidget::item:selected {
    background-color: $selection;
    color: $text_primary;
}

QTableWidget:focus {
    border-color: $accent;
}

QHeaderView::section {
    background-color: $surface_raised;
    color: $text_secondary;
    border: none;
    border-bottom: 1px solid $border;
    padding: ${space_sm}px;
}

QTableCornerButton::section {
    background-color: $surface_raised;
    border: none;
}

QScrollArea {
    background: $canvas;
    border: none;
}

QScrollBar:vertical {
    background: $canvas;
    width: 10px;
    margin: 0;
}

QScrollBar::handle:vertical {
    background: $border_strong;
    border-radius: 5px;
    min-height: 30px;
}

QScrollBar::handle:vertical:hover {
    background: $text_muted;
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0;
}

QScrollBar:horizontal {
    background: $canvas;
    height: 10px;
    margin: 0;
}

QScrollBar::handle:horizontal {
    background: $border_strong;
    border-radius: 5px;
    min-width: 30px;
}

QScrollBar::handle:horizontal:hover {
    background: $text_muted;
}

QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {
    width: 0;
}

QCheckBox {
    color: $text_primary;
    spacing: ${space_sm}px;
}

QCheckBox:disabled {
    color: $text_muted;
}

QCheckBox::indicator {
    width: 20px;
    height: 20px;
    border: 1px solid $border_strong;
    border-radius: 4px;
    background-color: $surface;
}

QCheckBox::indicator:hover {
    border-color: $accent;
}

QCheckBox::indicator:checked {
    background-color: $accent;
    border-color: $accent;
    image: url("$check_icon");
}

QCheckBox::indicator:checked:hover {
    background-color: $accent_hover;
    border-color: $accent_hover;
}

QCheckBox::indicator:disabled {
    background-color: $surface;
    border-color: $border;
}

QToolTip {
    background-color: $overlay;
    color: $text_primary;
    border: 1px solid $border_strong;
    border-radius: ${radius_sm}px;
    padding: ${space_sm}px;
}
"""
)


def build_stylesheet():

    values = dict(COLORS)
    values["check_icon"] = CHECK_ICON
    values["chevron_icon"] = CHEVRON_ICON
    values.update(
        {
            f"space_{key}": value
            for key, value in SPACE.items()
        }
    )
    values.update(
        {
            f"radius_{key}": value
            for key, value in RADIUS.items()
        }
    )

    return _STYLE_TEMPLATE.substitute(values)


def build_palette():

    palette = QPalette()
    palette.setColor(
        QPalette.ColorRole.Window,
        QColor(COLORS["canvas"]),
    )
    palette.setColor(
        QPalette.ColorRole.WindowText,
        QColor(COLORS["text_primary"]),
    )
    palette.setColor(
        QPalette.ColorRole.Base,
        QColor(COLORS["surface"]),
    )
    palette.setColor(
        QPalette.ColorRole.AlternateBase,
        QColor(COLORS["surface_raised"]),
    )
    palette.setColor(
        QPalette.ColorRole.Text,
        QColor(COLORS["text_primary"]),
    )
    palette.setColor(
        QPalette.ColorRole.Button,
        QColor(COLORS["surface_raised"]),
    )
    palette.setColor(
        QPalette.ColorRole.ButtonText,
        QColor(COLORS["text_primary"]),
    )
    palette.setColor(
        QPalette.ColorRole.BrightText,
        QColor(COLORS["danger"]),
    )
    palette.setColor(
        QPalette.ColorRole.Highlight,
        QColor(COLORS["accent"]),
    )
    palette.setColor(
        QPalette.ColorRole.HighlightedText,
        QColor(COLORS["canvas"]),
    )
    palette.setColor(
        QPalette.ColorRole.ToolTipBase,
        QColor(COLORS["overlay"]),
    )
    palette.setColor(
        QPalette.ColorRole.ToolTipText,
        QColor(COLORS["text_primary"]),
    )
    palette.setColor(
        QPalette.ColorRole.PlaceholderText,
        QColor(COLORS["text_muted"]),
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.Text,
        QColor(COLORS["text_muted"]),
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.ButtonText,
        QColor(COLORS["text_muted"]),
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.WindowText,
        QColor(COLORS["text_muted"]),
    )

    return palette


def ensure_application_theme(app=None):

    application = app or QApplication.instance()

    if application is None:

        return None

    ensure_application_font(application)

    if application.property(THEME_PROPERTY):

        return application

    style = QStyleFactory.create("Fusion")

    if style is not None:

        application.setStyle(style)

    application.setPalette(build_palette())
    application.setStyleSheet(build_stylesheet())
    application.setProperty(THEME_PROPERTY, True)

    return application


def set_button_variant(button, variant):
    """Set a QSS variant property and repolish the button."""

    button.setProperty("variant", variant)
    style = button.style()

    try:

        style.unpolish(button)
        style.polish(button)

    except (AttributeError, RuntimeError):

        pass

    return button


@dataclass(frozen=True)
class FontRole:
    scale: float
    weight: QFont.Weight
    families: tuple[str, ...]
    tabular: bool = False


ROLES = {
    "display": FontRole(
        1.5,
        QFont.Weight.DemiBold,
        DISPLAY_FAMILIES,
    ),
    "heading": FontRole(
        1.25,
        QFont.Weight.DemiBold,
        DISPLAY_FAMILIES,
    ),
    "subheading": FontRole(
        1.1,
        QFont.Weight.DemiBold,
        TEXT_FAMILIES,
    ),
    "body": FontRole(
        1.0,
        QFont.Weight.Normal,
        TEXT_FAMILIES,
    ),
    "label": FontRole(
        0.9,
        QFont.Weight.Medium,
        TEXT_FAMILIES,
    ),
    "caption": FontRole(
        0.8,
        QFont.Weight.Normal,
        TEXT_FAMILIES,
    ),
    "metric": FontRole(
        1.35,
        QFont.Weight.DemiBold,
        TEXT_FAMILIES,
        tabular=True,
    ),
    "mono": FontRole(
        0.9,
        QFont.Weight.Normal,
        MONO_FAMILIES,
        tabular=True,
    ),
    "mono_caption": FontRole(
        0.8,
        QFont.Weight.Normal,
        MONO_FAMILIES,
        tabular=True,
    ),
}


def configure_high_dpi():
    """Make Qt 6's per-monitor DPR policy explicit before QApplication.

    Qt 6 already enables high-DPI scaling.  Do not set
    AA_EnableHighDpiScaling again; only the rounding policy is made
    explicit so fractional display scales such as 125% and 150% keep
    their actual DPR instead of being rounded.
    """

    if QApplication.instance() is not None:

        return

    try:

        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )

    except (AttributeError, RuntimeError):

        # Older Qt builds may not expose the policy; Qt's default
        # high-DPI behavior is still used.
        pass


def system_base_point_size(font=None):
    """Return the system UI font's point size, with a readable floor."""

    source = font

    if source is None:

        app = QApplication.instance()

        source = app.font() if app is not None else QFont()

    point_size = source.pointSizeF()

    if point_size <= 0:

        point_size = QFontInfo(source).pointSizeF()

    if point_size <= 0:

        point_size = 9.0

    return max(MIN_BASE_POINT_SIZE, float(point_size))


def build_font(role="body", base_point_size=None):
    """Build a role font; sizes are relative to the system point size."""

    spec = ROLES.get(role)

    if spec is None:

        raise ValueError(f"Unknown font role: {role!r}")

    if base_point_size is None:

        base_point_size = configured_base_point_size()

    font = QFont()
    font.setFamilies(list(spec.families))
    font.setPointSizeF(
        max(1.0, float(base_point_size) * spec.scale)
    )
    font.setWeight(spec.weight)

    if spec.tabular:

        enable_tabular_numbers(font)

    return font


def enable_tabular_numbers(font):
    """Enable OpenType tabular figures when the font/Qt supports it."""

    try:

        font.setFeature(QFont.Tag("tnum"), 1)

    except (AttributeError, RuntimeError, TypeError):

        pass

    return font


def ensure_application_font(app=None):
    """Apply the system-anchored body font once to the QApplication."""

    application = app or QApplication.instance()

    if application is None:

        return None

    existing = application.property(BASE_POINT_PROPERTY)

    if existing is not None:

        return float(existing)

    base = system_base_point_size(application.font())

    application.setFont(build_font("body", base))
    application.setProperty(BASE_POINT_PROPERTY, base)

    return base


def configured_base_point_size():

    app = QApplication.instance()

    if app is not None:

        base = app.property(BASE_POINT_PROPERTY)

        if base is not None:

            return float(base)

    return ensure_application_font(app)


def font(role="body"):

    ensure_application_font()
    return build_font(role)


def apply_font(
    widget,
    role="body",
    weight=None,
    tabular=None,
):

    role_font = font(role)

    if weight is not None:

        role_font.setWeight(weight)

    if tabular is True:

        enable_tabular_numbers(role_font)

    widget.setFont(role_font)
    return role_font


def apply_muted_labels(root):

    for label in root.findChildren(QLabel):

        if label.objectName() == "muted":

            apply_font(label, "caption")


def apply_table_typography(table):
    """Apply body/mono roles and font-aware row/header heights."""

    body = font("body")
    table.setFont(body)

    header = table.horizontalHeader()
    header_font = font("label")
    header.setFont(header_font)

    body_height = QFontMetrics(body).height()
    header_height = QFontMetrics(header_font).height()

    table.verticalHeader().setDefaultSectionSize(
        max(32, body_height + 12)
    )
    header.setMinimumHeight(
        max(32, header_height + 12)
    )


def apply_chart_typography(chart):

    chart_font = font("caption")
    enable_tabular_numbers(chart_font)
    chart.setFont(chart_font)
    return chart.font()
