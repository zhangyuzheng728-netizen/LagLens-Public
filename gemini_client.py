"""Gemini ``streamGenerateContent`` adapter.

The adapter owns the Google request shape (contents / systemInstruction),
SSE chunk parsing and usageMetadata.  Only non-thought ``parts[].text``
is forwarded; thought parts and protocol fields are ignored.
"""

from __future__ import annotations

import urllib.parse

import ai_http
import ai_stream


API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:streamGenerateContent?alt=sse"
)
DEFAULT_MODEL = "gemini-2.5-flash"
MODELS = (
    "gemini-2.5-flash",
    "gemini-2.5-pro",
)


def _body(payload):

    system_parts = []
    contents = []

    for message in payload.get("messages") or ():

        role = str(message.get("role") or "user")
        text = str(message.get("content") or "")

        if not text:

            continue

        if role == "system":

            system_parts.append(text)
            continue

        role = "model" if role == "assistant" else "user"

        if contents and contents[-1]["role"] == role:

            contents[-1]["parts"].append({"text": text})

        else:

            contents.append(
                {
                    "role": role,
                    "parts": [{"text": text}],
                }
            )

    body = {"contents": contents}

    if system_parts:

        body["systemInstruction"] = {
            "parts": [{"text": "\n\n".join(system_parts)}]
        }

    return body


def build_body(payload, model=DEFAULT_MODEL):
    """Build the exact Gemini streamGenerateContent body."""

    return _body(payload)


def stream_body(
    body,
    model=DEFAULT_MODEL,
    api_key=None,
    timeout=ai_http.DEFAULT_TIMEOUT,
    should_stop=None,
):
    """Send one already-built body and parse Gemini's SSE chunks."""

    key = (api_key or "").strip()

    if not key:

        raise ai_stream.StreamError("missing_key")

    raw_body = (
        bytes(body)
        if isinstance(body, (bytes, bytearray))
        else ai_http.encode_json(body)
    )
    ai_http.ensure_body_size(raw_body)

    request = ai_http.build_request(
        API_URL.format(
            model=urllib.parse.quote(
                model or DEFAULT_MODEL,
                safe="",
            )
        ),
        raw_body,
        {
            "x-goog-api-key": key,
        },
    )

    finished = False
    saw_text = False
    usage = None
    model_seen = model or DEFAULT_MODEL
    finish_reason = ""

    try:

        with ai_http.open_stream(request, timeout) as response:

            for data in ai_http.iter_sse_data(response):

                if should_stop is not None and should_stop():

                    return

                event = ai_http.parse_event(data)

                if event.get("error"):

                    error = event.get("error") or {}
                    raise ai_stream.StreamError(
                        "server",
                        detail=str(
                            error.get("message")
                            if isinstance(error, dict)
                            else error
                        ),
                    )

                feedback = event.get("promptFeedback") or {}

                if feedback.get("blockReason"):

                    raise ai_stream.StreamError(
                        "blocked",
                        detail=str(feedback.get("blockReason")),
                    )

                metadata = event.get("usageMetadata")

                if isinstance(metadata, dict):

                    usage = ai_http.usage_dict(
                        metadata.get("promptTokenCount"),
                        metadata.get("candidatesTokenCount"),
                        metadata.get("totalTokenCount"),
                    )

                for candidate in event.get("candidates") or ():

                    content = candidate.get("content") or {}

                    for part in content.get("parts") or ():

                        if part.get("thought"):

                            continue

                        text = part.get("text")

                        if isinstance(text, str) and text:

                            saw_text = True
                            yield ai_stream.TextDelta(text)

                    reason = candidate.get("finishReason")

                    if reason:

                        finished = True
                        finish_reason = str(reason)

    except ai_stream.StreamError:

        raise

    except Exception as error:

        raise ai_http.transport_error(error) from error

    if should_stop is not None and should_stop():

        return

    if not finished:

        raise ai_stream.StreamError(
            "connection",
            detail="stream ended before finishReason",
        )

    if not saw_text:

        raise ai_stream.StreamError(
            "invalid_response",
            detail="empty assistant content",
        )

    yield ai_stream.StreamCompleted(
        usage=usage,
        model=model_seen,
        finish_reason=finish_reason or "stop",
    )


def stream_chat(
    payload,
    model=DEFAULT_MODEL,
    api_key=None,
    timeout=ai_http.DEFAULT_TIMEOUT,
    should_stop=None,
):
    """Backward-compatible wrapper: build the body, then stream it."""

    yield from stream_body(
        build_body(payload, model),
        model=model,
        api_key=api_key,
        timeout=timeout,
        should_stop=should_stop,
    )
