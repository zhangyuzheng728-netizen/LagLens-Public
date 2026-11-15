"""Settings card for AI provider, model, API keys and connection test.

Switching the provider or model only persists the selection; it never
sends a request.  Each provider keeps its own key in Windows Credential
Manager.  The DeepSeek credential target is unchanged, so existing users
keep their saved key without migrating anything.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from i18n import get_manager, tr
import ai_providers
import ai_stream
import deepseek_client
import ui_theme


def _error_message(code, status=0):
    if code == "http":
        return tr(
            "analysis.ai.error.http",
            status=int(status or 0),
        )

    key = f"analysis.ai.error.{code or 'unknown'}"
    message = tr(key)

    if message == key:
        message = tr("analysis.ai.error.unknown")

    return message


class _ConnectionWorker(QObject):

    finished = Signal(str)
    failed = Signal(str, int, str)

    def __init__(self, provider_id, model, parent=None):

        super().__init__(parent)
        self.provider_id = provider_id
        self.model = model

    def start(self):

        threading.Thread(
            target=self._run,
            name="LagLensAIConnectionTest",
            daemon=True,
        ).start()

    def _run(self):

        try:

            ok = ai_providers.probe(
                self.provider_id,
                self.model,
            )

        except deepseek_client.DeepSeekError as error:

            self.failed.emit(
                error.code,
                int(error.status or 0),
                str(error.detail or ""),
            )
            return

        except ai_stream.StreamError as error:

            self.failed.emit(
                error.code,
                int(error.status or 0),
                str(error.detail or ""),
            )
            return

        except Exception as error:

            self.failed.emit(
                "unknown",
                0,
                str(error),
            )
            return

        if not ok:

            self.failed.emit(
                "invalid_response",
                0,
                "no assistant text",
            )
            return

        self.finished.emit("OK")


class AISettingsCard(QWidget):
    """Provider/model selection, per-provider keys and a manual test."""

    key_changed = Signal()
    selection_changed = Signal(str, str)

    def __init__(self, settings=None, parent=None):
        super().__init__(parent)

        self.settings = settings
        self._testing = False
        self._worker = None
        self._loading = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(ui_theme.SPACE["md"])

        provider_row = QHBoxLayout()
        provider_row.setSpacing(ui_theme.SPACE["sm"])

        provider_label = QLabel()
        self._provider_label = provider_label
        provider_row.addWidget(provider_label)

        self.provider_combo = QComboBox()
        for provider in ai_providers.PROVIDER_LIST:

            self.provider_combo.addItem(
                provider.label,
                provider.id,
            )

        ui_theme.apply_font(self.provider_combo, "label")
        self.provider_combo.currentIndexChanged.connect(
            self._on_provider_changed
        )
        provider_row.addWidget(self.provider_combo)
        provider_row.addSpacing(ui_theme.SPACE["lg"])

        model_label = QLabel()
        self._model_label = model_label
        provider_row.addWidget(model_label)

        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.setInsertPolicy(
            QComboBox.InsertPolicy.NoInsert
        )
        ui_theme.apply_font(self.model_combo, "mono_caption")
        self.model_combo.activated.connect(
            self._on_model_changed
        )
        self.model_combo.lineEdit().editingFinished.connect(
            self._on_model_changed
        )
        provider_row.addWidget(self.model_combo, 1)
        layout.addLayout(provider_row)

        self.current_label = QLabel()
        self.current_label.setObjectName("muted")
        ui_theme.apply_font(self.current_label, "caption")
        layout.addWidget(self.current_label)

        self.status = QLabel()
        self.status.setWordWrap(True)
        ui_theme.apply_font(self.status, "body")
        layout.addWidget(self.status)

        input_row = QHBoxLayout()
        input_row.setSpacing(ui_theme.SPACE["sm"])

        self.key_input = QLineEdit()
        self.key_input.setEchoMode(
            QLineEdit.EchoMode.Password
        )
        ui_theme.apply_font(self.key_input, "body")
        input_row.addWidget(self.key_input, 1)

        self.save_button = QPushButton()
        ui_theme.apply_font(self.save_button, "label")
        ui_theme.set_button_variant(
            self.save_button,
            "primary",
        )
        self.save_button.clicked.connect(self.save_key)
        input_row.addWidget(self.save_button)
        layout.addLayout(input_row)

        actions = QHBoxLayout()
        actions.setSpacing(ui_theme.SPACE["sm"])

        self.remove_button = QPushButton()
        ui_theme.apply_font(self.remove_button, "label")
        ui_theme.set_button_variant(
            self.remove_button,
            "secondary",
        )
        self.remove_button.clicked.connect(self.remove_key)
        actions.addWidget(self.remove_button)

        self.test_button = QPushButton()
        ui_theme.apply_font(self.test_button, "label")
        ui_theme.set_button_variant(
            self.test_button,
            "secondary",
        )
        self.test_button.clicked.connect(self.test_connection)
        actions.addWidget(self.test_button)
        actions.addStretch()
        layout.addLayout(actions)

        self.test_status = QLabel()
        self.test_status.setWordWrap(True)
        self.test_status.setObjectName("muted")
        ui_theme.apply_font(self.test_status, "caption")
        layout.addWidget(self.test_status)

        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setObjectName("muted")
        ui_theme.apply_font(self.note, "caption")
        layout.addWidget(self.note)

        get_manager().language_changed.connect(
            self.retranslate
        )
        self._load_selection()
        self.retranslate()

    # --------------------------------------
    # Selection
    # --------------------------------------

    def selection(self):

        provider_id = self.provider_combo.currentData()
        model = self.model_combo.currentText().strip()
        provider = ai_providers.get(provider_id)
        return provider.id, (
            model or provider.default_model
        )

    def _load_selection(self):

        provider_id = None
        model = ""

        if self.settings is not None:

            provider_id = self.settings.ai_provider()

        provider = ai_providers.get(provider_id)
        self._loading = True

        try:

            index = self.provider_combo.findData(provider.id)

            if index >= 0:

                self.provider_combo.setCurrentIndex(index)

        finally:

            self._loading = False

        if self.settings is not None:

            model = self.settings.ai_model(provider.id)

        self._load_models(
            provider,
            model or provider.default_model,
        )

    def _load_models(self, provider, selected_model):

        self._loading = True

        try:

            self.model_combo.clear()
            self.model_combo.addItems(list(provider.models))
            self.model_combo.setCurrentText(
                selected_model or provider.default_model
            )

        finally:

            self._loading = False

        self._refresh_labels()
        self._update_controls()

    def _on_provider_changed(self, _index):

        if self._loading:

            return

        provider = ai_providers.get(
            self.provider_combo.currentData()
        )
        model = ""

        if self.settings is not None:

            model = self.settings.ai_model(provider.id)

        self._load_models(
            provider,
            model or provider.default_model,
        )
        self.test_status.setText("")
        self._persist(provider.id, self.selection()[1])
        self.selection_changed.emit(*self.selection())

    def _on_model_changed(self, *_args):

        if self._loading:

            return

        provider_id, model = self.selection()
        self._persist(provider_id, model)
        self._refresh_labels()
        self.selection_changed.emit(provider_id, model)

    def _persist(self, provider_id, model):

        if self.settings is None:

            return

        try:

            if self.settings.ai_provider() != provider_id:

                self.settings.set_ai_provider(provider_id)

            if model and self.settings.ai_model(provider_id) != model:

                self.settings.set_ai_model(provider_id, model)

        except (ValueError, RuntimeError):

            pass

    def _refresh_labels(self):

        provider_id, model = self.selection()
        self.current_label.setText(
            tr(
                "settings.ai.current",
                provider=ai_providers.label(provider_id),
                model=model,
            )
        )

    # --------------------------------------
    # Key state and actions
    # --------------------------------------

    def _provider(self):

        return ai_providers.get(self.selection()[0])

    def _update_controls(self):

        provider = self._provider()
        source = ai_providers.api_key_source(provider.id)
        saved = source == "saved"
        environment = source == "environment"
        session = source == "session"

        if saved:
            self.status.setText(tr("settings.ai.configured"))
        elif environment:
            self.status.setText(
                tr(
                    "settings.ai.env_fallback_provider",
                    provider=provider.label,
                )
            )
        elif session:
            self.status.setText(
                tr("settings.ai.session_only")
            )
        else:
            self.status.setText(
                tr(
                    "settings.ai.not_configured_provider",
                    provider=provider.label,
                )
            )

        self.save_button.setText(
            tr("settings.ai.change")
            if saved
            else tr("settings.ai.save")
        )
        self.remove_button.setEnabled(saved)
        self.remove_button.setText(tr("settings.ai.remove"))
        self.remove_button.setVisible(True)
        self.test_button.setEnabled(
            source != "none" and not self._testing
        )
        self.save_button.setEnabled(not self._testing)
        self.key_input.setEnabled(not self._testing)
        self.provider_combo.setEnabled(not self._testing)
        self.model_combo.setEnabled(not self._testing)
        self.key_input.setPlaceholderText(
            tr(
                "settings.ai.key_placeholder_provider",
                provider=provider.label,
            )
        )

    def retranslate(self):

        self._provider_label.setText(
            tr("settings.ai.provider")
        )
        self._model_label.setText(
            tr("settings.ai.model")
        )
        self.save_button.setText(
            tr("settings.ai.save")
        )
        self.test_button.setText(
            tr("settings.ai.test")
        )
        self.note.setText(tr("settings.ai.note"))
        self._refresh_labels()
        self._update_controls()

    def save_key(self):

        provider = self._provider()
        value = self.key_input.text().strip()

        if not value:

            self.status.setText(
                tr("settings.ai.empty_key")
            )
            return

        try:

            ai_providers.set_saved_api_key(
                provider.id,
                value,
            )

        except Exception as error:

            self.status.setText(
                tr(
                    "settings.ai.save_failed",
                    message=type(error).__name__,
                )
            )
            return

        self.key_input.clear()
        self.status.setText(
            tr("settings.ai.saved")
        )
        self.key_changed.emit()
        self._update_controls()

    def remove_key(self):

        provider = self._provider()

        try:

            ai_providers.delete_saved_api_key(provider.id)

        except Exception as error:

            self.status.setText(
                tr(
                    "settings.ai.remove_failed",
                    message=type(error).__name__,
                )
            )
            return

        self.key_changed.emit()
        self._update_controls()

        if ai_providers.api_key_source(provider.id) == "environment":

            self.status.setText(
                tr("settings.ai.removed_env")
            )

        else:

            self.status.setText(
                tr("settings.ai.removed")
            )

    def test_connection(self):

        if self._testing:

            return

        provider_id, model = self.selection()

        if ai_providers.api_key_source(provider_id) == "none":

            self.test_status.setText(
                tr("settings.ai.no_key")
            )
            return

        self._testing = True
        self.test_status.setText(
            tr("settings.ai.testing")
        )
        self._update_controls()

        worker = _ConnectionWorker(provider_id, model)
        worker.finished.connect(self._test_finished)
        worker.failed.connect(self._test_failed)
        self._worker = worker
        worker.start()

    def _finish_test(self):

        self._testing = False
        self._worker = None
        self._update_controls()

    def _test_finished(self, _answer):

        self._finish_test()
        self.test_status.setText(
            tr("settings.ai.test_ok")
        )

    def _test_failed(self, code, status, _detail):

        self._finish_test()
        self.test_status.setText(
            tr(
                "settings.ai.test_failed",
                message=_error_message(code, status),
            )
        )
