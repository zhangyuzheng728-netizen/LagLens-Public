"""Live network page and shared sampler controls."""

from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from i18n import get_manager, tr
import network_sampler
import ui_theme


def _metric_text(value, suffix=""):
    if value is None:
        return "—"
    try:
        return f"{float(value):.1f}{suffix}"
    except (TypeError, ValueError):
        return f"{value}{suffix}"


class NetworkPage(QWidget):
    """Standalone network view; the sampler keeps running when hidden."""

    def __init__(
        self,
        service,
        settings,
        parent=None,
    ):
        super().__init__(parent)

        ui_theme.ensure_application_theme()

        self.service = service
        self.settings = settings
        self._capture_running = False
        self._capture_network = False
        self._capture_network_failure = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(ui_theme.SPACE["md"])

        title = QLabel()
        title.setText(tr("network.title"))
        ui_theme.apply_font(title, "display")
        layout.addWidget(title)

        subtitle = QLabel()
        subtitle.setText(tr("network.subtitle"))
        subtitle.setWordWrap(True)
        subtitle.setObjectName("muted")
        ui_theme.apply_font(subtitle, "body")
        layout.addWidget(subtitle)

        target_row = QHBoxLayout()
        target_row.setSpacing(ui_theme.SPACE["sm"])

        target_label = QLabel()
        target_label.setText(tr("network.public_target"))
        ui_theme.apply_font(target_label, "label")
        target_row.addWidget(target_label)

        self.target_input = QLineEdit()
        self.target_input.setText(
            self.settings.network_public_target
        )
        self.target_input.setPlaceholderText("1.1.1.1")
        ui_theme.apply_font(self.target_input, "body")
        self.target_input.editingFinished.connect(
            self._save_target
        )
        target_row.addWidget(self.target_input, 1)

        self.start_button = QPushButton()
        self.start_button.setText(tr("network.start"))
        ui_theme.apply_font(self.start_button, "label")
        ui_theme.set_button_variant(
            self.start_button,
            "primary",
        )
        self.start_button.clicked.connect(self._start)
        target_row.addWidget(self.start_button)

        self.stop_button = QPushButton()
        self.stop_button.setText(tr("network.stop"))
        ui_theme.apply_font(self.stop_button, "label")
        ui_theme.set_button_variant(
            self.stop_button,
            "secondary",
        )
        self.stop_button.clicked.connect(self._stop)
        target_row.addWidget(self.stop_button)
        layout.addLayout(target_row)

        target_note = QLabel()
        target_note.setText(tr("network.public_target.tip"))
        target_note.setWordWrap(True)
        target_note.setObjectName("muted")
        ui_theme.apply_font(target_note, "caption")
        layout.addWidget(target_note)

        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setObjectName("muted")
        ui_theme.apply_font(self.status, "body")
        layout.addWidget(self.status)

        cards = QHBoxLayout()
        cards.setSpacing(ui_theme.SPACE["md"])

        self.gateway_card, self.gateway_values = (
            self._build_card("network.gateway")
        )
        self.public_card, self.public_values = (
            self._build_card("network.public")
        )
        cards.addWidget(self.gateway_card, 1)
        cards.addWidget(self.public_card, 1)
        layout.addLayout(cards)

        note = QLabel()
        note.setText(tr("network.game_server_note"))
        note.setWordWrap(True)
        note.setObjectName("muted")
        ui_theme.apply_font(note, "caption")
        layout.addWidget(note)

        layout.addStretch(1)

        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()

        get_manager().language_changed.connect(
            self.retranslate
        )

        self.refresh()

    def _build_card(self, title_key):

        card = QFrame()
        card.setObjectName("card")
        card.setMinimumWidth(320)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(
            ui_theme.SPACE["lg"],
            ui_theme.SPACE["lg"],
            ui_theme.SPACE["lg"],
            ui_theme.SPACE["lg"],
        )
        layout.setSpacing(ui_theme.SPACE["sm"])

        title = QLabel()
        title.setText(tr(title_key))
        ui_theme.apply_font(title, "subheading")
        layout.addWidget(title)

        grid = QGridLayout()
        grid.setHorizontalSpacing(ui_theme.SPACE["lg"])
        grid.setVerticalSpacing(ui_theme.SPACE["xs"])

        values = {}
        rows = (
            ("status", "network.status"),
            ("current", "network.current"),
            ("jitter", "network.jitter"),
            ("timeouts", "network.timeouts"),
            ("samples", "network.samples"),
            ("last", "network.last_sample"),
        )

        for row, (key, label_key) in enumerate(rows):

            label = QLabel()
            label.setText(tr(label_key))
            label.setObjectName("muted")
            ui_theme.apply_font(label, "caption")
            value = QLabel("—")
            value.setObjectName("value")
            value.setWordWrap(True)
            ui_theme.apply_font(value, "body")
            grid.addWidget(label, row, 0)
            grid.addWidget(value, row, 1)
            values[key] = value

        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        return card, values

    def _save_target(self):
        text = self.target_input.text().strip()

        if not text:
            self.status.setText(
                tr("network.invalid_target")
            )
            return False

        try:
            self.settings.set_network_public_target(
                text
            )
            return True
        except (OSError, ValueError):
            self.status.setText(
                tr("network.save_target_failed")
            )
            return False

    def _start(self):
        if self._capture_running:
            return

        if not self._save_target():
            return

        if self.service.start_standalone(
            self.target_input.text().strip()
        ):
            self.status.setText(tr("network.starting"))
        else:
            self.status.setText(
                tr("network.start_failed")
            )
        self.refresh()

    def _stop(self):
        if self.service.stop_standalone():
            self.status.setText(tr("network.stopped"))
        self.refresh()

    def set_capture_state(
        self,
        running,
        network_enabled,
        failure_reason="",
    ):
        self._capture_running = bool(running)
        self._capture_network = bool(network_enabled)
        self._capture_network_failure = str(
            failure_reason or ""
        )
        self.refresh()

    def _latest_ok(self, samples, name):
        for sample in reversed(samples):
            probe = (
                sample.get(name)
                if isinstance(sample, dict)
                else getattr(sample, name, None)
            )
            status = (
                probe.get("status")
                if isinstance(probe, dict)
                else getattr(probe, "status", None)
            )
            rtt = (
                probe.get("rtt_ms")
                if isinstance(probe, dict)
                else getattr(probe, "rtt_ms", None)
            )
            if status == "ok" and rtt is not None:
                return rtt
        return None

    def _probe_status_text(self, stats, name):
        if stats is None:
            return tr("network.no_data")
        if stats.get("responses"):
            return tr("network.has_data")
        if stats.get("timeouts"):
            return tr("network.no_response")
        if stats.get("unreachable"):
            return tr("network.unreachable")
        return tr("network.probe_error")

    def _update_card(self, values, stats, samples, name):
        values["status"].setText(
            self._probe_status_text(stats, name)
        )
        values["current"].setText(
            _metric_text(
                self._latest_ok(samples, name),
                " ms",
            )
        )
        values["jitter"].setText(
            _metric_text(
                stats.get("jitter_ms") if stats else None,
                " ms",
            )
        )
        values["timeouts"].setText(
            str(stats.get("timeouts", 0))
            if stats
            else "—"
        )
        values["samples"].setText(
            str(stats.get("samples", 0))
            if stats
            else "—"
        )
        last = samples[-1] if samples else None

        if last is None:

            values["last"].setText(
                tr("network.no_data")
            )
            return

        last_ns = (
            last.get("monotonic_ns", 0)
            if isinstance(last, dict)
            else getattr(last, "monotonic_ns", 0)
        )
        values["last"].setText(
            tr(
                "network.sample_age",
                seconds=max(
                    0,
                    int(
                        (
                            time.monotonic_ns()
                            - int(last_ns or 0)
                        )
                        / 1_000_000_000
                    ),
                ),
            )
        )

    def refresh(self):
        state = self.service.state()
        samples = self.service.snapshot()
        summary = network_sampler.summarize_samples(
            samples
        )
        running = state["running"]

        if self._capture_running and self._capture_network:
            if state.get("started_for_capture"):
                self.status.setText(
                    tr("network.capture_active")
                )
            else:
                self.status.setText(
                    tr("network.capture_reuse")
                )
        elif self._capture_running:

            if self._capture_network_failure:

                self.status.setText(
                    tr(
                        "network.capture_failed",
                        reason=self._capture_network_failure,
                    )
                )

            else:

                self.status.setText(
                    tr("network.capture_disabled")
                )
        elif not running:
            self.status.setText(
                tr("network.stopped")
                if samples
                else tr("network.idle")
            )
        elif (
            summary["gateway"]
            and summary["gateway"].get("responses")
        ) or (
            summary["public"]
            and summary["public"].get("responses")
        ):
            self.status.setText(tr("network.valid"))
        else:
            self.status.setText(
                tr("network.running_no_response")
            )

        self.start_button.setEnabled(
            not running
            and not self._capture_running
        )
        self.stop_button.setEnabled(
            running
            and state.get("standalone")
            and not self._capture_running
        )
        self.target_input.setEnabled(
            not running and not self._capture_running
        )

        self._update_card(
            self.gateway_values,
            summary["gateway"],
            samples,
            "gateway",
        )
        self._update_card(
            self.public_values,
            summary["public"],
            samples,
            "public",
        )

    def retranslate(self):
        self.start_button.setText(tr("network.start"))
        self.stop_button.setText(tr("network.stop"))
        self.refresh()
