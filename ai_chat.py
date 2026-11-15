"""Embedded AI chat page and per-report conversation state.

The chat is a first-class page in the main window, not a separate
window.  ``ChatSession`` owns one report's messages and one in-flight
request; ``ChatStore`` keeps sessions for the current process so switching
pages or reports does not lose the conversation or draft.
"""

from __future__ import annotations

import os
import threading
import time

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from i18n import get_manager, tr
import ai_diagnostics
import ai_insight
import ai_providers
import ai_stream
import deepseek_client
import diagnosis_pipeline
import ui_theme


GENERAL_KEY = "__general__"

QUICK_QUESTION_KEYS = {
    "full": "ai.chat.quick_question",
    "smoothness": "ai.chat.quick.smoothness",
    "hardware": "ai.chat.quick.hardware",
    "network": "ai.chat.quick.network",
    "optimization": "ai.chat.quick.optimization",
}

QUICK_LABEL_KEYS = {
    "full": "ai.chat.quick.label.full",
    "smoothness": "ai.chat.quick.label.smoothness",
    "hardware": "ai.chat.quick.label.hardware",
    "network": "ai.chat.quick.label.network",
    "optimization": "ai.chat.quick.label.optimization",
}

QUICK_OPTION_KINDS = (
    "smoothness",
    "hardware",
    "network",
    "optimization",
)


def default_mode():
    """Return the AI answer mode.

    ``freeform`` restores the older direct-text behavior (no JSON fact
    validation). ``structured`` keeps the evidence-checked JSON path for
    development and tests. The application defaults to freeform; set
    ``LAGLENS_AI_MODE=structured`` to opt back in.
    """

    mode = (
        os.environ.get("LAGLENS_AI_MODE")
        or "freeform"
    ).strip().lower()

    return "structured" if mode == "structured" else "freeform"


def _split_result(result):
    """Accept both plain text and (text, usage) client results."""

    if isinstance(result, tuple) and len(result) == 2:

        return result[0], result[1]

    return result, None


def _buffered_client_streamer(client):
    """Adapt an old one-shot client to the streaming contract.

    Used by tests and by any non-streaming client. The answer arrives in
    one delta, so it cannot show text before completion.
    """

    def stream(
        payload,
        api_key=None,
        timeout=None,
        should_stop=None,
    ):

        kwargs = {}

        if api_key is not None:

            kwargs["api_key"] = api_key

        if timeout is not None:

            kwargs["timeout"] = timeout

        answer, usage = _split_result(
            client(payload, **kwargs)
        )

        if should_stop is not None and should_stop():

            return

        yield from ai_stream.buffered_stream(
            answer,
            usage=usage,
        )

    return stream


def _elapsed_ms(started):

    return int((time.monotonic() - started) * 1000)


def _error_message(code, status=0, provider=None):
    if code == "prompt_too_large":
        return tr("ai.chat.prompt_too_large")

    if code == "http":
        return tr(
            "analysis.ai.error.http",
            status=int(status or 0),
        )

    key = f"analysis.ai.error.{code or 'unknown'}"
    message = tr(key)

    if message == key:
        message = tr("analysis.ai.error.unknown")

    if provider and code in ("auth", "missing_key"):

        message = (
            message
            + " "
            + tr(
                "analysis.ai.error.go_settings",
                provider=provider,
            )
        )

    return message


def general_report(language="zh_CN"):
    return {
        "report_key": GENERAL_KEY,
        "file": "",
        "application": "",
        "language": language,
        "no_report": True,
    }


def _default_selection():

    provider = ai_providers.get(ai_providers.DEFAULT_PROVIDER)
    return provider.id, provider.default_model


class ChatSession(QObject):
    """One report's messages and one in-flight request."""

    changed = Signal()
    request_started = Signal()
    request_finished = Signal(str)
    request_failed = Signal(str, int, str)
    request_stopped = Signal()

    def __init__(
        self,
        report,
        opening_answer="",
        parent=None,
        diagnostics=None,
        mode="structured",
    ):
        super().__init__(parent)

        self.diagnostics = diagnostics
        self.mode = (
            "structured" if mode == "structured" else "freeform"
        )
        self.report = dict(report or general_report())
        self.report_key = self.report.get(
            "report_key",
            GENERAL_KEY,
        )
        self.messages = []
        self.draft = ""
        self.scroll_value = 0
        self.pending = False
        self.stopped = False
        self.last_error_code = None
        self.last_error_status = 0
        self.last_error_provider = None
        self._active_provider = ai_providers.DEFAULT_PROVIDER
        self.last_structured = None
        self.last_validation_errors = []
        self.last_stream_usage = None
        self.failed_question = None
        self._request_id = 0
        self._thread = None
        self._cancel_event = threading.Event()
        self._stream_message = None

        self.maybe_add_opening(opening_answer)

    @property
    def can_retry(self):
        return bool(
            self.failed_question
            and not self.pending
        )

    @property
    def can_stop(self):
        return bool(self.pending)

    @property
    def streaming(self):
        return any(
            message.get("streaming")
            for message in self.messages
        )

    @property
    def has_report(self):
        return not self.report.get("no_report")

    def update_report(self, report, report_key=None):
        """Replace the measured context without touching the messages.

        Only the same report may be refreshed in place; a different key is
        ignored so a viewer update can never leak into another chat.
        """

        key = str(report_key or (report or {}).get("report_key") or "")

        if not key or key != str(self.report_key):
            return False

        merged = dict(self.report)
        merged.update(report or {})
        merged["report_key"] = key
        self.report = merged
        self.last_structured = None
        self.last_validation_errors = []
        self.changed.emit()

        return True

    def _diagnostic(self, event, **fields):
        """Write a bounded diagnostic record; never affect the request."""

        if self.diagnostics is None:

            return

        try:

            self.diagnostics.record(event, **fields)

        except Exception:  # pragma: no cover - logger is already safe

            pass

    def maybe_add_opening(self, answer):
        answer = (answer or "").strip()

        if not answer or self.messages or self.pending:
            return False

        self.messages.append(
            {
                "role": "assistant",
                "content": answer,
                "kind": "opening",
            }
        )
        self.changed.emit()
        return True

    def _history_snapshot(self, without_last=False):
        # An interrupted reply is kept for the user but never sent back as
        # a complete assistant answer, and it must not shift the retry
        # offset either.
        source = [
            message
            for message in self.messages
            if message.get("complete", True)
        ]

        if without_last:
            source = source[:-1]

        return [
            dict(message)
            for message in source
        ]

    def send(
        self,
        question,
        api_key=None,
        client=None,
        timeout=None,
        streamer=None,
        provider=None,
        model=None,
    ):
        question = (question or "").strip()

        if not question or self.pending:
            return False

        history = self._history_snapshot()
        self.messages.append(
            {
                "role": "user",
                "content": question,
                "kind": "chat",
            }
        )
        self._start(
            question,
            history,
            api_key=api_key,
            client=client,
            timeout=timeout,
            streamer=streamer,
            provider=provider,
            model=model,
        )
        return True

    def retry(
        self,
        api_key=None,
        client=None,
        timeout=None,
        streamer=None,
        provider=None,
        model=None,
    ):
        if self.pending or not self.failed_question:
            return False

        question = self.failed_question
        history = self._history_snapshot(
            without_last=True
        )
        self._start(
            question,
            history,
            api_key=api_key,
            client=client,
            timeout=timeout,
            streamer=streamer,
            provider=provider,
            model=model,
        )
        return True

    def _start(
        self,
        question,
        history,
        api_key=None,
        client=None,
        timeout=None,
        streamer=None,
        provider=None,
        model=None,
    ):
        self.pending = True
        self.stopped = False
        self.failed_question = None
        self.last_error_code = None
        self.last_error_status = 0
        self.last_error_provider = None
        self._stream_message = None
        self._cancel_event.clear()
        self._request_id += 1
        request_id = self._request_id
        self.request_started.emit()
        self.changed.emit()

        self._thread = threading.Thread(
            target=self._run,
            args=(
                request_id,
                question,
                history,
                api_key,
                client,
                timeout,
                dict(self.report),
                streamer,
                provider,
                model,
            ),
            name="laglens-ai-chat",
            daemon=True,
        )
        self._thread.start()

    def _run(
        self,
        request_id,
        question,
        history,
        api_key,
        client,
        timeout,
        report=None,
        streamer=None,
        provider=None,
        model=None,
    ):
        report = dict(report or self.report)
        provider_spec = ai_providers.get(provider)
        provider_id = provider_spec.id
        model = str(model or provider_spec.default_model)
        self._active_provider = provider_id
        diagnosis = report.get("diagnosis") or {}
        scenario = diagnosis.get("scenario") or {}
        quality = diagnosis.get("quality") or {}
        report_id, file_name = ai_diagnostics.report_identity(
            report
        )
        session_id = str(
            report.get("session_id") or "unknown"
        )
        started = time.monotonic()

        def log(event, **fields):

            self._diagnostic(
                event,
                model=model,
                provider=provider_id,
                report_id=report_id,
                file=file_name,
                session_id=session_id,
                **fields,
            )

        structured_mode = bool(
            self.mode == "structured"
            and provider_id == "deepseek"
        )
        body = None

        try:
            if not structured_mode and streamer is None and client is None:

                body_fn = lambda candidate: (
                    ai_providers.request_body(
                        provider_id,
                        model,
                        candidate,
                    )
                )
                payload, body = ai_insight.build_chat_payload(
                    report,
                    history,
                    question,
                    language=report.get(
                        "language",
                        "zh_CN",
                    ),
                    structured=False,
                    body_fn=body_fn,
                    body_limit=ai_insight.MAX_REQUEST_BYTES,
                    return_body=True,
                    model=model,
                )

            else:

                payload = ai_insight.build_chat_payload(
                    report,
                    history,
                    question,
                    language=report.get(
                        "language",
                        "zh_CN",
                    ),
                    structured=structured_mode,
                    max_bytes=ai_insight.MAX_REQUEST_BYTES,
                    model=model,
                )

            model = str(payload.get("model") or model)
            request_bytes = (
                len(body)
                if body is not None
                else len(ai_insight.encode_payload(payload))
            )
            log(
                "request",
                mode="structured" if structured_mode else "freeform",
                language=report.get("language", "zh_CN"),
                request_bytes=request_bytes,
                limit=ai_insight.MAX_REQUEST_BYTES,
                scenario=scenario.get("id"),
                scenario_source=scenario.get("source"),
                quality=quality.get("status"),
                message_count=len(
                    payload.get("messages") or ()
                ),
            )

            if not structured_mode:

                # Free-form chat streams assistant text. The validated
                # structured diagnosis (DeepSeek only) keeps the buffered
                # path below.
                self._run_freeform_stream(
                    request_id,
                    question,
                    payload,
                    api_key,
                    client,
                    streamer,
                    timeout,
                    log,
                    started,
                    provider=provider_id,
                    model=model,
                    body=body,
                )
                return

            call = client or deepseek_client.request_insight
            kwargs = {"api_key": api_key}

            if timeout is not None:
                kwargs["timeout"] = timeout

            if client is None:

                kwargs["return_usage"] = True

            call_started = time.monotonic()
            answer, usage = _split_result(
                call(payload, **kwargs)
            )
            self.last_structured = None
            self.last_validation_errors = []

            if structured_mode and diagnosis:

                structured = diagnosis_pipeline.parse_structured(
                    answer
                )
                structured, local_repairs = (
                    diagnosis_pipeline.normalize_structured_ids(
                        structured,
                        diagnosis,
                    )
                )

                if local_repairs:

                    log(
                        "local_repair",
                        phase="first",
                        repairs=local_repairs,
                    )

                errors = diagnosis_pipeline.validate_structured(
                    structured,
                    diagnosis,
                    report,
                )
                log(
                    "response",
                    parse_ok=structured is not None,
                    local_repairs=len(local_repairs),
                    validation=(
                        ai_diagnostics.classify_validation_errors(
                            errors
                        )
                    ),
                    elapsed_ms=_elapsed_ms(call_started),
                    usage=ai_diagnostics.usage_summary(usage),
                )

                if errors:

                    repair_attempted = True
                    repair_ok = False
                    log(
                        "repair_request",
                        validation=(
                            ai_diagnostics.classify_validation_errors(
                                errors
                            )
                        ),
                    )

                    try:

                        repair = ai_insight.build_repair_payload(
                            report,
                            question,
                            answer,
                            errors,
                            language=report.get(
                                "language",
                                "zh_CN",
                            ),
                        )
                        repair_started = time.monotonic()
                        repaired, repair_usage = _split_result(
                            call(repair, **kwargs)
                        )
                        repaired_structured = (
                            diagnosis_pipeline.parse_structured(
                                repaired
                            )
                        )
                        repaired_structured, repaired_repairs = (
                            diagnosis_pipeline.normalize_structured_ids(
                                repaired_structured,
                                diagnosis,
                            )
                        )

                        if repaired_repairs:

                            log(
                                "local_repair",
                                phase="repair",
                                repairs=repaired_repairs,
                            )

                        repaired_errors = (
                            diagnosis_pipeline.validate_structured(
                                repaired_structured,
                                diagnosis,
                                report,
                            )
                        )
                        log(
                            "repair_response",
                            parse_ok=(
                                repaired_structured is not None
                            ),
                            local_repairs=len(repaired_repairs),
                            validation=(
                                ai_diagnostics.classify_validation_errors(
                                    repaired_errors
                                )
                            ),
                            elapsed_ms=_elapsed_ms(
                                repair_started
                            ),
                            usage=ai_diagnostics.usage_summary(
                                repair_usage
                            ),
                        )

                    except Exception as error:
                        repaired_structured = None
                        repaired_errors = errors
                        log(
                            "repair_response",
                            parse_ok=None,
                            error_code=type(error).__name__,
                            elapsed_ms=_elapsed_ms(call_started),
                        )

                    if repaired_errors:

                        self.last_validation_errors = list(
                            repaired_errors
                        )
                        answer = diagnosis_pipeline.fallback_text(
                            diagnosis,
                            "；".join(repaired_errors),
                            language=report.get(
                                "language",
                                "zh_CN",
                            ),
                        )
                        log(
                            "final",
                            final_source="fallback",
                            repair_attempted=repair_attempted,
                            repair_ok=repair_ok,
                            validation=(
                                ai_diagnostics.classify_validation_errors(
                                    repaired_errors
                                )
                            ),
                            elapsed_ms=_elapsed_ms(started),
                        )

                    else:

                        repair_ok = True
                        self.last_structured = (
                            repaired_structured
                        )
                        answer = (
                            diagnosis_pipeline.structured_summary(
                                repaired_structured,
                                language=report.get(
                                    "language",
                                    "zh_CN",
                                ),
                            )
                        )
                        log(
                            "final",
                            final_source="ai",
                            repair_attempted=repair_attempted,
                            repair_ok=repair_ok,
                            elapsed_ms=_elapsed_ms(started),
                        )

                else:

                    self.last_structured = structured
                    answer = diagnosis_pipeline.structured_summary(
                        structured,
                        language=report.get(
                            "language",
                            "zh_CN",
                        ),
                    )
                    log(
                        "final",
                        final_source="ai",
                        repair_attempted=False,
                        repair_ok=False,
                        elapsed_ms=_elapsed_ms(started),
                    )

            else:

                log(
                    "response",
                    mode=self.mode,
                    parse_ok=None,
                    validation=[],
                    elapsed_ms=_elapsed_ms(call_started),
                    usage=ai_diagnostics.usage_summary(usage),
                )
                log(
                    "final",
                    mode=self.mode,
                    final_source="ai",
                    structured=False,
                    elapsed_ms=_elapsed_ms(started),
                )

        except ai_insight.PromptTooLarge as error:

            code = (
                "summary_too_large"
                if error.reason == "summary"
                else "prompt_too_large"
            )
            log(
                "api_error",
                error_code=code,
                actual_bytes=error.actual_bytes,
                limit=error.max_bytes,
                failure_stage=error.reason,
                elapsed_ms=_elapsed_ms(started),
            )
            self._finish_failure(
                request_id,
                question,
                code,
                0,
                "",
                retryable=False,
            )
            return

        except deepseek_client.DeepSeekError as error:
            log(
                "api_error",
                error_code=error.code,
                error_status=error.status,
                elapsed_ms=_elapsed_ms(started),
            )
            self._finish_failure(
                request_id,
                question,
                error.code,
                error.status,
                error.detail,
                retryable=True,
            )
            return

        except ValueError as error:
            log(
                "api_error",
                error_code="invalid_request",
                elapsed_ms=_elapsed_ms(started),
            )
            self._finish_failure(
                request_id,
                question,
                "invalid_request",
                0,
                str(error),
                retryable=False,
            )
            return

        except Exception as error:
            log(
                "api_error",
                error_code="unknown",
                error_type=type(error).__name__,
                elapsed_ms=_elapsed_ms(started),
            )
            self._finish_failure(
                request_id,
                question,
                "unknown",
                0,
                str(error),
                retryable=True,
            )
            return

        self._finish_success(request_id, answer)

    def _run_freeform_stream(
        self,
        request_id,
        question,
        payload,
        api_key,
        client,
        streamer,
        timeout,
        log,
        started,
        provider="deepseek",
        model="deepseek-flash",
        body=None,
    ):
        """Consume provider-neutral stream events and show text early.

        Runs on the chat worker thread. Message state is updated here and
        announced with ``changed``; the Qt widgets only read it. Every
        write is guarded by ``request_id`` so a cancelled or superseded
        request can never append text to a newer reply.
        """

        def should_stop():

            return bool(
                self._cancel_event.is_set()
                or request_id != self._request_id
            )

        if streamer is not None:

            adapter = streamer

        elif client is not None:

            adapter = _buffered_client_streamer(client)

        else:

            adapter = ai_providers.make_streamer(
                provider,
                model,
                body=body,
            )

        kwargs = {"should_stop": should_stop}

        if api_key is not None:

            kwargs["api_key"] = api_key

        if timeout is not None:

            kwargs["timeout"] = timeout

        usage = None
        first_delta_ms = None
        events = None

        try:

            events = adapter(payload, **kwargs)

            for event in events:

                if should_stop():

                    break

                if isinstance(event, ai_stream.TextDelta):

                    if not event.text:

                        continue

                    if first_delta_ms is None:

                        first_delta_ms = _elapsed_ms(started)
                        self._begin_stream_message(
                            request_id,
                            provider,
                            model,
                        )
                        log(
                            "first_delta",
                            elapsed_ms=first_delta_ms,
                        )

                    self._append_stream_text(
                        request_id,
                        event.text,
                    )

                elif isinstance(event, ai_stream.StreamCompleted):

                    usage = event.usage

        except deepseek_client.DeepSeekError as error:

            log(
                "api_error",
                error_code=error.code,
                error_status=error.status,
                first_delta_ms=first_delta_ms,
                elapsed_ms=_elapsed_ms(started),
            )
            self._finish_stream_failure(
                request_id,
                question,
                error.code,
                error.status,
                error.detail,
                retryable=True,
            )
            return

        except ai_stream.StreamError as error:

            log(
                "api_error",
                error_code=error.code,
                error_status=error.status,
                first_delta_ms=first_delta_ms,
                elapsed_ms=_elapsed_ms(started),
            )
            self._finish_stream_failure(
                request_id,
                question,
                error.code,
                error.status,
                error.detail,
                retryable=True,
            )
            return

        except ValueError as error:

            log(
                "api_error",
                error_code="invalid_request",
                first_delta_ms=first_delta_ms,
                elapsed_ms=_elapsed_ms(started),
            )
            self._finish_stream_failure(
                request_id,
                question,
                "invalid_request",
                0,
                str(error),
                retryable=False,
            )
            return

        except Exception as error:

            log(
                "api_error",
                error_code="unknown",
                error_type=type(error).__name__,
                first_delta_ms=first_delta_ms,
                elapsed_ms=_elapsed_ms(started),
            )
            self._finish_stream_failure(
                request_id,
                question,
                "unknown",
                0,
                str(error),
                retryable=True,
            )
            return

        finally:

            close = getattr(events, "close", None)

            if callable(close):

                try:

                    close()

                except Exception:

                    pass

        if should_stop():

            self._finish_stream_stopped(request_id)
            return

        self.last_stream_usage = usage
        log(
            "response",
            mode="freeform",
            parse_ok=None,
            validation=[],
            first_delta_ms=first_delta_ms,
            elapsed_ms=_elapsed_ms(started),
            usage=ai_diagnostics.usage_summary(usage),
        )
        log(
            "final",
            mode="freeform",
            final_source="ai",
            structured=False,
            first_delta_ms=first_delta_ms,
            elapsed_ms=_elapsed_ms(started),
        )
        self._finish_stream_success(request_id)

    def _begin_stream_message(
        self,
        request_id,
        provider="deepseek",
        model="deepseek-flash",
    ):

        if request_id != self._request_id:

            return None

        message = {
            "role": "assistant",
            "content": "",
            "kind": "chat",
            "streaming": True,
            "complete": False,
            "provider": str(provider),
            "model": str(model),
        }
        self._stream_message = message
        self.messages.append(message)
        self.changed.emit()
        return message

    def _append_stream_text(self, request_id, text):

        if request_id != self._request_id:

            return

        message = self._stream_message

        if message is None:

            return

        message["content"] += text
        self.changed.emit()

    def _finish_stream_success(self, request_id):

        if request_id != self._request_id:

            return

        message = self._stream_message
        answer = (
            str(message.get("content") or "").strip()
            if message is not None
            else ""
        )

        if not answer:

            self._finish_stream_failure(
                request_id,
                self._last_question(),
                "invalid_response",
                0,
                "empty assistant content",
                retryable=True,
            )
            return

        message["streaming"] = False
        message["complete"] = True
        self.pending = False
        self.stopped = False
        self.failed_question = None
        self.last_error_code = None
        self.last_error_status = 0
        self.last_error_provider = None
        self.request_finished.emit(answer)
        self.changed.emit()

    def _finish_stream_failure(
        self,
        request_id,
        question,
        code,
        status,
        detail,
        retryable,
    ):

        if request_id != self._request_id:

            return

        if self._stream_message is not None:

            self._stream_message["streaming"] = False
            self._stream_message["complete"] = False
            self._stream_message["interrupted"] = "error"
            self._stream_message["error_code"] = str(code)

        self.pending = False
        self.stopped = False
        self.last_error_code = code
        self.last_error_status = int(status or 0)
        self.last_error_provider = self._active_provider
        self.failed_question = (
            question if retryable else None
        )
        self.request_failed.emit(
            code,
            int(status or 0),
            detail,
        )
        self.changed.emit()

    def _finish_stream_stopped(self, request_id):

        if request_id != self._request_id:

            return

        if self._stream_message is not None:

            self._stream_message["streaming"] = False
            self._stream_message["complete"] = False
            self._stream_message["interrupted"] = "stopped"

        self.pending = False
        self.stopped = True
        self.failed_question = None
        self.last_error_code = None
        self.last_error_status = 0
        self.last_error_provider = None
        self.request_stopped.emit()
        self.changed.emit()

    def _last_question(self):

        for message in reversed(self.messages):

            if message.get("role") == "user":

                return str(message.get("content") or "")

        return ""

    def cancel(self):
        """Stop the current request, keeping the partial reply visible."""

        if not self.pending:

            return False

        self._cancel_event.set()
        # Invalidate this request immediately so no late delta or finalize
        # can touch the conversation after the user pressed stop.
        self._request_id += 1

        if self._stream_message is not None:

            self._stream_message["streaming"] = False
            self._stream_message["complete"] = False
            self._stream_message["interrupted"] = "stopped"

        self.pending = False
        self.stopped = True
        self.failed_question = None
        self.last_error_code = None
        self.last_error_status = 0
        self.last_error_provider = None
        self.request_stopped.emit()
        self.changed.emit()

        return True

    def _finish_success(self, request_id, answer):
        if request_id != self._request_id:
            return

        answer = (answer or "").strip()

        if not answer:
            self._finish_failure(
                request_id,
                self.messages[-1]["content"],
                "invalid_response",
                0,
                "empty assistant content",
                retryable=True,
            )
            return

        self.messages.append(
            {
                "role": "assistant",
                "content": answer,
                "kind": "chat",
                "complete": True,
            }
        )
        self.pending = False
        self.failed_question = None
        self.last_error_code = None
        self.last_error_status = 0
        self.last_error_provider = None
        self.request_finished.emit(answer)
        self.changed.emit()

    def _finish_failure(
        self,
        request_id,
        question,
        code,
        status,
        detail,
        retryable,
    ):
        if request_id != self._request_id:
            return

        self.pending = False
        self.last_error_code = code
        self.last_error_status = int(status or 0)
        self.last_error_provider = self._active_provider
        self.failed_question = (
            question if retryable else None
        )
        self.request_failed.emit(
            code,
            int(status or 0),
            detail,
        )
        self.changed.emit()


class ChatStore:
    """Process-local conversation map keyed by report path."""

    def __init__(self, diagnostics=None, mode="structured"):
        self._sessions = {}
        self.diagnostics = diagnostics
        self.mode = (
            "structured" if mode == "structured" else "freeform"
        )

    def session_for(self, report, opening_answer=""):
        key = str(
            report.get("report_key")
            or report.get("file")
            or GENERAL_KEY
        )
        session = self._sessions.get(key)

        if session is None:
            session = ChatSession(
                report,
                opening_answer=opening_answer,
                diagnostics=self.diagnostics,
                mode=self.mode,
            )
            self._sessions[key] = session
        else:
            session.diagnostics = self.diagnostics
            session.mode = self.mode
            session.update_report(report)
            session.maybe_add_opening(opening_answer)

        return session

    def general_session(self, language="zh_CN"):
        return self.session_for(
            general_report(language)
        )

    def get(self, key):
        return self._sessions.get(str(key))

    def clear(self):
        self._sessions.clear()

    def __len__(self):
        return len(self._sessions)


class ChatInput(QPlainTextEdit):
    submitted = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._composing = False

    def inputMethodEvent(self, event):
        super().inputMethodEvent(event)
        self._composing = bool(event.preeditString())

    def can_submit_key(self, event):
        return bool(
            event.key()
            in (
                Qt.Key.Key_Return,
                Qt.Key.Key_Enter,
            )
            and not (
                event.modifiers()
                & Qt.KeyboardModifier.ShiftModifier
            )
            and not self._composing
            and not event.isAutoRepeat()
        )

    def keyPressEvent(self, event):
        if self.can_submit_key(event):
            self.submitted.emit()
            event.accept()
            return

        super().keyPressEvent(event)


class ChatTranscript(QTextBrowser):
    """ChatGPT-style transcript: users right, assistant left, no role labels."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setReadOnly(True)
        self.setOpenExternalLinks(False)
        self.setObjectName("aiChatTranscript")
        self.setStyleSheet(
            "QTextBrowser#aiChatTranscript {"
            " background: transparent;"
            " border: none;"
            "}"
        )
        self.viewport().setAutoFillBackground(False)
        self._texts = []
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.timeout.connect(
            self.scroll_to_bottom
        )

    def render(
        self,
        messages,
        empty_text,
        scroll_to_bottom=True,
    ):
        self._texts = []

        for message in messages:

            content = str(message.get("content") or "")

            if (
                message.get("role") == "assistant"
                and message.get("complete") is False
                and not message.get("streaming")
            ):

                content = (
                    content
                    + "\n"
                    + tr("ai.chat.incomplete")
                )

            self._texts.append(content)
        parts = [
            "<style>"
            "body {"
            f" color: {ui_theme.COLORS['text_primary']};"
            f" background-color: {ui_theme.COLORS['canvas']};"
            " font-size: 15px;"
            "}"
            "p { margin: 0; padding: 0; }"
            ".assistant {"
            f" color: {ui_theme.COLORS['text_primary']};"
            " padding: 2px 0 4px 0;"
            "}"
            ".user-bubble {"
            f" background-color: {ui_theme.COLORS['surface_raised']};"
            f" color: {ui_theme.COLORS['text_primary']};"
            " padding: 10px 14px;"
            "}"
            ".empty {"
            f" color: {ui_theme.COLORS['text_muted']};"
            " padding: 36px 12px;"
            "}"
            ".incomplete {"
            f" color: {ui_theme.COLORS['text_muted']};"
            " font-size: 12px;"
            " padding: 2px 0 0 0;"
            "}"
            "</style>"
        ]

        if not messages:
            parts.append(
                "<table width=\"100%\" cellspacing=\"0\" "
                "cellpadding=\"0\"><tr><td align=\"center\">"
                "<p class=\"empty\"><i>"
                + self._escape(empty_text)
                + "</i></p></td></tr></table>"
            )
        else:
            for message in messages:
                content = self._escape(
                    str(message.get("content") or "")
                ).replace("\n", "<br>")

                if message.get("role") == "user":
                    parts.append(
                        "<table width=\"620\" align=\"right\" "
                        "cellspacing=\"0\" cellpadding=\"0\">"
                        "<tr><td class=\"user-bubble\">"
                        + content
                        + "</td></tr></table>"
                        "<p style=\"height:10px\"></p>"
                    )
                else:
                    parts.append(
                        "<table width=\"840\" align=\"left\" "
                        "cellspacing=\"0\" cellpadding=\"0\">"
                        "<tr><td class=\"assistant\">"
                        + content
                        + (
                            "<br><span class=\"incomplete\">"
                            + self._escape(
                                tr("ai.chat.incomplete")
                            )
                            + "</span>"
                            if (
                                message.get("complete") is False
                                and not message.get("streaming")
                            )
                            else ""
                        )
                        + "</td></tr></table>"
                        "<p style=\"height:8px\"></p>"
                    )

        self.setHtml("".join(parts))

        if scroll_to_bottom:
            self._scroll_timer.start(0)

    def _escape(self, text):
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )

    def toPlainText(self):
        return "\n".join(self._texts)

    def scroll_to_bottom(self):
        bar = self.verticalScrollBar()
        bar.setValue(bar.maximum())

    def scroll_value(self):
        return self.verticalScrollBar().value()

    def set_scroll_value(self, value):
        bar = self.verticalScrollBar()
        bar.setValue(min(int(value), bar.maximum()))


class ChatPanel(QWidget):
    """Scrollable transcript plus a fixed bottom composer."""

    settings_needed = Signal(str)

    def __init__(
        self,
        session,
        client=None,
        parent=None,
        streamer=None,
        selection=None,
    ):
        super().__init__(parent)

        self.client = client
        self.streamer = streamer
        self.selection = selection or _default_selection
        self.session = None
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.timeout.connect(self._render)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(ui_theme.SPACE["md"])

        self.transcript = ChatTranscript()
        layout.addWidget(self.transcript, 1)

        status_row = QHBoxLayout()
        status_row.setSpacing(ui_theme.SPACE["sm"])

        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setObjectName("muted")
        ui_theme.apply_font(self.status, "caption")
        status_row.addWidget(self.status, 1)

        self.stop_button = QPushButton()
        self.stop_button.setText(tr("ai.chat.stop"))
        ui_theme.apply_font(
            self.stop_button,
            "label",
        )
        ui_theme.set_button_variant(
            self.stop_button,
            "ghost",
        )
        self.stop_button.clicked.connect(self._stop)
        status_row.addWidget(self.stop_button)

        self.retry_button = QPushButton()
        self.retry_button.setText(tr("ai.chat.retry"))
        ui_theme.apply_font(
            self.retry_button,
            "label",
        )
        ui_theme.set_button_variant(
            self.retry_button,
            "ghost",
        )
        self.retry_button.clicked.connect(
            self._retry
        )
        status_row.addWidget(self.retry_button)
        layout.addLayout(status_row)

        self.composer = QFrame()
        self.composer.setObjectName("aiComposer")
        self.composer.setStyleSheet(
            "QFrame#aiComposer {"
            f" background: {ui_theme.COLORS['surface']};"
            f" border: 1px solid {ui_theme.COLORS['border_strong']};"
            " border-radius: 18px;"
            "}"
            "QPlainTextEdit#aiChatInput {"
            " background: transparent;"
            " border: none;"
            f" color: {ui_theme.COLORS['text_primary']};"
            " padding: 2px;"
            "}"
        )
        composer_layout = QHBoxLayout(self.composer)
        composer_layout.setContentsMargins(
            16, 8, 8, 8
        )
        composer_layout.setSpacing(
            ui_theme.SPACE["sm"]
        )

        self.input = ChatInput()
        self.input.setObjectName("aiChatInput")
        self.input.setPlaceholderText(
            tr("ai.chat.input")
        )
        self.input.setMinimumHeight(44)
        self.input.setMaximumHeight(120)
        ui_theme.apply_font(self.input, "body")
        composer_layout.addWidget(self.input, 1)

        self.send_button = QPushButton()
        self.send_button.setText(tr("ai.chat.send"))
        self.send_button.setObjectName("aiSendButton")
        self.send_button.setMinimumHeight(38)
        self.send_button.setMinimumWidth(72)
        ui_theme.apply_font(
            self.send_button,
            "label",
            weight=QFont.Weight.DemiBold,
        )
        self.send_button.setStyleSheet(
            "QPushButton#aiSendButton {"
            f" background: {ui_theme.COLORS['primary']};"
            f" color: {ui_theme.COLORS['button_text']};"
            " border: none;"
            " border-radius: 12px;"
            " padding: 8px 16px;"
            "}"
            "QPushButton#aiSendButton:hover {"
            f" background: {ui_theme.COLORS['primary_hover']};"
            "}"
            "QPushButton#aiSendButton:pressed {"
            f" background: {ui_theme.COLORS['primary_pressed']};"
            "}"
            "QPushButton#aiSendButton:disabled {"
            f" background: {ui_theme.COLORS['surface_raised']};"
            f" color: {ui_theme.COLORS['text_muted']};"
            "}"
        )
        self.send_button.clicked.connect(
            self._send
        )
        composer_layout.addWidget(self.send_button)
        layout.addWidget(self.composer)

        self.input.submitted.connect(self._send)
        self.input.textChanged.connect(
            self._update_state
        )

        self.set_session(session)

    def set_session(self, session):
        if session is self.session:
            return

        if self.session is not None:
            self.session.draft = (
                self.input.toPlainText()
            )
            self.session.scroll_value = (
                self.transcript.scroll_value()
            )
            self._disconnect_session(self.session)

        self.session = session
        self._connect_session(session)
        self.input.setPlainText(session.draft or "")
        self._render(scroll_to_bottom=False)
        self._update_state()
        self._restore_scroll()

    def _connect_session(self, session):
        session.changed.connect(self._on_changed)
        session.request_started.connect(
            self._update_state
        )
        session.request_finished.connect(
            self._on_finished
        )
        session.request_failed.connect(
            self._on_failed
        )
        session.request_stopped.connect(
            self._on_stopped
        )

    def _disconnect_session(self, session):
        try:
            session.changed.disconnect(self._on_changed)
            session.request_started.disconnect(
                self._update_state
            )
            session.request_finished.disconnect(
                self._on_finished
            )
            session.request_failed.disconnect(
                self._on_failed
            )
            session.request_stopped.disconnect(
                self._on_stopped
            )
        except (RuntimeError, TypeError):
            pass

    def _on_changed(self):
        # Status text and the stop button must follow the streaming state,
        # not only the request start/end.
        self._update_state()

        # Coalesce many small deltas into ~25 renders per second instead of
        # rebuilding the transcript for every token.
        if self.session is not None and self.session.streaming:

            if not self._render_timer.isActive():

                self._render_timer.start(40)

            return

        self._render()

    def _render(self, scroll_to_bottom=True):
        if self.session is None:
            return

        empty_key = (
            "ai.chat.empty"
            if self.session.has_report
            else "ai.chat.empty_unlinked"
        )
        self.transcript.render(
            self.session.messages,
            tr(empty_key),
            scroll_to_bottom=scroll_to_bottom,
        )

    def _restore_scroll(self):
        if self.session is None:
            return

        self.transcript.set_scroll_value(
            self.session.scroll_value
        )

    def _update_state(self):
        if self.session is None:
            return

        self.send_button.setEnabled(
            bool(
                not self.session.pending
                and self.input.toPlainText().strip()
            )
        )
        self.stop_button.setVisible(self.session.can_stop)
        self.stop_button.setEnabled(self.session.can_stop)
        self.retry_button.setVisible(
            self.session.can_retry
            and not self.session.pending
        )

        if self.session.pending:

            self.status.setText(
                tr(
                    "ai.chat.streaming"
                    if self.session.streaming
                    else "ai.chat.running"
                )
            )
        elif self.session.stopped:

            self.status.setText(tr("ai.chat.stopped"))
        elif self.session.last_error_code:
            provider_label = ""
            message = self.session.last_error_provider

            if message:

                provider_label = ai_providers.label(
                    message
                )

            self.status.setText(
                tr(
                    "ai.chat.error.title",
                    message=_error_message(
                        self.session.last_error_code,
                        self.session.last_error_status,
                        provider=provider_label,
                    ),
                )
            )
        elif self.session.messages:
            self.status.setText(tr("ai.chat.ready"))
        else:
            self.status.setText(
                tr(
                    "ai.chat.empty"
                    if self.session.has_report
                    else "ai.chat.empty_unlinked"
                )
            )

    def _request_context(self):
        """Resolve provider, model and key once, at send time."""

        provider_id, model = self.selection()
        provider = ai_providers.get(provider_id)
        api_key = ai_providers.get_api_key(provider.id)

        if not api_key:

            self.status.setText(
                tr(
                    "ai.chat.missing_key",
                    provider=provider.label,
                )
            )
            self.settings_needed.emit(provider.label)
            return None

        return provider, model, api_key

    def send_text(self, text):
        if self.session is None or self.session.pending:
            return False

        text = (text or "").strip()

        if not text:
            return False

        context = self._request_context()

        if context is None:
            return False

        provider, model, api_key = context
        streamer = self.streamer

        return self.session.send(
            text,
            api_key=api_key,
            client=self.client,
            streamer=streamer,
            provider=provider.id,
            model=model,
        )

    def ask_quick_question(self, kind="full"):
        if (
            self.session is None
            or not self.session.has_report
        ):
            return False

        key = QUICK_QUESTION_KEYS.get(
            kind,
            QUICK_QUESTION_KEYS["full"],
        )

        return self.send_text(tr(key))

    def _send(self):
        if self.session is None or self.session.pending:
            return

        text = self.input.toPlainText().strip()

        if not text:
            return

        if self.send_text(text):
            self.input.clear()
            self._update_state()

    def _retry(self):
        if self.session is None or self.session.pending:
            return

        context = self._request_context()

        if context is None:
            return

        provider, model, api_key = context
        streamer = self.streamer

        self.session.retry(
            api_key=api_key,
            client=self.client,
            streamer=streamer,
            provider=provider.id,
            model=model,
        )
        self._update_state()

    def _stop(self):
        if self.session is None:
            return

        if self.session.cancel():

            self._render()
            self._update_state()

    def _on_finished(self, _answer):
        self._render()
        self._update_state()
        self.input.setFocus()

    def _on_failed(self, code, _status, _detail):
        self._render()
        self._update_state()

        if (
            self.session is not None
            and code in ("auth", "missing_key")
        ):

            self.settings_needed.emit(
                ai_providers.label(
                    self.session.last_error_provider
                )
            )

    def _on_stopped(self):
        self._render()
        self._update_state()

    def retranslate(self):
        self.input.setPlaceholderText(
            tr("ai.chat.input")
        )
        self.retry_button.setText(tr("ai.chat.retry"))
        self.send_button.setText(tr("ai.chat.send"))
        self.stop_button.setText(tr("ai.chat.stop"))
        self._render()
        self._update_state()


class AIChatPage(QWidget):
    """Main-window AI assistant page with an explicitly linked report."""

    view_report_requested = Signal(str)
    open_ai_settings_requested = Signal()

    def __init__(
        self,
        store,
        language="zh_CN",
        client=None,
        parent=None,
        streamer=None,
        selection=None,
    ):
        super().__init__(parent)

        ui_theme.ensure_application_theme()

        self.store = store
        self.client = client
        self.streamer = streamer
        self.selection = selection or _default_selection
        self.session = None
        self.report_key = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 16, 28, 18)
        layout.setSpacing(ui_theme.SPACE["md"])

        header = QHBoxLayout()
        header.setSpacing(ui_theme.SPACE["md"])

        context_box = QVBoxLayout()
        context_box.setSpacing(ui_theme.SPACE["xs"])

        self.context_caption = QLabel()
        self.context_caption.setText(
            tr("ai.chat.linked_caption")
        )
        self.context_caption.setObjectName("muted")
        ui_theme.apply_font(
            self.context_caption,
            "caption",
        )
        context_box.addWidget(self.context_caption)

        self.report_label = QLabel()
        ui_theme.apply_font(
            self.report_label,
            "label",
            weight=QFont.Weight.DemiBold,
        )
        self.report_label.setWordWrap(True)
        context_box.addWidget(self.report_label)

        self.provider_label = QLabel()
        self.provider_label.setObjectName("muted")
        ui_theme.apply_font(
            self.provider_label,
            "caption",
        )
        context_box.addWidget(self.provider_label)
        header.addLayout(context_box, 1)

        self.view_report_button = QPushButton()
        self.view_report_button.setText(
            tr("ai.chat.view_report")
        )
        ui_theme.apply_font(
            self.view_report_button,
            "label",
        )
        ui_theme.set_button_variant(
            self.view_report_button,
            "secondary",
        )
        self.view_report_button.clicked.connect(
            self._view_report
        )
        header.addWidget(self.view_report_button)

        self.settings_button = QPushButton()
        self.settings_button.setText(
            tr("ai.chat.open_settings")
        )
        ui_theme.apply_font(
            self.settings_button,
            "label",
        )
        ui_theme.set_button_variant(
            self.settings_button,
            "ghost",
        )
        self.settings_button.clicked.connect(
            self.open_ai_settings_requested.emit
        )
        header.addWidget(self.settings_button)
        layout.addLayout(header)

        quick_row = QHBoxLayout()
        quick_row.setSpacing(ui_theme.SPACE["sm"])

        self.quick_button = QPushButton()
        self.quick_button.setText(
            tr(QUICK_LABEL_KEYS["full"])
        )
        self.quick_button.setToolTip(
            tr("ai.chat.quick_question")
        )
        ui_theme.apply_font(self.quick_button, "label")
        ui_theme.set_button_variant(
            self.quick_button,
            "primary",
        )
        self.quick_button.clicked.connect(
            self._ask_quick
        )
        quick_row.addWidget(self.quick_button)
        quick_row.addStretch()
        layout.addLayout(quick_row)

        optional_row = QHBoxLayout()
        optional_row.setSpacing(ui_theme.SPACE["sm"])
        self.quick_buttons = {}

        for kind in QUICK_OPTION_KINDS:

            button = QPushButton()
            button.setText(tr(QUICK_LABEL_KEYS[kind]))
            button.setToolTip(tr(QUICK_QUESTION_KEYS[kind]))
            ui_theme.apply_font(button, "caption")
            button.setObjectName("aiQuickChip")
            button.setStyleSheet(
                "QPushButton#aiQuickChip {"
                " background: transparent;"
                f" color: {ui_theme.COLORS['text_secondary']};"
                f" border: 1px solid {ui_theme.COLORS['border']};"
                " border-radius: 14px;"
                " padding: 6px 12px;"
                "}"
                "QPushButton#aiQuickChip:hover {"
                f" border-color: {ui_theme.COLORS['border_strong']};"
                f" color: {ui_theme.COLORS['text_primary']};"
                "}"
            )
            button.clicked.connect(
                lambda _checked=False, key=kind: self._ask_quick(
                    key
                )
            )
            self.quick_buttons[kind] = button
            optional_row.addWidget(button)

        optional_row.addStretch()
        layout.addLayout(optional_row)

        self.panel = ChatPanel(
            store.general_session(language),
            client=client,
            streamer=streamer,
            selection=self.selection,
        )
        self.panel.settings_needed.connect(
            self._show_settings_entry
        )
        layout.addWidget(self.panel, 1)

        self.set_report_context(None)

        get_manager().language_changed.connect(
            self.retranslate
        )

    def set_report_context(self, context):
        if context is None or not context.get(
            "report_key"
        ):
            session = self.store.general_session(
                get_manager().language
            )
            self.report_key = ""
        else:
            context = dict(context)
            context["language"] = get_manager().language
            session = self.store.session_for(context)
            self.report_key = str(
                context.get("report_key")
            )

        self.session = session
        self.panel.set_session(session)
        self._update_header()
        return session

    def refresh_report_context(self, context):
        """Update the same linked report without resetting the chat.

        A different ``report_key`` is rejected so a viewer refresh can
        never overwrite another report's conversation.
        """

        if context is None or not self.report_key:
            return False

        key = str(context.get("report_key") or "")

        if not key or key != self.report_key:
            return False

        context = dict(context)
        context["language"] = get_manager().language

        if not self.session.update_report(context, key):
            return False

        self._update_header()
        return True

    def refresh_key_state(self):
        if not hasattr(self, "settings_button"):
            return
        provider_id, _model = self.selection()
        self.settings_button.setVisible(
            ai_providers.api_key_source(provider_id) == "none"
        )

    def refresh_selection(self):
        """Re-read the provider/model after the settings page changes."""

        provider_id, model = self.selection()
        self.provider_label.setText(
            tr(
                "ai.chat.provider_line",
                provider=ai_providers.label(provider_id),
                model=model,
            )
        )
        self._update_header()

    def _show_settings_entry(self, _provider_label=""):
        if hasattr(self, "settings_button"):
            self.settings_button.setVisible(True)

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_key_state()

    def _update_header(self):
        session = self.session
        self.refresh_key_state()
        provider_id, model = self.selection()
        self.provider_label.setText(
            tr(
                "ai.chat.provider_line",
                provider=ai_providers.label(provider_id),
                model=model,
            )
        )

        if session is None or not session.has_report:
            self.report_label.setText(
                tr("ai.chat.unlinked")
            )
            self.view_report_button.setVisible(False)
            self.quick_button.setVisible(False)
            for button in self.quick_buttons.values():
                button.setVisible(False)
            return

        report = session.report
        name = (
            report.get("application")
            or report.get("file")
            or "n/a"
        )
        self.report_label.setText(
            tr("ai.chat.report_linked", name=name)
        )
        self.view_report_button.setVisible(
            bool(self.report_key)
        )
        self.quick_button.setVisible(True)
        self.quick_button.setEnabled(
            not session.pending
        )

        for button in self.quick_buttons.values():
            button.setVisible(True)
            button.setEnabled(not session.pending)

    def _view_report(self):
        if self.report_key:
            self.view_report_requested.emit(
                self.report_key
            )

    def _ask_quick(self, kind="full"):
        self.panel.ask_quick_question(kind)

    def _sync_session_language(self):
        if self.session is not None:
            self.session.report["language"] = (
                get_manager().language
            )

    def retranslate(self):
        self._sync_session_language()
        self.context_caption.setText(
            tr("ai.chat.linked_caption")
        )
        self.view_report_button.setText(
            tr("ai.chat.view_report")
        )
        self.settings_button.setText(
            tr("ai.chat.open_settings")
        )
        self.quick_button.setText(
            tr(QUICK_LABEL_KEYS["full"])
        )
        self.quick_button.setToolTip(
            tr("ai.chat.quick_question")
        )

        for kind, button in self.quick_buttons.items():
            button.setText(
                tr(QUICK_LABEL_KEYS[kind])
            )
            button.setToolTip(
                tr(QUICK_QUESTION_KEYS[kind])
            )

        self._update_header()
        self.panel.retranslate()
