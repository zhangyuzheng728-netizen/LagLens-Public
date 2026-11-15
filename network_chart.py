"""Network latency chart aligned to the capture-relative time axis."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from i18n import tr
import ui_theme


def _probe(sample, name):
    if isinstance(sample, dict):
        return sample.get(name) or {}
    return getattr(sample, name, None) or {}


def _status_rtt(sample, name):
    probe = _probe(sample, name)

    if isinstance(probe, dict):
        status = probe.get("status")
        rtt = probe.get("rtt_ms")
    else:
        status = getattr(probe, "status", None)
        rtt = getattr(probe, "rtt_ms", None)

    if status == "ok" and rtt is not None:
        return float(rtt)
    return None


def _t_ms(sample):
    if isinstance(sample, dict):
        return float(sample.get("t_ms") or 0.0)
    return 0.0


class NetworkChart(QWidget):
    """Two separate RTT series; never shares a y-axis with frame time."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.samples = []
        self.duration_ms = 1000.0
        self.setMinimumHeight(230)
        ui_theme.apply_chart_typography(self)

    def set_data(self, samples, duration_ms):
        self.samples = list(samples or [])
        self.duration_ms = max(
            1000.0,
            float(duration_ms or 1000.0),
        )
        self.update()

    def _series(self, name):
        points = []

        for sample in self.samples:
            rtt = _status_rtt(sample, name)

            if rtt is not None:
                points.append((_t_ms(sample), rtt))

        return points

    def _timeouts(self, name):
        result = []

        for sample in self.samples:
            probe = _probe(sample, name)

            status = (
                probe.get("status")
                if isinstance(probe, dict)
                else getattr(probe, "status", None)
            )

            if status in ("timeout", "unreachable", "error"):
                result.append(_t_ms(sample))

        return result

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(
            QPainter.RenderHint.Antialiasing,
            True,
        )

        width = self.width()
        height = self.height()
        painter.fillRect(
            self.rect(),
            QColor(ui_theme.CHART["surface"]),
        )

        left = 56.0
        right = max(left + 20.0, width - 18.0)
        top = 30.0
        bottom = max(top + 20.0, height - 34.0)

        painter.setPen(
            QColor(ui_theme.CHART["axis"])
        )
        font = QFont(self.font())
        font.setPointSizeF(
            max(7.5, font.pointSizeF() * 0.9)
        )
        painter.setFont(font)
        metrics = QFontMetrics(font)

        gateway = self._series("gateway")
        public = self._series("public")
        values = [
            value for _time, value in gateway + public
        ]
        max_value = max(values) if values else 50.0
        max_value = max(10.0, max_value * 1.2)

        for step in range(4):

            y = bottom - (
                (bottom - top) * step / 3.0
            )
            painter.setPen(
                QPen(
                    QColor(ui_theme.CHART["grid"]),
                    1,
                )
            )
            painter.drawLine(
                QPointF(left, y),
                QPointF(right, y),
            )
            painter.setPen(
                QColor(ui_theme.CHART["axis"])
            )
            value = max_value * step / 3.0
            painter.drawText(
                QRectF(0, y - 8, left - 8, 16),
                Qt.AlignmentFlag.AlignRight
                | Qt.AlignmentFlag.AlignVCenter,
                f"{value:.0f} ms",
            )

        painter.setPen(
            QColor(ui_theme.CHART["axis"])
        )
        painter.drawText(
            QRectF(left, bottom + 4, 120, 20),
            Qt.AlignmentFlag.AlignLeft,
            "0 s",
        )
        painter.drawText(
            QRectF(right - 160, bottom + 4, 160, 20),
            Qt.AlignmentFlag.AlignRight,
            f"{self.duration_ms / 1000.0:.0f} s",
        )

        def map_point(time_ms, rtt):
            x = left + (
                (right - left)
                * min(max(time_ms, 0.0), self.duration_ms)
                / self.duration_ms
            )
            y = bottom - (
                (bottom - top)
                * min(max(rtt, 0.0), max_value)
                / max_value
            )
            return QPointF(x, y)

        for points, color, label in (
            (
                gateway,
                QColor(ui_theme.CHART["line"]),
                tr("network.report.chart.gateway"),
            ),
            (
                public,
                QColor(ui_theme.CHART.get(
                    "info",
                    "#60A5FA",
                )),
                tr("network.report.chart.public"),
            ),
        ):

            if len(points) >= 2:

                painter.setPen(
                    QPen(color, 1.8)
                )
                polygon = QPolygonF(
                    [
                        map_point(time_ms, rtt)
                        for time_ms, rtt in points
                    ]
                )
                painter.drawPolyline(polygon)

            painter.setPen(color)
            painter.drawText(
                QRectF(
                    left + (
                        0 if label
                        == tr("network.report.chart.gateway")
                        else 110
                    ),
                    4,
                    110,
                    20,
                ),
                Qt.AlignmentFlag.AlignLeft,
                label,
            )

        for times, color in (
            (
                self._timeouts("gateway"),
                QColor(ui_theme.CHART.get(
                    "alert",
                    "#F87171",
                )),
            ),
            (
                self._timeouts("public"),
                QColor(ui_theme.CHART.get(
                    "alert",
                    "#F87171",
                )),
            ),
        ):

            painter.setPen(QPen(color, 2))

            for time_ms in times:
                x = left + (
                    (right - left)
                    * min(max(time_ms, 0.0), self.duration_ms)
                    / self.duration_ms
                )
                painter.drawLine(
                    QPointF(x, bottom - 5),
                    QPointF(x, bottom + 1),
                )

        painter.end()
