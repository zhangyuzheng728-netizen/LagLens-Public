"""Minimal DeepSeek chat client for the optional AI insight.

Only the Python standard library is used, matching the project's
existing dependency policy.  The key saved in Windows Credential Manager
is preferred; ``DEEPSEEK_API_KEY`` is the fallback for development and
tests, then an in-memory key typed into a prompt.

Errors are exposed as :class:`DeepSeekError` codes so the UI can show a
clear localized message for connection, authentication, balance, size
and service failures.
"""

from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request

from http import client as http_client

from ai_insight import encode_payload
import ai_stream
import credential_store


API_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-flash"
DEFAULT_TIMEOUT = 30.0
MAX_REQUEST_BYTES = 4096

API_KEY_ENV = "DEEPSEEK_API_KEY"

# Set only through the hidden prompt in the current run.
_session_api_key = None


class DeepSeekError(Exception):
    """A request failure with a stable code for localized UI text."""

    def __init__(self, code, status=0, detail=""):
        self.code = code
        self.status = int(status or 0)
        self.detail = detail

        parts = [code]

        if self.status:

            parts.append(f"HTTP {self.status}")

        if detail:

            parts.append(detail)

        super().__init__(": ".join(parts))


def get_saved_api_key():
    """Return the Windows Credential Manager key, if present."""

    try:

        value = credential_store.read_secret()

    except credential_store.CredentialError:

        return None

    value = (value or "").strip()
    return value or None


def has_saved_api_key():
    return bool(get_saved_api_key())


def has_env_api_key():
    return bool(
        (os.environ.get(API_KEY_ENV) or "").strip()
    )


def get_api_key_source():
    if get_saved_api_key():

        return "saved"

    if has_env_api_key():

        return "environment"

    if _session_api_key:

        return "session"

    return "none"


def get_api_key():
    """Return the saved key, then the environment key, then session."""

    value = get_saved_api_key()

    if value:

        return value

    value = (os.environ.get(API_KEY_ENV) or "").strip()

    if value:

        return value

    return _session_api_key


def set_saved_api_key(value):
    """Persist a key in Windows Credential Manager; never log it."""

    text = (value or "").strip()

    if not text:

        raise ValueError("API key is empty")

    credential_store.save_secret(text)
    return text


def delete_saved_api_key():
    """Remove the local saved credential; does not revoke the platform key."""

    return credential_store.delete_secret()


def set_session_api_key(value):
    """Keep a key for this process only; never persist or log it."""

    global _session_api_key

    text = (value or "").strip()
    _session_api_key = text or None

    return _session_api_key


def clear_session_api_key():
    global _session_api_key

    _session_api_key = None


def _raise_for_http(error):
    status = int(getattr(error, "code", 0) or 0)

    if status in (401, 403):

        code = "auth"

    elif status == 402:

        code = "balance"

    elif status == 413:

        code = "too_large"

    elif status == 429:

        code = "rate_limit"

    elif status >= 500:

        code = "server"

    else:

        code = "http"

    raise DeepSeekError(code, status=status)


def request_insight(
    payload,
    api_key=None,
    timeout=DEFAULT_TIMEOUT,
    return_usage=False,
):
    """POST a prepared payload and return the assistant text.

    ``payload`` must already be built by :func:`ai_insight.build_payload`.
    The final UTF-8 body is checked again here so a caller cannot send a
    larger request by bypassing the builder.

    With ``return_usage=True`` the result is ``(content, usage)`` where
    ``usage`` is the provider's token-usage object or ``None``.  The
    default keeps the string return type used by existing callers.
    """

    key = (api_key or "").strip() or get_api_key()

    if not key:

        raise DeepSeekError("missing_key")

    try:

        body = encode_payload(payload)

    except (TypeError, ValueError) as error:

        raise DeepSeekError(
            "invalid_request",
            detail=str(error),
        ) from error

    if len(body) > MAX_REQUEST_BYTES:

        raise DeepSeekError(
            "too_large",
            detail=f"{len(body)} bytes",
        )

    request = urllib.request.Request(
        API_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )

    try:

        with urllib.request.urlopen(
            request,
            timeout=float(timeout),
        ) as response:

            raw = response.read()

    except urllib.error.HTTPError as error:

        _raise_for_http(error)

    except (
        TimeoutError,
        socket.timeout,
    ) as error:

        raise DeepSeekError(
            "timeout",
            detail=str(error),
        ) from error

    except urllib.error.URLError as error:

        reason = getattr(error, "reason", None)

        if isinstance(
            reason,
            (TimeoutError, socket.timeout),
        ):

            code = "timeout"

        else:

            code = "connection"

        raise DeepSeekError(
            code,
            detail=str(reason or error),
        ) from error

    except OSError as error:

        raise DeepSeekError(
            "connection",
            detail=str(error),
        ) from error

    try:

        data = json.loads(raw.decode("utf-8"))

    except (UnicodeDecodeError, json.JSONDecodeError) as error:

        raise DeepSeekError(
            "invalid_response",
            detail=str(error),
        ) from error

    try:

        content = data["choices"][0]["message"]["content"]

    except (
        KeyError,
        IndexError,
        TypeError,
    ) as error:

        raise DeepSeekError(
            "invalid_response",
            detail=str(error),
        ) from error

    if not isinstance(content, str) or not content.strip():

        raise DeepSeekError(
            "invalid_response",
            detail="empty assistant content",
        )

    content = content.strip()
    usage = data.get("usage") if isinstance(data, dict) else None

    if return_usage:

        return content, usage

    return content


def _stream_transport_error(error):
    """Map a transport exception to a stable DeepSeek error code."""

    if isinstance(error, urllib.error.HTTPError):

        try:

            _raise_for_http(error)

        except DeepSeekError as mapped:

            return mapped

    if isinstance(
        error,
        (TimeoutError, socket.timeout),
    ):

        return DeepSeekError(
            "timeout",
            detail=str(error),
        )

    if isinstance(error, urllib.error.URLError):

        reason = getattr(error, "reason", None)

        code = (
            "timeout"
            if isinstance(
                reason,
                (TimeoutError, socket.timeout),
            )
            else "connection"
        )

        return DeepSeekError(
            code,
            detail=str(reason or error),
        )

    return DeepSeekError(
        "connection",
        detail=str(error),
    )


def build_body(payload, model=None):
    """Build the exact DeepSeek streaming body (without API key)."""

    body_payload = dict(payload)

    if model:

        body_payload["model"] = model

    body_payload["stream"] = True
    options = dict(body_payload.get("stream_options") or {})
    options["include_usage"] = True
    body_payload["stream_options"] = options

    return body_payload


def stream_body(
    body,
    api_key=None,
    timeout=DEFAULT_TIMEOUT,
    should_stop=None,
):
    """Send one already-built body and parse DeepSeek's SSE response.

    ``body`` is the exact UTF-8 request body produced by
    :func:`build_body` and measured by the chat layer.  It is sent
    unchanged, so measurement and transport use the same bytes.
    """

    key = (api_key or "").strip() or get_api_key()

    if not key:

        raise DeepSeekError("missing_key")

    if isinstance(body, (bytes, bytearray)):

        raw_body = bytes(body)

    else:

        try:

            raw_body = encode_payload(body)

        except (TypeError, ValueError) as error:

            raise DeepSeekError(
                "invalid_request",
                detail=str(error),
            ) from error

    if len(raw_body) > MAX_REQUEST_BYTES:

        raise DeepSeekError(
            "too_large",
            detail=f"{len(raw_body)} bytes",
        )

    request = urllib.request.Request(
        API_URL,
        data=raw_body,
        method="POST",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
    )

    usage = None
    model = ""
    finish_reason = ""
    saw_content = False
    saw_done = False

    try:

        with urllib.request.urlopen(
            request,
            timeout=float(timeout),
        ) as response:

            for raw_line in response:

                if should_stop is not None and should_stop():

                    return

                line = raw_line.decode(
                    "utf-8",
                    "replace",
                ).strip()

                if not line or line.startswith(":"):

                    continue

                if not line.startswith("data:"):

                    continue

                chunk = line[5:].strip()

                if not chunk:

                    continue

                if chunk == "[DONE]":

                    saw_done = True
                    break

                try:

                    event = json.loads(chunk)

                except json.JSONDecodeError as error:

                    raise DeepSeekError(
                        "invalid_response",
                        detail=str(error),
                    ) from error

                if not isinstance(event, dict):

                    continue

                if event.get("error"):

                    failure = event.get("error") or {}
                    raise DeepSeekError(
                        "server",
                        detail=str(
                            failure.get("message")
                            or failure
                        ),
                    )

                if event.get("model"):

                    model = str(event["model"])

                if isinstance(event.get("usage"), dict):

                    usage = event["usage"]

                choices = event.get("choices") or []

                if not choices:

                    continue

                choice = choices[0] or {}

                if choice.get("finish_reason"):

                    finish_reason = str(
                        choice["finish_reason"]
                    )

                delta = choice.get("delta") or {}

                # ``reasoning_content`` is deliberately not read.
                text = delta.get("content")

                if isinstance(text, str) and text:

                    saw_content = True
                    yield ai_stream.TextDelta(text)

    except urllib.error.HTTPError as error:

        raise _stream_transport_error(error) from error

    except (
        TimeoutError,
        socket.timeout,
    ) as error:

        raise DeepSeekError(
            "timeout",
            detail=str(error),
        ) from error

    except urllib.error.URLError as error:

        raise _stream_transport_error(error) from error

    except (
        http_client.HTTPException,
        OSError,
    ) as error:

        raise _stream_transport_error(error) from error

    if should_stop is not None and should_stop():

        return

    if not saw_content:

        raise DeepSeekError(
            "invalid_response",
            detail="empty assistant content",
        )

    if not (saw_done or finish_reason):

        raise DeepSeekError(
            "connection",
            detail="stream ended before [DONE]",
        )

    yield ai_stream.StreamCompleted(
        usage=usage,
        model=model,
        finish_reason=finish_reason,
    )


def stream_insight(
    payload,
    api_key=None,
    timeout=DEFAULT_TIMEOUT,
    should_stop=None,
    model=None,
):
    """Backward-compatible wrapper: build the body, then stream it."""

    yield from stream_body(
        build_body(payload, model),
        api_key=api_key,
        timeout=timeout,
        should_stop=should_stop,
    )


def test_connection(api_key=None, timeout=15.0):
    """Send one minimal request, without chat history or a report."""

    payload = {
        "model": MODEL,
        "thinking": {"type": "disabled"},
        "messages": [
            {
                "role": "user",
                "content": "Reply with OK only.",
            }
        ],
        "max_tokens": 8,
    }
    return request_insight(
        payload,
        api_key=api_key,
        timeout=timeout,
    )
